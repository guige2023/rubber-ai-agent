# Deliverable Template

Use the following Markdown structures as the blueprint for your output.
Adapt the headings and labels to match the user's requested language.

## Strategy Report

```md
# Apple Search Ads (ASA) Keyword Research Report

**App Name**: [App Name]
**Target Country/Region**: [Country]
**Report Date**: [YYYY-MM-DD]

---

## 1. Product Profile

- **Core Function**: [Core functionality]
- **Value Proposition**: [Value props]
- **Target Audience**: [User personas]
- **Main Subscription Price**: [e.g., $9.99/Year]

## 2. ROI & Target CPI/CPP Calculation

_Subscription trial funnel assumptions: tap-to-install CVR, install-to-trial-start CVR, trial-to-paid CVR, average paid renewals, Apple tax, and refund/churn buffer._

- **Net Revenue per Paid Subscriber**: [Price] × 0.85 = [Value]
- **Paid Subscriber LTV**: [Net Revenue] × [Renewals] × [Buffer] = [Value]
- **Target CPP**: [Break-even CPP] × 0.8 = **[Value]**
- **Target CPI**: [Target CPP] × [Install-to-paid CVR] = **[Value]**
- **Suggested Max CPT**: [Target CPI] × [Tap-to-install CVR] = **[Value]**

## 3. Keyword Matrix

### Competitor Candidate Evidence

| Candidate App | Seller | Appearance Count | Matched Seeds | Best Rank | Rating Count | Feature Similarity | Brand Strength | Competitor Score | Tier | Tier Reason |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| [app] | [seller] | [count] | [seed_1, seed_2] | [rank] | [count] | [0-100] | [0-100] | [0-100] | [Direct/Adjacent/Incumbent/Negative] | [reason] |

### 🏆 Brand

| Keyword   | Normalized Popularity | Raw Popularity | Source | Intent   | Suggested CPT | Target CPI | Target CPP |
| :-------- | :-------------------- | :------------- | :----- | :------- | :------------ | :--------- | :--------- |
| [keyword] | [0-100]               | [raw]          | [src]  | [intent] | [cpt]         | [cpi]      | [cpp]      |

### 🎯 Generic

| Keyword   | Normalized Popularity | Raw Popularity | Source | Competition | Suggested CPT | Target CPI | Target CPP |
| :-------- | :-------------------- | :------------- | :----- | :---------- | :------------ | :--------- | :--------- |
| [keyword] | [0-100]               | [raw]          | [src]  | [comp]      | [cpt]         | [cpi]      | [cpp]      |

### ⚔️ Competitor

| Competitor Name | Tier | Keyword   | Normalized Popularity | Source | Suggested CPT | Target CPI | Target CPP |
| :-------------- | :--- | :-------- | :-------------------- | :----- | :------------ | :--------- | :--------- |
| [comp_name]     | [tier] | [keyword] | [0-100]               | [src]  | [cpt]         | [cpi]      | [cpp]      |

## 4. Campaign Strategy

> Default Architecture: Exact Match is the primary budget driver; Broad Match is only used for Discovery; Search Match is only a low-budget experiment when explicitly requested.
>
> **Important Formatting Rule for Keywords**: For Exact Match, wrap each keyword in brackets and separate them with commas (e.g., `[keyword1], [keyword2]`). For Broad Match, omit the brackets (e.g., `keyword1, keyword2`). This ensures they can be copy-pasted directly into the ASA console.

### 📂 Campaign: [Brand - Defense]

**Strategy**: Lock in 100% Share of Voice, bid high, protect brand assets.

| Ad Group      | Match Type | Search Match Enabled | Keywords                   | Suggested CPT | Target CPI | Target CPP |
| :------------ | :--------- | :------------------- | :------------------------- | :------------ | :--------- | :--------- |
| `Brand_Exact` | Exact      | false                | [[keyword_1], [keyword_2]] | [cpt]         | [cpi]      | [cpp]      |

### 📂 Campaign: [Generic]

**Strategy**: Group by semantic function (Cluster) to adjust bids per feature.

| Ad Group (Cluster) | Match Type | Search Match Enabled | Keywords                   | Suggested CPT | Target CPI | Target CPP |
| :----------------- | :--------- | :------------------- | :------------------------- | :------------ | :--------- | :--------- |
| `[Cluster_Name_1]` | Exact      | false                | [[keyword_1], [keyword_2]] | [cpt]         | [cpi]      | [cpp]      |
| `[Cluster_Name_2]` | Exact      | false                | [[keyword_3], [keyword_4]] | [cpt]         | [cpi]      | [cpp]      |

### 📂 Campaign: [Competitor - Conquesting]

**Strategy**: Target direct competitors to siphon brand traffic, closely monitor CPA.

| Ad Group            | Match Type | Search Match Enabled | Keywords                       | Suggested CPT | Target CPI | Target CPP |
| :------------------ | :--------- | :------------------- | :----------------------------- | :------------ | :--------- | :--------- |
| `[Competitor_Name]` | Exact      | false                | [[comp_word_1], [comp_word_2]] | [cpt]         | [cpi]      | [cpp]      |

### 📂 Campaign: [Discovery]

**Strategy**: **[Search Match disabled by default]**. Find long-tail commercial keywords via broad match on core seeds. Must be paired with strict negative keywords.

| Ad Group          | Match Type | Search Match Enabled | Keywords                 | Suggested CPT | Target CPI | Target CPP |
| :---------------- | :--------- | :------------------- | :----------------------- | :------------ | :--------- | :--------- |
| `Discovery_Broad` | Broad      | false                | core_seed_1, core_seed_2 | [cpt]         | [cpi]      | [cpp]      |

## 5. Negative Keyword Matrix

### 5.1 Global/Account-Level Negatives (Negative Broad)
Blocks obvious irrelevant intent across all campaigns.

**Copy-paste (Broad)**:
`negative_word_1, negative_word_2, negative_word_3`

| Negative Keyword | Match Type | Reason |
| :--- | :--- | :--- |
| [negative_word_1] | Broad | [reason] |

### 5.2 Campaign-Level Negatives
Prevents Discovery campaign from matching exact terms already targeted in Exact campaigns, or blocks specific terms at campaign level.

**Copy-paste (Exact)**:
`[[exact_word_1], [exact_word_2], [exact_word_3]]`

| Campaign | Negative Keyword | Match Type | Reason |
| :--- | :--- | :--- | :--- |
| Discovery_Broad | [exact_word_1] | Exact | Prevent Discovery cannibalization |

### 5.3 Ad Group-Level Negatives
Prevents overlap between tight semantic clusters.

| Campaign | Ad Group | Negative Keyword | Match Type | Reason |
| :--- | :--- | :--- | :--- | :--- |
| [Campaign] | [Ad Group] | [exact_word] | Exact | Handled by [Other Ad Group] |

## 6. Executable CSV Contract

`asa-keywords-*.csv` must include:

`row_type`, `campaign_name`, `ad_group_name`, `keyword`, `match_type`, `negative_keyword`, `negative_match_type`, `negative_scope`, `search_match_enabled`, `country_or_region`, `normalized_popularity_0_100`, `popularity_source`, `raw_popularity`, `normalization_method`, `intent`, `competitor_tier`, `suggested_max_cpt`, `target_cpi`, `target_cpp`, `daily_budget`, `notes`

---

## 7. Execution Advice

1. **Verification & Setup**: Please download the attached `asa-keywords-*.csv` file. This table is strictly organized by the hierarchy `Campaign Name -> Ad Group Name (Cluster) -> Keyword`.
2. **Bulk Upload**: Because this data structure maps to the ASA account hierarchy, you can copy the core columns (Campaign, Ad Group, Keyword, Match Type, Bid) and paste them directly into Apple Search Ads' official Campaign Management (Bulk Upload) template for efficient mass creation.
3. **Search Match Audit**: Confirm every default Search Results Ad Group has Search Match turned off. Only explicitly requested Search Match experiment rows may set it to true.
4. **Cold Start**: We do not recommend frequently adjusting CPT within the first 3-5 days. Wait for Impressions and Taps to accumulate baseline data.
```
