"""The first gold-layer field scope, as named in the researcher template."""

HIGHLIGHTED_FIELDS = (
    "Date Of Incident", "Date Of Death", "Victim Name_First", "Victim Name_Last",
    "Victim Gender", "Victim Age", "Victim Race", "Victim Ethnicity",
    "Offender Name_First", "Offender Name_Last", "Offender Gender", "Offender Age",
    "Offender Race", "Offender Ethnicity", "Incident Information_Location",
    "NatureOfDeath", "Incident Information_Choice", "If a Firearm Was Used, Who Owned It?",
    "If Offender Died By Suicide, What Weapon method Was Used?",
)


def collect_claims(claims, sources):
    """Validate attributed claims and retain disagreements without selecting a value."""
    fields = {name: {"value": None, "status": "missing", "claims": []} for name in HIGHLIGHTED_FIELDS}
    for claim in claims:
        field = claim.get("field")
        if field not in fields:
            raise ValueError("Claim field is outside the highlighted scope.")
        value, passage = claim.get("value"), claim.get("passage")
        source = sources.get(claim.get("source_id"))
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Claims must have a nonempty value.")
        if not isinstance(passage, str) or not passage.strip() or not source or not source.get("url") or passage not in source.get("text", ""):
            raise ValueError("Claims must cite an exact passage from a supplied source.")
        evidence = {"value": value.strip(), "source_id": claim["source_id"],
                    "url": source["url"], "passage": passage}
        if evidence not in fields[field]["claims"]:
            fields[field]["claims"].append(evidence)
    for field in fields.values():
        values = {c["value"].casefold() for c in field["claims"]}
        if len(values) == 1:
            field.update(value=field["claims"][0]["value"], status="reported")
        elif len(values) > 1:
            field["status"] = "conflicting"
    return fields
