#!/usr/bin/env bash
# scan.sh — grep metadata for field patterns, value patterns, or any term
#
# Usage:
#   bash scripts/scan.sh "Product_Family"                  # all scopes, verbose
#   bash scripts/scan.sh "ARR_Content|ARR_Discovery" flows # scope to flows
#   bash scripts/scan.sh "Product_Family" all compact      # compact: file+line only
#
# Scope options: apex, flows, objects, layouts, workflows, flexipages,
#                reports, all (default)
#
# Mode options (3rd arg):
#   verbose  — 3 lines context, head-60 per file (default)
#   compact  — matching line + line number only, no context, no truncation
#              Use compact for broad discovery; verbose when you need context
#
# TIP: Always check cache/field-usage-index.json and cache/flows-index.json
#      before running a full scan — they answer "what reads/writes X?" instantly.

set -euo pipefail

# Ensure tools installed outside /usr/bin are reachable
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/local/lib/sf/bin:$PATH"

PATTERN="${1:-}"
SCOPE="${2:-all}"
MODE="${3:-verbose}"   # verbose | compact
METADATA_DIR="./metadata"
CONTEXT_LINES=3
[ "$MODE" = "compact" ] && CONTEXT_LINES=0

if [ -z "$PATTERN" ]; then
  echo "Usage: bash scripts/scan.sh <pattern> [scope]"
  echo "Scopes: apex, flows, objects, layouts, workflows, flexipages, reports, all"
  exit 1
fi

# Check ripgrep is available, fall back to grep
if command -v rg &>/dev/null; then
  GREP_CMD="rg"
  GREP_OPTS="-i --no-heading -A $CONTEXT_LINES -B $CONTEXT_LINES"
else
  GREP_CMD="grep"
  GREP_OPTS="-ri -A $CONTEXT_LINES -B $CONTEXT_LINES"
  echo "⚠  ripgrep not found, falling back to grep (slower)"
fi

# ── Scan functions ─────────────────────────────────────────────────────────────

scan_section() {
  local label="$1"
  local dir="$2"
  local file_pattern="$3"

  if [ ! -d "$METADATA_DIR/$dir" ]; then
    return
  fi

  local results
  if [ "$GREP_CMD" = "rg" ]; then
    results=$(rg -i "$PATTERN" "$METADATA_DIR/$dir" \
      --glob "$file_pattern" \
      -l 2>/dev/null || true)
  else
    results=$(grep -rl "$PATTERN" "$METADATA_DIR/$dir" \
      --include="$file_pattern" 2>/dev/null || true)
  fi

  local count
  count=$(echo "$results" | awk 'NF' | wc -l | tr -d ' ')

  if [ "$count" -eq 0 ]; then
    echo "  $label: no matches"
    return
  fi

  echo ""
  echo "══════════════════════════════════════════════"
  echo "  $label — $count file(s)"
  echo "══════════════════════════════════════════════"

  while IFS= read -r file; do
    [ -z "$file" ] && continue
    local basename
    basename=$(basename "$file")

    if [ "$MODE" = "compact" ]; then
      # Compact: one line per match with line number, no context, no truncation
      local match_count
      if [ "$GREP_CMD" = "rg" ]; then
        matches=$(rg -i "$PATTERN" "$file" -n --no-heading 2>/dev/null || true)
      else
        matches=$(grep -in "$PATTERN" "$file" 2>/dev/null || true)
      fi
      match_count=$(echo "$matches" | awk 'NF' | wc -l | tr -d ' ')
      echo ""
      echo "  📄 $basename  ($match_count matches)"
      echo "$matches" | sed 's/^/    /'
    else
      # Verbose: N lines context, head-60 per file
      echo ""
      echo "  📄 $basename"
      echo "  ─────────────────────────────────────────"
      if [ "$GREP_CMD" = "rg" ]; then
        rg -i "$PATTERN" "$file" \
          -A $CONTEXT_LINES -B $CONTEXT_LINES \
          --no-heading \
          2>/dev/null \
          | head -60 \
          | sed 's/^/    /'
      else
        grep -i "$PATTERN" "$file" \
          -A $CONTEXT_LINES -B $CONTEXT_LINES \
          2>/dev/null \
          | head -60 \
          | sed 's/^/    /'
      fi
    fi
  done <<< "$results"
}

# ── Field discovery mode ───────────────────────────────────────────────────────
discover_fields() {
  echo ""
  echo "══════════════════════════════════════════════"
  echo "  Field API names matching: $PATTERN"
  echo "══════════════════════════════════════════════"
  echo ""

  if [ "$GREP_CMD" = "rg" ]; then
    rg -i "$PATTERN" "$METADATA_DIR" \
      --type xml -o --no-filename \
      2>/dev/null \
      | grep -oE '[A-Za-z][A-Za-z0-9_]*__c' \
      | sort -u \
      | sed 's/^/  /'
  else
    grep -rioE '[A-Za-z][A-Za-z0-9_]*__c' "$METADATA_DIR" \
      2>/dev/null \
      | grep -i "$PATTERN" \
      | grep -oE '[A-Za-z][A-Za-z0-9_]*__c' \
      | sort -u \
      | sed 's/^/  /'
  fi

  echo ""
}

# ── Summary (files only) ───────────────────────────────────────────────────────
summary_only() {
  echo ""
  echo "══════════════════════════════════════════════"
  echo "  Files matching: $PATTERN"
  echo "══════════════════════════════════════════════"
  echo ""

  if [ "$GREP_CMD" = "rg" ]; then
    rg -i "$PATTERN" "$METADATA_DIR" \
      --type xml -l \
      2>/dev/null \
      | sed "s|$METADATA_DIR/||" \
      | sort \
      | sed 's/^/  /'
  else
    grep -ril "$PATTERN" "$METADATA_DIR" \
      2>/dev/null \
      | sed "s|$METADATA_DIR/||" \
      | sort \
      | sed 's/^/  /'
  fi

  echo ""
}

# ── Main ───────────────────────────────────────────────────────────────────────

echo ""
echo "Scanning for: \"$PATTERN\""
echo "Scope:        $SCOPE"
echo "Mode:         $MODE"
echo "Metadata dir: $METADATA_DIR"
echo ""

if [ ! -f "$METADATA_DIR/.retrieved_at" ]; then
  echo "⚠  Metadata not yet retrieved. Run: bash scripts/retrieve.sh"
  exit 1
fi

echo "  Metadata retrieved: $(cat $METADATA_DIR/.retrieved_at)"

case "$SCOPE" in
  discover)
    discover_fields
    ;;
  summary)
    summary_only
    ;;
  apex)
    scan_section "Apex Classes"  "classes"  "*.cls"
    scan_section "Apex Triggers" "triggers" "*.trigger"
    ;;
  flows)
    scan_section "Flows" "flows" "*.flow-meta.xml"
    ;;
  objects)
    scan_section "Custom Fields"      "objects" "*.field-meta.xml"
    scan_section "Custom Objects"     "objects" "*.object-meta.xml"
    scan_section "Validation Rules"   "objects" "*.validationRule-meta.xml"
    ;;
  layouts)
    scan_section "Layouts" "layouts" "*.layout-meta.xml"
    ;;
  workflows)
    scan_section "Workflow Rules"   "workflows" "*.workflow-meta.xml"
    scan_section "Field Updates"    "workflows" "*.fieldUpdate-meta.xml"
    ;;
  flexipages)
    scan_section "Flexipages" "flexipages" "*.flexipage-meta.xml"
    ;;
  reports)
    scan_section "Reports"    "reports"    "*.report-meta.xml"
    scan_section "Dashboards" "dashboards" "*.dashboard-meta.xml"
    ;;
  all)
    scan_section "Apex Classes"       "classes"    "*.cls"
    scan_section "Apex Triggers"      "triggers"   "*.trigger"
    scan_section "Flows"              "flows"      "*.flow-meta.xml"
    scan_section "Custom Fields"      "objects"    "*.field-meta.xml"
    scan_section "Custom Objects"     "objects"    "*.object-meta.xml"
    scan_section "Validation Rules"   "objects"    "*.validationRule-meta.xml"
    scan_section "Layouts"            "layouts"    "*.layout-meta.xml"
    scan_section "Workflow Rules"     "workflows"  "*.workflow-meta.xml"
    scan_section "Flexipages"         "flexipages" "*.flexipage-meta.xml"
    scan_section "Reports"            "reports"    "*.report-meta.xml"
    scan_section "Dashboards"         "dashboards" "*.dashboard-meta.xml"
    scan_section "Custom Metadata"    "customMetadata" "*.md-meta.xml"
    ;;
  *)
    echo "Unknown scope: $SCOPE"
    echo "Valid scopes: apex, flows, objects, layouts, workflows, flexipages, reports, all, discover, summary"
    exit 1
    ;;
esac

echo ""
echo "Scan complete."
