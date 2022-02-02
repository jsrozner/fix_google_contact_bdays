import copy
import os.path
from datetime import datetime
from pprint import pp
from pprint import pprint as pp
from typing import Dict, List, Tuple

import dateparser
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

#############
### CONFIG ###
k_default_year = 1900  # year that will be filled in when no year is present
k_do_update = False    # change this when you are ready for the program to actually update birthdays; o.w. is a dry run
# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/contacts']  # read/write

#############


class PeopleFetcher:
    """
    An iterable to fetch all contacts
    """

    def __init__(self, person_fields='names,birthdays', page_size=50):
        self.req_params = dict(
            resourceName='people/me',
            pageSize=page_size,
            personFields=person_fields,
        )

        self.service = None  # set up by iter
        self.next_page_token = None  # set in calls to next(); None == first iter call; -1 => stop iteration

    def setup(self):
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        service = build('people', 'v1', credentials=creds)
        return service

    def __iter__(self):
        self.service = self.setup()
        self.next_page_token = None
        print('iterable created')
        return self

    def make_request(self):
        """
        Wraps handling of next_page_token
        """
        if self.next_page_token is not None:
            self.req_params.update({'pageToken': self.next_page_token})
        res = self.service.people().connections().list(
            **self.req_params
        ).execute()
        return res

    def __next__(self):
        if self.next_page_token == -1:
            raise StopIteration
        res = self.make_request()
        self.next_page_token = res.get('nextPageToken', None)
        if self.next_page_token is None:
            self.next_page_token = -1  # stop iteration
        return res


Person = Dict


class BirthdayHelper:
    @staticmethod
    def get_people_with_bdays(pf: PeopleFetcher) -> List[Person]:
        total_contacts = 0
        ppl_with_bdays = []
        for res_list in pf:  # iterate through the API list functionality
            people_list = res_list.get('connections', [])
            for p in people_list:
                if 'birthdays' in p:
                    ppl_with_bdays.append(p)
            total_contacts += len(people_list)
        print(f'{total_contacts} contacts reviewed')
        return ppl_with_bdays

    @staticmethod
    def get_people_to_update(ppl_with_bdays: List[Person]) -> List[Tuple[Person, Person]]:
        """
        Will return a list of tuples where first entry is original Person and second entry is updated Person
        Updates are of the form:
            Background:
                Birthdays are present either as a date object (year, month, day) or text string
                Text strings don't behave well with iOS so we want to switch everything to date object that also
                    includes a year

            In particular the following changes are made:
            - if date obj present then
                - if no year add default year
                - ignore the bday text (todo: we could verify that it matches)
            - if only text is present then parse the text into a date object
            - ALWAYS remove the text after doing the above
            - anytime a given year is the current year, we assume this is because no year was present (rather than that
                the person was born in current year) and change to the default year

        :param ppl_with_bdays: List of Person with birthday field present
        :return: List of Tuple of Person for original, and new with bday updated
        """
        ppl_to_update: List[Tuple[Person, Person]] = []  # tuple of original new
        err_ct = 0
        for orig_person in ppl_with_bdays:

            p = copy.deepcopy(orig_person)  # the new person we will send to server

            bdays = p.get('birthdays')
            assert len(bdays) == 1  # todo support for mult bdays could be added
            bday = bdays[0]
            bday_date: Dict = bday.get('date', None)
            bday_text: str = bday.get('text', None)

            # since there is a bday, we expect that one of these is present
            assert bday_date is not None or bday_text is not None

            did_update = False  # whether we actually made any changes

            if bday_date is not None:
                bday_year = bday_date.get('year', None)
                if bday_year is None or bday_year == datetime.now().year:
                    print('Contact will have fake year added')
                    bday_date.update({'year': k_default_year})
                    did_update = True
            else:  # bday_date was none, so need to parse text
                print('Contact will have bday parsed from bday text')
                parsed_date: datetime = dateparser.parse(bday_text)
                try:
                    pp(f'{bday_text} => {parsed_date}')
                    # if the text did not have a year, then year will be current year (could have timezone issues on dec 31 or 1/1)
                    year_to_use = parsed_date.year if parsed_date.year != datetime.now().year else k_default_year
                    bday_date = {'year': year_to_use,
                                 'month': parsed_date.month,
                                 'day': parsed_date.day}
                    bday.update({'date': bday_date})
                    did_update = True
                except AttributeError:
                    print(f'Contact with unparseable bday text "{bday_text}". You need to update this contact manually')
                    pp(p)
                    err_ct += 1
                    continue

            # now birthdays[0].date has a valid date with default year
            # remove text field bc it is useless
            if bday_text is not None:
                bday.pop('text')
                did_update = True

            if did_update:
                ppl_to_update.append((orig_person, p))

        if err_ct > 0:
            print(f'Had {err_ct} errors while processing. Please manually update birthdays for printed contacts'
                  f' via contacts.google.com')

        return ppl_to_update

    @staticmethod
    def update_contact(service, contact_tuple: Tuple[Person, Person]):
        orig, new = contact_tuple
        assert orig['resourceName'] == new['resourceName']
        service.people().updateContact(
            resourceName=orig['resourceName'],
            updatePersonFields='birthdays',
            body=new
        ).execute()

    ####
    ## Extra helper methods
    ####
    @staticmethod
    def get_person_with_name(ppl_with_bdays: List[Person], name: str):
        """
        Helper method to print any person objects of a given name, for comparison to mac/ios contacts or to google
        contacts.

        :param ppl_with_bdays:
        :param name:
        :return:
        """
        for p in ppl_with_bdays:
            if name in p.get('names')[0].values():
                print(p)

    @staticmethod
    def review_contact(service, contact_tuple: Tuple[Person, Person]):
        """
        Prints a given contact
        """
        orig, new = contact_tuple
        res = service.people().get(
            resourceName=orig['resourceName'],
            personFields='names,birthdays'
        ).execute()
        pp(res)


def main():
    if k_do_update:
        print('Running with update -> contacts will be updated\n')
    else:
        print('Dry run only. Contacts will not be updated. Change k_do_update at top of file if you wish changes to be '
              'made\n')
    pf = PeopleFetcher()
    ppl_with_bdays = BirthdayHelper.get_people_with_bdays(pf)
    print(f'{len(ppl_with_bdays)} contacts with bdays found')

    # this is a list of tuples (old -> new) that whose bdays will be updated
    ppl_to_update = BirthdayHelper.get_people_to_update(ppl_with_bdays)
    print(f'Will potentially update {len(ppl_to_update)} records')

    if len(ppl_to_update) > 0:
        print('Now printing the contacts that will be changed\n ')
        for orig, new in ppl_to_update:
            pp(orig)
            print('\n ============>\n')
            pp(new)
            print('\n')
    else:
        print('no contacts to update')
        return

    # uncomment the following line when you are ready to update contacts
    if k_do_update:
        print('Now doing updates')

        # get the service pointer that is already authorized to do the updates
        service = pf.service
        list(map(lambda x: BirthdayHelper.update_contact(service, x), ppl_to_update))
    else:
        print('\n\n\n'
              'If you accept these changes, then change k_do_update to True at the top of the file\n\n')

if __name__ == '__main__':
    main()
