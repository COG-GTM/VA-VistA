# VistA PATIENT (file #2) to FHIR R4 Patient

| File | What it is |
|---|---|
| `MAPPING.md` | Field-by-field table: every field of FileMan file #2 and its subfiles -> FHIR R4 Patient element, or **NO FHIR EQUIVALENT** with the resource the data belongs in. Each row links the MUMPS line (`^DD(2,<field>,0)`) in `DD.zwr` and any local KIDS patch that carries the field. |
| `mapping.json` | Same content, machine-readable (`counts`, `fields[]`). |
| `mapping_rules.py` | The hand-authored rules. Edit this, then run `build_mapping.py`. |
| `build_mapping.py` | Joins `dd2_fields.json` with the rules and regenerates `mapping.json` + `MAPPING.md`. Fails if any DD field lacks a rule. |
| `dd2_fields.json` | Parsed `^DD` definitions (name, FileMan type, codes/pointer, global location, `DD.zwr` line, KIDS citations) for file #2 and its 47 subfiles. |
| `DD-2-extract.zwr` | The 17,256 `^DD` lines for file #2 and subfiles, each prefixed with its line number in the upstream `DD.zwr`, so citations can be checked offline. |
| `vista_patient_to_fhir.py` | The transform. `transform(record, lookups, dfn)` returns a FHIR Patient dict; `transform_with_report()` also returns the input fields that were flagged as having no equivalent. |
| `tests/` | pytest suite (synthetic data only). |

Source of the data dictionary: `Packages/VA FileMan/Globals/DD.zwr` in
[WorldVistA/VistA-M @ b7aecb9](https://github.com/WorldVistA/VistA-M/blob/b7aecb9029f9bb8639a7bfa63b635469065ab44d/Packages/VA%20FileMan/Globals/DD.zwr).
This repository carries KIDS patch builds, not the global export, so the full dictionary had to come from VistA-M; where a
local patch also defines a field, `MAPPING.md` links that file and line too.

## Run

```sh
cd FHIR/Patient
python3 -m pytest tests -q
python3 build_mapping.py                      # regenerate mapping.json + MAPPING.md
echo '{"dfn":"7","record":{".01":"DOE,JANE",".02":"F",".03":"2500704",".07":"WELDER"}}' | python3 vista_patient_to_fhir.py
```

No third-party dependencies (Python 3.8+ standard library).

## Input contract

`record` is a dict keyed by FileMan field number holding internal values exactly as stored in `^DPT(DFN,node)` pieces;
multiples are lists of dicts keyed by subfile field number. Pointer fields hold the IEN; pass a `Lookups` object to resolve
them (state abbreviation, ISO country code, CDC race/ethnicity code, marital status letter, religion code, name components
from file 20). Unresolved pointers fall back to the raw value rather than being dropped.

FHIR `dateTime` needs a time zone whenever a time of day is present and VistA stores local time without one, so
`Lookups.timezone_offset` (e.g. `"-05:00"`) must be supplied to keep times; otherwise date/times are truncated to the date.

## Mapping decisions worth knowing

- `.02 SEX` -> `Patient.gender` and the US Core `birthsex` extension; `.024 SELF IDENTIFIED GENDER` -> US Core `genderIdentity`.
- Race and ethnicity use the US Core extensions with CDC codes from files 10 / 10.2 (field 4 CDC VALUE); `0000-0` and `9999-4` become NullFlavor `ASKU` / `UNK`.
- Four VistA address blocks become four `Patient.address` entries: permanent (`home`/`postal`), residential (`home`/`physical`), temporary (`temp`, only when `.12105 = Y`, with period), confidential (only when `.14105 = Y`, categories carried in a local extension).
- Next of kin, secondary NOK, emergency contacts, designee, employer and both guardian blocks become `Patient.contact` with v2-0131 / v3 RoleCode relationships. The "same as NOK/patient" flags copy data as VistA intends.
- Identifiers: DFN, SSN (pseudo SSN -> `use=temp`), ICN (full form with checksum; history as `use=old`), claim number, Medicaid number, MPI temporary/foreign IDs, alias SSNs.
- `.082 PATIENT MERGED TO` -> `Patient.link[replaced-by]` and `active=false`; `.6 TEST PATIENT` -> `meta.security HTEST`.
- Veteran status (`1901`) and confidential phone (`.1315`) have no standard FHIR R4 representation and use local extensions under `http://va.gov/fhir/StructureDefinition/vista-patient-*`.
- Everything military-service, eligibility, means-test, insurance, enrollment, inpatient-status, employment-status, and audit-trail related is flagged **NO FHIR EQUIVALENT** with the resource (Coverage, Condition, Encounter, Provenance, ...) it belongs in.
