# sf-org-analyzer

A Claude Code project for deep Salesforce org metadata analysis. Ask any natural language question about your org — fields, automations, data flows, CPQ rules, reports — and get a complete structured report.

Metadata is retrieved once and indexed locally. All structural questions are answered from the index. SOQL is used only for live runtime data (record counts, last run dates, job status).

---

## What it does

Ask a question like:

> "Find all automations and processes where Product Family and values like value 1 and value 2 are used"

And it:

1. Parses your request into field patterns, value patterns, and object scope
2. Discovers exact field API names from the pre-built field index
3. Queries all cache indexes (Apex, Flows, Validation Rules, Workflow Rules, Reports, Dashboards, CPQ) to find every location
4. Searches string constants for picklist value usage across Apex and Flows
5. Reads only the specific files identified — not the full 430MB metadata
6. Documents the full logic of each automation (trigger, gate condition, reads, formula, writes)
7. Traces the dependency chain: follows written fields downstream to their consumers
8. Queries the live org only for runtime data that metadata cannot answer
9. Produces a structured report; optionally generates a Word document

---

## Prerequisites

```bash
# Node 18+
node --version

# Salesforce CLI
npm install -g @salesforce/cli
sf --version

# Claude Code
npm install -g @anthropic-ai/claude-code
claude --version

# ripgrep (used by scan.sh — highly recommended)
brew install ripgrep        # macOS
apt install ripgrep        # Ubuntu/Debian
choco install ripgrep      # Windows
```

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/your-org/sf-org-analyzer.git
cd sf-org-analyzer
npm install
```

### 2. Authenticate your org

```bash
# Sandbox
sf org login web --alias MyOrg --instance-url https://myorg.sandbox.my.salesforce.com

# Production
sf org login web --alias MyOrg

# Verify
sf org list
```

### 3. Configure your org

```bash
cp org.config.example org.config
```

Edit `org.config` — this is the only file you need to change:

```bash
ORG_ALIAS="MyOrg"
CPQ_INSTALLED="true"   # or false
```

`org.config` is gitignored. Your org details are never committed.

### 4. Launch Claude Code

```bash
claude
```

---

## Usage

### Retrieve metadata (required before first analysis)

```
/retrieve
```

This runs in two phases:
- **Phase 1** — pulls all XML metadata (Apex, Flows, Objects, Layouts, Workflows, Validation Rules, Reports...) into `metadata/`, then builds the cache indexes
- **Phase 2** — exports CPQ configuration records to `data/cpq/` via SOQL

Takes 5–15 minutes depending on org size. Re-run when metadata changes.

### Run an analysis

```
/analyze Find all automations and processes where Product Family, Product Pillar
and values like Engagement, Discovery, Content, Clarity are used
```

```
/analyze Where does ARR_Content__c on Opportunity get its value from
```

```
/analyze Map the complete data flow from CPQ Quote Line to Opportunity ARR to Account ARR
```

```
/analyze What reports and dashboards relate to Product Pillar and when were they last run
```

```
/analyze Find everything that fires when an OpportunityLineItem is created or updated
```

### Runtime-only queries

For live data that cannot be answered from metadata:

```
/runtime Which reports referencing Product Pillar have been run in the last 90 days
```

```
/runtime Are any CPQ Price Rules or Summary Variables configured
```

```
/runtime What scheduled jobs are currently active
```

---

## How it works

```
/analyze <question>
       │
       ▼
Phase 1 — Parse
  Extract FIELD_PATTERNS, VALUE_PATTERNS, OBJECT_SCOPE from natural language
       │
       ▼
Phase 2 — Freshness check
  metadata/.retrieved_at > 24h → run /retrieve
       │
       ▼
Phase 3 — Field discovery
  grep cache/fields-index.tsv for all matching field API names
  (1810 fields indexed — 0.1s, no XML scan needed)
       │
       ▼
Phase 4a — Field locations (index queries)
  field-usage-index.json   → Apex reads + writes, Trigger reads + writes, Flow writes
  flows-index.json         → Flow conditions referencing these fields
  validation-rules-index   → Validation rules with ISPICKVAL/field refs
  workflow-rules-index     → Workflow criteria + field update targets
  reports-index.json       → Reports matching by name/folder/description
  dashboards-index.json    → Dashboards matching by name/folder/components
  cpq-field-usage-index    → CPQ price rules, product rules, summary variables
       │
       ▼
Phase 4b — Value/constant locations
  constants-index.json     → Apex + Flow string literals ("Engagement", "Discovery"...)
  validation-rules-index   → ISPICKVAL values in formulas
  workflow-rules-index     → Criteria item values
       │
       ▼
Phase 4c — Compact scan
  scripts/scan.sh compact  → catch dynamic references missed by regex indexes
       │
       ▼
Phase 5 — Deep-dive (targeted file reads)
  Read only files identified in Phase 4 — not all matches
  For each automation extract:
    trigger (object + event) | gate condition | reads | logic/formula | writes | constants
       │
       ▼
Phase 6 — Chain trace
  For each field written → re-query field-usage-index for downstream readers
  Repeat until chain terminates
       │
       ▼
Phase 7 — Runtime SOQL
  Report LastRunDate, scheduled job NextFireTime, record counts
  Only what metadata cannot answer
       │
       ▼
Phase 8 — Output
  ./output/[slug]-[timestamp].md
  Optional Word document via scripts/docgen.js
```

---

## Cache indexes

After retrieval, `scripts/index.py` builds 11 compact indexes in `cache/`. These replace raw XML scanning for all structural questions.

| Index | Contents |
|---|---|
| `fields-index.tsv` | Every custom field: object, type, label, formula snippet, description |
| `flows-index.json` | Per flow: trigger object/event, field writes, condition expressions |
| `apex-index.json` | Per class: field reads, field writes, SOQL objects, methods |
| `triggers-index.json` | Per trigger: object, events, field reads, field writes, string constants |
| `validation-rules-index.json` | Per rule: formula fields, ISPICKVAL values tested, active flag |
| `workflow-rules-index.json` | Per rule: criteria fields/values, field update targets |
| `reports-index.json` | Per report: name, folder, last run date, searchable text |
| `dashboards-index.json` | Per dashboard: title, folder, component names, searchable text |
| `field-usage-index.json` | Reverse map: field → every file using it (read/write/condition) |
| `constants-index.json` | String constants → files referencing them |
| `cpq-field-usage-index.json` | CPQ parent-child: PriceRule/ProductRule/SummaryVariable → fields used |

**Note on reports/dashboards:** Salesforce does not expose report/dashboard XML via the Metadata API. Matching is by name, folder, and description. For column-level field analysis use `/runtime` with the Tooling API `Report.Metadata` field.

---

## Project structure

```
sf-org-analyzer/
├── org.config.example        ← copy to org.config, fill in your alias + instance
├── org.config                ← gitignored — your org details live here
├── CLAUDE.md                 ← project instructions (Claude reads automatically)
├── .claude/
│   └── commands/
│       ├── analyze.md        ← /analyze — main entry point
│       ├── retrieve.md       ← /retrieve — refresh metadata + CPQ data
│       └── runtime.md        ← /runtime — live SOQL queries
├── scripts/
│   ├── retrieve.sh           ← Phase 1+2 retrieval (sources org.config)
│   ├── index.sh              ← triggers index.py after retrieval
│   ├── index.py              ← builds all 11 cache indexes from metadata + data/
│   ├── scan.sh               ← ripgrep wrapper for raw metadata scanning
│   └── docgen.js             ← markdown → Word document (Node.js)
├── metadata/                 ← retrieved XML metadata (gitignored)
├── data/                     ← exported org data: CPQ records, reports (gitignored)
├── cache/                    ← built indexes (gitignored, rebuilt from metadata)
├── output/                   ← analysis reports (gitignored)
├── docs/                     ← org-specific findings from prior sessions
└── sfdx-project.json
```

---

## Output

Reports are saved to `output/` with timestamps. Each analysis includes:

- **Field inventory** — every matching field by object, with type, formula snippet, description
- **Automation inventory** — Apex, Flows, Workflow Rules, Validation Rules, CPQ rules
- **Dependency chain** — source-of-truth → propagation → consumers
- **Data consumers** — reports and dashboards with last run date
- **Issues** — orphaned fields, double-writes, missing symmetry, stale descriptions

Optionally generates a formatted Word document via `node scripts/docgen.js`.

---

## Token efficiency

| Approach | Structural questions | Runtime data | Relative token cost |
|---|---|---|---|
| SOQL only (MCP) | 50+ iterative queries | Direct | Very high |
| This repo | Index lookup, ~0.1s | Targeted SOQL | Low |

SOQL returns JSON with record wrappers on every row. A local grep or index lookup on retrieved XML is near-zero token cost and runs in milliseconds.

---

## License

MIT
