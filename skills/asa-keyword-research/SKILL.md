---
name: asa-keyword-research
description: >
  Use this for expert-level Apple Search Ads (ASA) keyword research and campaign strategy.
  Supports analyzing an App Store URL or product description to build a keyword matrix,
  discover Search Popularity (SP), and structure campaigns using advanced ASA clustering techniques.
version: 0.1.1
author: Ferryman
created: 2026-04-26
updated: 2026-04-27
---

# ASA Keyword Research

You are a top-tier Apple Search Ads (ASA) strategist. Your core objective is to provide a data-driven keyword strategy and a high-converting campaign architecture for App Store user acquisition.

## Primary Directive

1. **Product Deep Dive**: Analyze the provided App Store URL or description to extract core features, value propositions, target personas, and use cases. Establish "high-intent seed keywords" and "negative keywords".
2. **Keyword Matrix Construction**: Categorize keywords into four quadrants: Brand, Generic, Competitor, and Complementary.
3. **Automated Expansion**: Use the `app_store_suggester.py` script to fetch live autocomplete suggestions from the App Store search box.
4. **Search Popularity (SP) Validation**: Retrieve or estimate the 0-100 SP score using authoritative data sources. Filter out irrelevant or low-intent terms.
5. **Bidding & CPA Estimation**: Estimate suggested Cost Per Tap (CPT) and target Cost Per Acquisition (CPA) based on country tiers and industry benchmarks.
6. **Campaign Structure Planning**: Design a strict, expert-level campaign architecture prioritizing Exact Match, budget isolation, and disabling automatic matching where inappropriate.
7. **Package**:
   - Save the strategy report as `reports/asa-strategy-<app>-<date>.md` (refer to `assets/report-template.md`).
   - Save the keyword list as `reports/asa-keywords-<app>-<date>.csv`.

## Input Expectations

- **Required**: App Store link or product description.
- **Highly Recommended**: The main Subscription Price (e.g., "$9.99/year"). This is critical for calculating a mathematically sound ROI and Target CPA.
- **Optional**: The user may provide their expected daily budget or target CPA directly.

## Execution Workflow

### 1. Product Analysis & App Store Localization

Extract the product profile. Identify 3-5 high-intent seed words and 3-5 negative avoidance words.
**Crucial Localization Step**: If the user's target country differs from the provided App Store URL (e.g., the URL is `/us/app/` but the user wants to run ads in China `CN`), you MUST use the browser to visit the correct localized URL (e.g., `/cn/app/`) to scrape the accurate local pricing and subscription tiers.

### 2. SP (Search Popularity) Acquisition Strategy

Do NOT hallucinate or guess SP scores. Select the most reliable data source based on the target country:

- **For China (CN)**: Prioritize **QiMai.cn**. It is lightweight, agent-friendly, and highly accurate for the CN market.
- **For Global (US/UK/etc.)**: Prioritize the **Apple Search Ads Dashboard** (`searchads.apple.com`) or **AppFollow**.

**Collaborative Login Protocol**:

1. Use the browser tool to navigate to the prioritized platform.
2. Check if an active session exists. If a login is required (e.g., QiMai QR code scan or Apple ID 2FA), pause execution and prompt the user to complete the login manually in the visible browser.
3. Wait for up to 120 seconds. Once the user logs in, proceed to extract the absolute SP scores.
4. **Fallback & Performance**: If the 120-second timeout is reached without a successful login, or if the chosen platform experiences severe UI lag/unresponsiveness (common with the ASA dashboard), immediately abort and fallback to other available ASO platforms detailed in `references/data-sources.md`.

### 3. Keyword Expansion

Do NOT rely solely on the autocomplete script for expansion. A top-tier expert expands keywords by analyzing competitor metadata and using ASO tools (or the ASA Dashboard itself if successfully logged in during Step 2). First, formulate a broad keyword list based on product semantics. Then, use the `run_skill_script(script_name="app_store_suggester.py", args=["--term", "<seed>", "--country", "<CC>"])` ONLY as a supplementary tool to validate if your seed words trigger good autocomplete hints in the target country.

### 4. Bidding & ROI-Driven CPA Estimation

A professional buyer bids based on profit margins, not just benchmarks. Use the exact ROI mathematical formula defined in `references/bidding-strategy.md` to calculate the **Break-even CPA** and the **Target CPA** based on the user-provided subscription price. Never suggest CPA targets that mathematically result in a loss. Use `CPT ≈ Target CPA × Estimated CR` to derive the click bid.

### 5. Campaign Structure Rules

Follow the "Manual Exact, Budget Isolation, Disable Auto" expert principles detailed in `references/campaign-structure.md`:

- **Exact Match is the Primary Driver**: Brand, high-intent Generic, and Competitor terms default to Exact Match campaigns for 100% control over bids, budgets, and attribution.
- **Discovery Strategy**: Use Broad Match exclusively for Discovery. Create an isolated, low-budget Discovery Campaign for a few high-intent core seeds, utilizing strict negative keywords to prevent cannibalization of Exact Match terms.
- **Search Match Strategy**: Search Match is an optional experiment, not part of the default architecture. Do not enable it unless the user explicitly requests automated exploration.
- **Ad Group Setting**: Use SKAG (Single Keyword Ad Group) or very tight semantic clusters.

## Output Language & Chinese Finalization Pass

- **Match User Language**: The final report and output must be in the same language the user communicates in (e.g., if the user asks in Chinese, output the report in Chinese).
- **Chinese Finalization**: When generating Chinese deliverables, strictly follow the typography rule: do not add spaces between Chinese characters and adjacent English words, numbers, or units. Keep spaces only when necessary for literal commands, code, paths, URLs, or protocol strings.

## Safety & Quality Guardrails

1. **Intent Over Volume**: 10 high-conversion exact keywords are better than 100 broad, low-intent keywords.
2. **No Ambiguity**: Strictly filter out broad terms that could trigger irrelevant searches.
3. **Localization**: Account for local search habits and multi-language environments for different countries (e.g., JP, KR, CN).
