#!/usr/bin/env python3
"""
index.py — Build cache indexes for metadata and CPQ field usage.

Produces:
  cache/manifest.json                 — counts + timestamps
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

Run: python3 scripts/index.py
Called automatically by: bash scripts/retrieve.sh (at end of Phase 1)
"""

import datetime
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

        # Field reads: .Field__c references that are not assignments
        all_refs = re.findall(r'[\w]+\.([\w]+__c)', src)
        reads = list(dict.fromkeys([r for r in all_refs if r not in writes]))[:20]

        # SOQL FROM objects
        soql_from = list(dict.fromkeys(
            re.findall(r'\bFROM\s+(\w+)', src, re.IGNORECASE)
        ))[:10]

        classes.append({
            "file":      f.name,
            "methods":   methods,
            "reads":     reads,
            "writes":    writes,
            "soql_from": soql_from,
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
        ))[:20]

        # Field reads (simple pattern: .Field__c references)
        all_refs = re.findall(r'\.([\w]+__c)', src)
        reads = list(dict.fromkeys([r for r in all_refs if r not in writes]))[:20]

        # SOQL FROM objects
        soql_from = list(dict.fromkeys(
            re.findall(r'\bFROM\s+(\w+)', src, re.IGNORECASE)
        ))[:10]

        # String constants (quoted strings with meaningful content)
        strings = re.findall(r'["\']([^"\']{3,})["\']', src)
        constants = list(set([s for s in strings 
                             if any(c.isupper() or c == '_' for c in s) and len(s) > 3]))[:15]

        triggers.append({
            "file":      f.name,
            "name":      tname,
            "object":    obj,
            "events":    events,
            "reads":     reads,
            "writes":    writes,
            "soql_from": soql_from,
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

    # From Apex
    for cls in apex_classes:
        fname = cls.get("file", "")
        cname = cls.get("file", "").replace(".cls", "")
        for field in cls.get("writes", []):
            add_usage(field, fname, "Apex", "write", cname)
        for field in cls.get("reads", []):
            add_usage(field, fname, "Apex", "read", cname)

    # From Triggers
    for trig in triggers:
        fname = trig.get("file", "")
        tname = trig.get("name", "")
        events = ",".join(trig.get("events", []))
        for field in trig.get("writes", []):
            add_usage(field, fname, "Trigger", "write", f"{tname}({events})")
        for field in trig.get("reads", []):
            add_usage(field, fname, "Trigger", "read", f"{tname}({events})")

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

        # Extract quoted strings (length > 3)
        strings = re.findall(r'["\']([^"\']{3,})["\']', code)
        for s in strings:
            # Filter for meaningful constants (contain uppercase or underscores)
            if any(c.isupper() or c == '_' for c in s) and not s.isdigit():
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
    Built from SOQL-exported data (reports-all.json + reports-active.json).

    Report XML is NOT reliably retrievable via the Metadata API — the sf CLI
    retrieves reportTypes but not report definitions. This function reads the
    exported JSON instead.

    Matching is name/folder/description based. For column-level field analysis
    use /runtime with the Analytics REST API or name-pattern SOQL.
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

    # reports-active.json has accurate LastRunDate — use it to enrich reports-all
    active_by_id = {r["Id"]: r for r in load("reports-active.json") if r.get("Id")}

    reports = []
    for r in load("reports-all.json"):
        rid      = r.get("Id", "")
        name     = r.get("Name", "")
        dev_name = r.get("DeveloperName", "")
        folder   = r.get("FolderName", "")
        desc     = (r.get("Description") or "").strip()
        fmt      = r.get("Format", "")
        last_run = active_by_id.get(rid, {}).get("LastRunDate") or r.get("LastRunDate") or ""

        reports.append({
            "id":          rid,
            "name":        name,
            "dev_name":    dev_name,
            "folder":      folder,
            "format":      fmt,
            "last_run":    last_run,
            "description": desc[:200],
            # searchable is the primary matching surface — name + folder + description
            "searchable":  f"{name} {dev_name} {folder} {desc}".lower(),
        })

    # Fall back to reports-active.json alone if reports-all.json wasn't exported yet
    if not reports:
        for r in load("reports-active.json"):
            name   = r.get("Name", "")
            folder = r.get("FolderName", "")
            reports.append({
                "id":          r.get("Id", ""),
                "name":        name,
                "dev_name":    r.get("DeveloperName", ""),
                "folder":      folder,
                "format":      r.get("Format", ""),
                "last_run":    r.get("LastRunDate", ""),
                "description": "",
                "searchable":  f"{name} {folder}".lower(),
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
    ConfigurationAttribute, ProductOption, SearchFilter, CustomScript) produces:
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

        pr_entries.append({
            "id":         rid,
            "name":       rname,
            "fields":     all_fields,
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

        prd_entries.append({
            "id":                      rid,
            "name":                    rname,
            "fields":                  all_fields,
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

        sv_entries.append({
            "id":           sv.get("Id"),
            "name":         sv.get("Name", sv.get("Id")),
            "fields":       all_fields,
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

        lq_entries.append({
            "id":           lq_id,
            "name":         lq.get("Name", lq_id),
            "fields":       all_fields,
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
        ca_entries.append({
            "id":            ca.get("Id"),
            "name":          ca.get("Name", ca.get("Id")),
            "fields":        [target] if target else [],
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
        sf_entries.append({
            "id":       sf.get("Id"),
            "name":     sf.get("Name", sf.get("Id")),
            "fields":   [field] if field else [],
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
        cs_entries.append({
            "id":          cs.get("Id"),
            "name":        cs.get("Name", cs.get("Id")),
            "fields":      fields,
            "code_length": len(code),
        })

    result["CustomScript"] = cs_entries

    return result


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

    # Triggers
    print("  triggers...", end=" ", flush=True)
    triggers = build_triggers_index()
    triggers_json = json.dumps(triggers, separators=(",", ":"))
    (CACHE_DIR / "triggers-index.json").write_text(triggers_json, encoding="utf-8")
    print(f"{len(triggers)} triggers")

    # Validation rules
    print("  validation-rules...", end=" ", flush=True)
    val_rules = build_validation_rules_index()
    (CACHE_DIR / "validation-rules-index.json").write_text(
        json.dumps(val_rules, separators=(",", ":")), encoding="utf-8")
    print(f"{len(val_rules)} rules")

    # Workflow rules
    print("  workflow-rules...", end=" ", flush=True)
    wf_rules = build_workflow_rules_index()
    (CACHE_DIR / "workflow-rules-index.json").write_text(
        json.dumps(wf_rules, separators=(",", ":")), encoding="utf-8")
    print(f"{len(wf_rules)} rules")

    # Reports
    print("  reports...", end=" ", flush=True)
    reports = build_reports_index()
    (CACHE_DIR / "reports-index.json").write_text(
        json.dumps(reports, separators=(",", ":")), encoding="utf-8")
    if reports:
        print(f"{len(reports)} reports")
    else:
        print("0 reports (run /retrieve to fetch reports-all.json)")

    # Dashboards
    print("  dashboards...", end=" ", flush=True)
    dashboards = build_dashboards_index()
    (CACHE_DIR / "dashboards-index.json").write_text(
        json.dumps(dashboards, separators=(",", ":")), encoding="utf-8")
    print(f"{len(dashboards)} dashboards")

    # Comprehensive field usage (must run after val_rules and wf_rules are built)
    print("  field-usage...", end=" ", flush=True)
    field_usage = build_field_usage_index(flows, apex, triggers)
    usage_json = json.dumps(field_usage, separators=(",", ":"))
    (CACHE_DIR / "field-usage-index.json").write_text(usage_json, encoding="utf-8")
    print(f"{len(field_usage)} fields")

    # Constants
    print("  constants...", end=" ", flush=True)
    constants = build_constants_index()
    constants_json = json.dumps(constants, separators=(",", ":"))
    (CACHE_DIR / "constants-index.json").write_text(constants_json, encoding="utf-8")
    print(f"{len(constants)} constants")

    # CPQ field usage (parent-child)
    print("  cpq-field-usage...", end=" ", flush=True)
    cpq_usage = build_cpq_field_usage_index()
    cpq_usage_json = json.dumps(cpq_usage, indent=2)
    (CACHE_DIR / "cpq-field-usage-index.json").write_text(cpq_usage_json, encoding="utf-8")
    total_parents = sum(len(v) for v in cpq_usage.values())
    print(f"{total_parents} parent records across {len(cpq_usage)} types")

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
                  "cpq-field-usage-index.json"]:
        p = CACHE_DIR / fname
        if p.exists():
            kb = p.stat().st_size / 1024
            print(f"    {fname:<32} {kb:6.1f} KB")

if __name__ == "__main__":
    main()
