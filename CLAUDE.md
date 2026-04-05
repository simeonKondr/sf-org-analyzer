# sf-org-analyzer — Project Context

This repository is a Claude Code project for deep Salesforce org metadata analysis.
It was built during an extended analysis session of the BloomreachAWR org.

**Read `docs/bloomreach-audit-findings.md` before doing anything org-specific.**
It contains the complete findings from the previous analysis session so you don't
re-discover things already documented.

---

## Execution style

Run all phases autonomously without pausing to ask "shall I continue?".
Execute bash commands, file writes, and SOQL queries without asking for permission.
Only stop if:
- A command returns an error that blocks the next step
- The user's request is genuinely ambiguous (e.g. org alias not specified)
- A destructive action is about to happen that wasn't requested

---

## Org config

```
Alias:    BloomreachAWR
Type:     Sandbox
Instance: https://bloomreach--awr.sandbox.my.salesforce.com
CPQ:      Installed (SBQQ managed package)
```

---

## Critical rule — never hardcode CPQ or custom field names in SOQL

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
  --target-org BloomreachAWR \
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
cat metadata/.retrieved_at 2>/dev/null || echo "NOT RETRIEVED"
```

Retrieve if not retrieved or older than 24 hours:
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
# What writes this field?
grep -i "FIELD_NAME" cache/field-writers-index.tsv

# What flows touch this object/field?
python3 -c "
import json
flows = json.load(open('cache/flows-index.json'))
hits = [f for f in flows if any('PATTERN' in w for w in f.get('writes',[]) + f.get('conds',[]))]
for h in hits: print(h['file'], '|', h['type'], '|', h['obj'], '| writes:', h['writes'])
"

# What Apex classes write this field?
python3 -c "
import json
for c in json.load(open('cache/apex-index.json')):
    if any('PATTERN' in w for w in c['writes']): print(c['file'], c['writes'])
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

**Skip queries already answered in Known Facts below** — do not re-confirm
CPQ object counts documented as EMPTY, and do not re-query fields confirmed
as orphaned. Check `data/cpq/cpq-status.json` before any CPQ queries.

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

| Metadata type | File location | What to look for |
|---|---|---|
| Apex | `metadata/classes/*.cls` | Field refs, string comparisons, SOQL |
| Flow | `metadata/flows/*.flow-meta.xml` | `<field>`, `<stringValue>`, `<assignToReference>` |
| Object/Field | `metadata/objects/**/*.field-meta.xml` | `<formula>`, `<description>`, `<summaryFilterItems>` |
| Layout | `metadata/layouts/*.layout-meta.xml` | `<field>` in layout sections |
| Workflow | `metadata/workflows/*.workflow-meta.xml` | `<field>`, `<criteriaItems>`, `<fieldUpdates>` |
| Validation | `metadata/objects/**/*.validationRule-meta.xml` | `<errorConditionFormula>` |
| Flexipage | `metadata/flexipages/*.flexipage-meta.xml` | `<field>` in components |
| Report | `metadata/reports/**/*.report-meta.xml` | `<reportColumns>`, `<reportFilters>` |

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

---

## Known facts about BloomreachAWR org

These are confirmed findings — do not re-discover or re-query for these.

### CPQ configuration
- CPQ installed: YES (SBQQ managed package)
- Price Rules: **EMPTY** (0 records) — deleted, not in use
- Price Actions: **EMPTY** (0 records)
- Price Conditions: **EMPTY** (0 records)
- Summary Variables: **EMPTY** (0 records)
- Product Rules: **EMPTY** (0 records)
- Error Conditions: **EMPTY** (0 records)
- Configuration Rules: **EMPTY** (0 records)
- Custom Scripts: **EMPTY** (0 records)
- Lookup Queries: **EMPTY** (0 records)
- Custom Actions: 36 records — ALL standard CPQ UI buttons, none custom
- QuoteCalculatorPlugin: NOT implemented (no custom Apex implements it)

### ARR computation — actual working path
1. `SBQQ__QuoteLine__c.Product_Line_ARR_Total__c` [FORMULA]
   = `IF(ISBLANK(ARR_Override__c), IF(Revenue_Type__c='Recurring', SBQQ__NetTotal__c/Expected_Term__c*12, 0), ARR_Override__c)`
2. CPQ contracts Quote → creates OLIs
3. `OpportunityLineItemTriggerHandler` Apex reads `OLI.Product_Family__c`
   → writes `Opportunity.ARR_Content/Discovery/Engagement/Y1_*__c`
4. `SubscriptionArrCalculator` Apex (nightly + renewal trigger)
   reads `SBQQ__Subscription__c.Product_Line_ARR_Total__c`
   → writes `Opportunity.ARR_Renewal_Base_*__c`

### Critical: orphaned Quote ARR fields
`SBQQ__Quote__c.ARR_Content__c`, `ARR_Discovery__c`, `ARR_Engagement__c`,
`ARR_Engagement_Subscription__c`, `ARR_Engagement_Services__c`
— field descriptions reference "Price Rule 'Q: Update ARR Fields'" which was deleted.
— **no current automated writer exists for these fields**
— `Update_Opportunity_Fields_From_Quote` flow reads them and pushes zero/null to Opportunity
— CONFIRMED ISSUE: this means CPQ deals get ARR zeroed on every Quote save

### Product pillar values
- Active: Discovery (brSM), Content (brXM), Engagement (brEX), Clarity, Services
- Partially retired: SEO/brSEO (CD-004625, June 2024)
  — removed from Opp formula but still in Product2 formula

### Deprecated fields still live on Opportunity
- `Product_Pillar__c` (formula — labeled deprecated)
- `Opportunity_Product_Family__c` (formula — labeled deprecated)
- `Product_Family_Group__c` (formula — labeled deprecated)

### Clarity missing from total ARR
- `ARR_Y1_Clarity__c` exists (written by Apex Y1 path)
- `ARR_Renewal_Base_Clarity__c` exists (written by SubscriptionArrCalculator)
- `ARR_Clarity__c` total field **does NOT exist**
- Clarity deals always show zero in total ARR by pillar reports

### Double-write on Opportunity ARR fields
`ARR_Content__c`, `ARR_Discovery__c`, `ARR_Engagement_Subscription__c`,
`ARR_Engagement_Services__c` are written by BOTH:
- `OpportunityLineItemTriggerHandler` Apex (after every OLI change)
- `Update_Opportunity_Fields_From_Quote` Flow (after every CPQ Quote save)
No mutual exclusion exists between them.

### Finance lock gate issue
`Update_Opportunity_Fields_From_Quote` flow is blocked when
`Finance_Reviewed__c = true` on the Opportunity.
Apex trigger still fires. Silent data inconsistency on locked opps.

---

## Previous deliverable

A complete Word document was generated:
`ProductFamily_Pillar_Complete_Analysis.docx` (15 sections, landscape, ~44KB)

Sections covered:
1. Executive Summary (7 critical issues)
2. Field Inventory (all objects)
3. Legacy Code Mapping
4. Apex Classes (8 classes documented)
5. Flows (20+ flows)
6. Workflow Rules
7. CPQ Price Rules & Summary Variables
8. rh2 Rollup Helper
9. Validation Rules
10. Dependency Chains (4 ASCII diagrams)
11. Page Layouts / Lightning Pages / List Views
12. Known Issues & Recommendations
13. Complete Automation Inventory (30 automations)
14. CPQ Price Rules, Product Rules & Custom Scripts — Full Audit
15. Glossary

---

## What was NOT completed in the prior session

1. **Reports and dashboards section** — queries were run and data obtained,
   but the document was NOT updated with reports/dashboards findings before
   the session ended. The raw data is in `docs/bloomreach-reports-dashboards-raw.md`.

2. **Tooling API metadata for report columns/filters** — we identified which
   reports were recently run by name pattern, but did NOT retrieve the actual
   field API names used in each report's columns and filters via Tooling API.

3. **Dashboard component cross-reference** — we did not query
   `DashboardComponent` to map which reports feed which dashboard widgets.

---

## Pending next steps

1. Complete the reports & dashboards analysis:
   - Fetch report metadata via Tooling API to get actual column/filter field names
   - Cross-reference dashboard components to reports
   - Identify which reports read the orphaned Quote ARR fields
   - Update the Word document with Section 15 (Reports & Dashboards)

2. Fix recommendation for orphaned Quote ARR fields (implement one of):
   - Option 1 (recommended): Rewrite `Update_Opportunity_Fields_From_Quote`
     flow to aggregate from Quote Lines by `Product_Family__c` directly
   - Option 2: Restore CPQ Price Rules and Summary Variables
   - Option 3: Implement `SBQQ.QuoteCalculatorPlugin` in Apex

3. Fix recommendation for Clarity total ARR gap:
   - Create `ARR_Clarity__c` Currency field on Opportunity
   - Add to `OpportunityLineItemTriggerHandler` rollupArr() method
   - Add to CPQ flow assignments

4. Push `sf-org-analyzer` repo to GitHub (simeonKondr account):
   - Previous attempt failed: "simeonKondr does not have correct permissions to execute CreateRepository"
   - Fix: `gh auth login --scopes repo` or create repo manually on github.com then push
