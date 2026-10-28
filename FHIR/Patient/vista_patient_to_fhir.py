"""Transform a VistA PATIENT (FileMan file #2) record into a FHIR R4 Patient resource.

Input shape (``record``): a dict keyed by FileMan field number (string) holding the
*internal* FileMan value, as read from ^DPT(DFN,...) pieces:

    {".01": "SMITH,JOHN A JR", ".02": "M", ".03": "2500704", ".09": "123456789",
     ".05": "2",                      # pointer: IEN in file 11
     "2": [{".01": "3"}, ...],        # multiples: list of dicts keyed by subfile field
     ...}

Pointer values are IENs; ``Lookups`` resolves them to the code/name needed by FHIR.
Any pointer that cannot be resolved falls back to the raw value so no data is dropped.
Fields that have no FHIR equivalent (see MAPPING.md) are never silently discarded:
``transform_with_report`` returns them in ``report["dropped"]``.

Field-by-field rationale and MUMPS line citations: MAPPING.md / mapping.json.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- code systems -----------------------------------------------------------------------
SID_SSN = "http://hl7.org/fhir/sid/us-ssn"
OID_ICN = "urn:oid:2.16.840.1.113883.4.349"
SYS_DFN = "http://va.gov/identifier/vista-dfn"
SYS_CLAIM = "http://va.gov/identifier/claim-number"
SYS_MPI_TEMP = "http://va.gov/identifier/mpi-temporary-id"
SYS_MPI_FOREIGN = "http://va.gov/identifier/mpi-foreign-id"
V2_0203 = "http://terminology.hl7.org/CodeSystem/v2-0203"
V2_0131 = "http://terminology.hl7.org/CodeSystem/v2-0131"
V3_ROLE = "http://terminology.hl7.org/CodeSystem/v3-RoleCode"
V3_MARITAL = "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus"
V3_NULL = "http://terminology.hl7.org/CodeSystem/v3-NullFlavor"
V3_ACTREASON = "http://terminology.hl7.org/CodeSystem/v3-ActReason"
CDC_RACE = "urn:oid:2.16.840.1.113883.6.238"
SNOMED = "http://snomed.info/sct"
BCP47 = "urn:ietf:bcp:47"
SYS_VISTA_RELIGION = "http://va.gov/fhir/CodeSystem/vista-religion"

EXT_RACE = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
EXT_ETHNICITY = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
EXT_BIRTHSEX = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex"
EXT_GENDER_IDENTITY = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-genderIdentity"
EXT_RELIGION = "http://hl7.org/fhir/StructureDefinition/patient-religion"
EXT_BIRTHPLACE = "http://hl7.org/fhir/StructureDefinition/patient-birthPlace"
EXT_MOTHERS_MAIDEN = "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName"
LOCAL_BASE = "http://va.gov/fhir/StructureDefinition/vista-patient-"
EXT_VETERAN = LOCAL_BASE + "veteran-indicator"
EXT_CONF_ADDR_CAT = LOCAL_BASE + "confidential-address-category"
EXT_CONF_TELECOM = LOCAL_BASE + "confidential-telecom"

# ---- VistA code tables (from ^DD(2,field,0) piece 3; see MAPPING.md) --------------------
SEX_TO_GENDER = {"M": "male", "F": "female"}
# .024 SELF IDENTIFIED GENDER -> US Core gender identity value set
GENDER_IDENTITY = {
    "M": (SNOMED, "446151000124109", "Identifies as male gender"),
    "F": (SNOMED, "446141000124107", "Identifies as female gender"),
    "TM": (SNOMED, "407377005", "Female-to-male transsexual"),
    "TF": (SNOMED, "407376001", "Male-to-female transsexual"),
    "O": (V3_NULL, "OTH", "other"),
    "N": (V3_NULL, "ASKU", "asked but unknown"),
}
# file 11 field 2 MARITAL STATUS CODE -> v3 MaritalStatus
MARITAL = {"D": ("D", "Divorced"), "M": ("M", "Married"), "N": ("S", "Never Married"),
           "S": ("L", "Legally Separated"), "W": ("W", "Widowed"), "U": ("UNK", "unknown")}
OMB_RACE = {"1002-5": "American Indian or Alaska Native", "2028-9": "Asian", "2054-5": "Black or African American",
            "2076-8": "Native Hawaiian or Other Pacific Islander", "2106-3": "White"}
OMB_ETHNICITY = {"2135-2": "Hispanic or Latino", "2186-5": "Not Hispanic or Latino"}
CDC_NULL = {"0000-0": ("ASKU", "asked but unknown"), "9999-4": ("UNK", "unknown")}
CONF_ADDR_CATEGORY = {"1": "ELIGIBILITY/ENROLLMENT", "2": "APPOINTMENT/SCHEDULING", "3": "COPAYMENTS/VETERAN BILLING",
                      "4": "MEDICAL RECORDS", "5": "ALL OTHERS"}
LANGUAGE_BCP47 = {"ENGLISH": "en", "SPANISH": "es", "FRENCH": "fr", "GERMAN": "de", "TAGALOG": "tl", "FILIPINO": "fil",
                  "VIETNAMESE": "vi", "KOREAN": "ko", "CHINESE": "zh", "MANDARIN": "zh", "CANTONESE": "yue",
                  "JAPANESE": "ja", "RUSSIAN": "ru", "ARABIC": "ar", "PORTUGUESE": "pt", "ITALIAN": "it",
                  "POLISH": "pl", "AMERICAN SIGN LANGUAGE": "ase"}
NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "DO", "PHD", "ESQ", "DDS", "RN"}


@dataclass
class Lookups:
    """Resolvers for FileMan pointer fields. Each dict is keyed by IEN (string).

    state:            file 5   -> {"name": ..., "abbreviation": ...}
    county:           (state IEN, county number) -> county name   (file 5 subfile 5.01)
    country:          file 779.004 -> ISO 3166 alpha-3 code
    marital_status:   file 11  -> MARITAL STATUS CODE letter (field 2)
    race:             file 10  -> {"name": ..., "cdc": "2106-3"}
    ethnicity:        file 10.2 -> {"name": ..., "cdc": "2135-2"}
    religion:         file 13  -> {"name": ..., "code": "22"}
    institution:      file 4   -> name
    new_person:       file 200 -> name
    name_components:  file 20  -> {"family","given","middle","prefix","suffix","degree"}
    timezone_offset:  e.g. "-05:00"; when None, time-of-day is dropped from FileMan date/times
                      because FHIR dateTime requires a zone whenever a time is present.
    """
    state: Dict[str, Dict[str, str]] = field(default_factory=dict)
    county: Dict[Tuple[str, str], str] = field(default_factory=dict)
    country: Dict[str, str] = field(default_factory=dict)
    marital_status: Dict[str, str] = field(default_factory=dict)
    race: Dict[str, Dict[str, str]] = field(default_factory=dict)
    ethnicity: Dict[str, Dict[str, str]] = field(default_factory=dict)
    religion: Dict[str, Dict[str, str]] = field(default_factory=dict)
    institution: Dict[str, str] = field(default_factory=dict)
    new_person: Dict[str, str] = field(default_factory=dict)
    name_components: Dict[str, Dict[str, str]] = field(default_factory=dict)
    timezone_offset: Optional[str] = None


# ---- primitives --------------------------------------------------------------------------
def fileman_date(value: Any, tz: Optional[str] = None) -> Optional[str]:
    """FileMan YYYMMDD[.HHMMSS] -> FHIR date/dateTime. Imprecise dates keep partial precision.

    3100704 -> 2010-07-04; 3100700 -> 2010-07; 3100000 -> 2010; 3100704.1530 -> 2010-07-04T15:30:00<tz>
    """
    if value in (None, ""):
        return None
    s = str(value).strip()
    m = re.match(r"^(\d{3})(\d{2})(\d{2})(?:\.(\d{1,6}))?$", s)
    if not m:
        return None
    yyy, mm, dd, t = m.groups()
    year = 1700 + int(yyy)
    out = f"{year:04d}"
    if mm != "00":
        out += f"-{mm}"
        if dd != "00":
            out += f"-{dd}"
            if t and tz:
                t = (t + "000000")[:6]
                hh, mi, ss = t[0:2], t[2:4], t[4:6]
                if hh == "24":
                    hh = "00"
                out += f"T{hh}:{mi}:{ss}{tz}"
    return out


def parse_vista_name(text: str) -> Dict[str, Any]:
    """'LAST,FIRST MIDDLE SUFFIX' -> HumanName parts. Keeps raw text in HumanName.text."""
    name: Dict[str, Any] = {"text": text}
    if "," not in text:
        name["family"] = text.strip()
        return name
    family, rest = text.split(",", 1)
    name["family"] = family.strip()
    tokens = rest.split()
    suffix = []
    while tokens and tokens[-1].rstrip(".").upper() in NAME_SUFFIXES and len(tokens) > 1:
        suffix.insert(0, tokens.pop())
    if tokens:
        name["given"] = tokens
    if suffix:
        name["suffix"] = suffix
    return name


def name_from_components(comp: Dict[str, str], text: Optional[str] = None) -> Dict[str, Any]:
    name: Dict[str, Any] = {}
    if text:
        name["text"] = text
    if comp.get("family"):
        name["family"] = comp["family"]
    given = [g for g in (comp.get("given"), comp.get("middle")) if g]
    if given:
        name["given"] = given
    if comp.get("prefix"):
        name["prefix"] = [comp["prefix"]]
    suffix = [s for s in (comp.get("suffix"), comp.get("degree")) if s]
    if suffix:
        name["suffix"] = suffix
    return name


def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


# ---- transformer -------------------------------------------------------------------------
class PatientTransformer:
    def __init__(self, record: Dict[str, Any], lookups: Optional[Lookups] = None, dfn: Optional[str] = None,
                 station: Optional[str] = None):
        self.r = record
        self.lk = lookups or Lookups()
        self.dfn = dfn
        self.station = station
        self.tz = self.lk.timezone_offset

    # -- field access
    def v(self, fld: str) -> Optional[str]:
        val = self.r.get(fld)
        if val is None:
            return None
        val = str(val).strip()
        return val or None

    def multiple(self, fld: str) -> List[Dict[str, Any]]:
        val = self.r.get(fld) or []
        return [m for m in val if isinstance(m, dict)]

    def date(self, fld: str, with_time: bool = True) -> Optional[str]:
        return fileman_date(self.v(fld), self.tz if with_time else None)

    def state(self, fld: str) -> Optional[str]:
        ien = self.v(fld)
        if ien is None:
            return None
        st = self.lk.state.get(ien)
        return (st.get("abbreviation") or st.get("name")) if st else ien

    def country(self, fld: str) -> Optional[str]:
        ien = self.v(fld)
        if ien is None:
            return None
        return self.lk.country.get(ien, ien)

    def county(self, fld: str, state_fld: str) -> Optional[str]:
        num = self.v(fld)
        if num is None:
            return None
        return self.lk.county.get((self.v(state_fld) or "", num), num)

    # -- build
    def build(self) -> Dict[str, Any]:
        p: Dict[str, Any] = {"resourceType": "Patient"}
        if self.dfn:
            p["id"] = str(self.dfn)
        meta = self.meta()
        if meta:
            p["meta"] = meta
        ext = self.extensions()
        if ext:
            p["extension"] = ext
        p["identifier"] = self.identifiers()
        if self.v(".082"):
            p["active"] = False
        p["name"] = self.names()
        p["telecom"] = self.telecoms()
        gender = self.v(".02")
        if gender:
            p["gender"] = SEX_TO_GENDER.get(gender, "unknown")
        p["birthDate"] = self.date(".03", with_time=False)
        dod = self.date(".351")
        if dod:
            p["deceasedDateTime"] = dod
        p["address"] = self.addresses()
        p["maritalStatus"] = self.marital_status()
        mb = self.v("994")
        if mb in ("Y", "N"):
            p["multipleBirthBoolean"] = mb == "Y"
        p["contact"] = self.contacts()
        p["communication"] = self.communications()
        gp = self.v("404.01")
        if gp:
            p["generalPractitioner"] = [_clean({"reference": f"Practitioner/{gp}", "display": self.lk.new_person.get(gp)})]
        mo = self.v("27.02")
        if mo:
            p["managingOrganization"] = _clean({"reference": f"Organization/{mo}", "display": self.lk.institution.get(mo)})
        merged = self.v(".082")
        if merged:
            p["link"] = [{"other": {"reference": f"Patient/{merged}"}, "type": "replaced-by"}]
        return _clean(p)

    def meta(self) -> Dict[str, Any]:
        if self.v(".6") == "1":
            return {"security": [{"system": V3_ACTREASON, "code": "HTEST", "display": "test health data"}]}
        return {}

    # -- identifiers
    def identifiers(self) -> List[Dict[str, Any]]:
        ids: List[Dict[str, Any]] = []
        if self.dfn:
            system = f"{SYS_DFN}/{self.station}" if self.station else SYS_DFN
            ids.append({"use": "usual", "type": {"coding": [{"system": V2_0203, "code": "PI"}]}, "system": system, "value": str(self.dfn)})
        ssn = self.v(".09")
        if ssn:
            ids.append(self.ssn_identifier(ssn, "official"))
        icn = self.v("991.1") or self.v("991.01")
        if icn:
            if icn == self.v("991.01") and self.v("991.02"):
                icn = f"{icn}V{self.v('991.02')}"
            ids.append({"use": "temp" if self.v("991.04") == "1" else "official",
                        "type": {"coding": [{"system": V2_0203, "code": "NI"}]}, "system": OID_ICN, "value": icn})
        for h in self.multiple("991.91"):
            if h.get(".01"):
                ids.append({"use": "old", "system": OID_ICN, "value": str(h[".01"])})
        for h in self.multiple("992"):
            if h.get(".01"):
                val = str(h[".01"]) + (f"V{h['1']}" if h.get("1") else "")
                ident: Dict[str, Any] = {"use": "old", "system": OID_ICN, "value": val}
                end = fileman_date(h.get("3"), self.tz)
                if end:
                    ident["period"] = {"end": end}
                ids.append(ident)
        for fld, system in (("991.08", SYS_MPI_TEMP), ("991.09", SYS_MPI_FOREIGN)):
            if self.v(fld):
                ids.append(_clean({"use": "temp" if fld == "991.08" else None, "system": system, "value": self.v(fld)}))
        if self.v(".313"):
            ids.append({"system": SYS_CLAIM, "value": self.v(".313")})
        if self.v(".383"):
            ids.append({"type": {"coding": [{"system": V2_0203, "code": "MA", "display": "Patient Medicaid number"}]}, "value": self.v(".383")})
        for a in self.multiple("1"):
            if a.get("1"):
                ids.append(self.ssn_identifier(str(a["1"]), "old"))
        return ids

    @staticmethod
    def ssn_identifier(raw: str, use: str) -> Dict[str, Any]:
        pseudo = raw.upper().endswith("P")
        digits = re.sub(r"\D", "", raw)
        return {"use": "temp" if pseudo else use,
                "type": {"coding": [{"system": V2_0203, "code": "SS", "display": "Social Security number"}]},
                "system": SID_SSN, "value": digits or raw}

    # -- names
    def components(self, fld: str) -> Optional[Dict[str, str]]:
        ien = self.v(fld)
        return self.lk.name_components.get(ien) if ien else None

    def names(self) -> List[Dict[str, Any]]:
        out = []
        raw = self.v(".01")
        if raw:
            comp = self.components("1.01")
            name = name_from_components(comp, raw) if comp else parse_vista_name(raw)
            name["use"] = "official"
            out.append(name)
        pref = self.v(".2405")
        if pref:
            out.append({"use": "usual", "text": pref, "given": [pref]})
        for a in self.multiple("1"):
            alias = a.get(".01")
            if not alias:
                continue
            comp = self.lk.name_components.get(str(a.get("100.03") or ""))
            out.append(name_from_components(comp, str(alias)) if comp else parse_vista_name(str(alias)))
        return out

    # -- telecom
    def telecoms(self) -> List[Dict[str, Any]]:
        spec = [(".131", "phone", "home", ".1321"), (".132", "phone", "work", None), (".134", "phone", "mobile", ".139"),
                (".135", "pager", None, ".1312"), (".133", "email", None, ".136"), (".1219", "phone", "temp", None)]
        out = []
        for fld, system, use, start_fld in spec:
            val = self.v(fld)
            if not val:
                continue
            t: Dict[str, Any] = {"system": system, "value": val}
            if use:
                t["use"] = use
            start = self.date(start_fld) if start_fld else None
            if start:
                t["period"] = {"start": start}
            out.append(t)
        conf = self.v(".1315")
        if conf:
            out.append({"extension": [{"url": EXT_CONF_TELECOM, "valueBoolean": True}], "system": "phone", "value": conf})
        return out

    # -- addresses
    def address(self, lines, city, state, zip5, zip4, county, province, postal, country, use=None, typ=None,
                start=None, end=None, ext=None) -> Optional[Dict[str, Any]]:
        a: Dict[str, Any] = {}
        if ext:
            a["extension"] = ext
        if use:
            a["use"] = use
        if typ:
            a["type"] = typ
        a["line"] = [self.v(f) for f in lines if self.v(f)]
        a["city"] = self.v(city) if city else None
        a["district"] = self.county(county, state) if county and state else None
        a["state"] = (self.state(state) if state else None) or (self.v(province) if province else None)
        a["postalCode"] = (self.v(zip4) if zip4 else None) or (self.v(zip5) if zip5 else None) or (self.v(postal) if postal else None)
        a["country"] = self.country(country) if country else None
        period = _clean({"start": self.date(start) if start else None, "end": self.date(end) if end else None})
        if period:
            a["period"] = period
        a = _clean(a)
        if set(a) <= {"use", "type", "extension"}:
            return None
        return a

    def addresses(self) -> List[Dict[str, Any]]:
        out = []
        perm = self.address([".111", ".112", ".113"], ".114", ".115", ".116", ".1112", ".117", ".1171", ".1172", ".1173",
                            use="home", typ="postal", start=".118")
        if perm:
            out.append(perm)
        res = self.address([".1151", ".1152", ".1153"], ".1154", ".1155", None, ".1156", ".1157", ".11571", ".11572", ".11573",
                           use="home", typ="physical", start=".1158")
        if res:
            out.append(res)
        if self.v(".12105") == "Y":
            tmp = self.address([".1211", ".1212", ".1213"], ".1214", ".1215", ".1216", ".12112", ".12111", ".1221", ".1222", ".1223",
                               use="temp", start=".1217", end=".1218")
            if tmp:
                out.append(tmp)
        if self.v(".14105") == "Y":
            cats = [{"url": EXT_CONF_ADDR_CAT, "valueCoding": {"code": str(c[".01"]), "display": CONF_ADDR_CATEGORY.get(str(c[".01"]), "")}}
                    for c in self.multiple(".141") if c.get(".01") and str(c.get("1", "Y")) == "Y"]
            conf = self.address([".1411", ".1412", ".1413"], ".1414", ".1415", ".1416", None, ".14111", ".14114", ".14115", ".14116",
                                typ="postal", start=".1417", end=".1418", ext=cats or None)
            if conf:
                out.append(conf)
        return out

    # -- marital status
    def marital_status(self) -> Optional[Dict[str, Any]]:
        ien = self.v(".05")
        if not ien:
            return None
        letter = self.lk.marital_status.get(ien)
        if letter in MARITAL:
            code, display = MARITAL[letter]
            return {"coding": [{"system": V3_MARITAL, "code": code, "display": display}]}
        return {"text": letter or ien}

    # -- contacts
    def contact(self, rel_coding, rel_text_fld, name_fld, comp_fld, lines, city, state, zip5, zip4, phone, work,
                start=None, org_fld=None, org_is_pointer=False, copy_address=False) -> Optional[Dict[str, Any]]:
        c: Dict[str, Any] = {}
        rel: Dict[str, Any] = {"coding": [dict(rel_coding)]} if rel_coding else {}
        if rel_text_fld and self.v(rel_text_fld):
            rel["text"] = self.v(rel_text_fld)
        elif rel_coding and rel_coding.get("display"):
            rel["text"] = rel_coding["display"]
        if rel:
            c["relationship"] = [rel]
        if name_fld and self.v(name_fld):
            comp = self.components(comp_fld) if comp_fld else None
            c["name"] = name_from_components(comp, self.v(name_fld)) if comp else parse_vista_name(self.v(name_fld))
        telecom = []
        if phone and self.v(phone):
            telecom.append({"system": "phone", "use": "home", "value": self.v(phone)} if work else {"system": "phone", "value": self.v(phone)})
        if work and self.v(work):
            telecom.append({"system": "phone", "use": "work", "value": self.v(work)})
        if telecom:
            c["telecom"] = telecom
        if copy_address:
            pat = self.address([".111", ".112", ".113"], ".114", ".115", ".116", ".1112", None, ".1171", ".1172", ".1173")
            if pat:
                c["address"] = pat
        else:
            addr = self.address(lines, city, state, zip5, zip4, None, None, None, None)
            if addr:
                c["address"] = addr
        if org_fld and self.v(org_fld):
            if org_is_pointer:
                c["organization"] = _clean({"reference": f"Organization/{self.v(org_fld)}", "display": self.lk.institution.get(self.v(org_fld))})
            else:
                c["organization"] = {"display": self.v(org_fld)}
        if start and self.date(start):
            c["period"] = {"start": self.date(start)}
        if not any(k in c for k in ("name", "telecom", "address", "organization")):
            return None
        return c

    def contacts(self) -> List[Dict[str, Any]]:
        NOK = {"system": V2_0131, "code": "N", "display": "Next-of-Kin"}
        EMERG = {"system": V2_0131, "code": "C", "display": "Emergency Contact"}
        OTHER = {"system": V2_0131, "code": "O", "display": "Other"}
        EMPLOYER = {"system": V2_0131, "code": "E", "display": "Employer"}
        GUARD = {"system": V3_ROLE, "code": "GUARD", "display": "guardian"}
        out = []
        k = self.contact(NOK, ".212", ".211", "1.02", [".213", ".214", ".215"], ".216", ".217", ".218", ".2207", ".219", ".21011",
                         start=".21012", copy_address=self.v(".2125") == "Y")
        if k:
            out.append(k)
        k2 = self.contact(NOK, ".2192", ".2191", "1.03", [".2193", ".2194", ".2195"], ".2196", ".2197", ".2198", ".2203", ".2199", ".211011",
                          start=".211012", copy_address=self.v(".21925") == "Y")
        if k2:
            out.append(k2)
        if self.v(".3305") == "Y" and k:
            e = json.loads(json.dumps(k))
            e["relationship"] = [{"coding": [EMERG], "text": k["relationship"][0].get("text", EMERG["display"])}]
            e.pop("period", None)
            if self.date(".33012"):
                e["period"] = {"start": self.date(".33012")}
            out.append(e)
        else:
            e = self.contact(EMERG, ".332", ".331", "1.07", [".333", ".334", ".335"], ".336", ".337", ".338", ".2201", ".339", ".33011", start=".33012")
            if e:
                out.append(e)
        e2 = self.contact(EMERG, ".3312", ".3311", "1.08", [".3313", ".3314", ".3315"], ".3316", ".3317", ".3318", ".2204", ".3319", ".331011", start=".33112")
        if e2:
            out.append(e2)
        if self.v(".3405") == "Y" and k:
            d = json.loads(json.dumps(k))
            d["relationship"] = [{"coding": [OTHER], "text": "Designee"}]
            d.pop("period", None)
            if self.date(".3412"):
                d["period"] = {"start": self.date(".3412")}
            out.append(d)
        else:
            d = self.contact(OTHER, ".342", ".341", "1.09", [".343", ".344", ".345"], ".346", ".347", ".348", ".2202", ".349", ".34011", start=".3412")
            if d:
                if not d["relationship"][0].get("text") or d["relationship"][0]["text"] == "Other":
                    d["relationship"][0]["text"] = "Designee"
                out.append(d)
        emp = self.contact(EMPLOYER, None, None, None, [".3113", ".3114", ".3115"], ".3116", ".3117", ".3118", ".2205", None, ".3119", org_fld=".3111")
        if emp:
            out.append(emp)
        g = self.contact(GUARD, ".2913", ".2912", None, [".2914", ".2915"], ".2916", ".2917", ".2918", ".29013", ".2919", None,
                         start=".291", org_fld=".2911", org_is_pointer=True)
        if g:
            out.append(g)
        g2 = self.contact(GUARD, ".2923", ".2922", None, [".2924", ".2925"], ".2926", ".2927", ".2928", ".290012", ".2929", None,
                          start=".292", org_fld=".2921")
        if g2:
            out.append(g2)
        return out

    # -- communication
    def communications(self) -> List[Dict[str, Any]]:
        entries = [m for m in self.multiple("7") if m.get(".02")]
        entries.sort(key=lambda m: float(m.get(".01") or 0), reverse=True)
        out = []
        for i, m in enumerate(entries):
            text = str(m[".02"]).strip()
            lang: Dict[str, Any] = {"text": text}
            code = LANGUAGE_BCP47.get(text.upper())
            if code:
                lang["coding"] = [{"system": BCP47, "code": code, "display": text.title()}]
            out.append({"language": lang, "preferred": i == 0})
        return out

    # -- extensions
    def extensions(self) -> List[Dict[str, Any]]:
        ext: List[Dict[str, Any]] = []
        race = self.race_extension()
        if race:
            ext.append(race)
        eth = self.ethnicity_extension()
        if eth:
            ext.append(eth)
        sex = self.v(".02")
        if sex in ("M", "F"):
            ext.append({"url": EXT_BIRTHSEX, "valueCode": sex})
        gi = self.v(".024")
        if gi in GENDER_IDENTITY:
            system, code, display = GENDER_IDENTITY[gi]
            ext.append({"url": EXT_GENDER_IDENTITY, "valueCodeableConcept": {"coding": [{"system": system, "code": code, "display": display}]}})
        rel = self.v(".08")
        if rel:
            r = self.lk.religion.get(rel)
            cc = {"coding": [_clean({"system": SYS_VISTA_RELIGION, "code": r.get("code"), "display": r.get("name")})]} if r else {"text": rel}
            ext.append({"url": EXT_RELIGION, "valueCodeableConcept": cc})
        bp = _clean({"city": self.v(".092"), "state": self.state(".093") or self.v(".0932"), "country": self.country(".0931")})
        if bp:
            ext.append({"url": EXT_BIRTHPLACE, "valueAddress": bp})
        mm_comp = self.components("1.06")
        mm = (mm_comp or {}).get("family") or self.v(".2403")
        if mm:
            ext.append({"url": EXT_MOTHERS_MAIDEN, "valueString": mm})
        vet = self.v("1901")
        if vet in ("Y", "N"):
            ext.append({"url": EXT_VETERAN, "valueBoolean": vet == "Y"})
        return ext

    def _cdc_extension(self, url, iens, table, omb) -> Optional[Dict[str, Any]]:
        if not iens:
            return None
        sub = []
        texts = []
        for ien in iens:
            info = table.get(ien) or {}
            cdc = info.get("cdc")
            name = info.get("name") or ien
            texts.append(name)
            if cdc in CDC_NULL:
                code, display = CDC_NULL[cdc]
                sub.append({"url": "ombCategory", "valueCoding": {"system": V3_NULL, "code": code, "display": display}})
            elif cdc in omb:
                sub.append({"url": "ombCategory", "valueCoding": {"system": CDC_RACE, "code": cdc, "display": omb[cdc]}})
            elif cdc:
                sub.append({"url": "detailed", "valueCoding": {"system": CDC_RACE, "code": cdc, "display": name}})
        sub.append({"url": "text", "valueString": ", ".join(texts)})
        return {"url": url, "extension": sub}

    def race_extension(self):
        iens = [str(m[".01"]) for m in self.multiple("2") if m.get(".01")]
        if not iens and self.v(".06"):
            iens = [self.v(".06")]
        return self._cdc_extension(EXT_RACE, iens, self.lk.race, OMB_RACE)

    def ethnicity_extension(self):
        iens = [str(m[".01"]) for m in self.multiple("6") if m.get(".01")]
        return self._cdc_extension(EXT_ETHNICITY, iens, self.lk.ethnicity, OMB_ETHNICITY)


# ---- public API --------------------------------------------------------------------------
def transform(record: Dict[str, Any], lookups: Optional[Lookups] = None, dfn: Optional[str] = None,
              station: Optional[str] = None) -> Dict[str, Any]:
    """Return a FHIR R4 Patient (as a JSON-ready dict) for one file #2 record."""
    return PatientTransformer(record, lookups, dfn, station).build()


_MAPPING_CACHE: Optional[Dict[str, Any]] = None


def load_mapping() -> Dict[str, Any]:
    global _MAPPING_CACHE
    if _MAPPING_CACHE is None:
        with open(os.path.join(HERE, "mapping.json")) as f:
            _MAPPING_CACHE = json.load(f)
    return _MAPPING_CACHE


def transform_with_report(record: Dict[str, Any], lookups: Optional[Lookups] = None, dfn: Optional[str] = None,
                          station: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """transform() plus a report of input fields that have no FHIR Patient equivalent.

    report = {"dropped": [{"field", "name", "candidate", "dd_zwr_line"}...],   # present in input, no equivalent
              "unknown": [field, ...]}                                         # not in file #2 DD at all
    """
    rules = {r["field"]: r for r in load_mapping()["fields"] if r["file"] == "2"}
    dropped, unknown = [], []
    for fld, val in record.items():
        if val in (None, "", []):
            continue
        rule = rules.get(fld)
        if rule is None:
            unknown.append(fld)
        elif rule["status"] == "no-equivalent":
            dropped.append({"field": fld, "name": rule["name"], "candidate": rule["candidate"], "dd_zwr_line": rule["dd_zwr_line"]})
    return transform(record, lookups, dfn, station), {"dropped": dropped, "unknown": unknown}


if __name__ == "__main__":
    import sys
    rec = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else json.load(sys.stdin)
    patient, report = transform_with_report(rec.get("record", rec), dfn=rec.get("dfn"))
    json.dump({"patient": patient, "report": report}, sys.stdout, indent=2)
    print()
