---
name: asa-keyword-research
description: >
  Use this for Apple Search Ads (ASA) keyword research, App Store competitor
  keyword mining, search popularity validation, Target CPA estimation, campaign
  and ad group structuring, or executable ASA keyword CSV generation for an
  App Store app.
version: 0.1.19
author: Ferryman
updated: 2026-05-07
---

# ASA Keyword Research

**Expert Goal**: High-fidelity Target CPA ceilings and copy-paste ready campaign structures.

## Execution SOP
1. **Context**: Identify **Target Country (<CC>)** as ISO 2-letter uppercase (e.g. US, CN).
2. **Standardize Net**: Select the primary recurring SKU in this order: Weekly > Monthly > Annual. Use that SKU's single transaction price as `Price`; do not convert Annual to Monthly or blend multiple SKUs. Exclude trial/intro/lifetime prices from the primary model.
   - `Net_LTV = Price * Total_Payments * (1 - Apple_Fee)`.
3. **Rival Discovery**: Run `app_store_search.py --term <seed> --country <CC> --limit 5` (uppercase) for 3+ core seeds.
4. **Intelligence Mining**:
   - **Real Heat (Primary)**: Run `qimai_keyword_detail.py --appid <App_ID> --country <cc>` (lowercase) once for the target app, then once for each top rival app. Build a Search Popularity map from returned keywords. Label QiMai scores `[Real]`.
   - **Intent Scan (Secondary)**: Run `app_store_suggester.py --term <seed> --country <CC>` (uppercase). Use suggestions only as intent discovery; store suggestion position in `suggestion_rank`.
   - **Merge Rule**: For every candidate keyword, first try to fill `search_popularity` from the `[Real]` QiMai map. Never store suggestion rank in Search Popularity fields.
5. **ROI Modeling**: Use category-specific benchmarks.
   - **Formula**: `BreakEven_CPA = Net_LTV * Install_to_Paid_Rate`.
   - **Safety**: `Target_CPA = BreakEven_CPA * Realization_Factor * Safety_Margin`.
   - **Defaults**: `Realization_Factor = 0.9`; `Safety_Margin = 0.7`.
6. **Packaging**: Prioritize Top 50 keywords using **Heuristics**. Cluster into `Brand/Generic/Competitor/Discovery`. Follow the Output Contract.

## Output Contract
Every successful run produces a strategy report and keyword CSV under `reports/<yyyy-mm-dd>/` using [assets/report-template.md](assets/report-template.md) as the report blueprint:

1. Strategy report: `reports/<yyyy-mm-dd>/asa-strategy-<app_slug>.md`
2. Keyword CSV: `reports/<yyyy-mm-dd>/asa-keywords-<app_slug>.csv`

- `<yyyy-mm-dd>` is the current execution date.
- `<app_slug>` is a lowercase, filesystem-safe app name or app-id slug.
- Link both files in the final reply.

## Quality Standards
1. **Search Popularity Contract**: Search Popularity means QiMai native 0-100 popularity only.
   - QiMai rows: `search_popularity = <QiMai popularity>`.
   - Suggestion-only rows: `search_popularity = N/A`; record App Store suggestion position in `suggestion_rank`.
2. **Real Popularity Priority**: Keyword tables in the report and CSV MUST include `search_popularity` and `suggestion_rank` for every keyword. Prefer `[Real]` QiMai Search Popularity whenever available; do not output star ratings or guessed heat labels as Search Popularity.
   - If the same keyword appears in multiple rival QiMai results, keep the strongest popularity score and note rival frequency/source apps in `notes`.
   - `suggestion_rank` must be one integer: the best rank found for that keyword across all seed suggestion calls. If absent, use `N/A`; put matched seeds in `notes`.
3. **Seed Expansion Rules**: Run suggestions for at least 12 seeds:
   - Core feature seeds from the app name/subtitle/description.
   - Category seeds such as todo, reminder, checklist, calendar, planner, or localized equivalents.
   - Top rival brand seeds from `app_store_search.py`.
   - High-intent QiMai Chinese keywords with meaningful `search_popularity`.
4. **ROI Transparency**: The report MUST show `Price`, `Apple_Fee`, `Total_Payments`, `Install_to_Paid_Rate`, `Net_LTV`, `BreakEven_CPA`, `Realization_Factor`, `Safety_Margin`, and `Target_CPA` for each scenario.
5. **Output Balance**: Keep the Top 50 balanced across Brand, Generic, Competitor, and Discovery. Prefer `[Real]` Search Popularity keywords when available, and ensure differentiation and competitor terms are both represented. Explain any major imbalance in `notes` or the report.
6. **Country Alignment**: Use uppercase for App Store scripts, lowercase for QiMai.
7. **Category Integrity**: Do not use Productivity defaults for other categories. State selected benchmarks in the report.
8. **SKU Discipline**: Non-primary recurring SKUs and lifetime SKUs may be reported as sensitivity scenarios only. Do not invent SKU mix weights unless the user provides actual purchase distribution data.
9. **ASA Copy-Paste Formatting**: Every ad group in the strategy report MUST include a copy-paste keyword line for ASA.
   - Exact Match: wrap every keyword in brackets and separate with commas, e.g. `[a], [b], [c]`.
   - Broad Match: omit brackets and separate with commas, e.g. `a, b, c`.
   - Negative keywords follow the same bracket rule based on negative match type.

## Category Benchmarks (Reference Only)
| Category | Install-to-Paid Rate (Cons/Real/Opt) | Lifecycle Payments (Cons/Real/Opt) |
| :--- | :--- | :--- |
| **Productivity** | 5% / 10% / 15% | 2.5x / 4.5x / 6.0x |
| **Utilities** | 3% / 6% / 10% | 1.5x / 3.0x / 5.0x |
| **Games (Casual)** | 2% / 5% / 8% | 1.2x / 2.0x / 3.5x |

## Keyword Heuristics
Prioritize based on: JTBD Intent, `[Real]` Search Popularity, Cross-Rival frequency, and Search Hint rank only as a proxy fallback. Aggregate top 50 balanced between Generic and Competitor.

## Campaign Architecture
| Type | Match | Logic |
| :--- | :--- | :--- |
| **Brand** | Exact | `[name]` defense. |
| **Generic**| Exact | Feature clusters (e.g., "speech to task"). |
| **Competitor**| Exact | Direct rival names. |
| **Discovery** | Broad | Core seeds; Search Match OFF. |

## CSV Output Contract
Fields: `row_type`, `campaign_name`, `ad_group_name`, `keyword`, `match_type`, `negative_keyword`, `negative_match_type`, `negative_scope`, `search_match_enabled`, `country_or_region`, `search_popularity`, `suggestion_rank`, `intent`, `competitor_tier`, `target_cpa`, `daily_budget`, `notes`

## Final Pass
- **Action**: Provide clickable links in final reply.
- **Typography**: No spaces between Chinese and English/Numbers.
