# /runtime

Runs live SOQL queries against the org for runtime data that metadata cannot provide.

**Usage:**
```
/runtime Which reports referencing Product Pillar were run in the last 90 days
/runtime Are any CPQ Price Rules or Summary Variables configured
/runtime What scheduled jobs are currently active
/runtime Show me the field description for ARR_Content__c on SBQQ__Quote__c
/runtime How many active Subscriptions exist per product family
```

---

## Instructions for Claude

The user's runtime question is: **$ARGUMENTS**

Determine the minimal set of SOQL queries needed to answer the question.
Run them via the Salesforce MCP server (salesforce-dx:run_soql_query).

Do NOT run broad exploratory queries. Be targeted.

### Common runtime queries — use as needed

**CPQ rule objects — are they configured?**
```sql
SELECT COUNT() FROM SBQQ__PriceRule__c
SELECT COUNT() FROM SBQQ__SummaryVariable__c
SELECT COUNT() FROM SBQQ__CustomScript__c
SELECT COUNT() FROM SBQQ__ProductRule__c
SELECT COUNT() FROM SBQQ__ConfigurationRule__c
SELECT COUNT() FROM SBQQ__ErrorCondition__c
```

**Recently run reports**
```sql
SELECT Id, Name, LastRunDate, FolderName, Format
FROM Report
WHERE LastRunDate > LAST_N_DAYS:90
ORDER BY LastRunDate DESC
LIMIT 100
```

**Reports matching a pattern**
```sql
SELECT Id, Name, LastRunDate, FolderName
FROM Report
WHERE (Name LIKE '%Pillar%' OR Name LIKE '%Product Family%' OR Name LIKE '%ARR%')
  AND LastRunDate != null
ORDER BY LastRunDate DESC
```

**Dashboards matching a pattern**
```sql
SELECT Id, Title, LastModifiedDate, FolderName
FROM Dashboard
WHERE Title LIKE '%Pillar%' OR Title LIKE '%Discovery%' OR Title LIKE '%ARR%'
ORDER BY LastModifiedDate DESC
```

**Active scheduled jobs**
```sql
SELECT Id, CronJobDetail.Name, CronExpression, State, 
       NextFireTime, PreviousFireTime, TimesTriggered
FROM CronTrigger
WHERE State = 'WAITING'
ORDER BY NextFireTime
```

**Custom field description — orphaned field detection (Tooling API)**
```sql
SELECT Id, DeveloperName, Metadata
FROM CustomField
WHERE Id = 'FIELD_ID_HERE'
```
Note: Tooling API only returns Metadata for one record at a time.

**Product families in use**
```sql
SELECT Family, COUNT(Id) cnt
FROM Product2
WHERE IsActive = true AND Family != null
GROUP BY Family
ORDER BY cnt DESC
```

**Subscriptions by product family**
```sql
SELECT SBQQ__Product__r.Family, COUNT(Id) cnt
FROM SBQQ__Subscription__c
WHERE SBQQ__TerminatedDate__c = null
GROUP BY SBQQ__Product__r.Family
ORDER BY cnt DESC
```

**Opportunity ARR by pillar — data quality check**
```sql
SELECT COUNT_DISTINCT(Id) total,
       COUNT_DISTINCT(CASE WHEN ARR_Content__c > 0 THEN Id END) has_content,
       COUNT_DISTINCT(CASE WHEN ARR_Discovery__c > 0 THEN Id END) has_discovery,
       COUNT_DISTINCT(CASE WHEN ARR_Engagement_Subscription__c > 0 THEN Id END) has_engagement
FROM Opportunity
WHERE IsClosed = false AND StageName LIKE '6%'
```

---

## Output format

Present runtime results in a clean table where possible.
Always note the query timestamp and whether results look complete or truncated.
Cross-reference with metadata findings if relevant — e.g. "This report uses
ARR_Content__c which is an orphaned field (see Issue #7 in the analysis)."
