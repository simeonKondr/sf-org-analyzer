# BloomreachAWR — Complete Audit Findings

**Org:** BloomreachAWR (Sandbox)
**Analysis scope:** All automations, fields, Apex, Flows, Layouts, CPQ configuration
that reference Product Family, Product Pillar, and values Engagement, Discovery,
Content, Clarity, SEO, Services.
**Status:** Sections 1–14 complete. Section 15 (Reports & Dashboards) pending.

---

## Product Pillar Values

| Legacy Code | Human Name | Pillar | Status |
|---|---|---|---|
| brSM | Discovery | Discovery | Active |
| brXM | Content | Content | Active |
| brEX | Engagement | Engagement | Active |
| Clarity | Clarity | Clarity | Active |
| brSEO | SEO | SEO | Partially retired (CD-004625, June 2024) |
| Services | Services | Services → delegates to Services_Product_Family__c | Active |

**Root source:** `Product2.Family` (standard picklist).
All classification derives from here. Every formula, Apex class, flow, and
roll-up in this document depends on this field.

---

## Field Inventory

### Product2
| Field | Type | Notes |
|---|---|---|
| Family | Picklist (standard) | Root source of all classification |
| Product_Pillar__c | Formula (Text) | Maps Family → pillar name. brEX→Engagement, brXM→Content, brSM→Discovery, Clarity→Clarity, brSEO→SEO, Services→Services_Product_Family__c value |
| Services_Product_Family__c | Picklist | Sub-classification for Services family products |

### PricebookEntry
| Field | Type | Notes |
|---|---|---|
| Product_Family__c | Formula (Text) | CASE mapping: brEX→Engagement, brSM→Discovery, brXM→Content; else TEXT(Family). Bridge from Product2 to OLI. |

### OpportunityLineItem
| Field | Type | Notes |
|---|---|---|
| Product_Family__c | Formula (Text) | From PricebookEntry.Product_Family__c. Key field for ARR aggregations. |
| Product_Pillar_Text__c | Text (30) | Written by workflow rules. Feeds native roll-up summaries. |
| Product_Family_TEXT__c | Text | Written by workflow rules. Feeds Opportunity roll-up summaries. |
| Product_Pillar_From_Product_Object__c | Formula (Text) | Cross-object: PricebookEntry.Product2.Product_Pillar__c. Used in email templates. |
| Product_Family_Services__c | Formula (Text) | Derives services pillar. Maps brSM→Discovery, brXM→Content, brEX→Engagement. |
| Termination_Product_Family__c | Formula (Text) | Splits Content into 'Content SaaS' or 'Content PaaS/On-Prem' via DeliveryType__c. |

### Opportunity (key fields)
| Field | Type | Status | Notes |
|---|---|---|---|
| Product_Families__c | Text | ACTIVE | Semicolon-delimited string of all Product2.Family from CPQ Quote Lines. Master field. Written by flow. |
| Product_Families_S1__c | Text | ACTIVE | Snapshot of Product_Families__c at Stage 1 |
| Product_Families_S2__c | Text | ACTIVE | Snapshot at Stage 2 (overwritten each save) |
| Product_Families_S2_Initial__c | Text | ACTIVE | **IMMUTABLE** first-time Stage 2 snapshot via $Record__Prior |
| ARR_Content__c | Currency | ACTIVE | Written by Apex AND Flow — double-write issue |
| ARR_Discovery__c | Currency | ACTIVE | Written by Apex AND Flow — double-write issue |
| ARR_Engagement_Subscription__c | Currency | ACTIVE | Written by Apex AND Flow — double-write issue |
| ARR_Engagement_Services__c | Currency | ACTIVE | Written by Apex AND Flow |
| ARR_Engagement_Total__c | Currency | ACTIVE | Sum of Engagement sub + services. Flow only. |
| ARR_Y1_Engagement__c | Currency | ACTIVE | Year-1 Engagement. Apex only (Group_Year__c = 1). |
| ARR_Y1_Discovery__c | Currency | ACTIVE | Year-1 Discovery. Apex only. |
| ARR_Y1_Content__c | Currency | ACTIVE | Year-1 Content. Apex only. |
| ARR_Y1_Clarity__c | Currency | ACTIVE | Year-1 Clarity. Apex only. **NO total ARR_Clarity__c exists.** |
| ARR_Renewal_Base_Engagement__c | Currency | ACTIVE | Written by SubscriptionArrCalculator Apex |
| ARR_Renewal_Base_Discovery__c | Currency | ACTIVE | Written by SubscriptionArrCalculator Apex |
| ARR_Renewal_Base_Content__c | Currency | ACTIVE | Written by SubscriptionArrCalculator Apex |
| ARR_Renewal_Base_Clarity__c | Currency | ACTIVE | Written by SubscriptionArrCalculator Apex |
| Products_Count_Discovery__c | Roll-up | ACTIVE | COUNT OLIs where Product_Pillar_Text__c = Discovery |
| Products_Count_Content__c | Roll-up | ACTIVE | COUNT OLIs where Product_Pillar_Text__c = Content |
| Products_Count_Engagement__c | Roll-up | ACTIVE | COUNT OLIs where Product_Pillar_Text__c = Engagement |
| Start_Date_Engagement__c | Date | ACTIVE | rh2 MIN date from specific Engagement SKUs |
| End_Date_Engagement__c | Date | ACTIVE | rh2 MAX date from specific Engagement SKUs |
| Product_Pillar__c | Formula | DEPRECATED | Still live. Formula rolls up from Products_Count_* fields. |
| Opportunity_Product_Family__c | Formula | DEPRECATED | Still live. Derives from Account ARR fields. |
| Product_Family_Group__c | Formula | DEPRECATED | Still live. Builds combo strings like "Discovery & Content". |

### SBQQ__Quote__c — ORPHANED fields
| Field | Description Says | Actual Current Writer |
|---|---|---|
| ARR_Content__c | "Updated from Price Rule: Q: Update ARR Fields by Summary Variable: ARR Content" | **NOTHING — orphaned** |
| ARR_Discovery__c | Same — different Summary Variable | **NOTHING — orphaned** |
| ARR_Engagement_Subscription__c | Same | **NOTHING — orphaned** |
| ARR_Engagement_Services__c | Same | **NOTHING — orphaned** |
| ARR_Engagement__c | "Updated from Price Rule: Q: Update Quote Fields" | **NOTHING — orphaned** |

These fields have no writer. The `Update_Opportunity_Fields_From_Quote` flow
reads them and pushes zero/null to Opportunity ARR fields on every Quote save.

---

## Apex Classes

### OpportunityLineItemTriggerHandler
**Trigger:** after insert/update/delete on OpportunityLineItem
**What it does:** Recalculates per-pillar ARR on parent Opportunity.

```
'Engagement' → ARR_Engagement_Subscription__c, ARR_Y1_Engagement__c
               (if Services category: also ARR_Engagement_Services__c)
'Discovery'  → ARR_Discovery__c, ARR_Y1_Discovery__c
'Content'    → ARR_Content__c, ARR_Y1_Content__c
'Clarity'    → ARR_Y1_Clarity__c ONLY (no total ARR field — gap)
```

**Gap:** Clarity has no `ARR_Clarity__c` total field equivalent.

### SubscriptionArrCalculator
**Called by:** `Opportunity - New Renewal Opportunity` flow (invocable) + nightly scheduled batch
**What it does:** Reads `SBQQ__Subscription__c.Product_Line_ARR_Total__c`, takes
the highest `Group_Year__c` (last year of expiring contract), routes to:

```
'Clarity'    → ARR_Renewal_Base_Clarity__c
'Content'    → ARR_Renewal_Base_Content__c
'Discovery'  → ARR_Renewal_Base_Discovery__c
'Engagement' → ARR_Renewal_Base_Engagement__c
```

Also: `SubscriptionArrCalculatorSchedulable` — daily job wrapping above.

### AccountArrCalculator
**Path:** CPQ subscription path → Account per-pillar ARR fields
**Mapping:** Engagement→ARR_active_Engagement, Discovery→ARR_Personalization__c,
Content→ARR_Experience__c, Clarity→ARR_active_Clarity__c

### AccountNonCPQCalculator
**Path:** Non-CPQ OLI path → Account ARR_active_*_Non_CPQ__c fields
**Handles Content sub-types:** Content - SaaS, Content - BrXM, Content → all map to ARR_active_Content_Non_CPQ__c

### AccountTriggerHandler
Queries Opportunities where `Product_Pillar__c = 'Discovery'` + Account revenue < $100M
→ routing via `Opportunity_S0_S2_Highest_priority__mdt` custom metadata

### MultipleOpportunityTechController
Groups OLIs by `Product_Family__c` → creates `Opportunity_Technology__c` records per pillar

### CustomerTerminationCaseCreationInvocable
Groups OLIs by `Termination_Product_Family__c` → creates Case per pillar → sets `Case.Pillar__c`

### PreProcessQuoteData
**InvocableMethod.** Creates `QuoteLineGroupSummary__c` and `CPQ_Summary_View__c` for Quote
document display. Groups by `ProductCategory__c` (Communications, Services, Platform, Capacity)
— **NOT Product Family/Pillar.** Used for approval page and quote document display only.

---

## Active Flows (pillar/family relevant)

| Flow | Trigger | Key Logic |
|---|---|---|
| Update Opportunity Product Fields from QL | SBQQ__Quote after update (Primary=true) | Loops QLs → reads Product2.Family → builds semicolon string → writes Product_Families__c |
| Update Opportunity Fields From Quote | SBQQ__Quote after update | Copies Quote ARR fields → Opportunity ARR. **BLOCKED if Finance_Reviewed__c=true. SOURCE FIELDS ARE ORPHANED.** |
| Set Product Families | Opportunity before-save | Stamps S1/S2 snapshots on stage advance. S2_Initial uses $Record__Prior (IMMUTABLE). |
| Opportunity - New Renewal Opportunity | Opportunity after-create (Renewal=true) | Calls SubscriptionArrCalculator. Builds opp name from Product_Families__c. |
| Opportunity ARR Stamp at S2 | Opportunity before-save | Stamps ARR_at_S2__c on first Stage 2 entry |
| Create_new_Customer_Termination_Request_screenflow | Screen flow | Loops OLIs by Termination_Product_Family__c → sets Case.Pillar__c |
| Case_Customer_Termination_Decomissioning_Notifications | Case | Routes by Case.Pillar__c: Discovery→engineering email, Content→escalation email |
| Engagement_New_Project_Assign | Screen flow | Surfaces Product_Pillar__c in screen + Slack |
| Opportunity_Booked_Slack_Message | Opportunity | Routes CS team by Product_Family_Services__c. Emoji: 💛 Engagement, 💙 Discovery, 🤍 Content |
| Contact_Set_Operational_Persona | Contact | Manages BR Discovery/Engagement/Content User persona labels |

---

## Workflow Rules (legacy, on OLI)

- Product Family TEXT variants (3 rules) → write `Product_Family_TEXT__c`
- Opportunity Product Pillar Text → writes `Product_Pillar_Text__c` (feeds roll-up summaries)
- Opportunity Stage 2 - Engagement Pillar → stage logic

---

## CPQ Audit Results

**All CPQ rule objects are EMPTY:**

| Object | Records | Conclusion |
|---|---|---|
| SBQQ__PriceRule__c | 0 | No Price Rules — deleted |
| SBQQ__PriceAction__c | 0 | Consistent with no Price Rules |
| SBQQ__PriceCondition__c | 0 | Consistent with no Price Rules |
| SBQQ__SummaryVariable__c | 0 | Deleted — these populated Quote ARR fields |
| SBQQ__ProductRule__c | 0 | No Product Rules |
| SBQQ__ErrorCondition__c | 0 | No Error Conditions |
| SBQQ__ConfigurationRule__c | 0 | No Configuration Rules |
| SBQQ__CustomScript__c | 0 | No JavaScript calculators |
| SBQQ__LookupQuery__c | 0 | No Lookup Tables |
| SBQQ__CustomAction__c | 36 | All standard CPQ UI buttons |
| QuoteCalculatorPlugin | None | No custom Apex implements it |

---

## Dependency Chain — Primary ARR Path

```
Product2.Family (standard picklist)
  │
  ├─► PricebookEntry.Product_Family__c [FORMULA CASE]
  │     → OpportunityLineItem.Product_Family__c [FORMULA]
  │
  │   [CPQ PATH — Product_Families__c]
  │   Flow: Update_Opportunity_Product_Fields_from_QL
  │         → Opportunity.Product_Families__c (semicolon string)
  │               → Set_Product_Families flow [BEFORE-SAVE]
  │                     → Product_Families_S1__c / S2__c / S2_Initial__c
  │
  │   [CPQ ARR PATH — currently broken]
  │   Quote.ARR_Content/Discovery/Engagement__c ← NO WRITER (orphaned)
  │         ↓
  │   Flow: Update_Opportunity_Fields_From_Quote
  │         (BLOCKED if Finance_Reviewed__c = true)
  │         → Opportunity.ARR_Content/Discovery/Engagement__c ← ZERO
  │
  │   [NON-CPQ / LEGACY OLI PATH — actually working]
  │   Apex: OpportunityLineItemTriggerHandler
  │         'Engagement' → ARR_Engagement_Subscription__c + ARR_Y1_Engagement__c
  │         'Discovery'  → ARR_Discovery__c + ARR_Y1_Discovery__c
  │         'Content'    → ARR_Content__c + ARR_Y1_Content__c
  │         'Clarity'    → ARR_Y1_Clarity__c ONLY (gap: no total ARR field)
  │
  └─► [RENEWAL BASE PATH]
        SBQQ__Subscription__c.Product_Line_ARR_Total__c [FORMULA]
        = IF(ISBLANK(ARR_Override__c),
              IF(Revenue_Type__c='Recurring', SBQQ__NetTotal__c/Expected_Term__c*12, 0),
              ARR_Override__c)
        ↓
        Apex: SubscriptionArrCalculator (invocable + nightly batch)
              'Clarity'    → ARR_Renewal_Base_Clarity__c
              'Content'    → ARR_Renewal_Base_Content__c
              'Discovery'  → ARR_Renewal_Base_Discovery__c
              'Engagement' → ARR_Renewal_Base_Engagement__c
```

---

## Layouts & UI Exposure

- **11 Page Layouts** include pillar/family fields
- **4 Lightning Pages (Flexipages)** display Product_Pillar__c or Customer_Product_Family__c
- **12 List Views** filter by Product_Pillar__c (4 Product2 views + 7+ Account views)

---

## Reports & Dashboards — Raw Data (analysis pending)

### Recently-run reports referencing pillar/family (last 90 days, name-based)
- Q425 US/EMEA New S1/S2 Opps all Pillars (folder: 2023/2024)
- NB & CS Product Pillar Win Rate QoQ (Shopify Dashboard Reports)
- All Customer Termination Cases by Pillar (Customer Termination Case Reports)
- Q425_NB+CS_S2/S1/S0 Opps_Clarity + Q425_UP_Pipe_Clarity (multiple Clarity-specific)
- Customer Accounts ARR (By Pillar/Region) (Public Reports)
- South EMEA - Customers by pillar (EMEA Solenn)
- Accts with Discovery ARR by Acct Health (Sales Dashboard Reports)
- ARR Fields for Quote Lines - DD (DealDesk Reports) ← reads orphaned Quote ARR fields
- Discovery Opps Team Individual - Boyd (SC SA Reports)
- S0-S2 CVR_Clarity_NB+CS (Marketing KPI Reports 2023)
- Current Quarter - Clarity Opps / Clarity Pipe (Exec KPI sheet)
- Churned Discovery Customers This FY
- Q223 New Pipe -Upsell- all pillars / New Pipe Engagement/Discovery (historical, still run)

### Active dashboards referencing pillar/family
- Q425 US Clarity Dashboard (Global Dashboards, Oct 2025)
- Q325 US Clarity Dashboard (Global Dashboards)
- Clarity Dashboard (Customer Growth Dashboards)
- Copy of Clarity Program (Clarity Reporting)
- Discovery KPIs (Product Team Dashboards)
- Engagement KPIs (Product Team Dashboards)
- Discovery Business Dashboard (Product Team Dashboards)
- Customer ARR Dash (Finance + Sales Dashboards)
- Pillar CMO's Dash - Engagement (Marketing Dashboards)
- Content Pillar: Open Opportunities (Archived Dashboards)
- EMEA Engagement Account Management DASH
- Engagement Enterprise Performance Dashboard
- Deeto Engagement Dashboard / Base Metrics / Win Rates / Won-Lost (Deeto Dashboards)
- Experience SC Team Dashboard - Discovery KPIs (SC SA Dashboards)
- AMER Presales Dashboard - Discovery (SC SA Dashboards)
- Engagement Customers Dashboard / Discovery Customers Dashboard / Content Customers Dashboard (Sales)

**NEXT STEP:** Fetch Tooling API metadata for each report to get actual field names
used in columns and filters. Cross-reference with `DashboardComponent` to map
dashboard widgets to source reports.

---

## rh2 Rollup Helper (UI-configured, not SOQL-queryable)

- `Start_Date_Engagement__c` — MIN start date from specific Engagement SKUs
- `End_Date_Engagement__c` — MAX end date from specific Engagement SKUs
- `Products_Count_Do_Not_Book__c` — COUNT of do-not-book OLIs (drives validation rule)
- `Products_Count_Last_Modified_Date__c` — MAX(LastModifiedDate), triggers rh2 re-runs
