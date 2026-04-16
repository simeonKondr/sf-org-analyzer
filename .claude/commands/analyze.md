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

Follow the Phase 1 → 8 sequence defined below exactly.

### Phase 1 — Parse
Extract FIELD_PATTERNS and VALUE_PATTERNS from the request.
OBJECT_SCOPE is always **all objects** — never restrict by object name.
Print what you found. Proceed immediately (no need to wait for confirmation
unless the request is genuinely ambiguous).

**Pattern expansion rules (apply automatically):**
- Truncate field name patterns to catch plural/variant suffixes: e.g. `Product_Famil` (not `Product_Family`) matches both `Product_Family__c` AND `Product_Families__c`, `Product_Families_S1__c`, etc. Apply the same principle to any field whose name may have suffix variants.
- If the org uses legacy codes or abbreviations as picklist values (e.g. short codes that map to human-readable pillar names), always include BOTH forms in VALUE_PATTERNS — the codes appear in formulas, Apex switch statements, and flow conditions alongside the human-readable names.
- Standard Salesforce fields (e.g. `Product2.Family`) are not custom (`__c`) — grep for them by name in Apex/Flow/XML, not just the field index. The field-usage-index only tracks `__c` fields; standard fields referenced in Apex (e.g. `SBQQ__Product__r.Family`, `Product2.Name`) require a raw `rg` search.
  ```bash
  rg -l "\.Family\b" metadata/classes/ metadata/triggers/
  ```

### Phase 2 — Metadata check
```bash
cat metadata/.retrieved_at 2>/dev/null || echo "NOT RETRIEVED"
```
Retrieve if stale or missing. Use `bash scripts/retrieve.sh`.

**Index staleness check** — after retrieval, verify the cache was built with the current version of `index.py`:
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

**Step 1 — Cache first (reads ALL columns including formula and description):**
```bash
python3 -c "
import csv, re
pat = re.compile(r'PATTERN', re.I)
rows = list(csv.reader(open('cache/fields-index.tsv'), delimiter='\t'))
for row in rows[1:]:
    if pat.search('\t'.join(row)):
        obj, field = row[0], row[1]
        ftype   = row[2] if len(row) > 2 else ''
        label   = row[3] if len(row) > 3 else ''
        formula = row[4].strip() if len(row) > 4 and row[4].strip() else ''
        desc    = row[5].strip() if len(row) > 5 and row[5].strip() else ''
        kind = f'Formula({formula[:120]})' if formula else ftype
        deprecated = ' [DEPRECATED]' if 'deprecated' in desc.lower() or 'replaced' in desc.lower() else ''
        note = f' — {desc[:80]}' if desc else ''
        print(f'{obj}.{field}  [{kind}]{deprecated}{note}')
" | tee cache/discovered-fields.txt
```
> **Critical:** never use `cut -f1-4` — it silently drops the formula (col 5) and
> description (col 6). Formula fields must show their expression to trace the derivation chain.
> Flag any field whose description contains "deprecated" or "replaced" with `[DEPRECATED]`.

If cache/fields-index.tsv is missing, run `bash scripts/index.sh` first.

**Step 1b — Picklist value extraction (MANDATORY when any discovered field is a Picklist or MultiselectPicklist).**

For every field discovered in Step 1 whose type is `Picklist` or `MultiselectPicklist`:
- Extract its **active** values from the field XML (handles both local value sets and Global Value Sets).
- **Extend VALUE_PATTERNS with these values** — they are used in every subsequent scan step exactly like values the user specified manually.
- **List the active values in the Section 1 Field Inventory** for that field.

This is self-bootstrapping: you do not need the user to enumerate values. The org's metadata defines them.

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
        gvs_el = root.find(f'.//{tag(\"valueSetName\")}')
        if gvs_el is not None:
            gvs_file = f'metadata/globalValueSets/{gvs_el.text}.globalValueSet-meta.xml'
            if Path(gvs_file).exists():
                return extract_active_values(gvs_file)
            return []
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
# Lines may contain annotations: "Obj.Field  [Type] — note" — strip to bare Object.Field key
discovered = set()
if discovered_path.exists():
    for line in discovered_path.read_text().splitlines():
        key = line.split()[0] if line.strip() else ''
        if key:
            discovered.add(key)

rows = list(csv.reader(open('cache/fields-index.tsv'), delimiter='\t'))
all_values = {}

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

Record the output. **Extend VALUE_PATTERN with the printed values before running any Phase 4 step.**
If a field references a Global Value Set, note the GVS name; all objects sharing it are also in scope.

**Step 2 — Expand via write-back discovery (find downstream fields by following writers).**

Do NOT guess expanded patterns from field names. Instead, find every Apex class and flow
that reads a root field, then collect all fields those same files write. Those write targets
are downstream fields regardless of their name. This catches legacy-named fields (e.g. a field named after an old concept that now stores
a different value, or a field on a related object written by an invocable action)
that no name-pattern would ever find.

```bash
# Apex/Trigger write-back: files that read a root field → all fields they write
python3 -c "
import json
usage = json.load(open('cache/field-usage-index.json'))
root_pattern = 'FIELD_PATTERN'

reader_files = set()
for field, hits in usage.items():
    if root_pattern in field:
        for h in hits:
            if h['usage'] in ('read', 'condition'):
                reader_files.add(h['file'])

downstream = set()
for field, hits in usage.items():
    for h in hits:
        if h['file'] in reader_files and h['usage'] == 'write':
            downstream.add(field)

# Exclude root fields already discovered in Step 1
for field in list(usage):
    if root_pattern in field:
        downstream.discard(field)

for f in sorted(downstream):
    print(f)
" | tee -a cache/discovered-fields.txt

# Flow write-back: flows that read a root field → all fields they write
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN', re.I)
downstream = set()
for f in json.load(open('cache/flows-index.json')):
    field_text = (f.get('entry_conds',[]) + f.get('conds',[]) +
                  f.get('assign_values',[]) + f.get('formulas',[]) + f.get('screen_refs',[]))
    if any(pat.search(str(x)) for x in field_text):
        for w in f.get('writes', []):
            if not pat.search(w):
                downstream.add(w)
for f in sorted(downstream):
    print(f)
" | tee -a cache/discovered-fields.txt

sort -u cache/discovered-fields.txt -o cache/discovered-fields.txt
```

Report any fields found here that were not in Step 1 — they belong in Section 1.

**Step 3 — Global Value Set scan.**
Check whether any discovered field references a shared global picklist (e.g. `Product_Pillars`):
```bash
rg -l "globalValueSet\|valueSetName" metadata/objects/ --include="*.field-meta.xml" 2>/dev/null \
  | xargs grep -l "FIELD_PATTERN" 2>/dev/null | head -20

# Critical: scan by VALUE_PATTERN too — GVS files contain the picklist values, not the field API name.
# A GVS may match VALUE_PATTERN even if its name doesn't match FIELD_PATTERN.
rg -i "FIELD_PATTERN|VALUE_PATTERN" metadata/globalValueSets/ 2>/dev/null | head -30
```
If a global value set is found, note its name and every object/field that references it.

Report: "Found [N] matching fields across [M] objects: [list]"

### Phase 4 — Find all locations (index-first, then layouts/flexipages)

**Step 4a — Field locations.** Run all index queries before opening any file.

```bash
# All files reading or writing discovered fields (custom __c fields)
python3 -c "
import json
usage = json.load(open('cache/field-usage-index.json'))
for field, hits in usage.items():
    if 'FIELD_PATTERN' in field:
        for h in hits: print(field, '|', h['type'], h['usage'], '|', h['file'])
"

# Standard field cross-object reads in Apex/Triggers (e.g. SBQQ__Product__r.Family)
# Use when the topic involves a standard field (no __c) referenced via relationship traversal
python3 -c "
import json
apex = json.load(open('cache/apex-index.json'))
triggers = json.load(open('cache/triggers-index.json'))
for entry in apex + triggers:
    matched = [f for f in entry.get('cross_obj_reads',[]) if 'STANDARD_FIELD_NAME' in f]
    if matched:
        print(entry['file'], '| cross_obj_reads:', matched)
"
# Example: replace STANDARD_FIELD_NAME with 'Family' to find all Apex using .Family via relationships

# Flows: entry criteria + writes + decision conditions (RHS values) + assignment values + formula expressions + screen refs
# entry_conds = start-element filters that gate when the flow fires (e.g. Product_Families__c Contains Engagement)
# conds       = decision node conditions mid-flow (now includes RHS values)
# label is searched for VALUE_PATTERN only — catches action-only sub-flows whose name contains a pillar/value word
#   e.g. a sub-flow named after a value (like "..._Discovery_...") has no field refs but matches via its label
python3 -c "
import json
fp = 'FIELD_PATTERN'
vp = 'VALUE_PATTERN'
for f in json.load(open('cache/flows-index.json')):
    field_text = (f.get('entry_conds',[]) + f.get('writes',[]) + f.get('conds',[]) +
                  f.get('assign_values',[]) + f.get('formulas',[]) + f.get('screen_refs',[]))
    value_text  = field_text + [f.get('label','')]  # label-only for value pattern
    if any(fp in str(x) for x in field_text) or any(vp in str(x) for x in value_text):
        print(f['file'],'|',f.get('obj',''),'|',f.get('event',''),
              '| entry_conds:', f.get('entry_conds',[]),
              '| writes:',      f.get('writes',[]),
              '| conds:',       f.get('conds',[]),
              '| screen_refs:', f.get('screen_refs',[]),
              '| assigns:',     f.get('assign_values',[])[:5],
              '| subflows:',    f.get('subflows',[]))
"

# Sub-flow resolution: if a flow calls sub-flows, find those sub-flows too
python3 -c "
import json
fp = 'FIELD_PATTERN'
vp = 'VALUE_PATTERN'
flows = {f['file']: f for f in json.load(open('cache/flows-index.json'))}
for f in flows.values():
    field_text = (f.get('entry_conds',[]) + f.get('writes',[]) + f.get('conds',[]) +
                  f.get('assign_values',[]) + f.get('formulas',[]) + f.get('screen_refs',[]))
    value_text  = field_text + [f.get('label','')]
    if any(fp in str(x) for x in field_text) or any(vp in str(x) for x in value_text):
        for sf_name in f.get('subflows', []):
            sf_file = sf_name + '.flow-meta.xml'
            if sf_file in flows:
                sf = flows[sf_file]
                print('  SUB-FLOW:', sf['file'],
                      '| entry_conds:', sf.get('entry_conds',[]),
                      '| writes:', sf.get('writes',[]),
                      '| conds:', sf.get('conds',[]))
            else:
                print('  SUB-FLOW (not retrieved):', sf_name)
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

# Reports: name/folder/description + column/filter field search, sorted by recency
# fields[] and filter_values[] are populated when reports-all.json was fetched via Tooling API.
# searchable already includes all field names, so FIELD_PATTERN matches both name and column fields.
python3 -c "
import json, re
fp = re.compile(r'FIELD_PATTERN', re.I)
vp = re.compile(r'VALUE_PATTERN', re.I)
hits = []
for r in json.load(open('cache/reports-index.json')):
    if fp.search(r.get('searchable','')) or vp.search(r.get('searchable','')):
        field_matches = [f for f in r.get('fields',[]) if fp.search(f)]
        val_matches   = [v for v in r.get('filter_values',[]) if vp.search(v)]
        hits.append((r.get('last_run',''), r['name'], r['folder'], field_matches, val_matches))
hits.sort(key=lambda x: x[0] or '', reverse=True)
for last_run, name, folder, flds, vals in hits:
    print(last_run or 'never', '|', name, '|', folder,
          '| cols/filters:', flds[:5] or '(name match only)',
          '| filter_vals:', vals[:3])
"

# Dashboards: name/folder/description/component search
python3 -c "
import json
for d in json.load(open('cache/dashboards-index.json')):
    if 'FIELD_PATTERN' in d.get('searchable','') or 'VALUE_PATTERN' in d.get('searchable',''):
        print(d['title'],'|',d['folder'],'| last_modified:',d['last_modified'])
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

> **Critical: follow ALL files returned by constants output — every object is in scope.**
> Never filter by object name. A Contact flow, Task trigger, Lead Apex class, or any
> other match is equally valid and must be read and documented.

**Step 4c — Compact scan** to catch dynamic references missed by regex-based indexes:
```bash
bash scripts/scan.sh "FIELD_PATTERN|VALUE_PATTERN" all compact
```

**Step 4d — Mandatory raw XML fallback scan (ALWAYS run — not optional).**
The index misses flows that reference values inside local variable formulas
(e.g. `CONTAINS(SomeListVar,'SomeValue')`) rather than as direct field references.
Always run this regardless of how complete the index results look:
```bash
rg -l "FIELD_PATTERN|VALUE_PATTERN" metadata/flows/ metadata/classes/ metadata/triggers/
```
Add every file returned that was NOT already in Steps 4a–4c to your read list.

**Step 4d-GATE — Compile complete read list before reading anything.**
After Steps 4a–4d, collect ALL identified files into one list and print it.
Every file on that list MUST be read in Phase 5. Do not skip any file —
a file identified but not read is a guaranteed gap in the analysis.

**Step 4e — Layout scan (MANDATORY — use the index first, then grep for context).**
```bash
# Index lookup: which layouts contain the field pattern (instant, no grep)
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN', re.I)
for layout in json.load(open('cache/layouts-index.json')):
    matched = [f for f in layout.get('fields',[]) if pat.search(f)]
    if matched:
        print(layout['object'], '|', layout['file'], '|', matched)
"
```
If you need section-level context (which section the field is in), grep the raw file:
```bash
# Find all layouts containing the field pattern
rg -l "FIELD_PATTERN" metadata/layouts/ 2>/dev/null

# Get layout names + matched fields in one pass
rg "FIELD_PATTERN" metadata/layouts/ -l \
  | while read f; do
      echo "=== $(basename $f) ===";
      rg "FIELD_PATTERN" "$f" | head -5;
    done
```

**Step 4f — LWC / Aura components (use the index).**
```bash
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN|VALUE_PATTERN', re.I)
for c in json.load(open('cache/ui-components-index.json')):
    matched_fields    = [f for f in c.get('fields',[])    if pat.search(f)]
    matched_constants = [s for s in c.get('constants',[]) if pat.search(s)]
    matched_apex      = [a for a in c.get('apex_imports',[]) if pat.search(a)]
    if matched_fields or matched_constants or matched_apex:
        print(c['type'].upper(), c['name'],
              '| fields:', matched_fields,
              '| apex:', matched_apex,
              '| constants:', matched_constants[:5])
"
```

**Step 4g — Custom Metadata scan (MANDATORY — use the index).**
CMDT records contain configuration values (e.g. pillar names, territory mappings) that drive Apex/Flow logic:
```bash
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN|VALUE_PATTERN', re.I)
for type_name, records in json.load(open('cache/custom-metadata-index.json')).items():
    for r in records:
        matched = {k:v for k,v in r.get('values',{}).items() if pat.search(k) or pat.search(v)}
        if matched:
            print(type_name, '|', r['record'], '|', matched)
"
```

**Step 4h — Quick Actions scan (use the index).**
```bash
python3 -c "
import json, re
pat = re.compile(r'FIELD_PATTERN', re.I)
for a in json.load(open('cache/quick-actions-index.json')):
    matched = [f for f in a.get('fields',[]) if pat.search(f)]
    defaults = [d for d in a.get('defaults',[]) if pat.search(d['field']) or pat.search(d['value'])]
    if matched or defaults:
        print(a['object'], a['name'], a['type'], '| fields:', matched, '| defaults:', defaults)
"
```

**Step 4i — Flexipage scan (MANDATORY — grep only, not indexed).**
Lightning pages are not indexed. Use plain `|` in the pattern (no backslash escaping).
Flexipages use `<fieldItem>Record.FieldName</fieldItem>`, not `fieldApiName`:
```bash
# Find all flexipages containing the field pattern
rg -l "FIELD_PATTERN|VALUE_PATTERN" metadata/flexipages/ 2>/dev/null

# Extract fieldItem refs for each matching flexipage
rg -l "FIELD_PATTERN|VALUE_PATTERN" metadata/flexipages/ \
  | while read f; do
      echo "=== $(basename $f) ===";
      grep -o 'fieldItem>[^<]*' "$f" | grep -i "FIELD_PATTERN\|VALUE_PATTERN";
    done
```

**Step 4j — List View scan (MANDATORY — use find, not rg --include).**
`rg --include="*.listView-meta.xml"` fails silently on some systems. Use find:
```bash
find metadata/objects/ -name "*.listView-meta.xml" \
  | xargs grep -l "FIELD_PATTERN\|VALUE_PATTERN" 2>/dev/null | head -30
```

**Step 4k — Assignment Rules, Sharing Rules, Path Assistants, Approval Processes (scan).**
These are not indexed but can contain field-based routing and criteria logic:
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

**Step 4l — Email templates (use the index).**
Email template subjects and bodies reference merge fields with pillar names:
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

**Step 4m — Permission sets / profiles FLS (use the index).**
Shows which profiles and permission sets can read or edit the discovered fields.
Include a summary in Section 5 of the output:
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

**Step 4n — Formula dependency tracing (use the index).**
For formula fields found in Phase 3, trace upstream source fields:
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
Cross-object formulas reference source fields on other objects and won't appear in the
field-usage index — this is the only way to find them without reading raw XML.

---

### Phase 5 — Deep-dive into logic (targeted file reads)

You have a complete read list from the Phase 4 gate (Step 4d-GATE).
**Read every file on that list.** Do not skip any. Do not read files not on the list.

> **Critical: read COMPLETE files — never truncate.**
> Never use `sed -n '1,NNNp'`, `head -n`, `Read(limit=...)`, or any partial-read trick.
> Apex classes routinely have critical logic branches in the second half of the file that
> are invisible if you read only the first 130 lines. A partial read that misses one branch
> produces a confidently wrong analysis. Always read the entire file in one call.
>
> **Large files (>10K tokens):** If the Read tool returns a "file content exceeds maximum"
> error, use targeted grep to extract logic rather than giving up or reading only part:
> ```bash
> grep -n "FIELD_PATTERN\|VALUE_PATTERN" path/to/file.flow-meta.xml
> ```
> Extract all: entry conditions, decision branch values, assignment targets, formula
> expressions. Document every branch — do not stop at the first match.

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

---

### Phase 8 — Output

Write the report to `./output/[slug]-[timestamp].md`, then immediately convert it to HTML and open it in the browser:

```bash
python3 -c "
import markdown, pathlib, sys
slug = sys.argv[1]
md = pathlib.Path(f'output/{slug}.md').read_text()
html = markdown.markdown(md, extensions=['tables', 'fenced_code'])
page = '''<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>''' + slug + '''</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif;
         max-width: 1200px; margin: 40px auto; padding: 0 24px; color: #1a1a1a; line-height: 1.6; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.88em; }
  th, td { border: 1px solid #d0d0d0; padding: 7px 12px; text-align: left; vertical-align: top; }
  th { background: #f0f2f5; font-weight: 600; }
  tr:nth-child(even) td { background: #fafbfc; }
  code { background: #f0f2f5; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; font-family: monospace; }
  pre { background: #f0f2f5; padding: 14px; border-radius: 5px; overflow-x: auto; }
  pre code { background: none; padding: 0; }
  h1 { border-bottom: 2px solid #ddd; padding-bottom: 6px; }
  h2 { border-bottom: 1px solid #e8e8e8; padding-bottom: 4px; margin-top: 2em; }
  h3 { color: #333; margin-top: 1.5em; }
  blockquote { border-left: 4px solid #ccc; margin: 0; padding-left: 16px; color: #555; }
  a { color: #0969da; }
</style></head><body>''' + html + '</body></html>'
pathlib.Path(f'output/{slug}.html').write_text(page)
print(f'output/{slug}.html')
" "[slug]-[timestamp]"

open output/[slug]-[timestamp].html
```

Replace `[slug]-[timestamp]` with the actual filename (without `.md`).
Do **not** ask whether the user wants HTML — always generate and open it automatically.
Ask if the user wants a Word document (separate step, only if requested).

**The output must follow this 8-section structure** (matching the reference format):

---

#### Section 1 — Field Inventory
One comprehensive table covering **every object** where a matching field was found.
Include objects beyond the obvious ones — check snapshot objects, custom objects, junction objects.

| Object | Field API Name | Field Type | Formula / Description |
|---|---|---|---|
| ... | ... | ... | Full formula expression if Formula type; description otherwise. Mark `(Deprecated)` explicitly. |

- Group rows by object
- Formula fields: show the full formula expression (truncated to ~150 chars if very long)
- **Picklist / MultiselectPicklist fields: list all active values** (e.g. `Values: Active, Inactive, Pending`)
- Mark deprecated fields explicitly: append `(Deprecated)` in the Field Type column
- Note global value sets by name where used, and list all objects that reference the same GVS

#### Section 2 — Field Usage in Objects
For the most important fields, describe their role and how they relate to other fields on the same object.

| Field API Name | Object | Component Type | Component Name | Usage Description |
|---|---|---|---|---|

#### Section 3 — Field Usage in Apex
Concise table. One row per class per field/pattern. Show the specific field name and logic type.

| Apex Class | Field / Pattern Referenced | Logic Type | Description |
|---|---|---|---|

Include a "Key Apex Patterns" subsection showing 2–4 representative code snippets (branch structure, switch statement, etc.).

#### Section 4 — Field Usage in Flows
One row per flow per field. Include status (Active/Draft/Obsolete).

| Flow Name | Status | Field Referenced | Usage Type | Description |
|---|---|---|---|---|

Note any flows that are Draft or Obsolete but still exist.

#### Section 5 — Layouts, Lightning Pages, and Access
From Phase 4e (layouts), 4f (LWC/Aura), 4i (flexipages), 4j (list views), 4l (email templates), 4m (permission sets) results.

| Component Name | Component Type | Fields Referenced | Notes |
|---|---|---|---|

Include subsections:
- **Page Layouts** — which objects/layouts surface the fields
- **Lightning Pages (Flexipages)** — which record pages include fieldItem refs
- **List Views** — which list views filter or display the fields
- **LWC / Aura Components** — which UI components reference the fields or values
- **Email Templates** — which templates reference the fields as merge fields
- **Quick Actions** — from Phase 4h: which quick actions expose the fields or set defaults
- **Permission Set / Profile FLS** — which profiles/permission sets can read or edit the fields

#### Section 6 — CPQ Rules
From Phase 4a CPQ index and data/cpq/ records. Include live record counts.

| Rule Type | Rule Name | Condition | Field Referenced | Action / Effect |
|---|---|---|---|---|

Include subsections:
- **Summary Variables** — which SVs aggregate by pillar/family field; their filter logic
- **Price Rules** — which price rules fire on pillar/family conditions; calc events
- **Price Actions** — what each action writes and to which field
- **Product Rules** — which product rules use pillar/family in scope conditions
- **Configuration Rules** — if any reference pillar/family fields

#### Section 7 — Assignment Rules, Sharing Rules, Path Assistants, Approval Processes
From Phase 4k results. Only include if matches were found; omit section if none.

| Component Name | Component Type | Object | Field / Value Referenced | Effect |
|---|---|---|---|---|

#### Section 8 — Custom Metadata Configuration
From Phase 4g results. Show which CMDT types and records reference the fields/values as config.

| CMDT Type | Record Name | Field | Value | Purpose |
|---|---|---|---|---|

#### Section 9 — Calculation Logic
Map every formula and Apex transformation: input → logic location → output.

| Input Field / Source | Logic Location | Logic Type | Output Field / Result |
|---|---|---|---|

#### Section 10 — Dependency Chains
Full propagation table, source to final consumer.

| Source Object | Source Field | Intermediate / Logic | Target Field / Outcome |
|---|---|---|---|

End with a **Primary Dependency Chain Summary** — a one-paragraph or one-line description of the root-to-leaf path for the most important chain.

#### Section 11 — Issues & Risks
Use 🔴 Critical / 🟡 Warning / 🔵 Note severity. Focus on:
- Orphaned writers, double-writes, missing symmetry across pillars
- Deprecated fields still referenced in live automations or layouts
- Draft/Obsolete flows that have active sub-flows or email alerts
- Field naming mismatches (e.g. a value stored in a field whose name doesn't reflect what it holds — found via write-back discovery)
- Runtime data: recently run reports, active scheduled jobs

---

## Quality checks before finalising

Before outputting, verify:

**Phase 1–3**
- [ ] Phase 1: FIELD_PATTERN is truncated to catch suffix variants (e.g. `_Famil` catches both `_Family_` and `_Families_`) — apply this to any field with plural/variant suffix possibilities
- [ ] Phase 1: VALUE_PATTERNS include legacy codes or abbreviations alongside human-readable names, if the org uses them
- [ ] Phase 3 Step 1 ran — formula expressions shown, deprecated fields flagged
- [ ] Phase 3 Step 1b ran — all Picklist/MultiselectPicklist fields had active values extracted; values added to VALUE_PATTERNS and shown in Section 1 Field Inventory
- [ ] Phase 3 Step 2 ran — downstream write-back fields included; any legacy-named downstream fields added to Section 1
- [ ] Phase 3 Step 3 ran — global value sets identified if any fields use them; all sharing objects noted

**Phase 4 — every step**
- [ ] Phase 4a: field-usage-index query ran for all discovered __c fields
- [ ] Phase 4a: standard field cross-object reads scanned in apex-index + triggers-index (e.g. `.Family`)
- [ ] Phase 4a: flows query ran with both FIELD_PATTERN and VALUE_PATTERN against entry_conds+writes+conds+assign_values+formulas+screen_refs
- [ ] Phase 4a: sub-flow resolution ran — all sub-flows called by matching flows were also inspected
- [ ] Phase 4a: validation rules index queried
- [ ] Phase 4a: workflow rules index queried
- [ ] Phase 4a: reports index queried (sorted by recency); results in Section 5
- [ ] Phase 4a: dashboards index queried; results in Section 5
- [ ] Phase 4a: CPQ index queried (price rules, product rules, summary variables, config rules); results in Section 6
- [ ] Phase 4b: constants-index query ran — includes string literals in Apex and flow assign_values
- [ ] Phase 4c: compact scan ran — `bash scripts/scan.sh "FIELD_PATTERN|VALUE_PATTERN" all compact`
- [ ] Phase 4d: raw XML fallback scan ran (`rg -l`) — every new file added to read list
- [ ] Phase 4d-GATE: complete read list compiled and printed before Phase 5
- [ ] Phase 4e: layout scan ran (layouts-index.json); results in Section 5
- [ ] Phase 4f: LWC/Aura scan ran (ui-components-index.json); results in Section 5
- [ ] Phase 4g: Custom Metadata scan ran (custom-metadata-index.json); results in Section 8
- [ ] Phase 4h: Quick Actions scan ran (quick-actions-index.json); results in Section 5
- [ ] Phase 4i: Flexipage scan ran (raw grep, not indexed); results in Section 5
- [ ] Phase 4j: List View scan ran (find + xargs grep, not rg --include); results in Section 5
- [ ] Phase 4k: Assignment Rules scan ran; results in Section 7 if any matches found
- [ ] Phase 4k: Sharing Rules scan ran; results in Section 7 if any matches found
- [ ] Phase 4k: Path Assistants scan ran; results in Section 7 if any matches found
- [ ] Phase 4k: Approval Processes scan ran; results in Section 7 if any matches found
- [ ] Phase 4l: Email Templates scan ran (email-templates-index.json); results in Section 5
- [ ] Phase 4m: Permission Sets / Profiles FLS scan ran; results in Section 5
- [ ] Phase 4n: Formula dependency tracing ran (formula-deps-index.json); results in Section 9

**Phase 5 — file reads**
- [ ] Every file on the Phase 4d-GATE read list was read completely (no partial reads, no skips)
- [ ] Apex classes: noted what each one READS vs WRITES; full file read, not partial
- [ ] Flows: trigger object, trigger event, gate condition, assignment values, status (Active/Draft/Obsolete) documented for each
- [ ] Constants output: every file listed was read — including Contact/Task/Lead/Event flows not just Opportunity/Account

**Output completeness**
- [ ] Field inventory covers ALL objects — not just Opportunity/Account — check snapshots, CPQ objects, custom objects, junction objects, Event, Task
- [ ] Fallback rg scan returned no new files beyond what index found (or new files were read)
- [ ] Section 1 Field Inventory: formula fields show full formula expression; picklist fields list all active values; deprecated fields marked
- [ ] Section 3 Apex: includes "Key Apex Patterns" subsection with representative code snippets (switch statements, branch structure)
- [ ] Section 3 Apex: asymmetries noted (e.g. one pillar has more sub-types than others) — these are Issues in Section 11
- [ ] Section 4 Flows: sub-flow chains documented — if flow A calls sub-flow B, both appear with relationship noted
- [ ] Section 5: Quick Actions subsection present; Assignment Rules/Path Assistants in Section 7; CMDT in Section 8
- [ ] Section 6 CPQ Rules: live record counts from SOQL or data/cpq/ JSON; price rule calc events listed; SV filter logic shown
- [ ] Section 9 Calculation Logic: input→logic→output table for every formula and Apex transformation
- [ ] Section 10 Dependency Chains: table + primary chain summary paragraph; all propagation paths covered
- [ ] Section 11 Issues: covers orphaned writers, double-writes, missing symmetry, deprecated-but-live fields, Finance gate side effects
- [ ] Reports table includes LastRunDate and matching column/filter fields (from reports-index.json `fields` + `filter_values`)
- [ ] Output follows 11-section structure (field-inventory-first, not automation-first)
