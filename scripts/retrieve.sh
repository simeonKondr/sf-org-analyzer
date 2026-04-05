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

# Ensure tools installed outside /usr/bin are reachable
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/local/lib/sf/bin:$PATH"

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
    "ActionLinkGroupTemplate"
    "AnalyticSnapshot"
    "ApexClass"
    "ApexComponent"
    "ApexPage"
    "ApexTestSuite"
    "ApexTrigger"
    "AppMenu"
    "ApprovalProcess"
    "AssignmentRule"
    "AssignmentRules"
    "Audience"
    "AuraDefinitionBundle"
    "AuthProvider"
    "AutoResponseRule"
    "AutoResponseRules"
    "BrandingSet"
    "BusinessProcess"
    "CMSConnectSource"
    "CallCenter"
    "CaseSubjectParticle"
    "Certificate"
    "ChannelLayout"
    "ChatterExtension"
    "CleanDataService"
    "Community"
    "CommunityTemplateDefinition"
    "CommunityThemeDefinition"
    "CompactLayout"
    "ConnectedApp"
    "ContentAsset"
    "CorsWhitelistOrigin"
    "CspTrustedSite"
    "CustomApplication"
    "CustomApplicationComponent"
    "CustomFeedFilter"
    "CustomField"
    "CustomLabel"
    "CustomLabels"
    "CustomMetadata"
    "CustomObject"
    "CustomObjectTranslation"
    "CustomPageWebLink"
    "CustomPermission"
    "CustomSite"
    "CustomTab"
    "Dashboard"
    "DataCategoryGroup"
    "DelegateGroup"
    "Document"
    "DuplicateRule"
    "EclairGeoData"
    "EmailServicesFunction"
    "EmailTemplate"
    "EmbeddedServiceBranding"
    "EmbeddedServiceConfig"
    "EmbeddedServiceFieldService"
    "EscalationRule"
    "EscalationRules"
    "EventDelivery"
    "EventSubscription"
    "ExternalDataSource"
    "ExternalServiceRegistration"
    "FieldSet"
    "FlexiPage"
    "Flow"
    "FlowCategory"
    "FlowDefinition"
    "GlobalValueSet"
    "GlobalValueSetTranslation"
    "Group"
    "HomePageComponent"
    "HomePageLayout"
    "Index"
    "InstalledPackage"
    "Layout"
    "LeadConvertSettings"
    "Letterhead"
    "LightningBolt"
    "LightningComponentBundle"
    "LightningExperienceTheme"
    "ListView"
    "MatchingRule"
    "MatchingRules"
    "ModerationRule"
    "NamedCredential"
    "Network"
    "NetworkBranding"
    "PathAssistant"
    "PermissionSet"
    "PlatformCachePartition"
    "PostTemplate"
    "Profile"
    "ProfilePasswordPolicy"
    "ProfileSessionSetting"
    "Queue"
    "QuickAction"
    "RecordType"
    "RemoteSiteSetting"
    "Report"
    "ReportType"
    "Role"
    "SamlSsoConfig"
    "Scontrol"
    "SharingCriteriaRule"
    "SharingOwnerRule"
    "SharingReason"
    "SharingRules"
    "SharingSet"
    "SiteDotCom"
    "StandardValueSet"
    "StandardValueSetTranslation"
    "StaticResource"
    "SynonymDictionary"
    "TopicsForObjects"
    "TransactionSecurityPolicy"
    "UserCriteria"
    "ValidationRule"
    "WebLink"
    "Workflow"
    "WorkflowAlert"
    "WorkflowFieldUpdate"
    "WorkflowKnowledgePublish"
    "WorkflowOutboundMessage"
    "WorkflowRule"
    "WorkflowSend"
    "WorkflowTask"
    "Settings"
  )

  echo "  Retrieving ${#METADATA_TYPES[@]} metadata types..."

  # Build --metadata flags — one per type (sf CLI does not accept comma-joined string)
  METADATA_FLAGS=()
  for t in "${METADATA_TYPES[@]}"; do
    METADATA_FLAGS+=(--metadata "$t")
  done

  # Use if/else so set -e doesn't abort on partial retrieve failures
  if ! sf project retrieve start \
    --target-org "$ALIAS" \
    "${METADATA_FLAGS[@]}" \
    --output-dir "$OUTPUT_DIR" \
    --ignore-conflicts \
    2>&1 | tee /tmp/retrieve-meta-log.txt; then
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

  # Build compact cache index for token-efficient analysis
  echo ""
  bash scripts/index.sh
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
    # Strip sf CLI wrapper + per-record attributes — store only the records array
    local count
    count=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('totalSize',0))" 2>/dev/null || echo "?")
    echo "$result" | python3 -c "
import sys,json
d=json.load(sys.stdin)
records=d.get('result',{}).get('records',[])
for r in records: r.pop('attributes',None)
print(json.dumps(records))
" 2>/dev/null > "$filepath" || echo '[]' > "$filepath"
    echo " $count records"
  else
    # Object doesn't exist in this org (not a CPQ org, or different version)
    echo '[]' > "$filepath"
    echo " skipped (object not available)"
  fi
}

retrieve_cpq_data() {
  echo ""
  echo "Phase 2: Exporting CPQ record data to $DATA_DIR/..."
  echo ""

  mkdir -p "$DATA_DIR"

  # ── Field discovery helper ───────────────────────────────────────────────────
  # Returns space-separated list of fields that actually exist on an object.
  # Usage: FIELDS=$(discover_fields "SBQQ__PriceRule__c" "SBQQ__Active__c SBQQ__EvaluationEvent__c")
  discover_fields() {
    local obj="$1"
    shift
    local candidates=("$@")
    local valid_fields="Id Name"

    # Get field list from EntityDefinition via sf data query
    local describe_result
    describe_result=$(sf data query \
      --query "SELECT QualifiedApiName FROM FieldDefinition WHERE EntityDefinition.QualifiedApiName = '$obj' AND QualifiedApiName IN ('$(IFS="','"; echo "${candidates[*]}")')" \
      --target-org "$ALIAS" \
      --json 2>/dev/null || echo '{"result":{"records":[]}}')

    local found
    found=$(echo "$describe_result" | python3 -c "
import sys, json
d = json.load(sys.stdin)
fields = [r['QualifiedApiName'] for r in d.get('result', {}).get('records', [])]
print(' '.join(fields))
" 2>/dev/null || echo "")

    echo "$valid_fields $found"
  }

  # ── Safe query builder ───────────────────────────────────────────────────────
  # Builds a SELECT from only fields that exist on the object.
  # Falls back to "SELECT Id, Name" if field discovery fails entirely.
  export_query_safe() {
    local label="$1"
    local filename="$2"
    local obj="$3"
    local where_clause="${4:-}"
    local order_clause="${5:-}"
    local limit_clause="${6:-LIMIT 500}"
    shift 6
    local candidate_fields=("$@")

    # Discover which candidate fields exist
    local valid_fields
    valid_fields=$(discover_fields "$obj" "${candidate_fields[@]}" 2>/dev/null || echo "Id Name")

    # Build field list (deduplicate Id/Name)
    local field_list
    field_list=$(echo "Id Name $valid_fields" | tr ' ' '\n' | awk '!seen[$0]++' | grep -v '^$' | tr '\n' ',' | sed 's/,$//')

    # Build query
    local query="SELECT $field_list FROM $obj"
    [ -n "$where_clause" ] && query="$query WHERE $where_clause"
    [ -n "$order_clause" ] && query="$query ORDER BY $order_clause"
    query="$query $limit_clause"

    export_query "$label" "$filename" "$query"
  }

  # ── CPQ installed check ──────────────────────────────────────────────────────
  # Quick count check — SELECT COUNT() always works if the object exists
  echo "  [ CPQ installed? ]"
  cpq_check=$(sf data query \
    --query "SELECT COUNT() FROM SBQQ__PriceRule__c" \
    --target-org "$ALIAS" \
    --json 2>/dev/null | python3 -c "import sys,json; print('yes')" 2>/dev/null || echo "no")

  if [ "$cpq_check" != "yes" ]; then
    echo "  CPQ not installed or not accessible — skipping CPQ queries"
    echo '{"cpq_installed":false}' > "$DATA_DIR/cpq-status.json"
    return
  fi

  echo '{"cpq_installed":true}' > "$DATA_DIR/cpq-status.json"

  # ── CPQ Settings ─────────────────────────────────────────────────────────────
  echo ""
  echo "  [ CPQ Settings ]"

  # General settings — discover plugin fields first
  export_query_safe \
    "General Settings (plugin registrations)" \
    "general-settings.json" \
    "SBQQ__GeneralSettings__c" \
    "" "" "LIMIT 1" \
    SBQQ__CalculatorPlugin__c \
    SBQQ__QuoteCalculatorPlugin__c \
    SBQQ__ProductSearchPlugin__c \
    SBQQ__DocumentStore__c \
    SBQQ__LineEditorPlugin__c \
    SBQQ__OrderProductPlugin__c \
    SBQQ__ContractingPlugin__c

  # ── Price Rules ──────────────────────────────────────────────────────────────
  echo ""
  echo "  [ Price Rules ]"

  # Always-safe: COUNT only
  export_query "Price Rules (count)" "price-rules-count.json" \
    "SELECT COUNT() FROM SBQQ__PriceRule__c"

  export_query_safe \
    "Price Rules" \
    "price-rules.json" \
    "SBQQ__PriceRule__c" \
    "" "SBQQ__EvaluationOrder__c" "LIMIT 500" \
    SBQQ__Active__c \
    SBQQ__EvaluationEvent__c \
    SBQQ__EvaluationOrder__c \
    SBQQ__TargetObject__c \
    SBQQ__ConditionsMet__c \
    SBQQ__LookupObject__c \
    LastModifiedDate

  export_query_safe \
    "Price Conditions" \
    "price-conditions.json" \
    "SBQQ__PriceCondition__c" \
    "" "" "LIMIT 2000" \
    SBQQ__Rule__c \
    SBQQ__TestedField__c \
    SBQQ__TestedVariable__c \
    SBQQ__Operator__c \
    SBQQ__FilterValue__c \
    SBQQ__FilterType__c \
    SBQQ__Index__c

  export_query_safe \
    "Price Actions" \
    "price-actions.json" \
    "SBQQ__PriceAction__c" \
    "" "" "LIMIT 2000" \
    SBQQ__Rule__c \
    SBQQ__TargetField__c \
    SBQQ__TargetObject__c \
    SBQQ__Type__c \
    SBQQ__ValueType__c \
    SBQQ__Value__c \
    SBQQ__SourceVariable__c \
    SBQQ__Index__c

  # ── Summary Variables ─────────────────────────────────────────────────────────
  echo ""
  echo "  [ Summary Variables ]"

  export_query "Summary Variables (count)" "summary-variables-count.json" \
    "SELECT COUNT() FROM SBQQ__SummaryVariable__c"

  export_query_safe \
    "Summary Variables" \
    "summary-variables.json" \
    "SBQQ__SummaryVariable__c" \
    "" "Name" "LIMIT 500" \
    SBQQ__Object__c \
    SBQQ__Field__c \
    SBQQ__Type__c \
    SBQQ__FilterField__c \
    SBQQ__FilterOperator__c \
    SBQQ__FilterValue__c \
    SBQQ__ConditionsMet__c

  # ── Product Rules ─────────────────────────────────────────────────────────────
  echo ""
  echo "  [ Product Rules ]"

  export_query "Product Rules (count)" "product-rules-count.json" \
    "SELECT COUNT() FROM SBQQ__ProductRule__c"

  export_query_safe \
    "Product Rules" \
    "product-rules.json" \
    "SBQQ__ProductRule__c" \
    "" "" "LIMIT 500" \
    SBQQ__Active__c \
    SBQQ__Type__c \
    SBQQ__Scope__c \
    SBQQ__ConditionsMet__c \
    SBQQ__EvaluationEvent__c \
    SBQQ__EvaluationOrder__c \
    SBQQ__ErrorMessage__c \
    LastModifiedDate

  export_query_safe \
    "Error Conditions" \
    "error-conditions.json" \
    "SBQQ__ErrorCondition__c" \
    "" "" "LIMIT 2000" \
    SBQQ__Rule__c \
    SBQQ__TestedField__c \
    SBQQ__Operator__c \
    SBQQ__FilterValue__c \
    SBQQ__FilterType__c \
    SBQQ__Index__c

  export_query_safe \
    "Configuration Rules" \
    "configuration-rules.json" \
    "SBQQ__ConfigurationRule__c" \
    "" "Name" "LIMIT 500" \
    SBQQ__Active__c \
    SBQQ__Product__c \
    SBQQ__ConditionsMet__c

  # ── Custom Scripts & Actions ──────────────────────────────────────────────────
  echo ""
  echo "  [ Custom Scripts & Actions ]"

  export_query "Custom Scripts (count)" "custom-scripts-count.json" \
    "SELECT COUNT() FROM SBQQ__CustomScript__c"

  export_query_safe \
    "Custom Scripts" \
    "custom-scripts.json" \
    "SBQQ__CustomScript__c" \
    "" "Name" "LIMIT 100" \
    SBQQ__Code__c \
    SBQQ__ApiVersion__c \
    LastModifiedDate

  export_query_safe \
    "Custom Actions" \
    "custom-actions.json" \
    "SBQQ__CustomAction__c" \
    "" "" "LIMIT 200" \
    SBQQ__Type__c \
    SBQQ__Label__c \
    SBQQ__Location__c \
    SBQQ__DisplayOrder__c \
    SBQQ__Active__c \
    SBQQ__ConditionsMet__c \
    SBQQ__HandlerClass__c \
    SBQQ__URL__c

  export_query_safe \
    "Custom Action Conditions" \
    "custom-action-conditions.json" \
    "SBQQ__CustomActionCondition__c" \
    "" "" "LIMIT 2000" \
    SBQQ__Action__c \
    SBQQ__FilterField__c \
    SBQQ__FilterOperator__c \
    SBQQ__FilterValue__c \
    SBQQ__Index__c

  # ── Lookup Tables ─────────────────────────────────────────────────────────────
  echo ""
  echo "  [ Lookup Tables ]"

  export_query_safe \
    "Lookup Queries" \
    "lookup-queries.json" \
    "SBQQ__LookupQuery__c" \
    "" "Name" "LIMIT 500" \
    SBQQ__Object__c \
    SBQQ__MatchField__c \
    SBQQ__ResultField__c \
    SBQQ__DefaultField__c \
    SBQQ__PriceRule__c

  export_query "Lookup Data" "lookup-data.json" \
    "SELECT Id, Name FROM SBQQ__LookupData__c ORDER BY Name LIMIT 500"

  # ── Calculator Referenced Fields ──────────────────────────────────────────────
  echo ""
  echo "  [ Calculator Configuration ]"

  export_query_safe \
    "Calculator Referenced Fields" \
    "calculator-referenced-fields.json" \
    "SBQQ__CalculatorReferencedField__c" \
    "" "" "LIMIT 500" \
    SBQQ__FieldName__c \
    SBQQ__ObjectName__c

  # ── Product Catalog ───────────────────────────────────────────────────────────
  # Standard fields only — custom fields discovered dynamically from metadata XML
  echo ""
  echo "  [ Product Catalog ]"

  # Step 1: always-safe aggregate — no custom fields
  export_query \
    "Products by Family (counts)" \
    "products-all-families.json" \
    "SELECT Family, COUNT(Id) cnt
     FROM Product2
     WHERE Family != null
     GROUP BY Family
     ORDER BY cnt DESC"

  # Step 2: discover custom fields on Product2 from retrieved metadata XML
  echo "  Discovering Product2 custom fields from metadata..."
  PRODUCT2_CUSTOM_FIELDS=$(find metadata/ -path "*/Product2/*.field-meta.xml" \
    -exec basename {} .field-meta.xml \; 2>/dev/null | tr '\n' ' ' || echo "")

  export_query_safe \
    "Active Products with Family" \
    "products-active.json" \
    "Product2" \
    "IsActive = true" "Family, Name" "LIMIT 2000" \
    ProductCode \
    Family \
    IsActive \
    LastModifiedDate \
    $PRODUCT2_CUSTOM_FIELDS

  # ── CPQ Schema samples — discover fields from metadata before querying ─────────
  echo ""
  echo "  [ CPQ object samples — field-discovered ]"

  # Quote Line: discover custom fields from metadata
  QL_CUSTOM_FIELDS=$(find metadata/ -path "*/SBQQ__QuoteLine__c/*.field-meta.xml" \
    -exec basename {} .field-meta.xml \; 2>/dev/null | tr '\n' ' ' || echo "")

  export_query_safe \
    "Quote Line sample (5 recent)" \
    "quote-line-sample.json" \
    "SBQQ__QuoteLine__c" \
    "" "LastModifiedDate DESC" "LIMIT 5" \
    SBQQ__ProductFamily__c \
    SBQQ__Product__c \
    $QL_CUSTOM_FIELDS

  # Quote: discover custom fields from metadata, then check for non-zero ARR fields
  QUOTE_CUSTOM_FIELDS=$(find metadata/ -path "*/SBQQ__Quote__c/*.field-meta.xml" \
    -exec basename {} .field-meta.xml \; 2>/dev/null | tr '\n' ' ' || echo "")

  # Identify ARR fields specifically (to build WHERE clause)
  QUOTE_ARR_FIELDS=$(find metadata/ -path "*/SBQQ__Quote__c/*.field-meta.xml" \
    -exec basename {} .field-meta.xml \; 2>/dev/null \
    | grep -i "^ARR_" | tr '\n' ' ' || echo "")

  if [ -n "$QUOTE_ARR_FIELDS" ]; then
    # Build a WHERE clause checking if any ARR field is non-zero
    QUOTE_WHERE=$(echo "$QUOTE_ARR_FIELDS" | tr ' ' '\n' | grep -v '^$' \
      | awk '{print "("$1" != null AND "$1" != 0)"}' \
      | paste -sd ' OR ' -)
    export_query_safe \
      "Quotes with non-zero ARR fields (sample)" \
      "quote-arr-sample.json" \
      "SBQQ__Quote__c" \
      "$QUOTE_WHERE" "LastModifiedDate DESC" "LIMIT 10" \
      SBQQ__Opportunity2__c \
      $QUOTE_ARR_FIELDS
  else
    # No ARR fields found — just get recent quotes
    export_query "Recent Quotes (no ARR fields found)" "quote-arr-sample.json" \
      "SELECT Id, Name, LastModifiedDate FROM SBQQ__Quote__c ORDER BY LastModifiedDate DESC LIMIT 10"
  fi

  # Subscription: discover custom fields, use safe standard fields for GROUP BY
  SUB_CUSTOM_FIELDS=$(find metadata/ -path "*/SBQQ__Subscription__c/*.field-meta.xml" \
    -exec basename {} .field-meta.xml \; 2>/dev/null | tr '\n' ' ' || echo "")

  # Check if Product_Line_ARR_Total__c exists before using in aggregate
  if echo "$SUB_CUSTOM_FIELDS" | grep -q "Product_Line_ARR_Total__c"; then
    export_query \
      "Subscription ARR by product family" \
      "subscription-arr-by-family.json" \
      "SELECT SBQQ__Product__r.Family, COUNT(Id) cnt, SUM(Product_Line_ARR_Total__c) total_arr
       FROM SBQQ__Subscription__c
       WHERE SBQQ__TerminatedDate__c = null AND SBQQ__Product__r.Family != null
       GROUP BY SBQQ__Product__r.Family
       ORDER BY total_arr DESC"
  else
    export_query \
      "Subscription count by product family" \
      "subscription-arr-by-family.json" \
      "SELECT SBQQ__Product__r.Family, COUNT(Id) cnt
       FROM SBQQ__Subscription__c
       WHERE SBQQ__TerminatedDate__c = null AND SBQQ__Product__r.Family != null
       GROUP BY SBQQ__Product__r.Family
       ORDER BY cnt DESC"
  fi

  # Opportunity: discover ARR custom fields from metadata
  OPP_CUSTOM_FIELDS=$(find metadata/ -path "*/Opportunity/*.field-meta.xml" \
    -exec basename {} .field-meta.xml \; 2>/dev/null | tr '\n' ' ' || echo "")

  OPP_ARR_FIELDS=$(find metadata/ -path "*/Opportunity/*.field-meta.xml" \
    -exec basename {} .field-meta.xml \; 2>/dev/null \
    | grep -iE "^ARR_|^Product_Famil" | tr '\n' ' ' || echo "")

  if [ -n "$OPP_ARR_FIELDS" ]; then
    OPP_WHERE=$(echo "$OPP_ARR_FIELDS" | tr ' ' '\n' | grep -v '^$' \
      | awk '{print $1" > 0"}' \
      | paste -sd ' OR ' -)
    export_query_safe \
      "Open Opps with ARR by pillar (sample)" \
      "opportunity-arr-sample.json" \
      "Opportunity" \
      "IsClosed = false AND ($OPP_WHERE)" "LastModifiedDate DESC" "LIMIT 20" \
      Name \
      StageName \
      $OPP_ARR_FIELDS
  else
    export_query "Recent open Opportunities" "opportunity-arr-sample.json" \
      "SELECT Id, Name, StageName, LastModifiedDate FROM Opportunity WHERE IsClosed = false ORDER BY LastModifiedDate DESC LIMIT 20"
  fi

  # ── Reports & Dashboards ──────────────────────────────────────────────────────
  # These use only standard fields — always safe
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

  # ── Scheduled Jobs ────────────────────────────────────────────────────────────
  # Standard object — always safe
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
