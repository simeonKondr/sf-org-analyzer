# sf-org-analyzer — Project Context

A Claude Code project for deep Salesforce org metadata analysis.

**Before starting any org-specific work**, check whether prior findings exist:
```bash
ls docs/ 2>/dev/null && cat docs/*-findings.md 2>/dev/null || echo "No prior findings."
```

---

## Execution style

Run all phases autonomously without pausing to ask "shall I continue?".
Execute bash commands, file writes, and SOQL queries without asking for permission.
Only stop if:
- A command returns an error that blocks the next step
- The user's request is genuinely ambiguous (e.g. org alias not specified)
- A destructive action is about to happen that wasn't requested

### Admin mode

Read `ADMIN_MODE` from `org.config` at the start of every session:

```bash
source org.config 2>/dev/null && echo "ADMIN_MODE=$ADMIN_MODE  DRY_RUN=$DRY_RUN"
```

**`ADMIN_MODE=false` (default):**
- Do NOT edit any project files: scripts, indexes, commands, CLAUDE.md, README.
- Analysis runs normally — bash commands, SOQL queries, cache reads, and output writes are all fine.
- When you find an issue in tooling or scripts, report it clearly but do not fix it.
- This flag can only be changed manually by the user. Never set it to true yourself.

**`ADMIN_MODE=true`:**
- Full edit access: scripts, indexes, commands, CLAUDE.md, README, docgen.js, etc.
- Apply fixes to tooling issues found during analysis.
- Still never fix org issues (metadata, Apex, flows, workflow rules, fields).

---

## Org config

Stored in `org.config` (gitignored — never committed). Read it at the start of any session:

```bash
cat org.config 2>/dev/null || echo "org.config not found — copy org.config.example to get started"
```

To get the active alias for use in commands:
```bash
source org.config 2>/dev/null && echo "$ORG_ALIAS"
```

All scripts source `org.config` automatically. Never hardcode the alias — always use `$ORG_ALIAS`.

---

## Critical rule — never hardcode CPQ or custom field names in SOQL
## Critical rule — never hardcode target-org. always use ORG_ALIAS from org.config

CPQ managed package field availability varies by version.
Org-specific custom fields vary by org.
**Never write a SOQL query with field names you haven't confirmed exist first.**

Before querying any CPQ or custom object with specific fields:

```bash
# Discover which fields actually exist on this object
sf data query \
  --query "SELECT QualifiedApiName FROM FieldDefinition
           WHERE EntityDefinition.QualifiedApiName = 'SBQQ__PriceRule__c'
           ORDER BY QualifiedApiName" \
  --target-org "$ORG_ALIAS" \
  --json | python3 -c "
import sys, json
fields = [r['QualifiedApiName']
          for r in json.load(sys.stdin)['result']['records']]
print('\n'.join(fields))
"
```

Always-safe queries (no field discovery needed):
- `SELECT COUNT() FROM AnyObject`
- `SELECT Id, Name FROM AnyObject`
- `SELECT Id, Title FROM Dashboard`
- `SELECT Id, Name, LastRunDate, FolderName FROM Report`
- `SELECT Id, CronJobDetail.Name, State, NextFireTime FROM CronTrigger`

---

## Core principle — local grep beats SOQL for structural questions

**Never use SOQL to answer structural questions** (what fields exist, what a flow
does, what an Apex class references). That data is in the retrieved XML metadata.
Use grep. It is faster, cheaper, and more complete.

**Use SOQL only for runtime data:**
- Report LastRunDate
- Record counts in CPQ objects
- Scheduled job status
- Live field values on records

---

## Analysis workflow

### Phase 1 — Parse the request

Extract three things from the user's question:

**FIELD_PATTERNS** — partial API name patterns to grep for. Always include variations:
- "Customer Status" → `Customer_Statu` (covers `Customer_Status__c`, `Customer_Statuses__c`, `Customer_Status_History__c`, etc.)
- "Revenue by segment" → `Revenue_Seg|Revenue_By_Seg|ARR_Seg`

> **Critical:** truncate the pattern one character before the suffix diverges — e.g. use
> `Customer_Statu` not `Customer_Status` so plural/variant field names are not missed.
> Also include any managed-package equivalents (e.g. `SBQQ__ProductFamily` for CPQ family fields).

**VALUE_PATTERNS** — string literals that appear in code as picklist values:
- "Active, Inactive" → `'Active'|'Inactive'|"Active"|"Inactive"`
- If the org uses legacy codes alongside human-readable names (e.g. API codes translated by a formula),
  include both forms: `'LegacyCode1'|'LegacyCode2'|'HumanName1'|'HumanName2'`.

**OBJECT_SCOPE** — all objects.
Do not restrict by object. If any field, flow, Apex class, trigger, validation rule,
workflow rule, report, dashboard, or CPQ rule on any object references a FIELD_PATTERN
or VALUE_PATTERN, it is in scope.

> Never filter results by object name. A match on Task, Lead, Contact, Case, or any
> custom object is equally valid as one on Opportunity.

### Phase 2 — Check metadata freshness

```bash
source org.config 2>/dev/null
cat metadata/.retrieved_at 2>/dev/null || echo "NOT RETRIEVED"
```

Retrieve if any of the following are true:
- Metadata has never been retrieved
- Metadata is older than 72 hours
- `DRY_RUN=true` in org.config (forces fresh retrieval regardless of age)

```bash
bash scripts/retrieve.sh
```

**Index staleness check** — after retrieval, verify the cache was built with the current
version of `index.py`. If the hash has changed since the cache was built, run the indexer:

```bash
python3 -c "
import json, hashlib
from pathlib import Path
manifest = json.loads(Path('cache/manifest.json').read_text()) if Path('cache/manifest.json').exists() else {}
stored   = manifest.get('index_script_hash', '')
current  = hashlib.md5(Path('scripts/index.py').read_bytes()).hexdigest()
if stored != current:
    print('WARNING: index.py has changed since cache was built — re-running indexer')
else:
    print('Cache is up to date with index.py')
"
# If stale: python3 scripts/index.py
```

### Phase 3 — Field discovery

**Step 1 — Cache first (fast, ~1KB read):**
```bash
python3 -c "
import csv, re, sys
pat = re.compile(r'PATTERN', re.I)
rows = list(csv.reader(open('cache/fields-index.tsv'), delimiter='\t'))
header = rows[0]
for row in rows[1:]:
    if pat.search('\t'.join(row)):
        obj, field = row[0], row[1]
        ftype = row[2] if len(row) > 2 else ''
        label = row[3] if len(row) > 3 else ''
        formula = row[4].strip() if len(row) > 4 and row[4].strip() else ''
        desc    = row[5].strip() if len(row) > 5 and row[5].strip() else ''
        kind = f'Formula({formula[:120]})' if formula else ftype
        deprecated = ' [DEPRECATED]' if 'deprecated' in desc.lower() or 'replaced' in desc.lower() else ''
        note = f' — {desc[:80]}' if desc else ''
        print(f'{obj}.{field}  [{kind}]{deprecated}{note}')
" | tee cache/discovered-fields.txt
```
This reads ALL columns — including the formula text and description.
Formula fields show their source expression so you can trace the derivation chain immediately.
Fields whose description contains "deprecated" or "replaced" are flagged with `[DEPRECATED]`.

> **Critical:** never use `cut -f1-4` — it silently drops the formula (col 5) and description (col 6), hiding whether a field is a formula and what it computes from.

**Step 1b — Picklist value extraction (MANDATORY when any discovered field is a Picklist or MultiselectPicklist).**

For every field discovered in Step 1 whose type is `Picklist` or `MultiselectPicklist`:
- Extract its **active** picklist values from the field XML (handling both local value sets and global value sets).
- **Add those values to VALUE_PATTERNS** — they must be used in every subsequent scan step (Phase 4 Steps 1–12, Phase 5) exactly like any manually specified value.
- **Include the active values in the Section 1 Field Inventory** output for that field.

This makes the analysis self-bootstrapping: you do not need the user to list values upfront. The org's own metadata defines what to scan for.

```bash
python3 -c "
import csv, glob, re
import xml.etree.ElementTree as ET
from pathlib import Path

NS = 'http://soap.sforce.com/2006/04/metadata'

def tag(t):
    return f'{{{NS}}}{t}'

def extract_active_values(xml_path):
    try:
        root = ET.parse(xml_path).getroot()
        # GVS reference — delegate to the global value set file
        gvs_el = root.find(f'.//{tag(\"valueSetName\")}')
        if gvs_el is not None:
            gvs_file = f'metadata/globalValueSets/{gvs_el.text}.globalValueSet-meta.xml'
            if Path(gvs_file).exists():
                return extract_active_values(gvs_file)
            return []
        # Local value set — <value> in field XML, <customValue> in GVS XML
        vals = []
        for elem in root.iter():
            if elem.tag in (tag('value'), tag('customValue')):
                is_active = elem.find(tag('isActive'))
                if is_active is None or is_active.text.strip().lower() == 'true':
                    fn = elem.find(tag('fullName'))
                    if fn is not None and fn.text:
                        vals.append(fn.text.strip())
        return vals
    except Exception as e:
        print(f'  Warning: could not parse {xml_path}: {e}')
        return []

discovered_path = Path('cache/discovered-fields.txt')
# Lines in discovered-fields.txt may contain annotations: "Obj.Field  [Type] — note"
# Strip everything after the first whitespace to get bare Object.Field keys
discovered = set()
if discovered_path.exists():
    for line in discovered_path.read_text().splitlines():
        key = line.split()[0] if line.strip() else ''
        if key:
            discovered.add(key)

rows = list(csv.reader(open('cache/fields-index.tsv'), delimiter='\t'))
all_values = {}  # key: 'Object.Field__c', value: [active values]

for row in rows[1:]:
    if len(row) < 3: continue
    obj, field, ftype = row[0], row[1], row[2]
    if f'{obj}.{field}' not in discovered: continue
    if ftype.lower() not in ('picklist', 'multipicklist'): continue
    xml_paths = glob.glob(f'metadata/objects/{obj}/fields/{field}.field-meta.xml')
    if not xml_paths: continue
    vals = extract_active_values(xml_paths[0])
    if vals:
        all_values[f'{obj}.{field}'] = vals
        print(f'{obj}.{field}  [{ftype}]  active values: {vals}')

if all_values:
    flat = sorted({v for vals in all_values.values() for v in vals})
    print()
    print('Add to VALUE_PATTERNS for all subsequent steps:')
    print('  ' + '|'.join(re.escape(v) for v in flat))
else:
    print('No picklist fields with resolvable values among discovered fields.')
"
```

Record the printed values. **Extend VALUE_PATTERN with them before running any Phase 4 step.**
If a field references a Global Value Set, note the GVS name and all objects that share it (see Step 3).

**Step 2 — Expand via write-back discovery (find downstream fields by following writers).**

Do NOT guess expanded patterns from field names. Instead, find every Apex class and flow
that reads a root field, then collect all fields those same files write. Those write targets
are downstream fields — regardless of their name. This catches legacy-named fields
(e.g. a field named `OldConcept__c` that actually stores the value for a concept with a
different modern name) that no name-pattern would find.

```bash
python3 -c "
import json

# Step 2a: which files READ any root field?
usage = json.load(open('cache/field-usage-index.json'))
root_pattern = 'FIELD_PATTERN'   # same pattern used in Step 1

reader_files = set()
for field, hits in usage.items():
    if root_pattern in field:
        for h in hits:
            if h['usage'] in ('read', 'condition'):
                reader_files.add(h['file'])

# Step 2b: what do those same files WRITE?
downstream = set()
for field, hits in usage.items():
    for h in hits:
        if h['file'] in reader_files and h['usage'] == 'write':
            downstream.add(field)

# Remove root fields already found in Step 1
for field, hits in usage.items():
    if root_pattern in field:
        downstream.discard(field)

for f in sorted(downstream):
    print(f)
" | tee -a cache/discovered-fields.txt
sort -u cache/discovered-fields.txt -o cache/discovered-fields.txt
```

Then do the same for flows:
```bash
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN', re.I)

flows = json.load(open('cache/flows-index.json'))
downstream = set()
for f in flows:
    field_text = (f.get('entry_conds',[]) + f.get('conds',[]) +
                  f.get('assign_values',[]) + f.get('formulas',[]) + f.get('screen_refs',[]))
    if any(pat.search(str(x)) for x in field_text):
        # This flow reads a root field — collect everything it writes
        for w in f.get('writes', []):
            if not pat.search(w):   # skip root fields already found
                downstream.add(w)

for f in sorted(downstream):
    print(f)
" | tee -a cache/discovered-fields.txt
sort -u cache/discovered-fields.txt -o cache/discovered-fields.txt
```

Report any downstream fields found that were not in Step 1 — they belong in Section 1 of the output.

**Step 3 — Global Value Set scan.**
Check whether any discovered field references a shared global picklist:
```bash
rg -l "globalValueSet\|valueSetName" metadata/objects/ --include="*.field-meta.xml" 2>/dev/null \
  | xargs grep -l "FIELD_PATTERN" 2>/dev/null | head -20
# Critical: scan by VALUE_PATTERN too — GVS files contain the picklist value labels, not field name words.
# A global value set may match VALUE_PATTERN but not FIELD_PATTERN.
rg -i "FIELD_PATTERN|VALUE_PATTERN" metadata/globalValueSets/ 2>/dev/null | head -30
```
If a global value set is found, note its name and every object/field that references it.

**Step 4 — Only if cache missing or pattern needs raw XML:**
```bash
PATTERN="field.?name|related.?concept"   # replace with actual pattern derived in Phase 1
rg -i "$PATTERN" metadata/ --type xml -o --no-filename \
  | grep -oE '[A-Za-z][A-Za-z0-9_]*__c' \
  | sort -u > cache/discovered-fields.txt
```

### Phase 4 — Full metadata scan

**Step 1 — Check the pre-built indexes first:**
```bash
# All automations reading or writing this field (Apex, Flow, Trigger)
python3 -c "
import json
usage = json.load(open('cache/field-usage-index.json'))
for field, hits in usage.items():
    if 'PATTERN' in field:
        for h in hits: print(field, '|', h['type'], h['usage'], '|', h['file'], '|', h['context'])
"

# Flows touching this field/value.
# label is included in value-pattern search to catch action-only sub-flows named after values.
python3 -c "
import json
pat = 'PATTERN'
for f in json.load(open('cache/flows-index.json')):
    field_text = (f.get('entry_conds',[]) + f.get('writes',[]) + f.get('conds',[]) +
                  f.get('assign_values',[]) + f.get('formulas',[]) + f.get('screen_refs',[]))
    value_text = field_text + [f.get('label','')]  # label for value-pattern only
    if any(pat in str(x) for x in value_text):
        print(f['file'], '|', f.get('obj',''), f.get('event',''),
              '| entry_conds:', f.get('entry_conds',[]),
              '| writes:', f.get('writes',[]),
              '| screen_refs:', f.get('screen_refs',[]),
              '| assigns:', f.get('assign_values',[])[:3],
              '| subflows:', f.get('subflows',[]))
"

# Validation rules referencing this field or value
python3 -c "
import json
for r in json.load(open('cache/validation-rules-index.json')):
    if any('PATTERN' in x for x in r.get('fields',[]) + r.get('values',[])):
        print(r['object'], r['name'], '| active:', r['active'], '| fields:', r['fields'], '| values:', r['values'])
"

# Workflow rules referencing this field or value
python3 -c "
import json
for r in json.load(open('cache/workflow-rules-index.json')):
    if any('PATTERN' in x for x in r.get('fields',[]) + r.get('values',[])):
        print(r['object'], r['name'], '| active:', r['active'], '| writes:', r['writes'], '| values:', r['values'])
"

# Reports using this field in columns or filters, sorted by recency
# fields[] = column + grouping + filter field names (populated from Tooling API Metadata)
# searchable includes all field names, so FIELD_PATTERN matches name AND column fields
python3 -c "
import json, re
pat = re.compile(r'PATTERN', re.I)
hits = []
for r in json.load(open('cache/reports-index.json')):
    if pat.search(r.get('searchable','')):
        field_matches = [f for f in r.get('fields',[]) if pat.search(f)]
        val_matches   = [v for v in r.get('filter_values',[]) if pat.search(v)]
        hits.append((r.get('last_run',''), r['name'], r['folder'], field_matches, val_matches))
hits.sort(key=lambda x: x[0] or '', reverse=True)
for last_run, name, folder, flds, vals in hits:
    print(last_run or 'never', '|', name, '|', folder,
          '| cols/filters:', flds[:5] or '(name match only)',
          '| filter_vals:', vals[:3])
"

# CPQ price rules, product rules, summary variables — check BOTH field names AND constants/values
# NOTE: cpq-field-usage-index.json is a dict keyed by type — must iterate .items(), not the dict directly
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN|VALUE_PATTERN', re.I)
for rtype, records in json.load(open('cache/cpq-field-usage-index.json')).items():
    for r in records:
        if not isinstance(r, dict): continue
        field_hit = any(pat.search(f) for f in r.get('fields', []))
        const_hit = any(pat.search(c) for c in r.get('constants', []))
        if field_hit or const_hit:
            print(rtype, '|', r.get('name'), '| fields:', r.get('fields'), '| constants:', r.get('constants'))
            for cond in r.get('conditions', r.get('error_conditions', [])):
                print('  COND:', cond)
            for act in r.get('actions', []):
                print('  ACTION:', act)
"
```

**Step 2 — Compact scan for broad discovery (low token cost):**
```bash
bash scripts/scan.sh "FIELD_PATTERN" all compact
```
Compact mode returns filename + matching line only — no context bloat.
Use this to identify *which* files are relevant.

**Step 3 — Mandatory raw XML fallback scan (ALWAYS run — not optional).**
The index misses flows that reference values inside local variable formulas
(e.g. `CONTAINS(SomeListVar,'SomeValue')`) rather than as direct field refs.
Always run this regardless of how complete the index results look:
```bash
rg -l "FIELD_PATTERN|VALUE_PATTERN" metadata/flows/ metadata/classes/ metadata/triggers/
```
Add every file returned that was NOT already in Steps 1-2 to your read list.

**Step 4 — Compile a complete read list before reading anything.**
Before opening any file, collect ALL files from Steps 1, 2, and 3 into one list.
Print the complete list. Every file on that list MUST be read in Step 5.
Do not skip any identified file — a file identified but not read is a gap.

**Step 5 — Read every file on the list.**
Read each file completely — no partial reads, no skipping.

> **Critical: always read the COMPLETE file — never use partial reads.**
> Never use `sed -n '1,NNNp'`, `head -n`, `Read(limit=...)`, or any other truncation.
> Logic branches in Apex and Flow often appear in the second half of the file. A partial
> read that misses one branch will produce a wrong (and confidently wrong) analysis.

> **Large files (>10K tokens):** If the Read tool returns a "file content exceeds maximum"
> error, use targeted grep to extract the relevant logic instead of reading the whole file:
> ```bash
> grep -n "FIELD_PATTERN\|VALUE_PATTERN" path/to/file.flow-meta.xml
> ```
> Extract: entry conditions, decision branches, assignment targets, formula expressions.
> Document every branch found — do not stop at the first match.

**Step 6 — Layout scan (MANDATORY — run every analysis).**
Layouts are not covered by any cache index. Always grep them:
```bash
rg -l "FIELD_PATTERN" metadata/layouts/ 2>/dev/null
rg -l "FIELD_PATTERN" metadata/layouts/ \
  | while read f; do echo "=== $(basename $f) ==="; rg "FIELD_PATTERN" "$f" | head -5; done
```

**Step 7 — Flexipage scan (MANDATORY — run every analysis).**
Lightning pages are not indexed. Use plain `|` (no backslash) in the pattern:
```bash
rg -l "FIELD_PATTERN|VALUE_PATTERN" metadata/flexipages/ 2>/dev/null
rg -l "FIELD_PATTERN|VALUE_PATTERN" metadata/flexipages/ \
  | while read f; do echo "=== $(basename $f) ==="; grep -o 'fieldItem>[^<]*' "$f" | grep -i "FIELD_PATTERN\|VALUE_PATTERN"; done
```

**Step 8 — List View scan (MANDATORY — use find, not rg --include).**
`rg --include="*.listView-meta.xml"` fails silently on some systems. Use find:
```bash
find metadata/objects/ -name "*.listView-meta.xml" \
  | xargs grep -l "FIELD_PATTERN\|VALUE_PATTERN" 2>/dev/null | head -30
```

**Step 9 — Assignment Rules, Sharing Rules, Path Assistants, Approval Processes (scan).**
These are not indexed but can contain field-based routing logic:
```bash
find metadata/assignmentRules/ -name "*.assignmentRules-meta.xml" \
  | xargs grep -l "FIELD_PATTERN\|VALUE_PATTERN" 2>/dev/null
find metadata/sharingRules/ -name "*.sharingRules-meta.xml" \
  | xargs grep -l "FIELD_PATTERN\|VALUE_PATTERN" 2>/dev/null
find metadata/pathAssistants/ -name "*.pathAssistant-meta.xml" \
  | xargs grep -l "FIELD_PATTERN\|VALUE_PATTERN" 2>/dev/null
find metadata/approvalProcesses/ -name "*.approvalProcess-meta.xml" \
  | xargs grep -l "FIELD_PATTERN\|VALUE_PATTERN" 2>/dev/null
```

**Step 10 — Email templates (use the index).**
Email template subjects and bodies may reference field merge values or contain string constants matching VALUE_PATTERN:
```bash
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN|VALUE_PATTERN', re.I)
for t in json.load(open('cache/email-templates-index.json')):
    matched_fields    = [f for f in t.get('fields',[])    if pat.search(f)]
    matched_constants = [c for c in t.get('constants',[]) if pat.search(c)]
    if matched_fields or matched_constants or pat.search(t.get('subject','')):
        print(t['name'], '| subject:', t.get('subject','')[:80],
              '| fields:', matched_fields, '| constants:', matched_constants[:3])
"
```

**Step 11 — Permission sets / profiles FLS (use the index — mention in output but do not block analysis).**
Which profiles/permission sets grant read or edit access to the discovered fields:
```bash
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN', re.I)
for p in json.load(open('cache/permission-sets-index.json')):
    matched = [fp for fp in p.get('field_permissions',[]) if pat.search(fp['field'])]
    if matched:
        readable = [fp['field'] for fp in matched if fp['readable']]
        editable = [fp['field'] for fp in matched if fp['editable']]
        print(p['ptype'], p['name'], '| readable:', readable, '| editable:', editable)
"
```

**Step 12 — Formula dependency tracing (use the index for upstream fields).**
For any formula field found in Phase 3, trace which source fields it reads:
```bash
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN', re.I)
deps = json.load(open('cache/formula-deps-index.json'))
for formula_field, source_fields in deps.items():
    if pat.search(formula_field) or any(pat.search(f) for f in source_fields):
        print(formula_field, '->', source_fields)
"
```
This catches cross-object formula fields where the source field lives on a different object
and would not appear in the field-usage index (Apex/Flow read counts).

### Phase 5 — Runtime SOQL (targeted)

Run only what you need for *live runtime data*:
```sql
SELECT Id, Name, LastRunDate, FolderName FROM Report WHERE LastRunDate > LAST_N_DAYS:90 ORDER BY LastRunDate DESC LIMIT 100
SELECT Id, CronJobDetail.Name, State, NextFireTime FROM CronTrigger WHERE State = 'WAITING'
```
CPQ runtime data is already retrieved into `data/cpq/*.json` — do NOT query CPQ objects via SOQL.
Use the `cpq-field-usage-index.json` cache (Phase 4 Step 1) and raw `data/cpq/` JSON files directly.

### Phase 6 — Output

Save to `./output/analysis-[timestamp].md`.
Ask if the user wants a Word document: `node scripts/docgen.js ./output/analysis.md`

**The output must follow this 8-section structure** (field-inventory-first format):

1. **Field Inventory** — one table across ALL objects; Formula type shows expression; Picklist type shows active values; mark `(Deprecated)` explicitly; note global value sets and which objects share them
2. **Field Usage in Objects** — role/relationship of each key field within its object
3. **Field Usage in Apex** — table (class | field | logic type | description) + code pattern snippets
4. **Field Usage in Flows** — table (flow name | status | field | usage type | description)
5. **Layouts and Lightning Pages** — table (component | type | fields | notes) — from mandatory Steps 5/6/7
6. **Calculation Logic** — input → logic location → output table for every formula and Apex transform
7. **Dependency Chains** — table (source → intermediate → target) + primary chain summary paragraph

---

## Scan matrix

`[indexed]` = covered by cache; start here. `[scan]` = grep raw files if not answered by index.

| Metadata type | Cache index | Raw file location | What to look for |
|---|---|---|---|
| Apex | `apex-index.json` reads+writes **[indexed]** | `metadata/classes/*.cls` | Field refs, SOQL, string comparisons |
| Trigger | `triggers-index.json` reads+writes **[indexed]** | `metadata/triggers/*.trigger` | Field refs, events, constants |
| Flow | `flows-index.json` entry_conds+writes+conds+assign_values+formulas+screen_refs+subflows **[indexed]** | `metadata/flows/*.flow-meta.xml` | Start-element entry criteria, field writes, decision conditions (with RHS values), string assignments, formula expressions, screen/template field reads, sub-flow callouts |
| Object/Field | `fields-index.tsv` **[indexed]** | `metadata/objects/**/*.field-meta.xml` | `<formula>`, `<description>`, `<summaryFilterItems>` |
| Global Value Set | *(none)* **[scan]** | `metadata/globalValueSets/*.globalValueSet-meta.xml` | Picklist values shared across objects |
| Validation rule | `validation-rules-index.json` **[indexed]** | `metadata/objects/**/*.validationRule-meta.xml` | `<errorConditionFormula>`, ISPICKVAL values |
| Workflow rule | `workflow-rules-index.json` **[indexed]** | `metadata/workflows/*.workflow-meta.xml` | `<criteriaItems>`, `<fieldUpdates>` |
| Report | `reports-index.json` (name/folder/desc/columns/filters) **[indexed]** | `data/cpq/reports-all.json` — fetched via Tooling API with Metadata | Name + folder + column fields + filter fields/values; sorted by `last_run` descending |
| Dashboard | `dashboards-index.json` (name/folder/components) **[indexed]** | `data/cpq/dashboards.json` + `dashboard-components.json` | Name + component matching |
| LWC / Aura | `ui-components-index.json` **[indexed]** | `metadata/lwc/*/**.js`, `metadata/aura/**/*.{cmp,js}` | Field refs, Apex imports (`@salesforce/apex`), schema imports, string constants |
| Layout | `layouts-index.json` fields per layout **[indexed]** | `metadata/layouts/*.layout-meta.xml` | Which fields appear in each page layout |
| Custom Metadata | `custom-metadata-index.json` field→value per record **[indexed]** | `metadata/customMetadata/*.md-meta.xml` | Config values in CMDT records (e.g. category/territory/segment mappings) |
| Quick Action | `quick-actions-index.json` fields + defaults **[indexed]** | `metadata/quickActions/*.quickAction-meta.xml` | Fields shown and default values in quick actions |
| Flexipage | *(none)* **[scan — MANDATORY]** | `metadata/flexipages/*.flexipage-meta.xml` | `<fieldItem>` refs; use plain `\|` not `\\|`; run Phase 4 Step 7 every time |
| List View | *(none)* **[scan — MANDATORY]** | `metadata/objects/**/*.listView-meta.xml` | `<columns>` field references; use `find ... \| xargs grep -l`, NOT `rg --include` (fails silently) |
| Global Value Set | *(none)* **[scan]** | `metadata/globalValueSets/*.globalValueSet-meta.xml` | Picklist values shared across objects |
| Assignment Rules | *(none)* **[scan]** | `metadata/assignmentRules/*.assignmentRules-meta.xml` | `<criteriaItems>` field/value routing conditions |
| Sharing Rules | *(none)* **[scan]** | `metadata/sharingRules/*.sharingRules-meta.xml` | Criteria-based sharing rules that filter by discovered fields |
| Path Assistant | *(none)* **[scan]** | `metadata/pathAssistants/*.pathAssistant-meta.xml` | Stage-gate guidance that references discovered fields or values |
| Approval Processes | *(none)* **[scan]** | `metadata/approvalProcesses/*.approvalProcess-meta.xml` | Entry criteria referencing discovered fields |
| Email Templates | `email-templates-index.json` **[indexed]** | `metadata/email/**/*.email-meta.xml`, `metadata/emailTemplates/*.emailTemplate-meta.xml` | Subject + body merge fields (`{!Obj.Field__c}`), string constants matching VALUE_PATTERN |
| Permission Sets / Profiles | `permission-sets-index.json` **[indexed]** | `metadata/permissionsets/*.permissionset-meta.xml`, `metadata/profiles/*.profile-meta.xml` | Field-level security (readable/editable) for discovered fields — shows who can change values |
| Formula dependencies | `formula-deps-index.json` **[indexed]** | derived from `fields-index.tsv` formulas | Upstream `__c` references in formula expressions — traces which source fields feed a formula field |
| CPQ rules | `cpq-field-usage-index.json` **[indexed]** | `data/cpq/*.json` | Parent-child field references |

---

## Project structure

```
sf-org-analyzer/
├── CLAUDE.md                         ← this file
├── .claude/
│   ├── settings.json                 ← pre-approved commands (no prompts)
│   └── commands/
│       ├── analyze.md                ← /analyze <any question>
│       ├── retrieve.md               ← /retrieve [org-alias]
│       └── runtime.md                ← /runtime <question>
├── scripts/
│   ├── retrieve.sh                   ← metadata + CPQ data retrieval
│   ├── scan.sh                       ← grep wrapper for all metadata types
│   └── docgen.js                     ← markdown → Word document
├── docs/
│   ├── *-findings.md                 ← COMPLETE PRIOR AUDIT FINDINGS ← READ THIS
│   └── *-known-issues.md             ← critical issues with recommendations
├── metadata/                         ← retrieved metadata (gitignored)
├── data/cpq/                         ← exported CPQ record data (gitignored)
├── cache/                            ← field index cache (gitignored)
└── output/                           ← analysis outputs (gitignored)
```

---

## Slash commands

| Command | Purpose |
|---|---|
| `/analyze <question>` | Full end-to-end analysis from natural language |
| `/retrieve [alias]` | Force fresh metadata + CPQ data retrieval |
| `/runtime <question>` | Live SOQL queries for runtime data only |

