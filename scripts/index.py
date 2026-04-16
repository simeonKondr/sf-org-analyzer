#!/usr/bin/env python3
"""
index.py — Build cache indexes for metadata and CPQ field usage.

Produces:
  cache/manifest.json                 — counts + timestamps + index_script_hash
  cache/fields-index.tsv              — all custom fields across all objects
  cache/flows-index.json              — Flows: writes, conditions, trigger object/event
  cache/apex-index.json               — Apex: reads, writes, SOQL objects, methods
  cache/triggers-index.json           — Triggers: reads, writes, events
  cache/validation-rules-index.json   — Validation rules: formula fields + picklist values tested
  cache/workflow-rules-index.json     — Workflow rules: criteria fields/values + field updates
  cache/reports-index.json            — Reports: column fields + filter fields/values
  cache/field-usage-index.json        — reverse map: field → all files using it (all types)
  cache/constants-index.json          — string constants from Apex + Flows
  cache/cpq-field-usage-index.json    — CPQ parent-child: rule → fields used in conditions/actions
  cache/email-templates-index.json    — Email templates: subject, merge fields, string constants
  cache/permission-sets-index.json    — Permission sets + profiles: field-level security
  cache/formula-deps-index.json       — Formula fields: upstream __c field references

Run: python3 scripts/index.py
Called automatically by: bash scripts/retrieve.sh (at end of Phase 1)
"""

import datetime
import hashlib
import json
import re
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

def compact_dict(obj):
    """Recursively strip None, empty string, empty list, and empty dict values."""
    if isinstance(obj, dict):
        return {k: compact_dict(v) for k, v in obj.items()
                if v is not None and v != "" and v != [] and v != {}}
    if isinstance(obj, list):
        out = [compact_dict(item) for item in obj]
        return [item for item in out
                if item is not None and item != "" and item != [] and item != {}]
    return obj

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
            # Propagate label-based deprecation into desc so downstream detection fires.
            # Salesforce marks fields deprecated via the label (e.g. "Opportunity Product Pillar (Deprecated)")
            # rather than the description field, so we merge the signal here.
            if "(deprecated)" in label.lower() and "deprecated" not in desc.lower():
                desc = ("[Deprecated per field label] " + desc).strip()
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

        # Trigger object + event + entry criteria filters
        trigger_obj, trigger_event = "", ""
        entry_conds = []
        start = root.find(tag("start"))
        if start is not None:
            trigger_obj   = txt(start, "object")
            trigger_event = txt(start, "triggerType")
            if not trigger_event:
                trigger_event = txt(start, "scheduledPaths") and "Scheduled"
            # Entry criteria: <filters> inside <start> gate when the flow fires
            for filt in start.findall(tag("filters")):
                field = (filt.findtext(tag("field")) or "").strip()
                op    = (filt.findtext(tag("operator")) or "").strip()
                val_el = filt.find(tag("value"))
                val = ""
                if val_el is not None:
                    val = (val_el.findtext(tag("stringValue"))  or
                           val_el.findtext(tag("numberValue"))  or
                           val_el.findtext(tag("booleanValue")) or "").strip()
                if field:
                    entry_conds.append(f"{field} {op} {val}".strip())
            # filterFormula entry condition (used instead of discrete <filters>)
            # e.g. OR(ISNEW(), ISCHANGED({!$Record.SomeField__c}))
            filter_formula = txt(start, "filterFormula")
            if filter_formula:
                entry_conds.append(f"filterFormula: {filter_formula[:200]}")

        # Field writes: <assignToReference> that contain __c
        writes = []
        for el in root.findall(f".//{tag('assignToReference')}"):
            v = (el.text or "").strip()
            if "__c" in v and v not in writes:
                writes.append(v)

        # Conditions (decision rules) — capture left-hand field + operator + right-hand value.
        # <rightValue> is a wrapper element; stringValue/numberValue/elementReference live inside it.
        conditions = []
        for cond in root.findall(f".//{tag('conditions')}"):
            lref = (cond.findtext(tag("leftValueReference")) or "").strip()
            op   = (cond.findtext(tag("operator"))           or "").strip()
            rv   = cond.find(tag("rightValue"))
            if rv is not None:
                rval = (rv.findtext(tag("stringValue"))     or
                        rv.findtext(tag("numberValue"))     or
                        rv.findtext(tag("elementReference")) or "").strip()
            else:
                rval = ""
            if lref:
                conditions.append(f"{lref} {op} {rval}".strip())

        # Assignment values: string constants being written to fields.
        # Captures "Field__c = 'SomeValue'" so VALUE_PATTERN searches work on assignments.
        assign_values = []
        for item in root.findall(f".//{tag('assignmentItems')}"):
            target = (item.findtext(tag("assignToReference")) or "").strip()
            val_el = item.find(tag("value"))
            if val_el is not None:
                val = (val_el.findtext(tag("stringValue")) or "").strip()
                if val and target:
                    entry = f"{target} = {val}"
                    if entry not in assign_values:
                        assign_values.append(entry)

        # Formula resource expressions: named formulas defined within the flow.
        # Captures e.g. "LowerIndustryAccount: LOWER({!Account_Record.Industry__c})"
        formula_exprs = []
        for fmla in root.findall(f".//{tag('formulas')}"):
            fname_el = (fmla.findtext(tag("name"))       or "").strip()
            expr     = (fmla.findtext(tag("expression")) or "").strip()
            if fname_el and expr:
                formula_exprs.append(f"{fname_el}: {expr[:200]}")

        # Screen/template field reads: {!Var.Field__c} references in rich text and Slack templates.
        # Covers <fieldText> in screen components and <text> in textTemplates.
        screen_refs = []
        _field_ref_re = re.compile(r'\{![^}]*\.([\w]+__c)\}')
        for el_tag in (tag("fieldText"), tag("text")):
            for el in root.findall(f".//{el_tag}"):
                for field in _field_ref_re.findall(el.text or ""):
                    if field not in screen_refs:
                        screen_refs.append(field)

        # Sub-flow callouts: which flows does this flow invoke as sub-flows?
        subflows_called = []
        for sf in root.findall(f".//{tag('subflows')}"):
            sfname = (sf.findtext(tag("flowName")) or "").strip()
            if sfname and sfname not in subflows_called:
                subflows_called.append(sfname)

        flows.append({
            "file":          f.name,
            "label":         label,
            "type":          ptype,
            "status":        status,
            "obj":           trigger_obj,
            "event":         trigger_event,
            "writes":        writes,
            "entry_conds":   entry_conds,
            "conds":         conditions,
            "assign_values": assign_values,
            "formulas":      formula_exprs,
            "screen_refs":   screen_refs,
            "subflows":      subflows_called,
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
                   if m not in ("if","for","while","catch","new","return")]

        # Field writes: anything.Field__c = (excludes == comparisons)
        writes = list(dict.fromkeys(
            re.findall(r'[\w]+\.([\w]+__c)\s*[+\-]?=(?!=)', src)
        ))

        # Field reads: .Field__c references that are not assignments
        all_refs = re.findall(r'[\w]+\.([\w]+__c)', src)
        reads = list(dict.fromkeys([r for r in all_refs if r not in writes]))

        # SOQL FROM objects
        soql_from = list(dict.fromkeys(
            re.findall(r'\bFROM\s+(\w+)', src, re.IGNORECASE)
        ))

        # Cross-object standard field references: e.g. SBQQ__Product__r.Family
        # The __c-only regex misses standard fields accessed via relationship traversal.
        # Exclude custom fields (__c) and relationship names (__r) — not actual field reads.
        cross_obj_reads = list(dict.fromkeys(
            f for f in re.findall(r'\b\w+__r\.([A-Za-z][A-Za-z0-9_]*)\b', src)
            if not f.endswith('__c') and not f.endswith('__r')
        ))

        classes.append({
            "file":           f.name,
            "methods":        methods,
            "reads":          reads,
            "writes":         writes,
            "soql_from":      soql_from,
            "cross_obj_reads": cross_obj_reads,
        })
    return classes

# ─── Triggers index ──────────────────────────────────────────────────────────

def build_triggers_index():
    triggers = []
    for f in sorted(METADATA_DIR.glob("triggers/*.trigger")):
        try:
            src = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        tname = f.stem

        # Trigger event (before/after insert/update/delete/undelete)
        event_match = re.search(r'trigger\s+\w+\s+on\s+\w+\s+\(([^)]+)\)', src)
        events = event_match.group(1).replace(' ', '').split(',') if event_match else []

        # Trigger object
        obj_match = re.search(r'trigger\s+\w+\s+on\s+(\w+)\s+\(', src)
        obj = obj_match.group(1) if obj_match else ""

        # Field writes: anything.Field__c = (excludes == comparisons)
        writes = list(dict.fromkeys(
            re.findall(r'[\w]+\.([\w]+__c)\s*[+\-]?=(?!=)', src)
        ))

        # Field reads (simple pattern: .Field__c references)
        all_refs = re.findall(r'\.([\w]+__c)', src)
        reads = list(dict.fromkeys([r for r in all_refs if r not in writes]))

        # SOQL FROM objects
        soql_from = list(dict.fromkeys(
            re.findall(r'\bFROM\s+(\w+)', src, re.IGNORECASE)
        ))

        # Cross-object standard field references (same as Apex)
        # Exclude custom fields (__c) and relationship names (__r) — not actual field reads.
        cross_obj_reads = list(dict.fromkeys(
            f for f in re.findall(r'\b\w+__r\.([A-Za-z][A-Za-z0-9_]*)\b', src)
            if not f.endswith('__c') and not f.endswith('__r')
        ))

        # String constants (quoted strings with meaningful content)
        strings = re.findall(r'["\']([^"\']{3,})["\']', src)
        constants = list(set([s for s in strings
                             if any(c.isupper() or c == '_' for c in s) and len(s) > 3]))

        triggers.append({
            "file":           f.name,
            "name":           tname,
            "object":         obj,
            "events":         events,
            "reads":          reads,
            "writes":         writes,
            "soql_from":      soql_from,
            "cross_obj_reads": cross_obj_reads,
            "constants": constants,
        })
    return triggers

# ─── Comprehensive field usage index ──────────────────────────────────────────

def build_field_usage_index(flows, apex_classes, triggers):
    """Build comprehensive map: field → all files where it's used (with context)"""
    usage = {}  # field -> [(file, type, usage_type, context), ...]

    def add_usage(field, filename, ftype, usage_type, context=""):
        if field not in usage:
            usage[field] = []
        entry = {
            "file": filename,
            "type": ftype,  # Flow, Apex, Trigger, Formula, etc.
            "usage": usage_type,  # read, write, condition, constant, soql
            "context": context[:100]  # truncate long context
        }
        if entry not in usage[field]:
            usage[field].append(entry)

    # From flows
    for flow in flows:
        fname = flow.get("file", "")
        flabel = flow.get("label", "")
        for field in flow.get("writes", []):
            add_usage(field, fname, "Flow", "write", flabel)
        for cond in flow.get("conds", []):
            fields_in_cond = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*__c)\b', cond)
            for field in fields_in_cond:
                add_usage(field, fname, "Flow", "condition", cond[:80])
        for cond in flow.get("entry_conds", []):
            fields_in_cond = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*__c)\b', cond)
            for field in fields_in_cond:
                add_usage(field, fname, "Flow", "entry_condition", cond[:80])
        # Index assignment target fields from assign_values (field = value pairs)
        for av in flow.get("assign_values", []):
            fields_in_av = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*__c)\b', av)
            for field in fields_in_av:
                add_usage(field, fname, "Flow", "assign", av[:80])
        # Index field references from screen displays and text templates (read-only)
        for field in flow.get("screen_refs", []):
            add_usage(field, fname, "Flow", "screen_read", flabel)

    # From Apex
    for cls in apex_classes:
        fname = cls.get("file", "")
        cname = cls.get("file", "").replace(".cls", "")
        for field in cls.get("writes", []):
            add_usage(field, fname, "Apex", "write", cname)
        for field in cls.get("reads", []):
            add_usage(field, fname, "Apex", "read", cname)
        # Cross-object standard field reads (e.g. SBQQ__Product__r.Family)
        for field in cls.get("cross_obj_reads", []):
            add_usage(field, fname, "Apex", "cross_obj_read", cname)

    # From Triggers
    for trig in triggers:
        fname = trig.get("file", "")
        tname = trig.get("name", "")
        events = ",".join(trig.get("events", []))
        for field in trig.get("writes", []):
            add_usage(field, fname, "Trigger", "write", f"{tname}({events})")
        for field in trig.get("reads", []):
            add_usage(field, fname, "Trigger", "read", f"{tname}({events})")
        for field in trig.get("cross_obj_reads", []):
            add_usage(field, fname, "Trigger", "cross_obj_read", f"{tname}({events})")

    return usage

# ─── Constants index ──────────────────────────────────────────────────────────

def build_constants_index():
    """Extract string constants from Apex code and Flows"""
    constants = {}  # constant_value -> [(file, context), ...]

    # Extract from Apex classes
    for f in sorted(METADATA_DIR.glob("classes/*.cls")):
        if re.search(r'[Tt]est', f.stem):
            continue
        try:
            code = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Extract quoted strings (length 3–120, single line only)
        strings = re.findall(r'["\']([^"\']{3,120})["\']', code)
        for s in strings:
            # Filter for meaningful constants (contain uppercase or underscores, no newlines)
            if '\n' not in s and any(c.isupper() or c == '_' for c in s) and not s.isdigit():
                if s not in constants:
                    constants[s] = []
                constants[s].append({
                    "file": f.name,
                    "type": "Apex",
                    "context": f.stem
                })

    # Extract from Flows
    for f in sorted(METADATA_DIR.glob("flows/*.flow-meta.xml")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue

        flow_name = f.stem

        # Extract stringValue elements
        for sv in root.findall(f".//{tag('stringValue')}"):
            val = (sv.text or "").strip()
            if len(val) > 2 and any(c.isupper() or c == '_' for c in val):
                if val not in constants:
                    constants[val] = []
                constants[val].append({
                    "file": f.name,
                    "type": "Flow",
                    "context": flow_name
                })

        # Extract numberValue elements as strings
        for nv in root.findall(f".//{tag('numberValue')}"):
            val = (nv.text or "").strip()
            if val and not val.isdigit():
                if val not in constants:
                    constants[val] = []
                constants[val].append({
                    "file": f.name,
                    "type": "Flow",
                    "context": flow_name
                })

    return constants

# ─── Validation rules index ──────────────────────────────────────────────────

def build_validation_rules_index():
    """
    Per validation rule: object, active flag, fields referenced in formula,
    picklist values tested (ISPICKVAL/INCLUDES), and truncated formula + message.
    """
    rules = []
    for f in sorted(METADATA_DIR.glob("objects/**/*.validationRule-meta.xml")):
        parts = f.parts
        obj_name = parts[2] if len(parts) >= 4 else ""
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue

        active  = txt(root, "active") == "true"
        formula = txt(root, "errorConditionFormula")
        message = txt(root, "errorMessage")
        name    = f.name.replace(".validationRule-meta.xml", "")

        # Custom fields in formula
        fields = sorted(set(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*__c)\b', formula)))

        # Picklist values tested with ISPICKVAL or INCLUDES
        values = sorted(set(re.findall(
            r'(?:ISPICKVAL|INCLUDES)\s*\([^,]+,\s*["\']([^"\']+)["\']', formula
        )))

        rules.append({
            "file":    f.name,
            "object":  obj_name,
            "name":    name,
            "active":  active,
            "fields":  fields,
            "values":  values,
            "formula": formula[:200],
            "message": message[:120],
        })
    return rules


# ─── Workflow rules index ─────────────────────────────────────────────────────

def build_workflow_rules_index():
    """
    Per workflow rule: object, active flag, trigger type, criteria field/value pairs,
    formula, and which fields the rule's field-update actions write.
    """
    rules = []
    for f in sorted(METADATA_DIR.glob("workflows/*.workflow-meta.xml")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue

        obj_name = f.name.replace(".workflow-meta.xml", "")

        # Build name → field update map for this file
        fu_map = {}
        for fu in root.findall(f".//{tag('fieldUpdates')}"):
            fu_name    = txt(fu, "fullName")
            fu_field   = txt(fu, "field")
            fu_formula = txt(fu, "formula")
            fu_value   = txt(fu, "literalValue")
            if fu_name:
                fu_map[fu_name] = {
                    "field":   fu_field,
                    "formula": fu_formula[:100],
                    "value":   fu_value,
                }

        for rule in root.findall(f".//{tag('rules')}"):
            rule_name    = txt(rule, "fullName")
            active       = txt(rule, "active") == "true"
            trigger_type = txt(rule, "triggerType")
            formula      = txt(rule, "formula")

            # Criteria items
            criteria = []
            for ci in rule.findall(f".//{tag('criteriaItems')}"):
                field = txt(ci, "field")
                op    = txt(ci, "operation")
                val   = txt(ci, "value")
                if field:
                    criteria.append({"field": field, "operator": op, "value": val})

            # Fields updated by this rule's actions
            writes = []
            for action in rule.findall(f".//{tag('actions')}"):
                aname = txt(action, "name")
                atype = txt(action, "type")
                if atype == "FieldUpdate" and aname in fu_map:
                    fld = fu_map[aname].get("field", "")
                    if fld and fld not in writes:
                        writes.append(fld)

            # All field references (criteria + formula + writes)
            criteria_fields = [c["field"].split(".")[-1] for c in criteria if c["field"]]
            formula_fields  = re.findall(r'\b([A-Za-z][A-Za-z0-9_]*__c)\b', formula) if formula else []
            all_fields      = sorted(set(criteria_fields + formula_fields + writes))
            criteria_values = sorted(set(c["value"] for c in criteria if c["value"]))

            rules.append({
                "file":     f.name,
                "object":   obj_name,
                "name":     rule_name,
                "active":   active,
                "trigger":  trigger_type,
                "fields":   all_fields,
                "criteria": criteria,
                "values":   criteria_values,
                "formula":  formula[:150] if formula else "",
                "writes":   writes,
            })
    return rules


# ─── Reports index ────────────────────────────────────────────────────────────

def build_reports_index():
    """
    Built from SOQL-exported data (reports-all.json).

    reports-all.json is fetched via the Tooling API during retrieval and includes
    a Metadata compound field per report.  When Metadata is present this function
    extracts column fields, filter fields, and filter values so reports can be
    found by the fields they use.  Falls back to name/folder/description matching
    when Metadata is absent (standard-API fallback path).

    Each entry in the returned list:
      id, name, dev_name, folder, format, last_run, description,
      fields        — column + grouping + filter field API names (sorted, deduplicated)
      filter_values — values from filter criteria items
      searchable    — lowercase join of all matching surfaces
    """
    cpq_dir = Path("data/cpq")

    def load(filename):
        f = cpq_dir / filename
        if not f.exists():
            return []
        try:
            data = json.loads(f.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def parse_describe(desc_record):
        """
        Extract normalised field names and filter values from one Analytics describe record.

        Column/grouping names use Salesforce's report column ID format:
          - Cross-object custom:   Opportunity.Product_Families__c
          - Cross-object standard: ACCOUNT.NAME, OPPORTUNITY.STAGE_NAME
          - Bare custom:           MY_FIELD__C
        We keep the full form AND a bare-suffix form so both
        'Product_Families__c' and 'Opportunity.Product_Families__c' match.

        Returns (fields: list[str], filter_values: list[str]).
        """
        raw_fields = set()

        for col in desc_record.get("columns") or []:
            # Strip conversion suffix like ".CONVERT" from "Opportunity.ARR__c.CONVERT"
            name = col.split(".CONVERT")[0].strip() if isinstance(col, str) else ""
            if name:
                raw_fields.add(name)

        for g in desc_record.get("groupings") or []:
            name = g.split(".CONVERT")[0].strip() if isinstance(g, str) else ""
            if name:
                raw_fields.add(name)

        filter_values = []
        for f in desc_record.get("filters") or []:
            col = (f.get("column") or "").split(".CONVERT")[0].strip()
            val = (f.get("value") or "").strip()
            if col:
                raw_fields.add(col)
            if val:
                filter_values.append(val)

        # Build normalised set: keep original + bare suffix (after last dot)
        normalised = set()
        for f in raw_fields:
            normalised.add(f)
            suffix = f.split(".")[-1]
            if suffix != f:
                normalised.add(suffix)

        return sorted(normalised), filter_values

    # Load Analytics describe enrichment (reports-describe.json produced by retrieve.sh)
    describe_by_id = {}
    for d in load("reports-describe.json"):
        rid = d.get("id")
        if rid:
            describe_by_id[rid] = d

    reports = []
    for r in load("reports-all.json"):
        rid      = r.get("Id", "")
        name     = r.get("Name", "")
        dev_name = r.get("DeveloperName", "")
        folder   = r.get("FolderName", "")
        desc     = (r.get("Description") or "").strip()
        fmt      = r.get("Format", "")
        last_run = r.get("LastRunDate", "")

        fields, filter_values = (
            parse_describe(describe_by_id[rid])
            if rid in describe_by_id
            else ([], [])
        )

        reports.append({
            "id":            rid,
            "name":          name,
            "dev_name":      dev_name,
            "folder":        folder,
            "format":        fmt,
            "last_run":      last_run,
            "description":   desc[:200],
            "fields":        fields,
            "filter_values": filter_values,
            # searchable covers name + folder + description + all field names
            "searchable":    " ".join([name, dev_name, folder, desc] + fields).lower(),
        })

    return reports


# ─── Dashboards index ─────────────────────────────────────────────────────────

def build_dashboards_index():
    """
    Built from SOQL-exported data (dashboards.json + dashboard-components.json).

    dashboard-components.json is populated via Tooling API during retrieve and
    maps DashboardId → component names/types. Falls back gracefully if absent.
    """
    cpq_dir = Path("data/cpq")

    def load(filename):
        f = cpq_dir / filename
        if not f.exists():
            return []
        try:
            data = json.loads(f.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    components_by_dashboard = {}
    for c in load("dashboard-components.json"):
        did = c.get("DashboardId", "")
        if did:
            components_by_dashboard.setdefault(did, []).append(c.get("Name", ""))

    dashboards = []
    for d in load("dashboards.json"):
        did   = d.get("Id", "")
        title = d.get("Title", "")
        folder = d.get("FolderName", "")
        desc  = (d.get("Description") or "").strip()
        components = components_by_dashboard.get(did, [])

        dashboards.append({
            "id":           did,
            "title":        title,
            "dev_name":     d.get("DeveloperName", ""),
            "folder":       folder,
            "last_modified": d.get("LastModifiedDate", ""),
            "description":  desc[:200],
            "components":   components,
            # searchable covers title + folder + description + component names
            "searchable":   f"{title} {folder} {desc} {' '.join(components)}".lower(),
        })

    return dashboards


# ─── CPQ field usage index ───────────────────────────────────────────────────

def build_cpq_field_usage_index():
    """
    Parent-child CPQ field usage index.

    For each parent record (PriceRule, ProductRule, SummaryVariable, LookupQuery,
    ConfigurationAttribute, ProductOption, SearchFilter, CustomScript,
    ApprovalRule, ApprovalVariable) produces:
      {
        "id":     "...",
        "name":   "...",
        "fields": ["UniqueField__c", ...],   # unique field names across all children
        "<child_type>": [ { "field": ..., ... }, ... ]
      }

    "fields" contains the VALUES of content columns (e.g. SBQQ__TestedField__c = "Price__c"),
    NOT the column names themselves.
    """
    cpq_dir = Path("data/cpq")
    if not cpq_dir.exists():
        return {}

    def load(filename):
        f = cpq_dir / filename
        if not f.exists():
            return []
        try:
            data = json.loads(f.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def group_by(records, key):
        groups = {}
        for r in records:
            k = r.get(key)
            if k:
                groups.setdefault(k, []).append(r)
        return groups

    def is_field_name(val):
        """Return val if it looks like a Salesforce field API name, else None."""
        if not val or not isinstance(val, str):
            return None
        v = val.strip()
        if re.match(r'^[A-Za-z][A-Za-z0-9_]{1,79}$', v):
            return v
        return None

    def fields_from_formula(formula):
        """Extract __c field refs from a formula string."""
        if not formula or not isinstance(formula, str):
            return []
        return sorted(set(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*__c)\b', formula)))

    def extract_constants(values):
        """Return unique non-empty string values that are not Salesforce field API names."""
        seen = set()
        out = []
        for v in values:
            if not v or not isinstance(v, str):
                continue
            v = v.strip()
            if len(v) < 2:
                continue
            if is_field_name(v):   # skip bare field API names — already in "fields"
                continue
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    # ── Load data ─────────────────────────────────────────────────────────────
    price_rules       = load("price-rules.json")
    price_conditions  = load("price-conditions.json")
    price_actions     = load("price-actions.json")
    product_rules     = load("product-rules.json")
    error_conditions  = load("error-conditions.json")
    summary_variables = load("summary-variables.json")
    lookup_queries    = load("lookup-queries.json")
    lq_lines          = load("lookup-query-lines.json")
    config_attrs      = load("configuration-attributes.json")
    product_options   = load("product-options.json")
    search_filters    = load("search-filters.json")
    custom_scripts    = load("custom-scripts.json")

    result = {}

    # ── Price Rules ───────────────────────────────────────────────────────────
    conds_by_rule   = group_by(price_conditions, "SBQQ__Rule__c")
    actions_by_rule = group_by(price_actions,    "SBQQ__Rule__c")

    pr_entries = []
    for rule in price_rules:
        rid   = rule.get("Id")
        rname = rule.get("Name", rid)

        cond_out = []
        for c in conds_by_rule.get(rid, []):
            field = is_field_name(c.get("SBQQ__TestedField__c") or c.get("SBQQ__Field__c"))
            entry = {
                "field":    field or "",
                "object":   c.get("SBQQ__Object__c", ""),
                "operator": c.get("SBQQ__Operator__c", ""),
                "value":    c.get("SBQQ__FilterValue__c") or c.get("SBQQ__Value__c") or "",
            }
            if c.get("SBQQ__FilterFormula__c"):
                entry["formula"] = c["SBQQ__FilterFormula__c"]
            cond_out.append(entry)

        action_out = []
        for a in actions_by_rule.get(rid, []):
            field = is_field_name(a.get("SBQQ__TargetField__c") or a.get("SBQQ__Field__c"))
            entry = {
                "field":  field or "",
                "object": a.get("SBQQ__TargetObject__c", ""),
                "type":   a.get("SBQQ__Type__c", ""),
                "value":  a.get("SBQQ__Value__c", ""),
            }
            if a.get("SBQQ__Formula__c"):
                entry["formula"] = a["SBQQ__Formula__c"]
            action_out.append(entry)

        all_fields = sorted({e["field"] for e in cond_out + action_out if e.get("field")})
        all_constants = extract_constants(
            [e.get("value", "") for e in cond_out + action_out] +
            [e.get("formula", "") for e in cond_out + action_out]
        )

        pr_entries.append({
            "id":         rid,
            "name":       rname,
            "fields":     all_fields,
            "constants":  all_constants,
            "conditions": cond_out,
            "actions":    action_out,
        })

    result["PriceRule"] = pr_entries

    # ── Product Rules ─────────────────────────────────────────────────────────
    econd_by_rule = group_by(error_conditions, "SBQQ__Rule__c")

    prd_entries = []
    for rule in product_rules:
        rid   = rule.get("Id")
        rname = rule.get("Name", rid)

        econd_out = []
        for c in econd_by_rule.get(rid, []):
            field = is_field_name(c.get("SBQQ__TestedField__c") or c.get("SBQQ__Field__c"))
            entry = {
                "field":    field or "",
                "object":   c.get("SBQQ__Object__c", ""),
                "operator": c.get("SBQQ__Operator__c", ""),
                "value":    c.get("SBQQ__FilterValue__c") or c.get("SBQQ__Value__c") or "",
            }
            if c.get("SBQQ__FilterFormula__c"):
                entry["formula"] = c["SBQQ__FilterFormula__c"]
            econd_out.append(entry)

        formula_str = rule.get("SBQQ__ErrorConditionFormula__c", "") or ""
        formula_fields = fields_from_formula(formula_str)
        all_fields = sorted(
            {e["field"] for e in econd_out if e.get("field")} | set(formula_fields)
        )
        all_constants = extract_constants(
            [e.get("value", "") for e in econd_out] +
            [e.get("formula", "") for e in econd_out] +
            [formula_str]
        )

        prd_entries.append({
            "id":                      rid,
            "name":                    rname,
            "fields":                  all_fields,
            "constants":               all_constants,
            "error_condition_formula": formula_str,
            "error_conditions":        econd_out,
        })

    result["ProductRule"] = prd_entries

    # ── Summary Variables ─────────────────────────────────────────────────────
    sv_entries = []
    for sv in summary_variables:
        target     = is_field_name(sv.get("SBQQ__TargetField__c") or sv.get("SBQQ__Field__c"))
        filter_fld = is_field_name(sv.get("SBQQ__FilterField__c"))
        all_fields = sorted({f for f in [target, filter_fld] if f})

        sv_constants = extract_constants([
            sv.get("SBQQ__FilterValue__c", ""),
            sv.get("SBQQ__FilterFormula__c", ""),
        ])

        sv_entries.append({
            "id":           sv.get("Id"),
            "name":         sv.get("Name", sv.get("Id")),
            "fields":       all_fields,
            "constants":    sv_constants,
            "target_field": target or "",
            "filter": {
                "field":    filter_fld or "",
                "operator": sv.get("SBQQ__FilterOperator__c", ""),
                "value":    sv.get("SBQQ__FilterValue__c", ""),
                "formula":  sv.get("SBQQ__FilterFormula__c", ""),
            },
        })

    result["SummaryVariable"] = sv_entries

    # ── Lookup Queries ────────────────────────────────────────────────────────
    lines_by_lq = group_by(lq_lines, "SBQQ__LookupQuery__c")

    lq_entries = []
    for lq in lookup_queries:
        lq_id  = lq.get("Id")
        vfield = is_field_name(lq.get("SBQQ__ValueField__c") or lq.get("SBQQ__ResultField__c"))
        lfield = is_field_name(lq.get("SBQQ__LookupField__c") or lq.get("SBQQ__MatchField__c"))

        line_out = []
        for line in lines_by_lq.get(lq_id, []):
            f = is_field_name(line.get("SBQQ__Field__c"))
            line_out.append({"field": f or "", "value": line.get("SBQQ__Value__c", "")})

        all_fields = sorted(
            {f for f in [vfield, lfield] if f} |
            {l["field"] for l in line_out if l.get("field")}
        )

        lq_constants = extract_constants(
            [l.get("value", "") for l in line_out] +
            [lq.get("SBQQ__Query__c", "")]
        )

        lq_entries.append({
            "id":           lq_id,
            "name":         lq.get("Name", lq_id),
            "fields":       all_fields,
            "constants":    lq_constants,
            "value_field":  vfield or "",
            "lookup_field": lfield or "",
            "query":        lq.get("SBQQ__Query__c", ""),
            "lines":        line_out,
        })

    result["LookupQuery"] = lq_entries

    # ── Configuration Attributes ──────────────────────────────────────────────
    ca_entries = []
    for ca in config_attrs:
        target = is_field_name(ca.get("SBQQ__TargetField__c"))
        ca_constants = extract_constants([ca.get("SBQQ__DefaultValue__c", "")])

        ca_entries.append({
            "id":            ca.get("Id"),
            "name":          ca.get("Name", ca.get("Id")),
            "fields":        [target] if target else [],
            "constants":     ca_constants,
            "target_field":  target or "",
            "default_value": ca.get("SBQQ__DefaultValue__c", ""),
            "hidden":        ca.get("SBQQ__Hidden__c"),
            "required":      ca.get("SBQQ__Required__c"),
        })

    result["ConfigurationAttribute"] = ca_entries

    # ── Product Options ───────────────────────────────────────────────────────
    po_entries = []
    for po in product_options:
        filt        = po.get("SBQQ__Filter__c") or ""
        filt_fields = fields_from_formula(filt)
        po_entries.append({
            "id":     po.get("Id"),
            "name":   po.get("Name", po.get("Id")),
            "fields": filt_fields,
            "filter": filt,
        })

    result["ProductOption"] = po_entries

    # ── Search Filters ────────────────────────────────────────────────────────
    sf_entries = []
    for sf in search_filters:
        field = is_field_name(sf.get("SBQQ__Field__c"))
        sf_constants = extract_constants([sf.get("SBQQ__Value__c", "")])

        sf_entries.append({
            "id":       sf.get("Id"),
            "name":     sf.get("Name", sf.get("Id")),
            "fields":   [field] if field else [],
            "constants": sf_constants,
            "field":    field or "",
            "operator": sf.get("SBQQ__Operator__c", ""),
            "value":    sf.get("SBQQ__Value__c", ""),
        })

    result["SearchFilter"] = sf_entries

    # ── Custom Scripts ────────────────────────────────────────────────────────
    cs_entries = []
    for cs in custom_scripts:
        code   = cs.get("SBQQ__Code__c") or ""
        fields = fields_from_formula(code)
        # Extract quoted string literals from JS code (length >= 3, has uppercase or underscore)
        raw_strings = re.findall(r'["\']([^"\']{3,})["\']', code)
        cs_constants = extract_constants(
            [s for s in raw_strings if any(c.isupper() or c == '_' for c in s)]
        )
        cs_entries.append({
            "id":          cs.get("Id"),
            "name":        cs.get("Name", cs.get("Id")),
            "fields":      fields,
            "constants":   cs_constants,
            "code_length": len(code),
        })

    result["CustomScript"] = cs_entries

    # ── Approval Rules ────────────────────────────────────────────────────────
    approval_rules      = load("approval-rules.json")
    approval_conditions = load("approval-conditions.json")
    approval_variables  = load("approval-variables.json")

    acond_by_rule = group_by(approval_conditions, "SBQQ__Rule__c")

    # Build a lookup of variable Id → variable record for condition enrichment
    var_by_id = {v.get("Id"): v for v in approval_variables if v.get("Id")}

    ar_entries = []
    for rule in approval_rules:
        rid   = rule.get("Id")
        rname = rule.get("Name", rid)

        cond_out = []
        for c in acond_by_rule.get(rid, []):
            field = is_field_name(c.get("SBQQ__TestedField__c"))
            # Resolve variable name if condition references a variable
            var_id   = c.get("SBQQ__Variable__c")
            var_name = var_by_id.get(var_id, {}).get("Name", "") if var_id else ""
            entry = {
                "field":    field or "",
                "object":   c.get("SBQQ__Object__c", ""),
                "operator": c.get("SBQQ__Operator__c", ""),
                "value":    c.get("SBQQ__FilterValue__c", ""),
            }
            if c.get("SBQQ__FilterFormula__c"):
                entry["formula"] = c["SBQQ__FilterFormula__c"]
            if var_name:
                entry["variable"] = var_name
            cond_out.append(entry)

        # Approver field is also a field reference
        approver_field = is_field_name(rule.get("SBQQ__ApproverField__c"))

        all_fields = sorted(
            {e["field"] for e in cond_out if e.get("field")} |
            ({approver_field} if approver_field else set())
        )
        all_constants = extract_constants(
            [e.get("value", "") for e in cond_out] +
            [e.get("formula", "") for e in cond_out]
        )

        ar_entries.append({
            "id":             rid,
            "name":           rname,
            "active":         rule.get("SBQQ__Active__c"),
            "step_number":    rule.get("SBQQ__StepNumber__c"),
            "evaluation_event": rule.get("SBQQ__EvaluationEvent__c", ""),
            "conditions_met": rule.get("SBQQ__ConditionsMet__c", ""),
            "target_object":  rule.get("SBQQ__TargetObject__c", ""),
            "approver_field": approver_field or "",
            "reject_behavior": rule.get("SBQQ__RejectBehavior__c", ""),
            "fields":         all_fields,
            "constants":      all_constants,
            "conditions":     cond_out,
        })

    result["ApprovalRule"] = ar_entries

    # ── Approval Variables (standalone index) ─────────────────────────────────
    av_entries = []
    for av in approval_variables:
        target     = is_field_name(av.get("SBQQ__TargetField__c"))
        filter_fld = is_field_name(av.get("SBQQ__FilterField__c"))
        all_fields = sorted({f for f in [target, filter_fld] if f})
        av_constants = extract_constants([
            av.get("SBQQ__FilterValue__c", ""),
            av.get("SBQQ__FilterFormula__c", ""),
        ])
        av_entries.append({
            "id":           av.get("Id"),
            "name":         av.get("Name", av.get("Id")),
            "fields":       all_fields,
            "constants":    av_constants,
            "target_field": target or "",
            "object":       av.get("SBQQ__Object__c", ""),
            "filter": {
                "field":    filter_fld or "",
                "operator": av.get("SBQQ__FilterOperator__c", ""),
                "value":    av.get("SBQQ__FilterValue__c", ""),
                "formula":  av.get("SBQQ__FilterFormula__c", ""),
            },
        })

    result["ApprovalVariable"] = av_entries

    # ── Inverted constants index ───────────────────────────────────────────────
    # _constants: { "Engagement": [{"type": "PriceRule", "id": ..., "name": ...}, ...], ... }
    # Lets analysis query "which CPQ rules reference this picklist value?"
    inv = {}
    for type_name, entries in result.items():
        for entry in entries:
            for c in entry.get("constants", []):
                inv.setdefault(c, []).append({
                    "type": type_name,
                    "id":   entry.get("id"),
                    "name": entry.get("name"),
                })
    result["_constants"] = inv

    return result


# ─── LWC / Aura index ────────────────────────────────────────────────────────

def build_ui_components_index():
    """
    Index LWC and Aura components for field references, Apex imports, and
    string constants.

    For LWC (.js files):
      - @salesforce/apex/ClassName.method  → apex_imports
      - @salesforce/schema/Object.Field__c → schema_imports
      - .Field__c references in JS         → fields (reads)
      - string literals                    → constants

    For Aura (.cmp / controller .js files):
      - controller="ClassName"             → apex_imports
      - {!v.Record.Field__c} bindings      → fields
      - .Field__c references in JS         → fields
      - string literals                    → constants

    Output per entry:
      { "name": "...", "type": "lwc"|"aura", "files": [...],
        "apex_imports": [...], "schema_imports": [...],
        "fields": [...], "objects": [...], "constants": [...] }
    """
    components = []

    # ── LWC ──────────────────────────────────────────────────────────────────
    for comp_dir in sorted((METADATA_DIR / "lwc").iterdir()):
        if not comp_dir.is_dir():
            continue

        apex_imports   = []
        schema_imports = []
        fields         = []
        objects        = []
        constants      = []
        files_seen     = []

        for f in sorted(comp_dir.iterdir()):
            if f.suffix not in (".js", ".html"):
                continue
            try:
                src = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            files_seen.append(f.name)

            # @salesforce/apex/ClassName.methodName
            for imp in re.findall(
                r"from\s+['\"]@salesforce/apex/([A-Za-z0-9_.]+)['\"]", src
            ):
                cls = imp.split(".")[0]
                if cls not in apex_imports:
                    apex_imports.append(cls)

            # @salesforce/schema/ObjectName.FieldName or just ObjectName
            for imp in re.findall(
                r"from\s+['\"]@salesforce/schema/([A-Za-z0-9_.]+)['\"]", src
            ):
                schema_imports.append(imp)
                parts = imp.split(".")
                obj = parts[0]
                if obj not in objects:
                    objects.append(obj)
                if len(parts) > 1 and parts[1] not in fields:
                    fields.append(parts[1])

            # .Field__c and Field__c references in JS/HTML
            for ref in re.findall(r'\b([A-Za-z][A-Za-z0-9_]*__c)\b', src):
                if ref not in fields:
                    fields.append(ref)

            # String constants (meaningful: uppercase or underscore, 3–80 chars)
            for s in re.findall(r'["\']([^"\']{3,80})["\']', src):
                if '\n' not in s and any(c.isupper() or c == '_' for c in s):
                    if s not in constants:
                        constants.append(s)

        if fields or apex_imports or schema_imports:
            components.append({
                "name":           comp_dir.name,
                "type":           "lwc",
                "files":          files_seen,
                "apex_imports":   apex_imports,
                "schema_imports": schema_imports,
                "fields":         fields,
                "objects":        objects,
                "constants":      constants,
            })

    # ── Aura ─────────────────────────────────────────────────────────────────
    for comp_dir in sorted((METADATA_DIR / "aura").iterdir()):
        if not comp_dir.is_dir():
            continue

        apex_imports = []
        fields       = []
        objects      = []
        constants    = []
        files_seen   = []

        for f in sorted(comp_dir.iterdir()):
            if f.suffix not in (".cmp", ".js", ".app", ".evt"):
                continue
            try:
                src = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            files_seen.append(f.name)

            # Aura controller="ClassName" attribute
            for cls in re.findall(r'controller\s*=\s*["\']([A-Za-z0-9_]+)["\']', src):
                if cls not in apex_imports:
                    apex_imports.append(cls)

            # {!v.Record.Field__c} and {!v.Field__c} bindings in .cmp
            for ref in re.findall(r'\{![^}]*\b([A-Za-z][A-Za-z0-9_]*__c)\b[^}]*\}', src):
                if ref not in fields:
                    fields.append(ref)

            # .Field__c references in JS
            for ref in re.findall(r'\b([A-Za-z][A-Za-z0-9_]*__c)\b', src):
                if ref not in fields:
                    fields.append(ref)

            # String constants
            for s in re.findall(r'["\']([^"\']{3,80})["\']', src):
                if '\n' not in s and any(c.isupper() or c == '_' for c in s):
                    if s not in constants:
                        constants.append(s)

        if fields or apex_imports:
            components.append({
                "name":         comp_dir.name,
                "type":         "aura",
                "files":        files_seen,
                "apex_imports": apex_imports,
                "fields":       fields,
                "objects":      objects,
                "constants":    constants,
            })

    return components


# ─── Layouts index ───────────────────────────────────────────────────────────

def build_layouts_index():
    """
    Per layout: list of all field API names that appear in any section.
    Enables "which layouts show this field" queries without grepping 330 files.

    Output per entry:
      { "file": "...", "object": "...", "fields": ["Field__c", ...],
        "sections": [{"label": "...", "fields": [...]}, ...] }
    """
    layouts = []
    for f in sorted(METADATA_DIR.glob("layouts/*.layout-meta.xml")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue

        # Derive object name from filename: "Account-Account Layout.layout-meta.xml"
        obj_name = f.name.split("-")[0] if "-" in f.name else f.stem.replace(".layout-meta.xml", "")

        sections = []
        all_fields = []

        for section in root.findall(f".//{tag('layoutSections')}"):
            sec_label = txt(section, "label")
            sec_fields = []
            for item in section.findall(f".//{tag('layoutItems')}"):
                field = txt(item, "field")
                if field:
                    sec_fields.append(field)
                    if field not in all_fields:
                        all_fields.append(field)
            if sec_fields:
                sections.append({"label": sec_label, "fields": sec_fields})

        # Also catch fields outside layoutSections (e.g. related lists, header)
        for item in root.findall(f".//{tag('layoutItems')}"):
            field = txt(item, "field")
            if field and field not in all_fields:
                all_fields.append(field)

        if all_fields:
            layouts.append({
                "file":     f.name,
                "object":   obj_name,
                "fields":   all_fields,
                "sections": sections,
            })

    return layouts


# ─── Custom Metadata index ────────────────────────────────────────────────────

def build_custom_metadata_index():
    """
    Per CMDT record: the type name, record name/label, and all field→value pairs.
    Indexed so analysis can query "which CMDT records reference pillar value X".

    Output structure:
      {
        "TypeName": [
          { "record": "TypeName.RecordName", "label": "...",
            "values": { "Field__c": "value", ... } },
          ...
        ],
        ...
      }
    """
    by_type = {}
    NS_XSI = "http://www.w3.org/1999/XMLSchema-instance"

    for f in sorted(METADATA_DIR.glob("customMetadata/*.md-meta.xml")):
        # Filename: TypeName.RecordName.md-meta.xml
        parts = f.name.replace(".md-meta.xml", "").split(".", 1)
        type_name   = parts[0] if parts else f.stem
        record_name = parts[1] if len(parts) > 1 else ""

        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue

        label = txt(root, "label")
        values = {}

        for val_el in root.findall(tag("values")):
            field = txt(val_el, "field")
            # <value xsi:type="xsd:string">...</value>
            val_el_inner = val_el.find(tag("value"))
            value = (val_el_inner.text or "").strip() if val_el_inner is not None else ""
            if field:
                values[field] = value[:300]  # truncate very long text fields

        if values:
            by_type.setdefault(type_name, []).append({
                "record": f"{type_name}.{record_name}",
                "label":  label,
                "values": values,
            })

    return by_type


# ─── Quick Actions index ──────────────────────────────────────────────────────

def build_quick_actions_index():
    """
    Per quick action: target object, action type, and field API names shown
    in the action layout (including any with default values).

    Enables "which quick actions surface this field" queries.

    Output per entry:
      { "file": "...", "object": "...", "name": "...", "type": "...",
        "fields": ["Field__c", ...],
        "defaults": [{"field": "Field__c", "value": "..."}, ...] }
    """
    actions = []
    for f in sorted(METADATA_DIR.glob("quickActions/*.quickAction-meta.xml")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue

        # Filename: Object.ActionName.quickAction-meta.xml
        parts = f.name.replace(".quickAction-meta.xml", "").split(".", 1)
        obj_name    = parts[0] if parts else ""
        action_name = parts[1] if len(parts) > 1 else f.stem

        action_type   = txt(root, "type")
        target_object = txt(root, "targetObject") or obj_name

        # Fields in the quick action layout
        fields = []
        for item in root.findall(f".//{tag('quickActionLayoutItems')}"):
            field = txt(item, "field")
            if field and field not in fields:
                fields.append(field)

        # Field default values
        defaults = []
        for fd in root.findall(f".//{tag('fieldOverrides')}"):
            field = txt(fd, "field")
            formula = txt(fd, "formula")
            literal = txt(fd, "literalValue")
            value = formula or literal
            if field and value:
                defaults.append({"field": field, "value": value[:100]})
                if field not in fields:
                    fields.append(field)

        if fields or defaults:
            actions.append({
                "file":     f.name,
                "object":   obj_name,
                "name":     action_name,
                "type":     action_type,
                "target":   target_object,
                "fields":   fields,
                "defaults": defaults,
            })

    return actions


# ─── Email templates index ───────────────────────────────────────────────────

def build_email_templates_index():
    """
    Extract field refs and string constants from email templates.
    Covers both classic (.email / .email-meta.xml) and Lightning (.emailTemplate-meta.xml).

    Output per entry:
      { "file": "...", "name": "...", "subject": "...",
        "fields": ["Field__c", ...], "constants": [...] }
    """
    templates = []

    # ── Classic email templates (metadata/email/**/*.email-meta.xml) ──────────
    email_dir = METADATA_DIR / "email"
    if email_dir.exists():
        for meta_f in sorted(email_dir.rglob("*.email-meta.xml")):
            try:
                root = ET.parse(meta_f).getroot()
            except ET.ParseError:
                continue

            subject  = txt(root, "subject")
            name     = meta_f.name.replace(".email-meta.xml", "")
            rel_path = str(meta_f.relative_to(METADATA_DIR))

            # Body file: swap .email-meta.xml → .email
            body_f = meta_f.with_name(name + ".email")
            body_text = ""
            if body_f.exists():
                try:
                    body_text = body_f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass

            combined = subject + " " + body_text

            # Merge field refs like {!Opportunity.Product_Pillar__c}
            merge_fields = list(dict.fromkeys(
                re.findall(r'\{![\w.]+\.([\w]+__c)\}', combined)
            ))
            # Bare __c refs
            bare_fields = list(dict.fromkeys(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*__c)\b', combined)))
            fields = list(dict.fromkeys(merge_fields + bare_fields))

            constants = []
            for s in re.findall(r'["\']([^"\']{3,120})["\']', combined):
                if '\n' not in s and any(c.isupper() or c == '_' for c in s):
                    if s not in constants:
                        constants.append(s)

            if subject or fields:
                templates.append({
                    "file":      rel_path,
                    "name":      name,
                    "subject":   subject[:200],
                    "fields":    fields,
                    "constants": constants[:30],
                })

    # ── Lightning email templates (metadata/emailTemplates/*.emailTemplate-meta.xml) ─
    et_dir = METADATA_DIR / "emailTemplates"
    if et_dir.exists():
        for meta_f in sorted(et_dir.rglob("*.emailTemplate-meta.xml")):
            try:
                root = ET.parse(meta_f).getroot()
            except ET.ParseError:
                continue

            subject  = txt(root, "subject")
            name     = meta_f.name.replace(".emailTemplate-meta.xml", "")
            rel_path = str(meta_f.relative_to(METADATA_DIR))

            html_val  = txt(root, "htmlValue")
            text_val  = txt(root, "textValue")
            combined  = subject + " " + html_val + " " + text_val

            merge_fields = list(dict.fromkeys(
                re.findall(r'\{![\w.]+\.([\w]+__c)\}', combined)
            ))
            bare_fields = list(dict.fromkeys(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*__c)\b', combined)))
            fields = list(dict.fromkeys(merge_fields + bare_fields))

            constants = []
            for s in re.findall(r'["\']([^"\']{3,120})["\']', combined):
                if '\n' not in s and any(c.isupper() or c == '_' for c in s):
                    if s not in constants:
                        constants.append(s)

            if subject or fields:
                templates.append({
                    "file":      rel_path,
                    "name":      name,
                    "subject":   subject[:200],
                    "fields":    fields,
                    "constants": constants[:30],
                })

    return templates


# ─── Permission sets + profiles index ────────────────────────────────────────

def build_permission_sets_index():
    """
    Field-level security from permission sets and profiles.
    Enables "which profiles/perm sets can read or edit Product_Pillar__c" queries.

    Output: list of {file, name, label, ptype, field_permissions: [{field, readable, editable}]}

    field is in "Object.FieldApiName" format (as stored in the XML).
    Only entries with readable=true or editable=true are included to keep the index small.
    """
    entries = []

    def parse_fls(f, ptype):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            return None

        name  = f.name.split(".")[0]
        label = root.findtext(tag("label")) or name

        field_perms = []
        for fp in root.findall(tag("fieldPermissions")):
            field    = txt(fp, "field")   # e.g. "Opportunity.Product_Pillar__c"
            readable = txt(fp, "readable") == "true"
            editable = txt(fp, "editable") == "true"
            if field and (readable or editable):
                field_perms.append({
                    "field":    field,
                    "readable": readable,
                    "editable": editable,
                })

        if not field_perms:
            return None

        return {
            "file":              f.name,
            "name":              name,
            "label":             label,
            "ptype":             ptype,
            "field_permissions": field_perms,
        }

    for f in sorted(METADATA_DIR.glob("permissionsets/*.permissionset-meta.xml")):
        entry = parse_fls(f, "PermissionSet")
        if entry:
            entries.append(entry)

    for f in sorted(METADATA_DIR.glob("profiles/*.profile-meta.xml")):
        entry = parse_fls(f, "Profile")
        if entry:
            entries.append(entry)

    return entries


# ─── Formula cross-reference index ───────────────────────────────────────────

def build_formula_deps_index(fields_tsv):
    """
    For every formula field, extract all __c field references from the formula expression.
    Enables upstream tracing: "this field is a formula that reads these source fields".

    Input:  fields_tsv string (already built by build_fields_index)
    Output: { "Object.FormulaField__c": ["ReferencedField__c", ...], ... }

    Example: Opportunity.ARR_Engagement__c has formula TEXT(Product_Pillar__c)
    → {"Opportunity.ARR_Engagement__c": ["Product_Pillar__c"]}
    """
    import csv
    import io

    deps = {}
    reader = csv.reader(io.StringIO(fields_tsv), delimiter='\t')
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 5:
            continue
        obj     = row[0]
        field   = row[1]
        formula = row[4].strip() if len(row) > 4 else ""
        if not formula:
            continue
        refs = list(dict.fromkeys(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*__c)\b', formula)))
        if refs:
            deps[f"{obj}.{field}"] = refs

    return deps


# ─── Manifest ────────────────────────────────────────────────────────────────

def build_manifest(retrieved_at):
    # Hash of this script — lets Phase 2 detect when indexes need rebuilding
    script_hash = ""
    try:
        script_hash = hashlib.md5(Path(__file__).read_bytes()).hexdigest()
    except Exception:
        pass

    return {
        "retrieved_at":       retrieved_at,
        "index_generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "index_script_hash":  script_hash,
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

    SEP = (",", ":")  # compact separators — no whitespace

    # Flows
    print("  flows...", end=" ", flush=True)
    flows = build_flows_index()
    (CACHE_DIR / "flows-index.json").write_text(
        json.dumps(compact_dict(flows), separators=SEP), encoding="utf-8")
    print(f"{len(flows)} flows")

    # Apex
    print("  apex...", end=" ", flush=True)
    apex = build_apex_index()
    (CACHE_DIR / "apex-index.json").write_text(
        json.dumps(compact_dict(apex), separators=SEP), encoding="utf-8")
    print(f"{len(apex)} classes")

    # Triggers
    print("  triggers...", end=" ", flush=True)
    triggers = build_triggers_index()
    (CACHE_DIR / "triggers-index.json").write_text(
        json.dumps(compact_dict(triggers), separators=SEP), encoding="utf-8")
    print(f"{len(triggers)} triggers")

    # Validation rules
    print("  validation-rules...", end=" ", flush=True)
    val_rules = build_validation_rules_index()
    (CACHE_DIR / "validation-rules-index.json").write_text(
        json.dumps(compact_dict(val_rules), separators=SEP), encoding="utf-8")
    print(f"{len(val_rules)} rules")

    # Workflow rules
    print("  workflow-rules...", end=" ", flush=True)
    wf_rules = build_workflow_rules_index()
    (CACHE_DIR / "workflow-rules-index.json").write_text(
        json.dumps(compact_dict(wf_rules), separators=SEP), encoding="utf-8")
    print(f"{len(wf_rules)} rules")

    # Reports
    print("  reports...", end=" ", flush=True)
    reports = build_reports_index()
    (CACHE_DIR / "reports-index.json").write_text(
        json.dumps(compact_dict(reports), separators=SEP), encoding="utf-8")
    if reports:
        print(f"{len(reports)} reports")
    else:
        print("0 reports (run /retrieve to fetch reports-all.json)")

    # Dashboards
    print("  dashboards...", end=" ", flush=True)
    dashboards = build_dashboards_index()
    (CACHE_DIR / "dashboards-index.json").write_text(
        json.dumps(compact_dict(dashboards), separators=SEP), encoding="utf-8")
    print(f"{len(dashboards)} dashboards")

    # Comprehensive field usage (must run after val_rules and wf_rules are built)
    print("  field-usage...", end=" ", flush=True)
    field_usage = build_field_usage_index(flows, apex, triggers)
    (CACHE_DIR / "field-usage-index.json").write_text(
        json.dumps(compact_dict(field_usage), separators=SEP), encoding="utf-8")
    print(f"{len(field_usage)} fields")

    # Constants
    print("  constants...", end=" ", flush=True)
    constants = build_constants_index()
    (CACHE_DIR / "constants-index.json").write_text(
        json.dumps(compact_dict(constants), separators=SEP), encoding="utf-8")
    print(f"{len(constants)} constants")

    # CPQ field usage (parent-child)
    print("  cpq-field-usage...", end=" ", flush=True)
    cpq_usage = build_cpq_field_usage_index()
    (CACHE_DIR / "cpq-field-usage-index.json").write_text(
        json.dumps(compact_dict(cpq_usage), separators=SEP), encoding="utf-8")
    total_parents = sum(len(v) for v in cpq_usage.items()
                        if isinstance(v, list))
    print(f"{sum(len(v) for k,v in cpq_usage.items() if k != '_constants')} parent records across {len(cpq_usage)-1} types")

    # LWC + Aura components
    print("  ui-components...", end=" ", flush=True)
    ui_components = build_ui_components_index()
    (CACHE_DIR / "ui-components-index.json").write_text(
        json.dumps(compact_dict(ui_components), separators=SEP), encoding="utf-8")
    lwc_count  = sum(1 for c in ui_components if c["type"] == "lwc")
    aura_count = sum(1 for c in ui_components if c["type"] == "aura")
    print(f"{lwc_count} LWC, {aura_count} Aura")

    # Layouts
    print("  layouts...", end=" ", flush=True)
    layouts = build_layouts_index()
    (CACHE_DIR / "layouts-index.json").write_text(
        json.dumps(compact_dict(layouts), separators=SEP), encoding="utf-8")
    print(f"{len(layouts)} layouts")

    # Custom Metadata records
    print("  custom-metadata...", end=" ", flush=True)
    cmdt = build_custom_metadata_index()
    (CACHE_DIR / "custom-metadata-index.json").write_text(
        json.dumps(compact_dict(cmdt), separators=SEP), encoding="utf-8")
    total_cmdt = sum(len(v) for v in cmdt.values())
    print(f"{total_cmdt} records across {len(cmdt)} types")

    # Quick Actions
    print("  quick-actions...", end=" ", flush=True)
    qactions = build_quick_actions_index()
    (CACHE_DIR / "quick-actions-index.json").write_text(
        json.dumps(compact_dict(qactions), separators=SEP), encoding="utf-8")
    print(f"{len(qactions)} quick actions")

    # Email templates
    print("  email-templates...", end=" ", flush=True)
    email_templates = build_email_templates_index()
    (CACHE_DIR / "email-templates-index.json").write_text(
        json.dumps(compact_dict(email_templates), separators=SEP), encoding="utf-8")
    print(f"{len(email_templates)} templates")

    # Permission sets + profiles (field-level security)
    print("  permission-sets...", end=" ", flush=True)
    perm_sets = build_permission_sets_index()
    (CACHE_DIR / "permission-sets-index.json").write_text(
        json.dumps(compact_dict(perm_sets), separators=SEP), encoding="utf-8")
    ps_count = sum(1 for p in perm_sets if p.get("ptype") == "PermissionSet")
    pr_count = sum(1 for p in perm_sets if p.get("ptype") == "Profile")
    print(f"{ps_count} permission sets, {pr_count} profiles")

    # Formula cross-refs (upstream field dependencies for formula fields)
    print("  formula-deps...", end=" ", flush=True)
    formula_deps = build_formula_deps_index(fields_tsv)
    (CACHE_DIR / "formula-deps-index.json").write_text(
        json.dumps(compact_dict(formula_deps), separators=SEP), encoding="utf-8")
    print(f"{len(formula_deps)} formula fields with cross-refs")

    # Manifest
    manifest = build_manifest(retrieved_at)
    (CACHE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Print sizes
    print()
    for fname in ["manifest.json", "fields-index.tsv", "flows-index.json",
                  "apex-index.json", "triggers-index.json",
                  "validation-rules-index.json", "workflow-rules-index.json",
                  "reports-index.json", "dashboards-index.json",
                  "field-usage-index.json", "constants-index.json",
                  "cpq-field-usage-index.json",
                  "layouts-index.json", "custom-metadata-index.json",
                  "quick-actions-index.json", "ui-components-index.json",
                  "email-templates-index.json", "permission-sets-index.json",
                  "formula-deps-index.json"]:
        p = CACHE_DIR / fname
        if p.exists():
            kb = p.stat().st_size / 1024
            print(f"    {fname:<32} {kb:6.1f} KB")

if __name__ == "__main__":
    main()
