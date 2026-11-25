"""Shared field contract inspected from the existing homicide_gold table."""

GOLD_FIELDS = ('Date Of Incident', 'Date Of Death', 'Victim Name_First', 'Victim Name_Last', 'Victim Gender', 'Victim Age', 'Victim Race', 'Victim Ethnicity', 'Offender Name_First', 'Offender Name_Last', 'Offender Gender', 'Offender Age', 'Offender Race', 'Offender Ethnicity', 'Incident Information_Location', 'NatureOfDeath', 'Incident Information_Choice', 'If a Firearm Was Used, Who Owned It?', 'If Offender Died By Suicide, What Weapon method Was Used?', 'case_id')
CODEBOOK_VERSION = "gold-reported-text-v1"


def gold_field(name):
    """Map exact canonical names and unambiguous legacy fields only."""
    if name in GOLD_FIELDS:
        return name
    subject, separator, field = name.partition('.')
    if separator and field in GOLD_FIELDS:
        return field
    if not separator:
        field = name
    incident = {'incident_date': 'Date Of Incident', 'death_date': 'Date Of Death',
                'location': 'Incident Information_Location', 'manner': 'NatureOfDeath'}
    if field in incident:
        return incident[field]
    person = {'age': 'Age', 'gender': 'Gender', 'race': 'Race', 'ethnicity': 'Ethnicity',
              'first_name': 'Name_First', 'last_name': 'Name_Last'}
    if separator and field in person:
        if subject.startswith('victim_'):
            return 'Victim ' + person[field]
        if subject.startswith('offender_'):
            return 'Offender ' + person[field]
    return None
