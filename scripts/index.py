#!/usr/bin/env python3
"""
index.py — Build compact cache index files from retrieved metadata.

Produces:
  cache/manifest.json            — counts + timestamps
  cache/fields-index.tsv         — all custom fields across all objects
  cache/flows-index.json         — flows with writes/reads/conditions (compact)
  cache/apex-index.json          — Apex classes with writes/SOQL refs (compact)
  cache/field-writers-index.tsv  — reverse map: field → what writes/reads it

Run: python3 scripts/index.py
Called automatically by: bash scripts/retrieve.sh (at end of Phase 1)
"""

import datetime
import json
import os
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

METADATA_DIR = Path("metadata")
CACHE_DIR    = Path("cache")
NS           = "http://soap.sforce.com/2006/04/metadata"

def tag(name):
    return f"{{{NS}}}{name}"

def txt(el, name, default=""):
    found = el.findtext(tag(name))
    return (found or default).strip()

# ─── Fields index ────────────────────────────────────────────────────────────

def build_fields_index():
    rows = ["Object\tField\tType\tLabel\tFormula\tDescription"]
    for f in sorted(METADATA_DIR.glob("objects/**/*.field-meta.xml")):
        parts = f.parts
        if len(parts) < 4:
            continue
        obj_name   = parts[2]
        field_name = f.name.replace(".field-meta.xml", "")
        try:
            root    = ET.parse(f).getroot()
            ftype   = txt(root, "type")
            label   = txt(root, "label")
            formula = txt(root, "formula").replace("\n", " ")[:100]
            desc    = txt(root, "description").replace("\n", " ")[:150]
        except ET.ParseError:
            ftype = label = formula = desc = ""
        rows.append(f"{obj_name}\t{field_name}\t{ftype}\t{label}\t{formula}\t{desc}")
    return "\n".join(rows)

# ─── Flows index ──────────────────────────────────────────────────────────────

def build_flows_index():
    flows = []
    for f in sorted(METADATA_DIR.glob("flows/*.flow-meta.xml")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue

        label  = txt(root, "label") or f.stem
        ptype  = txt(root, "processType")
        status = txt(root, "status")

        # Trigger object + event
        trigger_obj, trigger_event = "", ""
        start = root.find(tag("start"))
        if start is not None:
            trigger_obj   = txt(start, "object")
            trigger_event = txt(start, "triggerType")
            if not trigger_event:
                trigger_event = txt(start, "scheduledPaths") and "Scheduled"

        # Field writes: <assignToReference> that contain __c
        writes = []
        for el in root.findall(f".//{tag('assignToReference')}"):
            v = (el.text or "").strip()
            if "__c" in v and v not in writes:
                writes.append(v)

        # Conditions (decision rules) referencing __c fields
        conditions = []
        for cond in root.findall(f".//{tag('conditions')}"):
            lref = (cond.findtext(tag("leftValueReference")) or "").strip()
            op   = (cond.findtext(tag("operator"))           or "").strip()
            rval = (cond.findtext(tag("stringValue")) or
                    cond.findtext(tag("numberValue"))  or
                    cond.findtext(tag("elementReference")) or "").strip()
            if lref:
                conditions.append(f"{lref} {op} {rval}".strip())

        flows.append({
            "file":    f.name,
            "label":   label,
            "type":    ptype,
            "status":  status,
            "obj":     trigger_obj,
            "event":   trigger_event,
            "writes":  writes[:25],
            "conds":   conditions[:10],
        })
    return flows

# ─── Apex index ───────────────────────────────────────────────────────────────

def build_apex_index():
    classes = []
    for f in sorted(METADATA_DIR.glob("classes/*.cls")):
        # Skip test classes — they add noise and are rarely the answer
        if re.search(r'[Tt]est', f.stem):
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Public/global methods (not test, not constructors)
        methods = re.findall(
            r'(?:public|global|protected|private)(?:\s+(?:static|override|virtual|abstract))*'
            r'\s+\w+\s+(\w+)\s*\(',
            src
        )
        methods = [m for m in methods
                   if m not in ("if","for","while","catch","new","return")][:20]

        # Field writes: anything.Field__c = (excludes == comparisons)
        writes = list(dict.fromkeys(
            re.findall(r'[\w]+\.([\w]+__c)\s*[+\-]?=(?!=)', src)
        ))[:20]

        # SOQL FROM objects
        soql_from = list(dict.fromkeys(
            re.findall(r'\bFROM\s+(\w+)', src, re.IGNORECASE)
        ))[:10]

        classes.append({
            "file":      f.name,
            "methods":   methods,
            "writes":    writes,
            "soql_from": soql_from,
        })
    return classes

# ─── Field-writers reverse index ─────────────────────────────────────────────

def build_field_writers(flows, apex_classes):
    rows = ["Field\tObject\tWriter\tWriterType\tFile\tMode"]
    seen = set()

    def add(field, obj, writer, wtype, wfile, mode):
        key = (field, writer, mode)
        if key in seen:
            return
        seen.add(key)
        rows.append(f"{field}\t{obj}\t{writer}\t{wtype}\t{wfile}\t{mode}")

    for flow in flows:
        obj   = flow.get("obj", "")
        label = flow.get("label", "")
        fname = flow.get("file", "")
        for ref in flow.get("writes", []):
            field = ref.rsplit(".", 1)[-1] if "." in ref else ref
            if "__c" in field:
                add(field, obj, label, "Flow", fname, "WRITE")

    for cls in apex_classes:
        cname = cls["file"].replace(".cls", "")
        for field in cls.get("writes", []):
            add(field, "(Apex)", cname, "Apex", cls["file"], "WRITE")

    return "\n".join(rows)

# ─── Manifest ────────────────────────────────────────────────────────────────

def build_manifest(retrieved_at):
    return {
        "retrieved_at":       retrieved_at,
        "index_generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "flows":              len(list(METADATA_DIR.glob("flows/*.flow-meta.xml"))),
        "apex_classes":       len(list(METADATA_DIR.glob("classes/*.cls"))),
        "triggers":           len(list(METADATA_DIR.glob("triggers/*.trigger"))),
        "fields":             len(list(METADATA_DIR.glob("objects/**/*.field-meta.xml"))),
        "layouts":            len(list(METADATA_DIR.glob("layouts/*.layout-meta.xml"))),
        "flexipages":         len(list(METADATA_DIR.glob("flexipages/*.flexipage-meta.xml"))),
        "workflows":          len(list(METADATA_DIR.glob("workflows/*.workflow-meta.xml"))),
        "validation_rules":   len(list(METADATA_DIR.glob("objects/**/*.validationRule-meta.xml"))),
    }

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    CACHE_DIR.mkdir(exist_ok=True)

    ts_file      = METADATA_DIR / ".retrieved_at"
    retrieved_at = ts_file.read_text().strip() if ts_file.exists() else "unknown"

    # Fields
    print("  fields...", end=" ", flush=True)
    fields_tsv = build_fields_index()
    (CACHE_DIR / "fields-index.tsv").write_text(fields_tsv, encoding="utf-8")
    print(f"{fields_tsv.count(chr(10))} rows")

    # Flows
    print("  flows...", end=" ", flush=True)
    flows = build_flows_index()
    flows_json = json.dumps(flows, separators=(",", ":"))
    (CACHE_DIR / "flows-index.json").write_text(flows_json, encoding="utf-8")
    print(f"{len(flows)} flows")

    # Apex
    print("  apex...", end=" ", flush=True)
    apex = build_apex_index()
    apex_json = json.dumps(apex, separators=(",", ":"))
    (CACHE_DIR / "apex-index.json").write_text(apex_json, encoding="utf-8")
    print(f"{len(apex)} classes")

    # Field writers
    print("  field-writers...", end=" ", flush=True)
    writers_tsv = build_field_writers(flows, apex)
    (CACHE_DIR / "field-writers-index.tsv").write_text(writers_tsv, encoding="utf-8")
    print(f"{writers_tsv.count(chr(10))} entries")

    # Manifest
    manifest = build_manifest(retrieved_at)
    (CACHE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Print sizes
    print()
    for fname in ["manifest.json", "fields-index.tsv", "flows-index.json",
                  "apex-index.json", "field-writers-index.tsv"]:
        p = CACHE_DIR / fname
        kb = p.stat().st_size / 1024
        print(f"    {fname:<32} {kb:6.1f} KB")

if __name__ == "__main__":
    main()
