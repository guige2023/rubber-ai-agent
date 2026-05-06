# Deliverable Template

Use this as a compact output blueprint. Adapt headings and labels to the user's requested language.

```md
# Apple Search Ads Keyword Research Report

**App**: [App Name]
**App ID**: [App ID]
**Target Market**: [CC]
**Category**: [Category]
**Report Date**: [YYYY-MM-DD]

## 1. Product And Pricing

| Field | Value |
| :--- | :--- |
| Primary Recurring SKU | [Weekly/Monthly/Annual] |
| Price | [price] |
| Excluded SKUs | [trial/intro/lifetime/non-primary recurring SKUs] |
| Apple Fee Scenarios | 15%, 30% |

## 2. ROI And Target CPA

Show the full calculation path for every scenario.

| Scenario | Apple Fee | Price | Total Payments | Install-to-Paid Rate | Net LTV | BreakEven CPA | Realization Factor | Safety Margin | Target CPA |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Conservative | [15/30%] | [price] | [x] | [%] | [value] | [value] | 0.9 | 0.7 | [value] |
| Realistic | [15/30%] | [price] | [x] | [%] | [value] | [value] | 0.9 | 0.7 | [value] |
| Optimistic | [15/30%] | [price] | [x] | [%] | [value] | [value] | 0.9 | 0.7 | [value] |

## 3. Evidence Summary

| Evidence Type | Result |
| :--- | :--- |
| App Store search seeds | [seed list] |
| Top rivals analyzed with QiMai | [app names / IDs] |
| Suggestion seeds analyzed | [seed list] |
| Real Search Popularity keyword count | [count] |
| Suggestion-only keyword count | [count] |

## 4. Keyword Matrix

No star ratings. `search_popularity` is QiMai native 0-100 only. `suggestion_rank` is a single best rank or `N/A`.

| Tier | Keyword | Match Type | search_popularity | suggestion_rank | Intent | Target CPA | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Brand | [keyword] | Exact | [0-100 or N/A] | [rank or N/A] | [intent] | [value] | [source apps/seeds] |
| Generic | [keyword] | Exact | [0-100 or N/A] | [rank or N/A] | [intent] | [value] | [source apps/seeds] |
| Competitor | [keyword] | Exact | [0-100 or N/A] | [rank or N/A] | [intent] | [value] | [source apps/seeds] |
| Discovery | [keyword] | Broad | [0-100 or N/A] | [rank or N/A] | [intent] | [value] | [source apps/seeds] |

## 5. Campaign Structure

### Campaign: [Brand]
- **Ad Group**: [ad_group_name]
- **Match Type**: Exact
- **Copy-paste Keywords**: `[keyword_1], [keyword_2]`
- **Search Match**: false
- **Target CPA**: [value]

### Campaign: [Generic]
- **Ad Group**: [ad_group_name]
- **Match Type**: Exact
- **Copy-paste Keywords**: `[keyword_1], [keyword_2]`
- **Search Match**: false
- **Target CPA**: [value]

### Campaign: [Competitor]
- **Ad Group**: [ad_group_name]
- **Match Type**: Exact
- **Copy-paste Keywords**: `[keyword_1], [keyword_2]`
- **Search Match**: false
- **Target CPA**: [value]

### Campaign: [Discovery]
- **Ad Group**: Discovery_Broad
- **Match Type**: Broad
- **Copy-paste Keywords**: `keyword_1, keyword_2`
- **Search Match**: false
- **Target CPA**: [value]

## 6. Negatives

| Scope | Negative Keyword | Match Type | Copy-paste Form | Reason |
| :--- | :--- | :--- | :--- | :--- |
| Account | [keyword] | Broad | keyword | [reason] |
| Campaign | [keyword] | Exact | [keyword] | [reason] |

## 7. CSV Contract

`asa-keywords-*.csv` must include:

`row_type`, `campaign_name`, `ad_group_name`, `keyword`, `match_type`, `negative_keyword`, `negative_match_type`, `negative_scope`, `search_match_enabled`, `country_or_region`, `search_popularity`, `suggestion_rank`, `intent`, `competitor_tier`, `target_cpa`, `daily_budget`, `notes`
```
