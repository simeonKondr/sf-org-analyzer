# /analyze

Runs a full Salesforce metadata analysis based on the user's natural language request.

**Usage:** `/analyze <your question>`

**Examples:**
```
/analyze Find all automations and processes where Product Family, Product Pillar 
and values like Engagement, Discovery, Content, Clarity are used

/analyze Where does ARR_Content__c on Opportunity get its value from

/analyze Map the complete flow from CPQ Quote Line to Opportunity ARR to Account ARR

/analyze What reports and dashboards consume Product_Pillar__c and when were they last run

/analyze Find everything that fires when an OpportunityLineItem is created or updated
```

---

## Instructions for Claude

The user's request is: **$ARGUMENTS**

Follow the Phase 1 → 6 sequence defined in CLAUDE.md exactly.

### Phase 1 — Parse
Extract FIELD_PATTERNS, VALUE_PATTERNS, OBJECT_SCOPE from the request.
Print what you found. Proceed immediately (no need to wait for confirmation
unless the request is genuinely ambiguous).

### Phase 2 — Metadata check
```bash
cat metadata/.retrieved_at 2>/dev/null || echo "NOT RETRIEVED"
```
Retrieve if stale or missing. Use `bash scripts/retrieve.sh`.

### Phase 3 — Field discovery

```bash
# 1. Cache first — fast and cheap
grep -i "PATTERN" cache/fields-index.tsv | cut -f1-4 | tee cache/discovered-fields.txt
```
If cache/fields-index.tsv is missing, run `bash scripts/index.sh` first.
Report: "Found [N] matching fields: [list]"

### Phase 4 — Find all locations (index-first, zero raw file reads)

**Step 4a — Field locations.** Run all index queries before opening any file.

```bash
# All files reading or writing discovered fields
python3 -c "
import json
usage = json.load(open('cache/field-usage-index.json'))
for field, hits in usage.items():
    if 'FIELD_PATTERN' in field:
        for h in hits: print(field, '|', h['type'], h['usage'], '|', h['file'])
"

# Flows: writes + conditions
python3 -c "
import json
for f in json.load(open('cache/flows-index.json')):
    if any('FIELD_PATTERN' in str(x) for x in f.get('writes',[])+f.get('conds',[])):
        print(f['file'],'|',f['obj'],f['event'],'| writes:',f['writes'],'| conds:',f['conds'])
"

# Validation rules: formula fields + picklist values
python3 -c "
import json
for r in json.load(open('cache/validation-rules-index.json')):
    if any('FIELD_PATTERN' in x for x in r.get('fields',[])+r.get('values',[])):
        print(r['object'],r['name'],'active:',r['active'],'| fields:',r['fields'],'| values:',r['values'])
"

# Workflow rules: criteria + field updates
python3 -c "
import json
for r in json.load(open('cache/workflow-rules-index.json')):
    if any('FIELD_PATTERN' in x for x in r.get('fields',[])+r.get('values',[])):
        print(r['object'],r['name'],'active:',r['active'],'| writes:',r['writes'],'| criteria:',r['criteria'])
"

# Reports: name/folder/description search
python3 -c "
import json
for r in json.load(open('cache/reports-index.json')):
    if 'FIELD_PATTERN' in r.get('searchable','') or 'VALUE_PATTERN' in r.get('searchable',''):
        print(r['name'],'|',r['folder'],'| last_run:',r['last_run'])
"

# Dashboards: name/folder/description/component search
python3 -c "
import json
for d in json.load(open('cache/dashboards-index.json')):
    if 'FIELD_PATTERN' in d.get('searchable','') or 'VALUE_PATTERN' in d.get('searchable',''):
        print(d['title'],'|',d['folder'],'| last_modified:',d['last_modified'])
"

# CPQ rules
python3 -c "
import json
for rtype,records in json.load(open('cache/cpq-field-usage-index.json')).items():
    for r in records:
        if any('FIELD_PATTERN' in f for f in r.get('fields',[])):
            print(rtype, r['name'], '| fields:', r['fields'])
"
```

**Step 4b — Value/constant locations.** Search for VALUE_PATTERNS as string literals.

```bash
python3 -c "
import json
constants = json.load(open('cache/constants-index.json'))
for val, hits in constants.items():
    if any(p.lower() in val.lower() for p in ['VALUE1','VALUE2']):
        files = list({h['file'] for h in hits})
        print(repr(val), '->', files)
"
```

Also check validation rule and workflow criteria values:
```bash
python3 -c "
import json
for r in json.load(open('cache/validation-rules-index.json')):
    if any(v in r.get('values',[]) for v in ['VALUE1','VALUE2']):
        print('VR:', r['object'], r['name'], r['values'])
for r in json.load(open('cache/workflow-rules-index.json')):
    if any(v in r.get('values',[]) for v in ['VALUE1','VALUE2']):
        print('WF:', r['object'], r['name'], r['values'])
"
```

**Step 4c — Compact scan** to catch dynamic references missed by regex-based indexes:
```bash
bash scripts/scan.sh "FIELD_PATTERN|VALUE_PATTERN" all compact
```

---

### Phase 5 — Deep-dive into logic (targeted file reads)

You now have a list of files from Phase 4. Read each one and extract the full logic.
**Do not read files not identified in Phase 4.**

For every automation found, document all of the following:

| Slot | What to extract | Where to look |
|---|---|---|
| **Trigger** | Object + event (create/update/delete/scheduled) | Flow `<start>`, trigger declaration, workflow `<triggerType>` |
| **Gate condition** | The condition that must be true to execute | Flow decision nodes, Apex `if` blocks, workflow `<criteriaItems>` |
| **Reads** | Input fields consumed | Flow `<leftValueReference>`, Apex field reads, criteria `<field>` |
| **Logic** | What computation or comparison is applied | Formulas, `ISPICKVAL`, Apex expressions, SOQL filters |
| **Writes** | Output fields set, with the value or formula used | Flow `<assignToReference>`, Apex assignments, field update `<field>` |
| **Constants** | String/picklist values that gate or drive the logic | Flow `<stringValue>`, Apex string literals, criteria `<value>` |

For validation rules: extract the full error condition formula and when it fires.
For CPQ price rules: read the conditions array and actions array from `cpq-field-usage-index.json` directly — no raw file needed.

---

### Phase 6 — Chain trace (follow writes downstream)

After documenting each automation, collect every **field that was written**.
For each written field, re-query the field-usage index to find what reads it next:

```bash
python3 -c "
import json
usage = json.load(open('cache/field-usage-index.json'))
for field in ['WRITTEN_FIELD_1', 'WRITTEN_FIELD_2']:
    hits = [h for h in usage.get(field,[]) if h['usage'] in ('read','condition')]
    if hits:
        print(field, '->', [(h['type'], h['file']) for h in hits])
"
```

If downstream consumers are found, add them to the analysis — they are part of the same data flow.
Repeat until no new consumers are found (the chain terminates).

---

### Phase 7 — Runtime SOQL

**Do NOT re-run queries for facts already in CLAUDE.md Known Facts.**

Run only what metadata cannot answer:
- Report `LastRunDate` (not in metadata)
- Scheduled job `NextFireTime`
- Record counts for objects with unknown counts

### Phase 8 — Output
Write to `./output/[slug]-[timestamp].md`.
Print the full report in chat.
Ask if the user wants a Word document.

---

## Quality checks before finalising

Before outputting, verify:
- [ ] Every field in discovered-fields.txt has been checked across all metadata types
- [ ] Apex classes: noted what each one READS vs WRITES
- [ ] Flows: noted trigger, condition, and assignment for each
- [ ] Dependency chain covers source → all propagation paths → all consumers
- [ ] Issues section covers: orphaned writers, double-writes, missing fields, stale docs
- [ ] Reports table includes LastRunDate from SOQL (not just from metadata names)
