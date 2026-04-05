# /retrieve

Forces a fresh metadata retrieval from the org.

**Usage:**
```
/retrieve              # uses org alias from CLAUDE.md
/retrieve StagingOrg   # retrieves from a different alias
```

---

## Instructions for Claude

Target org alias: **$ARGUMENTS** (use CLAUDE.md org alias if empty)

Run:
```bash
bash scripts/retrieve.sh ${ARGUMENTS:-}
```

After completion report:
1. Timestamp written to `metadata/.retrieved_at`
2. File count per metadata type:
   ```bash
   echo "Apex classes:     $(find metadata/classes -name '*.cls' 2>/dev/null | wc -l)"
   echo "Flows:            $(find metadata/flows -name '*.flow-meta.xml' 2>/dev/null | wc -l)"
   echo "Objects:          $(find metadata/objects -name '*.object-meta.xml' 2>/dev/null | wc -l)"
   echo "Custom fields:    $(find metadata/objects -name '*.field-meta.xml' 2>/dev/null | wc -l)"
   echo "Layouts:          $(find metadata/layouts -name '*.layout-meta.xml' 2>/dev/null | wc -l)"
   echo "Validation rules: $(find metadata/objects -name '*.validationRule-meta.xml' 2>/dev/null | wc -l)"
   echo "Workflow rules:   $(find metadata/workflows -name '*.workflow-meta.xml' 2>/dev/null | wc -l)"
   echo "Flexipages:       $(find metadata/flexipages -name '*.flexipage-meta.xml' 2>/dev/null | wc -l)"
   echo "Reports:          $(find metadata/reports -name '*.report-meta.xml' 2>/dev/null | wc -l)"
   echo "Dashboards:       $(find metadata/dashboards -name '*.dashboard-meta.xml' 2>/dev/null | wc -l)"
   echo "Custom metadata:  $(find metadata/customMetadata -name '*.md-meta.xml' 2>/dev/null | wc -l)"
   ```
3. Total size: `du -sh metadata/`
4. Confirm: "Metadata ready. Run /analyze to start your analysis."
