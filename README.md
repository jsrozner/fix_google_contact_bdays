# Background
Sometime recently, mac OS and iOS contacts stopped synchronizing
with google contacts under various circumstances.
It appears those circumstances are when a year is missing from the
bday or when Google has not been able to parse a date object
from the inputted birthday string.

This code will address that by updating birthdays at
contacts.google.com as follows below.

# Running
1. Follow the instructions at [google People API](https://developers.google.com/people/v1/getting-started)
to enable API access.
   
2. Set up environment 


## Code details
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