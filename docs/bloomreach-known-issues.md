# BloomreachAWR — Known Issues & Recommendations

Priority order. Address top issues first.

---

## 🔴 CRITICAL — Orphaned Quote ARR Fields

**What:** `SBQQ__Quote__c.ARR_Content__c`, `ARR_Discovery__c`, `ARR_Engagement__c`,
`ARR_Engagement_Subscription__c`, `ARR_Engagement_Services__c` have no current writer.
The CPQ Price Rules and Summary Variables that populated them were deleted.

**Impact:** The `Update_Opportunity_Fields_From_Quote` flow reads these fields and
pushes them to Opportunity ARR fields on every CPQ Quote save. Because the Quote
fields are zero/null, this flow is overwriting correctly-calculated Opportunity ARR
(from the OLI Apex path) with zeros for all CPQ deals.

**Three remediation options:**

1. **Recommended — rewrite flow to aggregate from Quote Lines directly:**
   Modify `Update_Opportunity_Fields_From_Quote` to loop through Quote Lines and
   SUM `Product_Line_ARR_Total__c` grouped by `Product_Family__c` (Engagement/
   Discovery/Content/Clarity). Eliminates the orphaned intermediate Quote fields.
   This is what `PreProcessQuoteData` Apex already does for `ProductCategory__c`.

2. **Restore CPQ Price Rules:**
   Recreate `Q: Update ARR Fields` Price Rule with Summary Variables that aggregate
   `Product_Line_ARR_Total__c` by `Product2.Family` across Quote Lines.
   Re-populates Quote ARR fields so the existing flow works correctly.
   Higher maintenance burden.

3. **Apex Calculator Plugin:**
   Implement `SBQQ.QuoteCalculatorPlugin` in Apex, write pillar ARR to Quote
   fields in `onAfterCalculate`. Most flexible, highest complexity.

**Interim guard (apply immediately while permanent fix is designed):**
Add a condition to `Update_Opportunity_Fields_From_Quote` flow:
only copy a Quote ARR field to Opportunity if the Quote value is NOT null and > 0.
This prevents the flow from zeroing out values that Apex correctly computed.

---

## 🔴 HIGH — Double-Write on Opportunity ARR Fields

**What:** `ARR_Content__c`, `ARR_Discovery__c`, `ARR_Engagement_Subscription__c`,
`ARR_Engagement_Services__c` are written by two independent automations with no
mutual exclusion:
1. `OpportunityLineItemTriggerHandler` Apex — fires on every OLI change
2. `Update_Opportunity_Fields_From_Quote` Flow — fires on every CPQ Quote save

**Impact:** On a CPQ deal, if a user makes a manual OLI change after a Quote sync,
Apex overwrites the Quote-computed values. Order of execution is unpredictable.

**Recommendation:** Add a check in `OpportunityLineItemTriggerHandler` to detect
whether the parent Opportunity has a Primary CPQ Quote (`SBQQ__PrimaryQuote__c`).
If yes, skip Apex ARR writes and defer to the CPQ flow path.

```apex
// In rollupArr() method — add at top:
if (opp.SBQQ__PrimaryQuote__c != null) {
    return; // CPQ flow handles ARR for CPQ deals
}
```

---

## 🔴 HIGH — Clarity Missing from Total ARR Rollup

**What:** `ARR_Y1_Clarity__c` is written by Apex (Y1 path).
`ARR_Renewal_Base_Clarity__c` is written by SubscriptionArrCalculator.
But `ARR_Clarity__c` (total ARR) **does not exist**.

**Impact:** All Clarity deals report zero in total ARR by pillar.
Any report or dashboard showing ARR by pillar excludes Clarity from totals.

**Recommendation:**
1. Create `ARR_Clarity__c` Currency field on Opportunity
2. Add to `OpportunityLineItemTriggerHandler.rollupArr()`:
   ```apex
   } else if (item.Product_Family__c == 'Clarity') {
       opp.ARR_Clarity__c += ARR / term * 12;
   }
   ```
3. Add to `Update_Opportunity_Fields_From_Quote` flow field assignments
4. Add to CPQ Summary Variables (or to the rewritten flow from Issue #1)

---

## 🟡 MEDIUM — Finance_Reviewed Gate Creates Silent Inconsistency

**What:** `Update_Opportunity_Fields_From_Quote` flow is skipped when
`Finance_Reviewed__c = true` on the Opportunity. But `OpportunityLineItemTriggerHandler`
Apex still fires on any OLI change regardless of lock status.

**Impact:** On finance-locked Opportunities, if a Quote is modified, the flow
won't push updated ARR. But if an OLI is touched (even minor edit), Apex will
recalculate and overwrite ARR — potentially with different values than the
finance-reviewed Quote.

**Recommendation:** Add notification/validation: when a Quote ARR changes on an
Opportunity with `Finance_Reviewed__c = true`, surface an alert to the user
rather than silently skipping the write.

---

## 🟡 MEDIUM — Product_Families__c is a Freeform Semicolon String

**What:** Built by concatenation in `Update_Opportunity_Product_Fields_from_QL`
flow. No deduplication. Exact-match SOQL queries fail; CONTAINS() works.

**Impact:** Any flow, Apex, or report that tries to filter with `=` against
`Product_Families__c` will return no results even for exact matches.

**Recommendation:** Document this constraint clearly. Do not use EqualTo operator
against this field in flows or reports. Use `CONTAINS()` in formulas and
`LIKE '%value%'` in SOQL.

---

## 🟢 LOW — Partial SEO Removal

**What:** `brSEO` was removed from `Opportunity.Product_Pillar__c` formula
(CD-004625, June 2024) but remains in `Product2.Product_Pillar__c` formula.

**Impact:** Active brSEO products still receive the SEO pillar at the product
level but won't aggregate to the deprecated Opportunity formula. Low impact
since the Opp formula is deprecated anyway.

**Recommendation:** When fully retiring brSEO products, remove from Product2
formula too. No immediate action required.

---

## 🟢 LOW — Three Deprecated Formula Fields Still Live

**What:** These three fields are labeled "Deprecated" in their descriptions
but remain active formula fields on Opportunity:
- `Product_Pillar__c`
- `Opportunity_Product_Family__c`
- `Product_Family_Group__c`

**Impact:** Consume formula compute on every Opportunity save.
May be used in undocumented reports or external integrations.

**Recommendation:**
1. Search metadata for any remaining references (reports, flows, Apex, layouts)
2. Once confirmed unused, deactivate the formulas first (set to blank formula)
3. After a safety period, delete the fields

---

## Completed — No Action Needed

- CPQ Custom Scripts: none exist, none needed
- CPQ Product Rules: none exist (intentional — product configuration not used)
- CPQ Calculator Plugin: not implemented (intentional)
- rh2 rollup configurations: correctly configured, no issues found
