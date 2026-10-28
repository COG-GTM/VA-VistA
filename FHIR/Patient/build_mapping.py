#!/usr/bin/env python3
"""Render mapping.json and MAPPING.md from dd2_fields.json + mapping_rules.py.

Usage: python3 build_mapping.py  (run from any directory; writes next to this file)
"""
import json
import os
import re
from collections import Counter

import mapping_rules as R

HERE = os.path.dirname(os.path.abspath(__file__))
DD_COMMIT = "b7aecb9029f9bb8639a7bfa63b635469065ab44d"
DD_URL = f"https://github.com/WorldVistA/VistA-M/blob/{DD_COMMIT}/Packages/VA%20FileMan/Globals/DD.zwr"
REPO_URL = "https://github.com/COG-GTM/VA-VistA/blob/master"


def load_dd():
    with open(os.path.join(HERE, "dd2_fields.json")) as f:
        return json.load(f)


def subfile_parents(dd):
    """subfile number -> (parent file, parent field) using the 'spec' piece of ^DD(file,field,0)."""
    parents = {}
    for fnum, fields in dd.items():
        for fld, meta in fields.items():
            m = re.match(r"^(2\.[0-9]+)", meta["spec"])
            if m and m.group(1) in dd:
                parents[m.group(1)] = (fnum, fld)
    return parents


def root_rule_for(dd, parents, fnum):
    """Walk subfile ancestry up to file 2 and return the root field's rule."""
    while fnum != "2":
        fnum, fld = parents[fnum]
        if fnum == "2":
            return fld, R.resolve_root(fld)
    raise AssertionError


def build():
    dd = load_dd()
    parents = subfile_parents(dd)
    rows = []
    for fnum in sorted(dd, key=float):
        for fld in sorted(dd[fnum], key=float):
            meta = dd[fnum][fld]
            if fnum == "2":
                rule = R.resolve_root(fld)
                parent_field = ""
            else:
                parent_field, parent_rule = root_rule_for(dd, parents, fnum)
                rule = R.resolve_subfile(fnum, fld, parent_rule)
            flags = []
            if meta["name"].startswith("*") or "*" in meta["spec"].split("P")[0] or meta["spec"].startswith("*"):
                flags.append("deprecated")
            if "C" in meta["spec"] and not meta["loc"].strip(" ;"):
                flags.append("computed")
            if re.match(r"^2\.[0-9]+", meta["spec"]):
                flags.append("multiple")
            rows.append({
                "file": fnum,
                "field": fld,
                "name": meta["name"],
                "fileman_type": meta["spec"],
                "codes_or_pointer": meta["codes_or_ptr"],
                "global_location": meta["loc"],
                "parent_field": parent_field,
                "flags": flags,
                "status": rule["status"],
                "fhir": rule["fhir"],
                "candidate": rule["candidate"],
                "note": rule["note"],
                "dd_zwr_line": meta["dd_line"],
                "dd_zwr_url": f"{DD_URL}#L{meta['dd_line']}",
                "kids_citations": [f"{k['path']}:{k['line']}" for k in meta.get("kids", [])],
            })
    counts = Counter(r["status"] for r in rows)
    root_counts = Counter(r["status"] for r in rows if r["file"] == "2")
    return {
        "source": {
            "dd_zwr": "WorldVistA/VistA-M Packages/VA FileMan/Globals/DD.zwr",
            "commit": DD_COMMIT,
            "url": DD_URL,
            "local_extract": "FHIR/Patient/DD-2-extract.zwr (same lines, prefixed with DD.zwr line number)",
        },
        "target": "FHIR R4 Patient (http://hl7.org/fhir/R4/patient.html)",
        "counts": {"all_fields": dict(counts), "root_fields": dict(root_counts), "total": len(rows), "root_total": sum(root_counts.values())},
        "fields": rows,
    }


def md_escape(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_md(m):
    c = m["counts"]
    rc = c["root_fields"]
    out = []
    out.append("# FileMan file #2 (PATIENT) to FHIR R4 Patient\n")
    out.append(f"Source data dictionary: `^DD(2,...)` from [{m['source']['dd_zwr']} @ {m['source']['commit'][:12]}]({m['source']['url']}). "
               "The `DD.zwr line` column is the line in that file where `^DD(<file>,<field>,0)` (the field definition node) sits; "
               "`FHIR/Patient/DD-2-extract.zwr` in this repo carries the same lines with the same numbers. "
               "`KIDS` lists local patch files in this repo (`Packages/.../*.KID[S]`) that also carry the field definition, as `path:line`.\n")
    out.append("Status legend: **mapped** = FHIR R4 Patient core element; **mapped-extension** = standard HL7 / US Core extension on Patient; "
               "**mapped-local-extension** = extension defined by this package because no standard one exists; "
               "**NO FHIR EQUIVALENT** = nothing on Patient; the `FHIR element / candidate` column says where the data would go instead.\n")
    out.append("## Counts\n")
    out.append("| Scope | mapped | mapped-extension | mapped-local-extension | NO FHIR EQUIVALENT | total |")
    out.append("|---|---|---|---|---|---|")
    out.append(f"| File #2 root fields | {rc.get(R.MAPPED,0)} | {rc.get(R.EXT,0)} | {rc.get(R.LOCAL,0)} | {rc.get(R.NONE,0)} | {c['root_total']} |")
    ac = c["all_fields"]
    out.append(f"| Root + all subfile fields | {ac.get(R.MAPPED,0)} | {ac.get(R.EXT,0)} | {ac.get(R.LOCAL,0)} | {ac.get(R.NONE,0)} | {c['total']} |\n")

    def table(rows, with_file):
        hdr = (["Subfile"] if with_file else []) + ["VistA field", "Name", "FileMan type", "Global loc", "Status", "FHIR element / candidate", "Note", "DD.zwr line", "KIDS"]
        out.append("| " + " | ".join(hdr) + " |")
        out.append("|" + "---|" * len(hdr))
        for r in rows:
            status = "**NO FHIR EQUIVALENT**" if r["status"] == R.NONE else r["status"]
            target = r["fhir"] or r["candidate"]
            flags = (" _(" + ", ".join(r["flags"]) + ")_") if r["flags"] else ""
            kids = "<br>".join(f"[{k}]({REPO_URL}/{k.rsplit(':',1)[0]}#L{k.rsplit(':',1)[1]})" for k in r["kids_citations"][:3])
            if len(r["kids_citations"]) > 3:
                kids += f"<br>+{len(r['kids_citations'])-3} more"
            cells = ([r["file"]] if with_file else []) + [
                f"`{r['field']}`", md_escape(r["name"]) + flags, f"`{md_escape(r['fileman_type'])}`", f"`{md_escape(r['global_location'])}`",
                status, md_escape(target), md_escape(r["note"]), f"[{r['dd_zwr_line']}]({r['dd_zwr_url']})", kids or ""]
            out.append("| " + " | ".join(cells) + " |")
        out.append("")

    out.append("## File #2 root fields\n")
    table([r for r in m["fields"] if r["file"] == "2"], False)
    out.append("## Subfile fields (multiples under file #2)\n")
    out.append("Rows without their own rule inherit the status of the parent multiple field in file #2 (`parent` column).\n")
    sub = [r for r in m["fields"] if r["file"] != "2"]
    for r in sub:
        r = dict(r)
    hdr = ["Subfile", "Parent field", "VistA field", "Name", "FileMan type", "Global loc", "Status", "FHIR element / candidate", "Note", "DD.zwr line"]
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "---|" * len(hdr))
    for r in sub:
        status = "**NO FHIR EQUIVALENT**" if r["status"] == R.NONE else r["status"]
        target = r["fhir"] or r["candidate"]
        flags = (" _(" + ", ".join(r["flags"]) + ")_") if r["flags"] else ""
        cells = [r["file"], f"`{r['parent_field']}`", f"`{r['field']}`", md_escape(r["name"]) + flags, f"`{md_escape(r['fileman_type'])}`",
                 f"`{md_escape(r['global_location'])}`", status, md_escape(target), md_escape(r["note"]), f"[{r['dd_zwr_line']}]({r['dd_zwr_url']})"]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    m = build()
    with open(os.path.join(HERE, "mapping.json"), "w") as f:
        json.dump(m, f, indent=1)
        f.write("\n")
    with open(os.path.join(HERE, "MAPPING.md"), "w") as f:
        f.write(render_md(m))
    print(json.dumps(m["counts"], indent=1))
