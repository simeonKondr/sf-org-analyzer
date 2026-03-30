# sf-org-analyzer

A Claude Code project for deep Salesforce org analysis. Given any natural language question about your org — fields, automations, data flows, dependencies — it retrieves all metadata locally and produces a complete structured report.

No iterative SOQL round-trips for structural questions. Metadata is retrieved once and scanned locally via grep. SOQL is used only for live runtime data.

---

## What it does

You paste a question like:

> "I would like to understand all processes and automations in Salesforce where Product Family, Product Pillar and specific values like Engagement, Discovery, Content, Clarity are used"

And it:

1. Parses your request into field patterns, value patterns, and object scope
2. Retrieves all metadata from your org (Apex, Flows, Objects, Layouts, Rules, Reports...)
3. Discovers the exact field API names via grep before scanning
4. Scans every metadata type for references to those fields and values
5. Queries the live org only for runtime data (last run dates, record counts, job status)
6. Produces a structured report: field inventory, automation inventory, dependency chain, issues
7. Optionally generates a Word document

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

# ripgrep (fast grep — highly recommended)
# macOS:
brew install ripgrep
# Ubuntu/Debian:
apt install ripgrep
# Windows:
choco install ripgrep
```

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-org/sf-org-analyzer.git
cd sf-org-analyzer
```

### 2. Authenticate your org

```bash
# Sandbox
sf org login web --alias MyOrg --instance-url https://your-org.sandbox.my.salesforce.com

# Production
sf org login web --alias MyOrg
```

### 3. Configure your org

Edit `CLAUDE.md` — update the org section at the top:

```markdown
## Org config
- Alias: MyOrg
- Type: Sandbox | Production
- Instance: https://your-org.sandbox.my.salesforce.com
```

That's it. Everything else is generic.

### 4. Launch Claude Code

```bash
claude
```

---

## Usage

### Run an analysis

```
/analyze I would like to understand all automations and processes where 
Product Family, Product Pillar and values like Engagement, Discovery, 
Content, Clarity are used across the org
```

```
/analyze Find everything that reads or writes to the ARR fields on Opportunity
```

```
/analyze Where does the Account_ARR_Product_Pillar__c field get its value from, 
and what reports and dashboards consume it
```

```
/analyze Map the complete data flow for CPQ quoting — from Quote Line to 
Opportunity ARR to Account ARR
```

### Force a metadata refresh

```
/retrieve
```

Or refresh for a different org:

```
/retrieve StagingOrg
```

### Runtime-only queries

```
/runtime Which reports referencing Product Pillar have been run in the last 90 days
```

```
/runtime Are any CPQ Price Rules or Summary Variables configured
```

---

## How it works

```
User question
     │
     ▼
Phase 1: Parse request
  Extract field patterns, value patterns, object scope
  Show user what was found, confirm
     │
     ▼
Phase 2: Metadata freshness check
  If metadata/ older than 24h → run retrieve.sh
  Else reuse cached metadata
     │
     ▼
Phase 3: Field discovery
  grep across all XML for pattern variations
  Build definitive list of exact API names in this org
     │
     ▼
Phase 4: Full metadata scan
  Apex → what reads/writes these fields
  Flows → triggers, conditions, assignments
  Objects → formulas, roll-ups, field definitions  
  Layouts → UI exposure
  Workflows/Validation → rule logic
     │
     ▼
Phase 5: Runtime SOQL (targeted)
  Record counts, last run dates, scheduled job status
  Only questions grep cannot answer
     │
     ▼
Phase 6: Structured report
  Field inventory
  Automation inventory  
  Dependency chain (ASCII)
  Issues & gaps
  Optional: Word doc output
```

---

## Token efficiency vs MCP-only approach

| Approach | Structural analysis | Runtime data | Token cost |
|---|---|---|---|
| MCP SOQL only | Iterative, 50+ queries | ✅ Direct | Very high |
| This repo | Local grep, one pass | ✅ Targeted SOQL | Low |

The difference: SOQL returns JSON with structural overhead on every row. Local grep on retrieved XML is near-zero token cost and runs in milliseconds.

---

## Output

Reports are saved to `./output/` with timestamps. The final analysis includes:

- **Field inventory** — every field matching the pattern, by object, with type and formula
- **Automation inventory** — Apex, Flows, Workflow Rules, Process Builder, Validation Rules
- **UI exposure** — Page Layouts, Flexipages, List Views
- **Data consumers** — Reports and Dashboards with last run date
- **Dependency chain** — source-of-truth → propagation → consumers → outputs
- **Issues** — orphaned fields, double-writes, missing fields, stale documentation

---

## Project structure

```
sf-org-analyzer/
├── CLAUDE.md                    # Claude Code reads this automatically
├── .claude/
│   └── commands/
│       ├── analyze.md           # /analyze — main entry point
│       ├── retrieve.md          # /retrieve — refresh metadata
│       └── runtime.md           # /runtime — live SOQL queries
├── scripts/
│   ├── retrieve.sh              # metadata retrieval
│   ├── scan.sh                  # grep helpers
│   └── docgen.js                # Word doc generation (Node.js)
├── metadata/                    # retrieved metadata lands here (gitignored)
├── cache/                       # field index cache (gitignored)
├── output/                      # analysis outputs (gitignored)
├── docs/                        # reference docs you want Claude to know about
└── sfdx-project.json
```

---

## Customising for your org

Add org-specific context to the `## Known facts about this org` section in `CLAUDE.md`. For example:

```markdown
## Known facts about this org
- CPQ installed: yes / no
- Custom ARR calculation: Apex-based, NOT CPQ Price Rules
- Deprecated fields still live: Opportunity.Product_Pillar__c (formula)
- Known issue: ARR_Clarity__c total field does not exist
```

This means Claude won't re-discover things you already know, and will flag deviations from the documented state.

---

## License

MIT
