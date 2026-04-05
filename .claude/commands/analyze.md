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

### Phase 4 — Scan (cache → compact → targeted read)

**Always follow this order to minimise tokens:**

1. Check the pre-built writer index:
```bash
grep -i "FIELD_PATTERN" cache/field-writers-index.tsv
```

2. Check flows-index.json and apex-index.json for matching automations:
```bash
python3 -c "
import json
flows = json.load(open('cache/flows-index.json'))
for f in flows:
    if any('PATTERN' in str(w) for w in f.get('writes',[])+f.get('conds',[])):
        print(f['file'],'|',f['type'],'|',f['obj'],'→',f['writes'])
"
```

3. Compact scan to confirm coverage:
```bash
bash scripts/scan.sh "FIELD_PATTERN" all compact
```

4. Read only the specific files identified above — do NOT read all matching files.

For every automation: state what it reads, what condition gates it, what it writes.

### Phase 5 — Runtime SOQL

**Do NOT re-run queries for facts already in CLAUDE.md Known Facts.**
CPQ object counts are confirmed EMPTY — skip those unless explicitly asked.

Run only what is needed for live data:
- Report LastRunDate (not in metadata)
- Scheduled job NextFireTime
- Record counts for objects with *unknown* record counts

### Phase 6 — Output
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
