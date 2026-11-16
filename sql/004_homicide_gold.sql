-- Template fields remain strings until the research coding schema is defined.
CREATE TABLE homicide_research.research.homicide_gold (
  `Date Of Incident` STRING,
  `Date Of Death` STRING,
  `Victim Name_First` STRING,
  `Victim Name_Last` STRING,
  `Victim Gender` STRING,
  `Victim Age` STRING,
  `Victim Race` STRING,
  `Victim Ethnicity` STRING,
  `Offender Name_First` STRING,
  `Offender Name_Last` STRING,
  `Offender Gender` STRING,
  `Offender Age` STRING,
  `Offender Race` STRING,
  `Offender Ethnicity` STRING,
  `Incident Information_Location` STRING,
  `NatureOfDeath` STRING,
  `Incident Information_Choice` STRING,
  `If a Firearm Was Used, Who Owned It?` STRING,
  `If Offender Died By Suicide, What Weapon method Was Used?` STRING
) USING DELTA
TBLPROPERTIES ('delta.columnMapping.mode' = 'id');
