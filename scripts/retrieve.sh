#!/usr/bin/env bash
# retrieve.sh — pull all metadata AND CPQ record data from a Salesforce org
#
# Two phases:
#   Phase 1 — sf project retrieve  (XML metadata: Apex, Flows, Objects, Layouts...)
#   Phase 2 — sf data query        (CPQ records exported to JSON in ./data/cpq/)
#
# Usage:
#   bash scripts/retrieve.sh                  # uses default org
#   bash scripts/retrieve.sh MyOrgAlias       # uses specified alias
#   bash scripts/retrieve.sh MyOrgAlias meta  # metadata only
#   bash scripts/retrieve.sh MyOrgAlias cpq   # CPQ data only
#   bash scripts/retrieve.sh MyOrgAlias all   # both (default)
#
# Requires: @salesforce/cli (sf command)

set -euo pipefail

ALIAS="${1:-}"
MODE="${2:-all}"   # meta | cpq | all
OUTPUT_DIR="./metadata"
DATA_DIR="./data/cpq"
TIMESTAMP_FILE="$OUTPUT_DIR/.retrieved_at"

# ── Resolve org ───────────────────────────────────────────────────────────────
if [ -z "$ALIAS" ]; then
  if [ -f "CLAUDE.md" ]; then
    ALIAS=$(grep -oP '(?<=Alias:\s{0,10})\S+' CLAUDE.md | head -1 || true)
  fi
fi

if [ -z "$ALIAS" ]; then
  echo "ERROR: No org alias provided and none found in CLAUDE.md"
  echo "Usage: bash scripts/retrieve.sh <OrgAlias> [meta|cpq|all]"
  exit 1
fi

echo "──────────────────────────────────────────────"
echo "Org:    $ALIAS"
echo "Mode:   $MODE  (meta=XML metadata, cpq=record data, all=both)"
echo "──────────────────────────────────────────────"

# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — XML METADATA RETRIEVE
# ═════════════════════════════════════════════════════════════════════════════

retrieve_metadata() {
  echo ""
  echo "Phase 1: Retrieving XML metadata..."
  echo ""

  mkdir -p "$OUTPUT_DIR"

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

  METADATA_STRING=$(IFS=','; echo "${METADATA_TYPES[*]}")

  echo "  Retrieving ${#METADATA_TYPES[@]} metadata types..."

  sf project retrieve start \
    --target-org "$ALIAS" \
    --metadata "$METADATA_STRING" \
    --output-dir "$OUTPUT_DIR" \
    --ignore-conflicts \
    2>&1 | tee /tmp/retrieve-meta-log.txt

  RETRIEVE_EXIT=${PIPESTATUS[0]}
  if [ $RETRIEVE_EXIT -ne 0 ]; then
    echo "  ⚠  Some metadata types unavailable — continuing with what was retrieved."
  fi

  echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') from $ALIAS" > "$TIMESTAMP_FILE"

  echo ""
  echo "  Metadata summary:"
  printf "    %-28s %s\n" "Apex classes"      "$(find $OUTPUT_DIR -name '*.cls' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Apex triggers"     "$(find $OUTPUT_DIR -name '*.trigger' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Flows"             "$(find $OUTPUT_DIR -name '*.flow-meta.xml' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Custom fields"     "$(find $OUTPUT_DIR -name '*.field-meta.xml' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Layouts"           "$(find $OUTPUT_DIR -name '*.layout-meta.xml' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Validation rules"  "$(find $OUTPUT_DIR -name '*.validationRule-meta.xml' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Workflow rules"    "$(find $OUTPUT_DIR -name '*.workflow-meta.xml' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Flexipages"        "$(find $OUTPUT_DIR -name '*.flexipage-meta.xml' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Reports"           "$(find $OUTPUT_DIR -name '*.report-meta.xml' 2>/dev/null | wc -l | tr -d ' ') files"
  printf "    %-28s %s\n" "Dashboards"        "$(find $OUTPUT_DIR -name '*.dashboard-meta.xml' 2>/dev/null | wc -l | tr -d ' ') files"
  echo "    Total size: $(du -sh $OUTPUT_DIR 2>/dev/null | cut -f1)"
  echo ""
  echo "  ✅ Metadata complete — $(cat $TIMESTAMP_FILE)"
}

# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — CPQ RECORD DATA EXPORT
#  Exports all CPQ configuration records to local JSON so analysis
#  never needs live SOQL callouts for structural CPQ questions.
# ═════════════════════════════════════════════════════════════════════════════

# Helper: run SOQL and save to file; silently skip if object doesn't exist
export_query() {
  local label="$1"
  local filename="$2"
  local query="$3"
  local use_tooling="${4:-false}"

  local filepath="$DATA_DIR/$filename"
  local tooling_flag=""
  [ "$use_tooling" = "true" ] && tooling_flag="--use-tooling-api"

  printf "  %-50s" "$label..."

  # Run query, capture exit code
  local result
  if result=$(sf data query \
      --query "$query" \
      --target-org "$ALIAS" \
      $tooling_flag \
      --json 2>&1); then
    echo "$result" > "$filepath"
    local count
    count=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('totalSize',0))" 2>/dev/null || echo "?")
    echo " $count records"
  else
    # Object doesn't exist in this org (not a CPQ org, or different version)
    echo '{"status":0,"result":{"totalSize":0,"done":true,"records":[]}}' > "$filepath"
    echo " skipped (object not available)"
  fi
}

retrieve_cpq_data() {
  echo ""
  echo "Phase 2: Exporting CPQ record data to $DATA_DIR/..."
  echo ""

  mkdir -p "$DATA_DIR"

  # ── CPQ Settings ────────────────────────────────────────────────────────────
  echo "  [ CPQ Settings ]"

  export_query \
    "General Settings (plugin registrations)" \
    "general-settings.json" \
    "SELECT Id, SBQQ__CalculatorPlugin__c, SBQQ__QuoteCalculatorPlugin__c,
            SBQQ__ProductSearchPlugin__c, SBQQ__DocumentStore__c,
            SBQQ__LineEditorPlugin__c, SBQQ__OrderProductPlugin__c,
            SBQQ__ContractingPlugin__c
     FROM SBQQ__GeneralSettings__c
     LIMIT 1"

  # ── Price Rules ─────────────────────────────────────────────────────────────
  echo ""
  echo "  [ Price Rules ]"

  export_query \
    "Price Rules" \
    "price-rules.json" \
    "SELECT Id, Name, SBQQ__Active__c, SBQQ__EvaluationEvent__c,
            SBQQ__EvaluationOrder__c, SBQQ__TargetObject__c,
            SBQQ__ConditionsMet__c, SBQQ__LookupObject__c,
            SBQQ__LookupProductFamily__c, LastModifiedDate
     FROM SBQQ__PriceRule__c
     ORDER BY SBQQ__EvaluationOrder__c
     LIMIT 500"

  export_query \
    "Price Conditions" \
    "price-conditions.json" \
    "SELECT Id, Name, SBQQ__Rule__c, SBQQ__Rule__r.Name,
            SBQQ__TestedField__c, SBQQ__TestedVariable__c,
            SBQQ__Operator__c, SBQQ__FilterValue__c,
            SBQQ__FilterType__c, SBQQ__Index__c
     FROM SBQQ__PriceCondition__c
     ORDER BY SBQQ__Rule__c, SBQQ__Index__c
     LIMIT 2000"

  export_query \
    "Price Actions" \
    "price-actions.json" \
    "SELECT Id, Name, SBQQ__Rule__c, SBQQ__Rule__r.Name,
            SBQQ__TargetField__c, SBQQ__TargetObject__c,
            SBQQ__Type__c, SBQQ__ValueType__c,
            SBQQ__Value__c, SBQQ__SourceVariable__c,
            SBQQ__SourceVariableName__c, SBQQ__Index__c
     FROM SBQQ__PriceAction__c
     ORDER BY SBQQ__Rule__c, SBQQ__Index__c
     LIMIT 2000"

  # ── Summary Variables ───────────────────────────────────────────────────────
  echo ""
  echo "  [ Summary Variables ]"

  export_query \
    "Summary Variables" \
    "summary-variables.json" \
    "SELECT Id, Name, SBQQ__Object__c, SBQQ__Field__c,
            SBQQ__Type__c, SBQQ__FilterField__c,
            SBQQ__FilterOperator__c, SBQQ__FilterValue__c,
            SBQQ__ConditionsMet__c
     FROM SBQQ__SummaryVariable__c
     ORDER BY Name
     LIMIT 500"

  # ── Product Rules ───────────────────────────────────────────────────────────
  echo ""
  echo "  [ Product Rules ]"

  export_query \
    "Product Rules" \
    "product-rules.json" \
    "SELECT Id, Name, SBQQ__Active__c, SBQQ__Type__c,
            SBQQ__Scope__c, SBQQ__ConditionsMet__c,
            SBQQ__EvaluationEvent__c, SBQQ__EvaluationOrder__c,
            SBQQ__ErrorMessage__c, LastModifiedDate
     FROM SBQQ__ProductRule__c
     ORDER BY SBQQ__EvaluationOrder__c
     LIMIT 500"

  export_query \
    "Error Conditions" \
    "error-conditions.json" \
    "SELECT Id, Name, SBQQ__Rule__c, SBQQ__Rule__r.Name,
            SBQQ__TestedField__c, SBQQ__Operator__c,
            SBQQ__FilterValue__c, SBQQ__FilterType__c, SBQQ__Index__c
     FROM SBQQ__ErrorCondition__c
     ORDER BY SBQQ__Rule__c, SBQQ__Index__c
     LIMIT 2000"

  export_query \
    "Configuration Rules" \
    "configuration-rules.json" \
    "SELECT Id, Name, SBQQ__Active__c, SBQQ__Product__c,
            SBQQ__Product__r.Name, SBQQ__Product__r.Family,
            SBQQ__ConditionsMet__c
     FROM SBQQ__ConfigurationRule__c
     ORDER BY Name
     LIMIT 500"

  # ── Custom Scripts ──────────────────────────────────────────────────────────
  echo ""
  echo "  [ Custom Scripts & Actions ]"

  export_query \
    "Custom Scripts" \
    "custom-scripts.json" \
    "SELECT Id, Name, SBQQ__Code__c, SBQQ__ApiVersion__c,
            LastModifiedDate, LastModifiedBy.Name
     FROM SBQQ__CustomScript__c
     ORDER BY Name
     LIMIT 100"

  export_query \
    "Custom Actions" \
    "custom-actions.json" \
    "SELECT Id, Name, SBQQ__Type__c, SBQQ__Label__c,
            SBQQ__Location__c, SBQQ__DisplayOrder__c,
            SBQQ__Active__c, SBQQ__ConditionsMet__c,
            SBQQ__HandlerClass__c, SBQQ__URL__c
     FROM SBQQ__CustomAction__c
     ORDER BY SBQQ__DisplayOrder__c
     LIMIT 200"

  export_query \
    "Custom Action Conditions" \
    "custom-action-conditions.json" \
    "SELECT Id, Name, SBQQ__Action__c, SBQQ__Action__r.Name,
            SBQQ__FilterField__c, SBQQ__FilterOperator__c,
            SBQQ__FilterValue__c, SBQQ__Index__c
     FROM SBQQ__CustomActionCondition__c
     ORDER BY SBQQ__Action__c, SBQQ__Index__c
     LIMIT 2000"

  # ── Lookup Tables ───────────────────────────────────────────────────────────
  echo ""
  echo "  [ Lookup Tables ]"

  export_query \
    "Lookup Queries" \
    "lookup-queries.json" \
    "SELECT Id, Name, SBQQ__Object__c, SBQQ__MatchField__c,
            SBQQ__ResultField__c, SBQQ__DefaultField__c,
            SBQQ__PriceRule__c, SBQQ__PriceRule__r.Name
     FROM SBQQ__LookupQuery__c
     ORDER BY Name
     LIMIT 500"

  export_query \
    "Lookup Data" \
    "lookup-data.json" \
    "SELECT Id, Name FROM SBQQ__LookupData__c
     ORDER BY Name LIMIT 500"

  # ── Calculator Referenced Fields ────────────────────────────────────────────
  echo ""
  echo "  [ Calculator Configuration ]"

  export_query \
    "Calculator Referenced Fields" \
    "calculator-referenced-fields.json" \
    "SELECT Id, Name, SBQQ__FieldName__c, SBQQ__ObjectName__c
     FROM SBQQ__CalculatorReferencedField__c
     ORDER BY SBQQ__ObjectName__c, SBQQ__FieldName__c
     LIMIT 500"

  # ── Product Configuration ───────────────────────────────────────────────────
  echo ""
  echo "  [ Product Catalog ]"

  export_query \
    "Products with Family (active)" \
    "products-active.json" \
    "SELECT Id, Name, ProductCode, Family,
            Product_Pillar__c, Services_Product_Family__c,
            Revenue_Type__c, Product_Category__c,
            IsActive, LastModifiedDate
     FROM Product2
     WHERE IsActive = true
     ORDER BY Family, Name
     LIMIT 2000"

  export_query \
    "Products with Family (all)" \
    "products-all-families.json" \
    "SELECT Family, COUNT(Id) cnt
     FROM Product2
     WHERE Family != null
     GROUP BY Family
     ORDER BY cnt DESC"

  # ── Quote Line Fields (key custom fields) ───────────────────────────────────
  echo ""
  echo "  [ CPQ Schema — Quote Line custom field sample ]"

  export_query \
    "Quote Line field sample (5 recent)" \
    "quote-line-sample.json" \
    "SELECT Id, SBQQ__ProductFamily__c, Product_Line_ARR_Total__c,
            ARR_Override__c, Revenue_Type__c, Expected_Term__c,
            ProductCategory__c, ProductSubCategory__c,
            Group_Year__c, SBQQ__Product__r.Family,
            SBQQ__Product__r.Product_Pillar__c
     FROM SBQQ__QuoteLine__c
     ORDER BY LastModifiedDate DESC
     LIMIT 5"

  # ── Quote ARR Fields (orphaned field check) ─────────────────────────────────
  echo ""
  echo "  [ Quote ARR field audit ]"

  export_query \
    "Quotes with non-zero pillar ARR (sample)" \
    "quote-arr-sample.json" \
    "SELECT Id, SBQQ__Opportunity2__r.Name,
            ARR_Content__c, ARR_Discovery__c,
            ARR_Engagement__c, ARR_Engagement_Subscription__c,
            ARR_Engagement_Services__c,
            LastModifiedDate
     FROM SBQQ__Quote__c
     WHERE (ARR_Content__c != null AND ARR_Content__c != 0)
        OR (ARR_Discovery__c != null AND ARR_Discovery__c != 0)
        OR (ARR_Engagement__c != null AND ARR_Engagement__c != 0)
     ORDER BY LastModifiedDate DESC
     LIMIT 10"

  # ── Subscription ARR (renewal base source of truth) ────────────────────────
  echo ""
  echo "  [ Subscriptions ]"

  export_query \
    "Subscription ARR by product family" \
    "subscription-arr-by-family.json" \
    "SELECT SBQQ__Product__r.Family, COUNT(Id) cnt,
            SUM(Product_Line_ARR_Total__c) total_arr
     FROM SBQQ__Subscription__c
     WHERE SBQQ__TerminatedDate__c = null
       AND SBQQ__Product__r.Family != null
     GROUP BY SBQQ__Product__r.Family
     ORDER BY total_arr DESC"

  # ── Opportunity ARR data quality ────────────────────────────────────────────
  echo ""
  echo "  [ Opportunity ARR data quality ]"

  export_query \
    "Open opps with ARR by pillar (sample)" \
    "opportunity-arr-sample.json" \
    "SELECT Id, Name, StageName,
            ARR_Content__c, ARR_Discovery__c,
            ARR_Engagement_Subscription__c, ARR_Engagement_Services__c,
            ARR_Y1_Clarity__c, ARR_Renewal_Base_Content__c,
            ARR_Renewal_Base_Discovery__c, ARR_Renewal_Base_Engagement__c,
            ARR_Renewal_Base_Clarity__c, Product_Families__c,
            LastModifiedDate
     FROM Opportunity
     WHERE IsClosed = false
       AND (ARR_Content__c > 0 OR ARR_Discovery__c > 0
            OR ARR_Engagement_Subscription__c > 0 OR ARR_Y1_Clarity__c > 0)
     ORDER BY LastModifiedDate DESC
     LIMIT 20"

  # ── Active reports (last 90 days) ───────────────────────────────────────────
  echo ""
  echo "  [ Reports & Dashboards ]"

  export_query \
    "Reports run in last 90 days" \
    "reports-active.json" \
    "SELECT Id, Name, DeveloperName, LastRunDate, FolderName, Format
     FROM Report
     WHERE LastRunDate > LAST_N_DAYS:90
     ORDER BY LastRunDate DESC
     LIMIT 500"

  export_query \
    "Dashboards (all)" \
    "dashboards.json" \
    "SELECT Id, Title, DeveloperName, LastModifiedDate, FolderName
     FROM Dashboard
     ORDER BY LastModifiedDate DESC
     LIMIT 500"

  # ── Scheduled jobs ──────────────────────────────────────────────────────────
  echo ""
  echo "  [ Scheduled Jobs ]"

  export_query \
    "Active scheduled jobs" \
    "scheduled-jobs.json" \
    "SELECT Id, CronJobDetail.Name, CronExpression, State,
            NextFireTime, PreviousFireTime, TimesTriggered
     FROM CronTrigger
     WHERE State = 'WAITING'
     ORDER BY NextFireTime"

  # ── Write CPQ timestamp ──────────────────────────────────────────────────────
  echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') from $ALIAS" > "$DATA_DIR/.retrieved_at"

  echo ""
  echo "  Total CPQ data size: $(du -sh $DATA_DIR 2>/dev/null | cut -f1)"
  echo ""
  echo "  ✅ CPQ data complete — $(cat $DATA_DIR/.retrieved_at)"
}

# ═════════════════════════════════════════════════════════════════════════════
#  RUN
# ═════════════════════════════════════════════════════════════════════════════

case "$MODE" in
  meta)
    retrieve_metadata
    ;;
  cpq)
    retrieve_cpq_data
    ;;
  all)
    retrieve_metadata
    retrieve_cpq_data
    ;;
  *)
    echo "Unknown mode: $MODE. Valid: meta | cpq | all"
    exit 1
    ;;
esac

echo ""
echo "──────────────────────────────────────────────"
echo "Retrieval complete. Run /analyze to start."
echo "──────────────────────────────────────────────"
