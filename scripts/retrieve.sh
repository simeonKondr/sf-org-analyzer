#!/usr/bin/env bash
# retrieve.sh — pull all analysis-relevant metadata from a Salesforce org
#
# Usage:
#   bash scripts/retrieve.sh              # uses default org
#   bash scripts/retrieve.sh MyOrgAlias   # uses specified alias
#
# Requires: @salesforce/cli (sf command)

set -euo pipefail

ALIAS="${1:-}"
OUTPUT_DIR="./metadata"
TIMESTAMP_FILE="$OUTPUT_DIR/.retrieved_at"

# ── Resolve org ───────────────────────────────────────────────────────────────
if [ -z "$ALIAS" ]; then
  # Try to read from CLAUDE.md
  if [ -f "CLAUDE.md" ]; then
    ALIAS=$(grep -oP '(?<=Alias:\s{0,10})\S+' CLAUDE.md | head -1 || true)
  fi
fi

if [ -z "$ALIAS" ]; then
  echo "ERROR: No org alias provided and none found in CLAUDE.md"
  echo "Usage: bash scripts/retrieve.sh <OrgAlias>"
  exit 1
fi

echo "──────────────────────────────────────────────"
echo "Retrieving metadata from: $ALIAS"
echo "Output directory:         $OUTPUT_DIR"
echo "──────────────────────────────────────────────"

# ── Clean previous retrieve (optional — comment out to keep cache) ────────────
# rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# ── Metadata types to retrieve ────────────────────────────────────────────────
# Covers everything needed for a field usage analysis:
# - Apex classes (logic, triggers)
# - Flows (automation)
# - Custom objects and fields (schema, formulas, roll-ups)
# - Layouts (UI exposure)
# - Workflow rules (legacy automation)
# - Validation rules (logic)
# - Flexipages (Lightning pages)
# - Custom metadata types (configuration tables)
# - Reports and Dashboards (data consumers)
# - Assignment/Escalation/AutoResponse rules (process logic)
# - Email templates (merge field references)
# - List views (filter references)
# - Named credentials, custom settings (referenced in Apex)

METADATA_TYPES=(
  "ApexClass"
  "ApexTrigger"
  "CustomObject"
  "CustomField"
  "Flow"
  "FlowDefinition"
  "WorkflowRule"
  "WorkflowFieldUpdate"
  "WorkflowAlert"
  "ValidationRule"
  "Layout"
  "FlexiPage"
  "CustomMetadata"
  "CustomSetting"
  "Report"
  "Dashboard"
  "AssignmentRule"
  "AutoResponseRule"
  "EscalationRule"
  "EmailTemplate"
  "ListView"
  "NamedCredential"
  "CustomLabel"
  "CustomPermission"
  "Profile"
  "PermissionSet"
  "RecordType"
)

# Join with commas
METADATA_STRING=$(IFS=','; echo "${METADATA_TYPES[*]}")

echo ""
echo "Retrieving ${#METADATA_TYPES[@]} metadata types..."
echo ""

# ── Run retrieval ─────────────────────────────────────────────────────────────
sf project retrieve start \
  --target-org "$ALIAS" \
  --metadata "$METADATA_STRING" \
  --output-dir "$OUTPUT_DIR" \
  --ignore-conflicts \
  2>&1 | tee /tmp/retrieve-log.txt

RETRIEVE_EXIT=${PIPESTATUS[0]}

if [ $RETRIEVE_EXIT -ne 0 ]; then
  echo ""
  echo "⚠  Retrieve completed with warnings or partial failures."
  echo "   Some metadata types may not be available in this org."
  echo "   Check /tmp/retrieve-log.txt for details."
  echo "   Continuing with whatever was retrieved..."
fi

# ── Write timestamp ───────────────────────────────────────────────────────────
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') from $ALIAS" > "$TIMESTAMP_FILE"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "──────────────────────────────────────────────"
echo "Retrieval complete"
echo "──────────────────────────────────────────────"
echo ""

print_count() {
  local label="$1"
  local pattern="$2"
  local count
  count=$(find "$OUTPUT_DIR" -name "$pattern" 2>/dev/null | wc -l | tr -d ' ')
  printf "  %-28s %s\n" "$label" "$count files"
}

print_count "Apex classes"       "*.cls"
print_count "Apex triggers"      "*.trigger"
print_count "Flows"              "*.flow-meta.xml"
print_count "Custom fields"      "*.field-meta.xml"
print_count "Custom objects"     "*.object-meta.xml"
print_count "Layouts"            "*.layout-meta.xml"
print_count "Validation rules"   "*.validationRule-meta.xml"
print_count "Workflow rules"     "*.workflow-meta.xml"
print_count "Flexipages"         "*.flexipage-meta.xml"
print_count "Reports"            "*.report-meta.xml"
print_count "Dashboards"         "*.dashboard-meta.xml"
print_count "Custom metadata"    "*.md-meta.xml"
print_count "Email templates"    "*.email-meta.xml"
print_count "Record types"       "*.recordType-meta.xml"
print_count "Permission sets"    "*.permissionset-meta.xml"

echo ""
TOTAL_SIZE=$(du -sh "$OUTPUT_DIR" 2>/dev/null | cut -f1)
echo "  Total size: $TOTAL_SIZE"
echo ""
echo "  Timestamp: $(cat $TIMESTAMP_FILE)"
echo ""
echo "Ready. Run /analyze to start your analysis."
