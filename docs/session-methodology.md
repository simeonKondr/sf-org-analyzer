# Analysis Methodology & Lessons Learned

Context for continuing this project. Captures decisions made and why,
so you don't re-litigate them.

---

## Why local metadata grep instead of MCP SOQL for structural questions

The MCP Salesforce DX server was used extensively in early analysis and works,
but is significantly more expensive for structural questions than local grep:

- SOQL returns JSON with per-row `attributes`, `type`, `url` overhead — 3-4x
  more tokens than equivalent XML
- Each query is a round-trip that permanently grows the context window
- Discovery requires iterative queries (find what exists, then fetch details)
- Tooling API returns full Apex class bodies for every match regardless of relevance
- `$Record__Prior`, Flow XML, field formulas — all exist in retrieved metadata XML
  and are unsearchable via SOQL

**Use MCP/SOQL only for:**
- `LastRunDate` on reports
- Record counts (especially CPQ rule objects)
- Scheduled job status
- Whether specific fields have non-zero live data

**Use local grep for everything structural.**

---

## Why pasting a zipped metadata archive is token-efficient

When a full metadata archive is pasted into the chat, it lands once as input tokens.
Reading it costs nothing additional — the model attends over what's already present.

With MCP, every query generates output tokens and permanently adds the result JSON
to the context. 50 queries × average 2KB JSON each = 100KB context growth.

For the BloomreachAWR analysis, the MCP-only approach used roughly 5x more tokens
than the archive approach for the same structural information.

---

## sf-org-analyzer repo — what it is

A Claude Code project template built to eliminate the manual archive approach.
Instead of zipping and pasting metadata, the repo:

1. Runs `sf project retrieve start` to pull all metadata to disk
2. Uses `bash scripts/scan.sh` (ripgrep wrapper) to search across all XML
3. Uses `sf data query` for the small set of runtime questions
4. Generates Word documents via `node scripts/docgen.js`

The repo was created and refined during this session. Key improvements made:

- Added `discover_fields()` function in `retrieve.sh` — queries `FieldDefinition`
  before querying CPQ objects to avoid "No such column" errors
- Added `export_query_safe()` function — builds SELECT from only confirmed fields
- Added `.claude/settings.json` — pre-approves bash commands so Claude Code
  doesn't prompt for permission on every operation
- Added "Execute autonomously" instruction to all slash commands and CLAUDE.md

---

## GitHub push issue

Attempted to push `sf-org-analyzer` to `simeonKondr` GitHub account.
Error: "simeonKondr does not have correct permissions to execute CreateRepository"

This is a `gh` CLI scope issue. Fix:
```bash
gh auth login --scopes repo
# Then retry:
cd sf-org-analyzer
git init && git add . && git commit -m "Initial commit"
gh repo create simeonKondr/sf-org-analyzer --public --source=. --push
```

Or: create the repo manually on github.com/new, then:
```bash
git remote add origin https://github.com/simeonKondr/sf-org-analyzer.git
git push -u origin main
```

---

## Claude Desktop vs Claude Code for this work

| | Claude.ai (this chat) | Claude Code |
|---|---|---|
| Runs bash commands | ❌ | ✅ |
| Reads local metadata files | ❌ paste manually | ✅ via bash |
| SOQL queries | ✅ MCP | ✅ sf data query |
| Slash commands | ❌ | ✅ |
| CLAUDE.md auto-loaded | ❌ | ✅ |
| Autonomous multi-step analysis | ❌ | ✅ |

Claude Desktop can approximate Claude Code by:
1. Running `bash scripts/retrieve.sh` manually in terminal
2. Adding a filesystem MCP server pointed at `./metadata`
3. Pasting `CLAUDE.md` content at session start

But Claude Code is the right tool for the sf-org-analyzer workflow.

---

## Document generation

The Word document was built with `docx` npm package (not pandoc, not LibreOffice).
It generates `.docx` via JavaScript directly — no system dependencies beyond Node.js.

Landscape format, 1-inch margins, navy/blue colour scheme.
`scripts/docgen.js` converts markdown analysis output → Word document.

Previous document: `ProductFamily_Pillar_Complete_Analysis.docx` (15 sections, ~44KB)
Covers findings up to and including the CPQ audit (Section 14).
Section 15 (Reports & Dashboards) was not added — this is the next task.

---

## Analysis pattern for any future Salesforce field audit

1. **Name variants** — always search for multiple forms of field names:
   `Product_Family` AND `ProductFamily` AND `SBQQ__ProductFamily`

2. **Value literals** — always search for string values that appear in Apex/Flow:
   `'Engagement'` AND `"Engagement"` — Apex uses either quote style

3. **Both read and write** — for each field, determine separately:
   - What WRITES it (source of truth)
   - What READS it (consumers)
   - Whether write-side and read-side are still in sync

4. **Description archaeology** — check field descriptions for "Updated from [X]".
   If [X] doesn't exist in the metadata, the field is orphaned.

5. **Symmetry check** — if Content/Discovery/Engagement have fields, check Clarity.
   This org added Clarity later and missed several field parity items.
