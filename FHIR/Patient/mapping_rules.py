"""Hand-authored mapping rules: FileMan file #2 (PATIENT) field -> FHIR R4 Patient.

Every field in dd2_fields.json must resolve to exactly one rule here; build_mapping.py
enforces that and renders MAPPING.md / mapping.json from these tables.

Status values
  mapped                  FHIR R4 Patient core element
  mapped-extension        standard HL7 / US Core extension on Patient
  mapped-local-extension  extension defined by this package (no standard one exists)
  no-equivalent           flagged: nothing on FHIR Patient. `candidate` names where the
                          data would go in FHIR (another resource, Provenance, or none).
"""
import re

MAPPED = "mapped"
EXT = "mapped-extension"
LOCAL = "mapped-local-extension"
NONE = "no-equivalent"

LOCAL_EXT_BASE = "http://va.gov/fhir/StructureDefinition/vista-patient-"

# --- explicit rules for root file #2 fields ---------------------------------------------
# field -> (status, fhir element / candidate, note)
ROOT = {
    ".01": (MAPPED, "Patient.name[use=official] (family/given/suffix parsed from LAST,FIRST MIDDLE SUFFIX; text = raw)", ""),
    ".02": (MAPPED, "Patient.gender (M->male, F->female); also us-core-birthsex extension", "FHIR gender is administrative; VistA SEX is the registration value"),
    ".024": (EXT, "Patient.extension[us-core-genderIdentity] (SNOMED CT / NullFlavor)", "M->446151000124109, F->446141000124107, TM->407377005, TF->407376001, O->OTH, N->ASKU"),
    ".03": (MAPPED, "Patient.birthDate", "FileMan imprecise dates keep FHIR partial precision (YYYY or YYYY-MM)"),
    ".033": (NONE, "derived (age = today - birthDate)", "computed field, no storage"),
    ".05": (MAPPED, "Patient.maritalStatus (v3 MaritalStatus)", "file 11 code: D->D, M->M, N->S, S->L, W->W, U->UNK"),
    ".06": (EXT, "Patient.extension[us-core-race] (CDC code from file 10 field 4)", "deprecated single-value field; multiple #2 RACE INFORMATION is preferred"),
    ".07": (NONE, "Observation (ODH Past or Present Job)", "free text"),
    ".08": (EXT, "Patient.extension[patient-religion]", "file 13 has no v3 ReligiousAffiliation code; coding.code = file 13 CODE, display = NAME"),
    ".081": (NONE, "none (duplicate-record bookkeeping)", ""),
    ".082": (MAPPED, "Patient.link[type=replaced-by].other + Patient.active=false", ""),
    ".083": (NONE, "none (duplicate-record bookkeeping)", ""),
    ".09": (MAPPED, "Patient.identifier[system=http://hl7.org/fhir/sid/us-ssn, type=SS]", "pseudo SSN (trailing P) -> identifier.use=temp"),
    ".0901": (NONE, "derived from SSN", "computed field"),
    ".0905": (NONE, "derived from SSN + name", "computed field"),
    ".0906": (NONE, "none", "pseudo-SSN flag itself is carried by identifier.use=temp (derived from .09); the reason has no element"),
    ".0907": (NONE, "none", "verification status of an identifier has no FHIR element"),
    ".091": (NONE, "none (Patient has no note element)", ""),
    ".092": (EXT, "Patient.extension[patient-birthPlace].valueAddress.city", ""),
    ".093": (EXT, "Patient.extension[patient-birthPlace].valueAddress.state", "file 5 ABBREVIATION"),
    ".0931": (EXT, "Patient.extension[patient-birthPlace].valueAddress.country", "file 779.004 CODE (ISO 3166 alpha-3)"),
    ".0932": (EXT, "Patient.extension[patient-birthPlace].valueAddress.state (foreign province)", "only when .093 is empty"),
    ".096": (NONE, "Provenance.agent", ""),
    ".097": (NONE, "Provenance.recorded", ""),
    ".098": (NONE, "none", ""),
    ".109": (NONE, "Consent / Patient.meta.security", "facility directory opt-out; no Patient element"),
    ".1112": (MAPPED, "Patient.address[home,postal].postalCode (preferred over .116 when present)", ""),
    ".1118": (NONE, "none (CASS certification flag)", ""),
    ".111": (MAPPED, "Patient.address[home,postal].line[0]", ""),
    ".112": (MAPPED, "Patient.address[home,postal].line[1]", ""),
    ".113": (MAPPED, "Patient.address[home,postal].line[2]", ""),
    ".114": (MAPPED, "Patient.address[home,postal].city", ""),
    ".115": (MAPPED, "Patient.address[home,postal].state", "file 5 ABBREVIATION"),
    ".116": (MAPPED, "Patient.address[home,postal].postalCode", ""),
    ".117": (MAPPED, "Patient.address[home,postal].district", "county name resolved from file 5 COUNTY subfile; raw number if unresolved"),
    ".1171": (MAPPED, "Patient.address[home,postal].state (foreign province, when .115 empty)", ""),
    ".1172": (MAPPED, "Patient.address[home,postal].postalCode (foreign, when .116/.1112 empty)", ""),
    ".1173": (MAPPED, "Patient.address[home,postal].country", "file 779.004 CODE"),
    ".118": (MAPPED, "Patient.address[home,postal].period.start", ""),
    ".119": (NONE, "Provenance.agent", ""),
    ".12": (NONE, "Provenance.agent", ""),
    ".121": (NONE, "none", "could drive address.use=old; left flagged because HOMELESS/OTHER are not address states"),
    ".122": (NONE, "Provenance.agent", ""),
    ".1151": (MAPPED, "Patient.address[home,physical].line[0]", ""),
    ".1152": (MAPPED, "Patient.address[home,physical].line[1]", ""),
    ".1153": (MAPPED, "Patient.address[home,physical].line[2]", ""),
    ".1154": (MAPPED, "Patient.address[home,physical].city", ""),
    ".1155": (MAPPED, "Patient.address[home,physical].state", ""),
    ".1156": (MAPPED, "Patient.address[home,physical].postalCode", ""),
    ".1157": (MAPPED, "Patient.address[home,physical].district", ""),
    ".11571": (MAPPED, "Patient.address[home,physical].state (foreign province)", ""),
    ".11572": (MAPPED, "Patient.address[home,physical].postalCode (foreign)", ""),
    ".11573": (MAPPED, "Patient.address[home,physical].country", ""),
    ".1158": (MAPPED, "Patient.address[home,physical].period.start", ""),
    ".11581": (NONE, "Provenance.agent", ""),
    ".11582": (NONE, "Provenance.agent", ""),
    ".1159": (NONE, "none (CASS certification flag)", ""),
    ".12105": (MAPPED, "gate: Patient.address[temp] emitted only when Y", ""),
    ".1211": (MAPPED, "Patient.address[temp].line[0]", ""),
    ".1212": (MAPPED, "Patient.address[temp].line[1]", ""),
    ".1213": (MAPPED, "Patient.address[temp].line[2]", ""),
    ".1214": (MAPPED, "Patient.address[temp].city", ""),
    ".1215": (MAPPED, "Patient.address[temp].state", ""),
    ".1216": (MAPPED, "Patient.address[temp].postalCode", ""),
    ".12111": (MAPPED, "Patient.address[temp].district", ""),
    ".12112": (MAPPED, "Patient.address[temp].postalCode (preferred over .1216)", ""),
    ".1217": (MAPPED, "Patient.address[temp].period.start", ""),
    ".1218": (MAPPED, "Patient.address[temp].period.end", ""),
    ".1219": (MAPPED, "Patient.telecom[phone,use=temp]", ""),
    ".1221": (MAPPED, "Patient.address[temp].state (foreign province)", ""),
    ".1222": (MAPPED, "Patient.address[temp].postalCode (foreign)", ""),
    ".1223": (MAPPED, "Patient.address[temp].country", ""),
    ".12113": (NONE, "Provenance.recorded", ""),
    ".12114": (NONE, "Provenance.agent", ""),
    ".12115": (NONE, "none (CASS certification flag)", ""),
    ".131": (MAPPED, "Patient.telecom[phone,use=home]", ""),
    ".132": (MAPPED, "Patient.telecom[phone,use=work]", ""),
    ".133": (MAPPED, "Patient.telecom[email]", ""),
    ".134": (MAPPED, "Patient.telecom[phone,use=mobile]", ""),
    ".135": (MAPPED, "Patient.telecom[pager]", ""),
    ".1315": (LOCAL, "Patient.telecom[phone] + extension vista-patient-confidential-telecom=true", "FHIR ContactPoint.use has no 'confidential'"),
    ".1316": (NONE, "none", "indicator that an email was asked for; no element"),
    ".1317": (NONE, "Provenance.recorded", ""),
    ".1321": (MAPPED, "Patient.telecom[phone,home].period.start", ""),
    ".139": (MAPPED, "Patient.telecom[phone,mobile].period.start", ""),
    ".1312": (MAPPED, "Patient.telecom[pager].period.start", ""),
    ".136": (MAPPED, "Patient.telecom[email].period.start", ""),
    ".14": (NONE, "Coverage / VA means test", ""),
    ".141": (LOCAL, "Patient.address[confidential].extension vista-patient-confidential-address-category (one per active category)", "subfile 2.141"),
    ".14105": (MAPPED, "gate: confidential Patient.address emitted only when Y", ""),
    ".1411": (LOCAL, "Patient.address[postal + confidential extension].line[0]", ""),
    ".1412": (LOCAL, "Patient.address[confidential].line[1]", ""),
    ".1413": (LOCAL, "Patient.address[confidential].line[2]", ""),
    ".1414": (LOCAL, "Patient.address[confidential].city", ""),
    ".1415": (LOCAL, "Patient.address[confidential].state", ""),
    ".1416": (LOCAL, "Patient.address[confidential].postalCode", ""),
    ".1417": (LOCAL, "Patient.address[confidential].period.start", ""),
    ".1418": (LOCAL, "Patient.address[confidential].period.end", ""),
    ".14111": (LOCAL, "Patient.address[confidential].district", ""),
    ".14114": (LOCAL, "Patient.address[confidential].state (foreign province)", ""),
    ".14115": (LOCAL, "Patient.address[confidential].postalCode (foreign)", ""),
    ".14116": (LOCAL, "Patient.address[confidential].country", ""),
    ".14112": (NONE, "Provenance.recorded", ""),
    ".14113": (NONE, "Provenance.agent", ""),
    ".14117": (NONE, "none (CASS certification flag)", ""),
    ".19": (NONE, "derived", "computed field"),
    ".2403": (EXT, "Patient.extension[patient-mothersMaidenName]", ""),
    ".2405": (MAPPED, "Patient.name[use=usual].given[0] (text = raw)", ""),
    ".2401": (NONE, "RelatedPerson", ""),
    ".2402": (NONE, "RelatedPerson", ""),
    ".313": (MAPPED, "Patient.identifier[system=urn:oid:2.16.840.1.113883.4.349 is ICN; claim number uses http://va.gov/identifier/claim-number]", "VA claim (C-file) number"),
    ".383": (MAPPED, "Patient.identifier[type=MA (Medicaid number)]", ""),
    ".351": (MAPPED, "Patient.deceasedDateTime", "absent -> deceasedBoolean omitted"),
    ".6": (MAPPED, "Patient.meta.security[HTEST] when 1", ""),
    "1": (MAPPED, "Patient.name (one per alias; subfile 2.01)", ""),
    "1.01": (MAPPED, "Patient.name[use=official] family/given/prefix/suffix from file 20 components (overrides parse of .01)", ""),
    "1.04": (NONE, "RelatedPerson.name", ""),
    "1.05": (NONE, "RelatedPerson.name", ""),
    "1.06": (EXT, "Patient.extension[patient-mothersMaidenName] (family component preferred over .2403 text)", ""),
    "2": (EXT, "Patient.extension[us-core-race] ombCategory/detailed/text (subfile 2.02)", ""),
    "6": (EXT, "Patient.extension[us-core-ethnicity] ombCategory/text (subfile 2.06)", ""),
    "7": (MAPPED, "Patient.communication.language (+ preferred=true on the newest entry; subfile 2.07)", "VistA stores free text; BCP-47 code set when text matches the bundled lookup"),
    "27.02": (MAPPED, "Patient.managingOrganization (Reference to Organization for file 4 entry)", "field is marked deprecated (*) in the DD"),
    "404.01": (MAPPED, "Patient.generalPractitioner (Reference to Practitioner for file 200 entry)", "field is marked deprecated (*) in the DD"),
    "404.02": (NONE, "CareTeam", "generalPractitioner cannot reference a team"),
    "991.01": (MAPPED, "Patient.identifier[system=urn:oid:2.16.840.1.113883.4.349 (VA ICN), type=NI]", "ICN without checksum"),
    "991.02": (MAPPED, "folded into FULL ICN identifier value (ICN V checksum)", ""),
    "991.04": (MAPPED, "Patient.identifier[ICN].use = temp when 1 (locally assigned)", ""),
    "991.1": (MAPPED, "Patient.identifier[ICN].value (preferred form when present)", ""),
    "991.08": (MAPPED, "Patient.identifier[system=http://va.gov/identifier/mpi-temporary-id, use=temp]", ""),
    "991.09": (MAPPED, "Patient.identifier[system=http://va.gov/identifier/mpi-foreign-id]", ""),
    "991.91": (MAPPED, "Patient.identifier[ICN, use=old] (subfile 2.0991)", ""),
    "992": (MAPPED, "Patient.identifier[ICN, use=old] (subfile 2.0992)", ""),
    "994": (MAPPED, "Patient.multipleBirthBoolean (Y->true, N->false)", ""),
    "1901": (LOCAL, "Patient.extension[vista-patient-veteran-indicator] valueBoolean", "no standard FHIR R4 element for veteran status"),
    "537025": (NONE, "none", "My HealtheVet network identifier; semantics not documented in the DD"),
}

# Contact blocks: K (primary next of kin), K2 (secondary NOK), E (emergency), E2 (secondary emergency), D (designee),
# plus employer and the two guardian blocks. Each becomes one Patient.contact.
def _contact(prefix, fields):
    for fld, element in fields.items():
        ROOT[fld] = (MAPPED, f"Patient.contact[{prefix}].{element}", "")

_contact("relationship=N next-of-kin", {
    ".211": "name.text", ".212": "relationship.text", ".213": "address.line[0]", ".214": "address.line[1]",
    ".215": "address.line[2]", ".216": "address.city", ".217": "address.state", ".218": "address.postalCode",
    ".2207": "address.postalCode (preferred)", ".219": "telecom[phone,home]", ".21011": "telecom[phone,work]",
    ".2125": "address (copied from patient when Y)", ".21012": "period.start",
    "1.02": "name family/given from file 20 components",
})
_contact("relationship=N next-of-kin #2", {
    ".2191": "name.text", ".2192": "relationship.text", ".2193": "address.line[0]", ".2194": "address.line[1]",
    ".2195": "address.line[2]", ".2196": "address.city", ".2197": "address.state", ".2198": "address.postalCode",
    ".2203": "address.postalCode (preferred)", ".2199": "telecom[phone,home]", ".211011": "telecom[phone,work]",
    ".21925": "address (copied from patient when Y)", ".211012": "period.start",
    "1.03": "name family/given from file 20 components",
})
_contact("relationship=C emergency", {
    ".331": "name.text", ".332": "relationship.text", ".333": "address.line[0]", ".334": "address.line[1]",
    ".335": "address.line[2]", ".336": "address.city", ".337": "address.state", ".338": "address.postalCode",
    ".2201": "address.postalCode (preferred)", ".339": "telecom[phone,home]", ".33011": "telecom[phone,work]",
    ".3305": "contact copied from next-of-kin when Y", ".33012": "period.start",
    "1.07": "name family/given from file 20 components",
})
_contact("relationship=C emergency #2", {
    ".3311": "name.text", ".3312": "relationship.text", ".3313": "address.line[0]", ".3314": "address.line[1]",
    ".3315": "address.line[2]", ".3316": "address.city", ".3317": "address.state", ".3318": "address.postalCode",
    ".2204": "address.postalCode (preferred)", ".3319": "telecom[phone,home]", ".331011": "telecom[phone,work]",
    ".33112": "period.start",
    "1.08": "name family/given from file 20 components",
})
_contact("relationship=O other, text=Designee", {
    ".341": "name.text", ".342": "relationship.text", ".343": "address.line[0]", ".344": "address.line[1]",
    ".345": "address.line[2]", ".346": "address.city", ".347": "address.state", ".348": "address.postalCode",
    ".2202": "address.postalCode (preferred)", ".349": "telecom[phone,home]", ".34011": "telecom[phone,work]",
    ".3405": "contact copied from next-of-kin when Y", ".3412": "period.start",
    "1.09": "name family/given from file 20 components",
})
_contact("relationship=E employer", {
    ".3111": "organization.display", ".3113": "address.line[0]", ".3114": "address.line[1]", ".3115": "address.line[2]",
    ".3116": "address.city", ".3117": "address.state", ".3118": "address.postalCode", ".2205": "address.postalCode (preferred)",
    ".3119": "telecom[phone,work]",
})
_contact("relationship=GUARD (VA)", {
    ".2912": "name.text", ".2913": "relationship.text", ".2914": "address.line[0]", ".2915": "address.line[1]",
    ".2916": "address.city", ".2917": "address.state", ".2918": "address.postalCode", ".29013": "address.postalCode (preferred)",
    ".2919": "telecom[phone]", ".2911": "organization (Reference to file 4 entry)", ".291": "period.start (date ruled incompetent)",
})
_contact("relationship=GUARD (civil)", {
    ".2922": "name.text", ".2923": "relationship.text", ".2924": "address.line[0]", ".2925": "address.line[1]",
    ".2926": "address.city", ".2927": "address.state", ".2928": "address.postalCode", ".290012": "address.postalCode (preferred)",
    ".2929": "telecom[phone]", ".2921": "organization.display", ".292": "period.start (date ruled incompetent)",
})

# --- pattern rules for everything not listed above (root file) -----------------------------
# (regex on field number, candidate, note). All are NONE.
PATTERNS = [
    (r"^\.10[0-9]*$|^\.1$", "Encounter / Location (inpatient status)", "current inpatient ward, bed, movement, provider"),
    (r"^\.13(1[1-4]|11|22|23|7|8)$|^\.13111$", "Provenance.agent / recorded", "telecom change audit"),
    (r"^\.15[23]$|^\.16$|^\.165", "Flag / VA eligibility", "missing-person and ineligible status"),
    (r"^\.172$", "none", "fee basis hospital ID card status"),
    (r"^\.181$", "none", "disaster response indicator"),
    (r"^\.220[56]$|^\.25", "RelatedPerson (spouse) / Observation ODH", "spouse employment"),
    (r"^\.293$", "none", "incompetency rating"),
    (r"^\.30|^\.31$|^\.309$", "Coverage / Condition (VA service connection and benefits)", ""),
    (r"^\.3111[56]$|^\.3112$", "Observation (ODH Employment Status)", "employment status / retirement date"),
    (r"^\.312$|^\.314$", "none", "VA claim folder location"),
    (r"^\.3121$|^\.3192$", "Coverage", "insurance"),
    (r"^\.32|^\.52|^\.53|^\.54", "none (VA military service history; VA uses local extensions / MilitaryServiceEpisode)", ""),
    (r"^\.35[2-8]$", "Provenance (death record audit)", ""),
    (r"^\.36|^\.37", "Coverage / Condition (VA eligibility, income, dental, rated disabilities)", ""),
    (r"^\.38", "Coverage (Medicaid, pension)", ""),
    (r"^\.39|^\.40", "Condition (catastrophic disability)", ""),
    (r"^3$|^25\.0[12]$|^27\.0[13]$|^361$", "EpisodeOfCare / Coverage (enrollment)", ""),
    (r"^53$", "AllergyIntolerance", "deprecated"),
    (r"^57\.[12]$", "Observation (vital signs)", "deprecated"),
    (r"^57\.4$", "Condition", ""),
    (r"^6[37]$", "none (Lab package back-pointer)", ""),
    (r"^148$", "none (community nursing home)", ""),
    (r"^220", "Coverage (dental eligibility)", ""),
    (r"^391$", "none", "VA patient type (e.g. SC VETERAN, EMPLOYEE, COLLATERAL)"),
    (r"^401\.[34]$", "Flag (seriously ill list)", ""),
    (r"^534$", "none (Purple Heart audit)", ""),
    (r"^991\.0[3567]$|^993$", "none (Master Patient Index bookkeeping)", ""),
    (r"^999", "derived", "computed field"),
    (r"^1000$", "Encounter (disposition log)", ""),
    (r"^1010\.", "none (10-10EZ application tracking)", ""),
    (r"^1100\.", "Flag (fugitive felon)", ""),
    (r"^1900$", "Appointment", ""),
    (r"^1903$", "none (archive bookkeeping)", ""),
    (r"^2001$", "none (insurance capture buffer run date)", ""),
    (r"^3000$", "none (Veterans Transportation Service flag)", ""),
    (r"^11500\.", "none (Operation Desert Storm)", ""),
    (r"^5370(2[6-9]|3[0-9]|4[12])$", "none (My HealtheVet registration)", ""),
    (r"^\.11[0-9]*$|^\.12|^\.14", "Provenance", "address change audit"),
]

# --- subfile rules -------------------------------------------------------------------------
# (subfile, field) -> (status, element, note). Subfiles not listed inherit the parent's rule.
SUBFILE = {
    ("2.01", ".01"): (MAPPED, "Patient.name (alias; text = raw, family/given parsed)", ""),
    ("2.01", "1"): (MAPPED, "Patient.identifier[us-ssn, use=old]", "alias SSN"),
    ("2.01", "100.03"): (MAPPED, "Patient.name (alias) family/given from file 20 components", ""),
    ("2.02", ".01"): (EXT, "Patient.extension[us-core-race].ombCategory|detailed (CDC code), .text", ""),
    ("2.02", ".02"): (NONE, "none", "collection method; no extension slot"),
    ("2.06", ".01"): (EXT, "Patient.extension[us-core-ethnicity].ombCategory (CDC code), .text", ""),
    ("2.06", ".02"): (NONE, "none", "collection method; no extension slot"),
    ("2.07", ".01"): (MAPPED, "selects Patient.communication.preferred (newest date wins)", ""),
    ("2.07", ".02"): (MAPPED, "Patient.communication.language.text (+ BCP-47 coding when known)", ""),
    ("2.141", ".01"): (LOCAL, "Patient.address[confidential].extension vista-patient-confidential-address-category.valueCode", ""),
    ("2.141", "1"): (LOCAL, "gate: category emitted only when Y", ""),
    ("2.0991", ".01"): (MAPPED, "Patient.identifier[ICN, use=old]", ""),
    ("2.0992", ".01"): (MAPPED, "Patient.identifier[ICN, use=old].value", ""),
    ("2.0992", "1"): (MAPPED, "folded into identifier value (ICN V checksum)", ""),
    ("2.0992", "2"): (NONE, "none (MPI bookkeeping)", ""),
    ("2.0992", "3"): (MAPPED, "Patient.identifier[ICN, use=old].period.end", ""),
}

# parent multiple field for each subfile number (filled by build_mapping from the DD)
def resolve_root(field):
    if field in ROOT:
        status, element, note = ROOT[field]
        return {"status": status, "fhir": element if status != NONE else "", "candidate": element if status == NONE else "", "note": note}
    for pat, candidate, note in PATTERNS:
        if re.search(pat, field):
            return {"status": NONE, "fhir": "", "candidate": candidate, "note": note}
    raise KeyError(f"no mapping rule for file 2 field {field}")


def resolve_subfile(subfile, field, parent_rule):
    if (subfile, field) in SUBFILE:
        status, element, note = SUBFILE[(subfile, field)]
        return {"status": status, "fhir": element if status != NONE else "", "candidate": element if status == NONE else "", "note": note}
    note = f"subfile {subfile}; follows parent field rule"
    if parent_rule["status"] == NONE:
        return {"status": NONE, "fhir": "", "candidate": parent_rule["candidate"], "note": note}
    raise KeyError(f"mapped multiple {subfile} has unmapped field {field}")
