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
- "Product Family"   → `Product_Family|ProductFamily|SBQQ__ProductFamily`
- "ARR by pillar"    → `ARR_Content|ARR_Discovery|ARR_Engagement|ARR_Clarity|ARR_Y1`

**VALUE_PATTERNS** — string literals that appear in code as picklist values:
- "Engagement, Discovery" → `'Engagement'|'Discovery'|"Engagement"|"Discovery"`

**OBJECT_SCOPE** — default set:
`Opportunity, OpportunityLineItem, Product2, Account,
SBQQ__QuoteLine__c, SBQQ__Quote__c, SBQQ__Subscription__c, Case`

### Phase 2 — Check metadata freshness

```bash
source org.config 2>/dev/null
cat metadata/.retrieved_at 2>/dev/null || echo "NOT RETRIEVED"
```

Retrieve if any of the following are true:
- Metadata has never been retrieved
- Metadata is older than 24 hours
- `DRY_RUN=true` in org.config (forces fresh retrieval regardless of age)

```bash
bash scripts/retrieve.sh
```

### Phase 3 — Field discovery

**Step 1 — Cache first (fast, ~1KB read):**
```bash
grep -i "PATTERN" cache/fields-index.tsv | cut -f1-4
```
This reads the pre-built index instead of scanning 430MB of raw XML.
Save matching field names to `cache/discovered-fields.txt`.

**Step 2 — Only if cache missing or pattern needs raw XML:**
```bash
PATTERN="product.?family|product.?pillar"
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

# Flows touching this field (writes or conditions)
python3 -c "
import json
for f in json.load(open('cache/flows-index.json')):
    if any('PATTERN' in str(x) for x in f.get('writes',[]) + f.get('conds',[])):
        print(f['file'], '|', f['obj'], f['event'], '| writes:', f['writes'])
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

# Reports using this field in columns or filters
python3 -c "
import json
for r in json.load(open('cache/reports-index.json')):
    if any('PATTERN' in x for x in r.get('fields',[]) + r.get('filter_values',[])):
        print(r['name'], '| folder:', r['folder'], '| fields:', r['fields'])
"
```

**Step 2 — Compact scan for broad discovery (low token cost):**
```bash
bash scripts/scan.sh "FIELD_PATTERN" all compact
```
Compact mode returns filename + matching line only — no context bloat.
Use this to identify *which* files are relevant.

**Step 3 — Read specific files for full context:**
Only read raw files for the specific automations identified in steps 1-2.
Do not read files not flagged by the index or compact scan.

For every match: explain what each automation actually does (trigger, condition, write).

### Phase 5 — Runtime SOQL (targeted)

Check `data/cpq/cpq-status.json` before any CPQ queries to avoid re-querying
objects already confirmed empty.

Run only what you need for *live runtime data*:
```sql
SELECT Id, Name, LastRunDate, FolderName FROM Report WHERE LastRunDate > LAST_N_DAYS:90 ORDER BY LastRunDate DESC LIMIT 100
SELECT Id, CronJobDetail.Name, State, NextFireTime FROM CronTrigger WHERE State = 'WAITING'
```
CPQ counts (only if explicitly requested, since all are confirmed EMPTY):
```sql
SELECT COUNT() FROM SBQQ__PriceRule__c
SELECT COUNT() FROM SBQQ__SummaryVariable__c
```

### Phase 6 — Output

Save to `./output/analysis-[timestamp].md`.
Ask if the user wants a Word document: `node scripts/docgen.js ./output/analysis.md`

---

## Scan matrix

`[indexed]` = covered by cache; start here. `[scan]` = grep raw files if not answered by index.

| Metadata type | Cache index | Raw file location | What to look for |
|---|---|---|---|
| Apex | `apex-index.json` reads+writes **[indexed]** | `metadata/classes/*.cls` | Field refs, SOQL, string comparisons |
| Trigger | `triggers-index.json` reads+writes **[indexed]** | `metadata/triggers/*.trigger` | Field refs, events, constants |
| Flow | `flows-index.json` writes+conds **[indexed]** | `metadata/flows/*.flow-meta.xml` | `<assignToReference>`, `<stringValue>` |
| Object/Field | `fields-index.tsv` **[indexed]** | `metadata/objects/**/*.field-meta.xml` | `<formula>`, `<description>`, `<summaryFilterItems>` |
| Validation rule | `validation-rules-index.json` **[indexed]** | `metadata/objects/**/*.validationRule-meta.xml` | `<errorConditionFormula>`, ISPICKVAL values |
| Workflow rule | `workflow-rules-index.json` **[indexed]** | `metadata/workflows/*.workflow-meta.xml` | `<criteriaItems>`, `<fieldUpdates>` |
| Report | `reports-index.json` (name/folder/desc) **[indexed]** | `data/cpq/reports-all.json` — XML not retrievable | Name + folder matching; column-level needs `/runtime` |
| Dashboard | `dashboards-index.json` (name/folder/components) **[indexed]** | `data/cpq/dashboards.json` + `dashboard-components.json` | Name + component matching |
| Layout | *(none — structural only)* **[scan]** | `metadata/layouts/*.layout-meta.xml` | `<field>` in layout sections |
| Flexipage | *(none)* **[scan]** | `metadata/flexipages/*.flexipage-meta.xml` | `<field>` in components |
| CPQ rules | `cpq-field-usage-index.json` **[indexed]** | `data/cpq/*.json` | Parent-child field references |

---

## Known issues to flag automatically

During any analysis, always check for and flag:

1. **Orphaned writer** — field description says "Updated from [automation]" but
   that automation no longer exists in the metadata
2. **Double-write** — two automations both write the same field with no mutual exclusion
3. **Missing symmetry** — fields exist for Content/Discovery/Engagement but not Clarity
4. **Stale description** — description references automation names that don't exist
5. **Deprecated field still live** — labeled "deprecated" but still in formulas/layouts
6. **Finance/lock gate** — flow skips writes when locked, but Apex still fires

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
│   ├── bloomreach-audit-findings.md  ← COMPLETE PRIOR AUDIT FINDINGS ← READ THIS
│   └── bloomreach-known-issues.md    ← critical issues with recommendations
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

