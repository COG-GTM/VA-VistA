"""Tests for the file #2 (PATIENT) -> FHIR R4 Patient transform. All data is synthetic."""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import vista_patient_to_fhir as t  # noqa: E402
import build_mapping  # noqa: E402

LK = t.Lookups(
    state={"5": {"name": "CALIFORNIA", "abbreviation": "CA"}, "48": {"name": "TEXAS", "abbreviation": "TX"}},
    county={("5", "37"): "LOS ANGELES"},
    country={"1": "USA", "77": "DEU"},
    marital_status={"1": "D", "2": "M", "3": "N", "4": "S", "5": "W", "6": "U"},
    race={"3": {"name": "ASIAN", "cdc": "2028-9"}, "7": {"name": "WHITE", "cdc": "2106-3"},
          "9": {"name": "DECLINED TO ANSWER", "cdc": "0000-0"}, "12": {"name": "FILIPINO", "cdc": "2036-2"}},
    ethnicity={"1": {"name": "HISPANIC OR LATINO", "cdc": "2135-2"}, "4": {"name": "UNKNOWN BY PATIENT", "cdc": "9999-4"}},
    religion={"22": {"name": "LUTHERAN", "code": "22"}},
    institution={"500": "ALBANY VAMC"},
    new_person={"1234": "PROVIDER,ONE"},
    name_components={"77": {"family": "SMITH", "given": "JOHN", "middle": "ADAM", "prefix": "MR", "suffix": "JR", "degree": "PHD"},
                     "78": {"family": "JONES", "given": "MARY"}},
    timezone_offset="-05:00",
)


def ids(p, system=None, use=None):
    return [i for i in p.get("identifier", []) if (system is None or i.get("system") == system) and (use is None or i.get("use") == use)]


def ext(p, url):
    return [e for e in p.get("extension", []) if e["url"] == url]


# ---- primitives -------------------------------------------------------------------------
@pytest.mark.parametrize("fm, tz, expected", [
    ("2500704", None, "1950-07-04"),
    ("3100700", None, "2010-07"),
    ("3100000", None, "2010"),
    ("3100704.1530", None, "2010-07-04"),            # no zone -> time dropped
    ("3100704.1530", "-05:00", "2010-07-04T15:30:00-05:00"),
    ("3100704.153045", "Z", "2010-07-04T15:30:45Z"),
    ("3100704.24", "Z", "2010-07-04T00:00:00Z"),
    ("", None, None), (None, None, None), ("garbage", None, None), ("20100704", None, None),
])
def test_fileman_date(fm, tz, expected):
    assert t.fileman_date(fm, tz) == expected


@pytest.mark.parametrize("raw, family, given, suffix", [
    ("SMITH,JOHN A JR", "SMITH", ["JOHN", "A"], ["JR"]),
    ("O'BRIEN-DOE,MARY ANN", "O'BRIEN-DOE", ["MARY", "ANN"], None),
    ("DOE,JOHN III", "DOE", ["JOHN"], ["III"]),
    ("CHER", "CHER", None, None),
    ("DOE,JR", "DOE", ["JR"], None),   # single token after comma is a given name, not a suffix
])
def test_parse_vista_name(raw, family, given, suffix):
    n = t.parse_vista_name(raw)
    assert n["text"] == raw and n["family"] == family
    assert n.get("given") == given and n.get("suffix") == suffix


# ---- demographics -----------------------------------------------------------------------
def test_core_demographics():
    rec = {".01": "SMITH,JOHN A JR", ".02": "M", ".03": "2500704", ".05": "2", ".351": "3200101.1430", "994": "Y", ".6": "1"}
    p = t.transform(rec, LK, dfn="100", station="500")
    assert p["resourceType"] == "Patient" and p["id"] == "100"
    assert p["name"][0] == {"use": "official", "text": "SMITH,JOHN A JR", "family": "SMITH", "given": ["JOHN", "A"], "suffix": ["JR"]}
    assert p["gender"] == "male"
    assert ext(p, t.EXT_BIRTHSEX)[0]["valueCode"] == "M"
    assert p["birthDate"] == "1950-07-04"
    assert p["deceasedDateTime"] == "2020-01-01T14:30:00-05:00"
    assert p["multipleBirthBoolean"] is True
    assert p["maritalStatus"]["coding"][0] == {"system": t.V3_MARITAL, "code": "M", "display": "Married"}
    assert p["meta"]["security"][0]["code"] == "HTEST"
    assert "deceasedBoolean" not in p and "active" not in p
    dfn = ids(p, t.SYS_DFN + "/500")[0]
    assert dfn["value"] == "100" and dfn["type"]["coding"][0]["code"] == "PI"


def test_marital_status_codes():
    for ien, code in (("1", "D"), ("3", "S"), ("4", "L"), ("5", "W"), ("6", "UNK")):
        assert t.transform({".05": ien}, LK)["maritalStatus"]["coding"][0]["code"] == code
    assert t.transform({".05": "42"}, LK)["maritalStatus"] == {"text": "42"}   # unresolved pointer kept


def test_gender_values():
    assert t.transform({".02": "F"})["gender"] == "female"
    assert t.transform({".02": "X"})["gender"] == "unknown"
    assert "gender" not in t.transform({})
    gi = ext(t.transform({".024": "TF"}), t.EXT_GENDER_IDENTITY)[0]["valueCodeableConcept"]["coding"][0]
    assert gi == {"system": t.SNOMED, "code": "407376001", "display": "Male-to-female transsexual"}
    gi = ext(t.transform({".024": "N"}), t.EXT_GENDER_IDENTITY)[0]["valueCodeableConcept"]["coding"][0]
    assert gi["system"] == t.V3_NULL and gi["code"] == "ASKU"


def test_name_components_override_parse_and_aliases():
    rec = {".01": "SMITH,JOHN A JR", "1.01": "77", ".2405": "JOHNNY",
           "1": [{".01": "SMYTHE,JOHN", "1": "987654321"}, {".01": "JONES,MARY", "100.03": "78"}]}
    p = t.transform(rec, LK)
    official = p["name"][0]
    assert official["prefix"] == ["MR"] and official["given"] == ["JOHN", "ADAM"] and official["suffix"] == ["JR", "PHD"]
    assert p["name"][1] == {"use": "usual", "text": "JOHNNY", "given": ["JOHNNY"]}
    assert p["name"][2]["family"] == "SMYTHE" and "use" not in p["name"][2]
    assert p["name"][3] == {"text": "JONES,MARY", "family": "JONES", "given": ["MARY"]}
    alias_ssn = ids(p, t.SID_SSN, "old")
    assert alias_ssn[0]["value"] == "987654321"


# ---- identifiers ------------------------------------------------------------------------
def test_ssn_and_pseudo_ssn():
    p = t.transform({".09": "123456789"})
    s = ids(p, t.SID_SSN)[0]
    assert s["use"] == "official" and s["value"] == "123456789" and s["type"]["coding"][0]["code"] == "SS"
    p = t.transform({".09": "123456789P", ".0906": "R"})
    assert ids(p, t.SID_SSN)[0]["use"] == "temp" and ids(p, t.SID_SSN)[0]["value"] == "123456789"


def test_icn_identifiers():
    p = t.transform({"991.01": "1008596379", "991.02": "765432"})
    icn = ids(p, t.OID_ICN)[0]
    assert icn["value"] == "1008596379V765432" and icn["use"] == "official" and icn["type"]["coding"][0]["code"] == "NI"
    p = t.transform({"991.01": "1008596379", "991.02": "765432", "991.1": "1008596379V765432", "991.04": "1"})
    assert ids(p, t.OID_ICN)[0]["use"] == "temp" and len(ids(p, t.OID_ICN)) == 1
    p = t.transform({"991.1": "1V2", "991.91": [{".01": "3V4"}], "992": [{".01": "5", "1": "6", "3": "3150101"}]}, LK)
    old = ids(p, t.OID_ICN, "old")
    assert [o["value"] for o in old] == ["3V4", "5V6"]
    assert old[1]["period"] == {"end": "2015-01-01"}


def test_other_identifiers():
    p = t.transform({".313": "C12345678", ".383": "MA-1", "991.08": "T1", "991.09": "F1"})
    assert ids(p, t.SYS_CLAIM)[0]["value"] == "C12345678"
    assert [i for i in p["identifier"] if i.get("type", {}).get("coding", [{}])[0].get("code") == "MA"][0]["value"] == "MA-1"
    assert ids(p, t.SYS_MPI_TEMP)[0]["use"] == "temp"
    assert ids(p, t.SYS_MPI_FOREIGN)[0]["value"] == "F1"


# ---- addresses & telecom ----------------------------------------------------------------
def test_permanent_and_residential_addresses():
    rec = {".111": "1 MAIN ST", ".112": "APT 2", ".114": "LOS ANGELES", ".115": "5", ".116": "90001", ".1112": "900011234",
           ".117": "37", ".1173": "1", ".118": "3180315",
           ".1151": "9 PHYSICAL RD", ".1154": "AUSTIN", ".1155": "48", ".1156": "78701", ".11573": "1"}
    p = t.transform(rec, LK)
    perm, res = p["address"]
    assert perm == {"use": "home", "type": "postal", "line": ["1 MAIN ST", "APT 2"], "city": "LOS ANGELES", "district": "LOS ANGELES",
                    "state": "CA", "postalCode": "900011234", "country": "USA", "period": {"start": "2018-03-15"}}
    assert res["type"] == "physical" and res["state"] == "TX" and res["line"] == ["9 PHYSICAL RD"]


def test_foreign_address_uses_province_and_postal_code():
    p = t.transform({".111": "HAUPTSTR 1", ".114": "BERLIN", ".1171": "BRANDENBURG", ".1172": "10115", ".1173": "77"}, LK)
    assert p["address"][0]["state"] == "BRANDENBURG" and p["address"][0]["postalCode"] == "10115" and p["address"][0]["country"] == "DEU"


def test_temporary_address_gate_and_period():
    base = {".1211": "2 TEMP ST", ".1214": "SOMEWHERE", ".1215": "5", ".1216": "90002", ".1217": "3200601", ".1218": "3200901", ".1219": "555-0000"}
    assert t.transform(dict(base, **{".12105": "N"}), LK).get("address", []) == []
    p = t.transform(dict(base, **{".12105": "Y"}), LK)
    a = p["address"][0]
    assert a["use"] == "temp" and a["period"] == {"start": "2020-06-01", "end": "2020-09-01"}
    assert {"system": "phone", "value": "555-0000", "use": "temp"} in p["telecom"]


def test_confidential_address_carries_categories():
    rec = {".14105": "Y", ".1411": "PO BOX 9", ".1414": "HIDDEN", ".1415": "5", ".1416": "90003",
           ".141": [{".01": "1", "1": "Y"}, {".01": "4", "1": "N"}, {".01": "5", "1": "Y"}]}
    a = t.transform(rec, LK)["address"][0]
    assert a["type"] == "postal" and "use" not in a
    assert [e["valueCoding"]["code"] for e in a["extension"]] == ["1", "5"]
    assert all(e["url"] == t.EXT_CONF_ADDR_CAT for e in a["extension"])
    rec[".14105"] = "N"
    assert t.transform(rec, LK).get("address", []) == []


def test_telecom():
    rec = {".131": "555-1111", ".1321": "3190101", ".132": "555-2222", ".133": "a@b.org", ".136": "3190202.0900",
           ".134": "555-3333", ".135": "555-4444", ".1315": "555-5555"}
    tel = t.transform(rec, LK)["telecom"]
    assert {"system": "phone", "use": "home", "value": "555-1111", "period": {"start": "2019-01-01"}} in tel
    assert {"system": "phone", "use": "work", "value": "555-2222"} in tel
    assert {"system": "email", "value": "a@b.org", "period": {"start": "2019-02-02T09:00:00-05:00"}} in tel
    assert {"system": "phone", "use": "mobile", "value": "555-3333"} in tel
    assert {"system": "pager", "value": "555-4444"} in tel
    conf = [x for x in tel if x["value"] == "555-5555"][0]
    assert conf["extension"] == [{"url": t.EXT_CONF_TELECOM, "valueBoolean": True}]


# ---- contacts ---------------------------------------------------------------------------
def test_next_of_kin_copies_patient_address_when_flagged():
    rec = {".111": "1 MAIN ST", ".114": "LA", ".115": "5", ".116": "90001",
           ".211": "SMITH,JANE", ".212": "WIFE", ".219": "555-1", ".21011": "555-2", ".2125": "Y", ".21012": "3180101", "1.02": "78"}
    c = t.transform(rec, LK)["contact"][0]
    assert c["relationship"][0]["coding"][0]["code"] == "N" and c["relationship"][0]["text"] == "WIFE"
    assert c["name"] == {"text": "SMITH,JANE", "family": "JONES", "given": ["MARY"]}   # file 20 components win
    assert c["address"]["line"] == ["1 MAIN ST"] and c["period"] == {"start": "2018-01-01"}
    assert c["telecom"] == [{"system": "phone", "use": "home", "value": "555-1"}, {"system": "phone", "use": "work", "value": "555-2"}]


def test_emergency_and_designee_copy_from_nok():
    rec = {".211": "SMITH,JANE", ".212": "WIFE", ".213": "5 K ST", ".3305": "Y", ".3405": "Y",
           ".3311": "DOE,BOB", ".3312": "FRIEND", ".3319": "555-9"}
    cs = t.transform(rec, LK)["contact"]
    codes = [c["relationship"][0]["coding"][0]["code"] for c in cs]
    assert codes == ["N", "C", "C", "O"]
    assert cs[1]["name"]["text"] == "SMITH,JANE" and cs[3]["relationship"][0]["text"] == "Designee"
    assert cs[2]["name"]["family"] == "DOE" and cs[2]["telecom"] == [{"system": "phone", "use": "home", "value": "555-9"}]


def test_employer_and_guardians():
    rec = {".3111": "ACME CORP", ".3113": "1 WORK WAY", ".3116": "LA", ".3117": "5", ".3118": "90001", ".2205": "900019999", ".3119": "555-7",
           ".2912": "GUARD,VA", ".2913": "SON", ".2911": "500", ".291": "3150101", ".2919": "555-8",
           ".2922": "GUARD,CIVIL", ".2921": "COUNTY COURT", ".2926": "LA", ".2927": "5"}
    cs = t.transform(rec, LK)["contact"]
    emp, g1, g2 = cs
    assert emp["relationship"][0]["coding"][0]["code"] == "E" and emp["organization"] == {"display": "ACME CORP"}
    assert emp["address"]["postalCode"] == "900019999" and emp["telecom"] == [{"system": "phone", "use": "work", "value": "555-7"}]
    assert g1["relationship"][0]["coding"][0] == {"system": t.V3_ROLE, "code": "GUARD", "display": "guardian"}
    assert g1["organization"] == {"reference": "Organization/500", "display": "ALBANY VAMC"} and g1["period"] == {"start": "2015-01-01"}
    assert g1["telecom"] == [{"system": "phone", "value": "555-8"}]
    assert g2["organization"] == {"display": "COUNTY COURT"} and g2["address"] == {"city": "LA", "state": "CA"}


# ---- extensions & communication ---------------------------------------------------------
def test_race_and_ethnicity_extensions():
    p = t.transform({"2": [{".01": "7"}, {".01": "12"}], "6": [{".01": "1"}]}, LK)
    race = ext(p, t.EXT_RACE)[0]["extension"]
    assert race[0] == {"url": "ombCategory", "valueCoding": {"system": t.CDC_RACE, "code": "2106-3", "display": "White"}}
    assert race[1] == {"url": "detailed", "valueCoding": {"system": t.CDC_RACE, "code": "2036-2", "display": "FILIPINO"}}
    assert race[2] == {"url": "text", "valueString": "WHITE, FILIPINO"}
    eth = ext(p, t.EXT_ETHNICITY)[0]["extension"]
    assert eth[0]["valueCoding"]["code"] == "2135-2" and eth[1] == {"url": "text", "valueString": "HISPANIC OR LATINO"}


def test_race_null_flavors_and_deprecated_single_field():
    race = ext(t.transform({"2": [{".01": "9"}]}, LK), t.EXT_RACE)[0]["extension"]
    assert race[0]["valueCoding"] == {"system": t.V3_NULL, "code": "ASKU", "display": "asked but unknown"}
    eth = ext(t.transform({"6": [{".01": "4"}]}, LK), t.EXT_ETHNICITY)[0]["extension"]
    assert eth[0]["valueCoding"]["code"] == "UNK"
    # .06 RACE (deprecated) is used only when multiple #2 is empty
    assert ext(t.transform({".06": "3"}, LK), t.EXT_RACE)[0]["extension"][0]["valueCoding"]["code"] == "2028-9"
    assert ext(t.transform({".06": "3", "2": [{".01": "7"}]}, LK), t.EXT_RACE)[0]["extension"][0]["valueCoding"]["code"] == "2106-3"
    assert ext(t.transform({}, LK), t.EXT_RACE) == []


def test_religion_birthplace_mothers_maiden_veteran():
    rec = {".08": "22", ".092": "BERLIN", ".0932": "BRANDENBURG", ".0931": "77", ".2403": "MAIDEN", "1901": "Y"}
    p = t.transform(rec, LK)
    assert ext(p, t.EXT_RELIGION)[0]["valueCodeableConcept"]["coding"][0] == {"system": t.SYS_VISTA_RELIGION, "code": "22", "display": "LUTHERAN"}
    assert ext(p, t.EXT_BIRTHPLACE)[0]["valueAddress"] == {"city": "BERLIN", "state": "BRANDENBURG", "country": "DEU"}
    assert ext(p, t.EXT_MOTHERS_MAIDEN)[0]["valueString"] == "MAIDEN"
    assert ext(p, t.EXT_VETERAN)[0]["valueBoolean"] is True
    p = t.transform({".093": "5", ".0932": "IGNORED", "1.06": "78", ".2403": "TEXT", "1901": "N"}, LK)
    assert ext(p, t.EXT_BIRTHPLACE)[0]["valueAddress"] == {"state": "CA"}
    assert ext(p, t.EXT_MOTHERS_MAIDEN)[0]["valueString"] == "JONES"
    assert ext(p, t.EXT_VETERAN)[0]["valueBoolean"] is False


def test_communication_newest_is_preferred():
    p = t.transform({"7": [{".01": "3200101", ".02": "SPANISH"}, {".01": "3210101", ".02": "KLINGON"}]})
    assert p["communication"][0] == {"language": {"text": "KLINGON"}, "preferred": True}
    assert p["communication"][1]["language"]["coding"][0]["code"] == "es" and p["communication"][1]["preferred"] is False


def test_merge_link_and_references():
    p = t.transform({".082": "42", "27.02": "500", "404.01": "1234"}, LK)
    assert p["active"] is False and p["link"] == [{"other": {"reference": "Patient/42"}, "type": "replaced-by"}]
    assert p["managingOrganization"] == {"reference": "Organization/500", "display": "ALBANY VAMC"}
    assert p["generalPractitioner"] == [{"reference": "Practitioner/1234", "display": "PROVIDER,ONE"}]


def test_empty_record_and_unresolved_pointers():
    assert t.transform({}) == {"resourceType": "Patient"}
    p = t.transform({".115": "99", ".1173": "99", ".111": "X"})
    assert p["address"][0]["state"] == "99" and p["address"][0]["country"] == "99"


# ---- flagged fields & report -------------------------------------------------------------
def test_report_flags_fields_without_equivalent():
    rec = {".01": "DOE,JANE", ".07": "WELDER", ".301": "Y", ".32101": "Y", "1900": [{".01": "3200101"}], "99999": "x", ".091": ""}
    p, report = t.transform_with_report(rec, LK)
    assert p["name"][0]["family"] == "DOE"
    assert [d["field"] for d in report["dropped"]] == [".07", ".301", ".32101", "1900"]
    assert report["dropped"][0]["candidate"].startswith("Observation")
    assert all(d["dd_zwr_line"] > 0 for d in report["dropped"])
    assert report["unknown"] == ["99999"]


def test_cli_roundtrip(tmp_path):
    f = tmp_path / "rec.json"
    f.write_text(json.dumps({"dfn": "7", "record": {".01": "DOE,JANE", ".02": "F", ".07": "WELDER"}}))
    out = subprocess.run([sys.executable, os.path.join(PKG, "vista_patient_to_fhir.py"), str(f)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    assert data["patient"]["id"] == "7" and data["patient"]["gender"] == "female"
    assert data["report"]["dropped"][0]["field"] == ".07"


# ---- mapping artifact integrity ----------------------------------------------------------
def test_every_dd_field_has_a_rule_and_citation():
    m = build_mapping.build()
    with open(os.path.join(PKG, "dd2_fields.json")) as f:
        dd = json.load(f)
    assert m["counts"]["total"] == sum(len(v) for v in dd.values()) == 889
    assert m["counts"]["root_total"] == len(dd["2"]) == 524
    for r in m["fields"]:
        assert r["status"] in ("mapped", "mapped-extension", "mapped-local-extension", "no-equivalent"), r
        assert r["dd_zwr_line"] > 0 and r["dd_zwr_url"].endswith(f"#L{r['dd_zwr_line']}")
        if r["status"] == "no-equivalent":
            assert r["candidate"] and not r["fhir"], r
        else:
            assert r["fhir"] and not r["candidate"], r


def test_committed_mapping_matches_rules():
    with open(os.path.join(PKG, "mapping.json")) as f:
        committed = json.load(f)
    assert committed == build_mapping.build(), "run build_mapping.py and commit mapping.json / MAPPING.md"
    with open(os.path.join(PKG, "MAPPING.md")) as f:
        assert f.read() == build_mapping.render_md(committed)


def test_dd_extract_line_numbers_match_dd_zwr_citations():
    with open(os.path.join(PKG, "dd2_fields.json")) as f:
        dd = json.load(f)
    lines = {}
    with open(os.path.join(PKG, "DD-2-extract.zwr"), encoding="latin-1") as f:
        for raw in f:
            n, _, rest = raw.partition(":")
            if n.isdigit():
                lines[int(n)] = rest
    for fnum, fields in dd.items():
        for fld, meta in fields.items():
            cited = lines[meta["dd_line"]]
            import re
            assert re.match(rf'^\^DD\("?{re.escape(fnum)}"?,"?{re.escape(fld)}"?,0\)=', cited), (fnum, fld, cited)


def test_transform_covers_every_mapped_field():
    """Every field the mapping table calls mapped is referenced by the transform source."""
    with open(os.path.join(PKG, "vista_patient_to_fhir.py")) as f:
        src = f.read()
    with open(os.path.join(PKG, "mapping.json")) as f:
        rows = json.load(f)["fields"]
    missing = [(r["file"], r["field"]) for r in rows if r["status"] != "no-equivalent" and f'"{r["field"]}"' not in src]
    assert missing == []
