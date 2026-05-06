---
name: asa-keyword-research
description: Expert ASA engine for keyword mining, popularity validation, and ROI-based campaign structuring.
version: 0.1.5
author: Ferryman
updated: 2026-05-05
---

# ASA Keyword Research

**Quality Goal**: Deliver high-conversion Target CPA redlines and copy-paste ready campaign structures.

## Execution SOP
1. **Product Audit**: Visit URL (construct `https://apps.apple.com/app/id<ID>` if App ID given). Extract category and exact Monthly/Annual pricing.
2. **Rival Discovery**: Run `app_store_search.py --term <seed> --limit 5` for 3+ core seeds to identify top organic rivals.
3. **Intelligence Mining**:
   - **Reverse Lookup**: Run `qimai_keyword_detail.py --appid <Rival_ID>` for top 3 rivals to fetch real-world popularity (0-100).
   - **Semantic Scan**: Run `app_store_suggester.py --term <seed>` for Apple's real-time intent suggestions.
4. **Keyword Selection (Heuristics)**: Prioritize Top 50 based on:
   - **JTBD Intent**: Problem-solving phrases (e.g., "voice to do").
   - **Cross-Rival Alpha**: High frequency across 3+ rivals' lists.
   - **Fidelity**: Validated `popularity_source` only (No AI hallucination).
   - **Negative Filter**: Remove high-traffic low-intent noise (e.g., "free", "games").
5. **ROI Modeling**: Focus on **Target CPA (Install)** using **Monthly SKU**.
   - **Formula**: `CPA = Monthly_Net * Total_Payments * 0.9 * Install_to_Paid_Rate * 0.7`.
   - **Matrix**: Contrast 15% Small Biz vs 30% Standard fees across [Cons. (5% Pay)/Real. (10% Pay)/Opt. (15% Pay)] tiers.
6. **Packaging**: Cluster into `Brand / Generic / Competitor / Discovery`. Deliver MD Strategy and Executable CSV with brackets `[]` for Exact Match.

## Campaign Architecture
| Type | Match | Logic |
| :--- | :--- | :--- |
| **Brand** | Exact | Own name defense. |
| **Generic**| Exact | Feature clusters (e.g., "AI Voice"). |
| **Competitor**| Exact | Rival conquesting. |
| **Discovery** | Broad | Core seeds; Search Match OFF. |

## CSV Contract
Columns: `row_type`, `campaign_name`, `ad_group_name`, `keyword`, `match_type`, `negative_keyword`, `negative_match_type`, `negative_scope`, `search_match_enabled`, `country_or_region`, `normalized_popularity_0_100`, `popularity_source`, `raw_popularity`, `normalization_method`, `intent`, `competitor_tier`, `target_cpa`, `daily_budget`, `notes`

## Final Pass
- **Action**: Provide clickable links in final reply.
- **Typography**: No spaces between Chinese and English/Numbers.
