---
name: asa-keyword-research
description: >
  Use this for Apple Search Ads (ASA) keyword research, App Store competitor
  keyword mining, search popularity validation, Target CPA estimation, campaign
  and ad group structuring, or executable ASA keyword CSV generation for an
  App Store app.
version: 0.1.9
author: Ferryman
updated: 2026-05-06
---

# ASA Keyword Research

**Expert Goal**: High-fidelity Target CPA ceilings and copy-paste ready campaign structures.

## Execution SOP
1. **Context**: Identify **Target Country (<CC>)** as ISO 2-letter uppercase (e.g. US, CN).
2. **Standardize Net**: Use the single purchase price for the selected paid SKU. Exclude trial/intro/lifetime prices.
   - `Net_LTV = Price * Total_Payments * (1 - Apple_Fee)`.
3. **Rival Discovery**: Run `app_store_search.py --term <seed> --country <CC> --limit 5` (uppercase) for 3+ core seeds.
4. **Intelligence Mining**:
   - **Real Heat**: Run `qimai_keyword_detail.py --appid <Rival_ID> --country <cc>` (lowercase). Label `[Real]`. If country unsupported, label `[N/A]`.
   - **Intent Scan**: Run `app_store_suggester.py --term <seed> --country <CC>` (uppercase). Label `[Proxy: Rank X]`.
5. **ROI Modeling**: Use category-specific benchmarks.
   - **Formula**: `BreakEven_CPA = Net_LTV * Install_to_Paid_Rate`.
   - **Safety**: `Target_CPA = BreakEven_CPA * Realization_Factor * Safety_Margin`.
   - **Defaults**: `Realization_Factor = 0.9`; `Safety_Margin = 0.7`.
6. **Packaging**: Prioritize Top 50 keywords using **Heuristics**. Cluster into `Brand/Generic/Competitor/Discovery`.

## Quality Standards
1. **CSV Proxy Contract**: For `[Proxy]` rows (suggestions):
   - `normalized_popularity_0_100`: Set to `N/A`.
   - `raw_popularity`: Set to `rank:<X>`.
   - `normalization_method`: Set to `apple_suggestion_rank_no_score`.
2. **Country Alignment**: Use uppercase for App Store scripts, lowercase for QiMai.
3. **Category Integrity**: Do not use Productivity defaults for other categories. State selected benchmarks in the report.

## Category Benchmarks (Reference Only)
| Category | Install-to-Paid Rate (Cons/Real/Opt) | Lifecycle Payments (Cons/Real/Opt) |
| :--- | :--- | :--- |
| **Productivity** | 5% / 10% / 15% | 2.5x / 4.5x / 6.0x |
| **Utilities** | 3% / 6% / 10% | 1.5x / 3.0x / 5.0x |
| **Games (Casual)** | 2% / 5% / 8% | 1.2x / 2.0x / 3.5x |

## Keyword Heuristics
Prioritize based on: JTBD Intent, Cross-Rival frequency, and real-time Search Hint rank. Aggregate top 50 balanced between Generic and Competitor.

## Campaign Architecture
| Type | Match | Logic |
| :--- | :--- | :--- |
| **Brand** | Exact | `[name]` defense. |
| **Generic**| Exact | Feature clusters (e.g., "speech to task"). |
| **Competitor**| Exact | Direct rival names. |
| **Discovery** | Broad | Core seeds; Search Match OFF. |

## CSV Output Contract
Fields: `row_type`, `campaign_name`, `ad_group_name`, `keyword`, `match_type`, `negative_keyword`, `negative_match_type`, `negative_scope`, `search_match_enabled`, `country_or_region`, `normalized_popularity_0_100`, `popularity_source`, `raw_popularity`, `normalization_method`, `intent`, `competitor_tier`, `target_cpa`, `daily_budget`, `notes`

## Final Pass
- **Action**: Provide clickable links in final reply.
- **Typography**: No spaces between Chinese and English/Numbers.
