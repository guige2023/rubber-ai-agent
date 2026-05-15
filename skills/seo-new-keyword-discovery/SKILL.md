---
name: seo-new-keyword-discovery
description: Opportunity engine for emerging SEO keywords. Discovers seed terms, expands candidates through public search signals, audits SERP feasibility, and produces build-or-reject decisions for fast SEO page or micro-site opportunities.
version: 0.1.1
author: RabAiAgent
created: 2026-05-05
updated: 2026-05-07
---

# SEO New Keyword Discovery

**Quality Goal**: Find keywords worth building, not merely keywords worth noticing.

## Execution SOP
1. **Seed Mining**: Expand candidates from user seeds, root words, public rankings, directories, site-to-site discovery, keyword-to-keyword expansion, competitor pages, sitemaps, autocomplete, related searches, PAA, and public trend surfaces.
2. **Demand Check**: Validate demand with Google Trends when accessible, autocomplete, PAA, related searches, repeated public discussion, product-directory signals, or competitor targeting.
3. **SERP Audit**: Inspect top results for homepage vs inner page, Title/H1/URL match, weak hosted pages, forums, directories, thin/outdated/off-intent content, missing tools, and KD/DR/backlinks only when actually available.
4. **Product Gate**: Reject or downgrade candidates that are not AI-intensive, low-frequency, lack a user-data flywheel, or have unclear monetization.
5. **Counter-Check**: Record the decisive reason for the final verdict: tiny traffic ceiling, deceptively strong #1, official/navigational intent, unstable spike, weak monetization, weak AI value, or weak retention.
6. **Scoring**: Apply `references/scoring-guide.md`, then assign `build_now`, `build_light`, `observe`, or `reject`.
7. **Packaging**: Save Strategy MD and CSV using `assets/report-template.md`. Link both in the final reply.

## Output Contract
- **Strategy Report**: `reports/new-keyword-discovery-<topic>-<date>.md`
- **Keyword CSV**: `reports/new-keyword-discovery-<topic>-<date>.csv`
- **CSV Columns**: `keyword,source,source_url,trend_signal,demand_evidence,serp_weakness,product_gate,decision_rationale,kill_criteria,intent,page_type,minimum_useful_page,opportunity_score,decision,build_priority,notes`

## Decision Matrix
- **Build Now**: Strong demand + clear SERP weakness + feasible useful page + acceptable upside.
- **Build Light**: Promising but uncertain; test with a small but useful page.
- **Observe**: Interesting trend, but demand/intent is not yet stabilized.
- **Reject**: Weak demand, impenetrable SERP (e.g., official dominance), or low-value spike.

## Product Gate
A candidate must pass most of these to be `build_now`:
- **AI-intensive**: AI is the core value, not a cosmetic wrapper.
- **High-frequency**: users have recurring or multi-session need.
- **Data flywheel**: user inputs/results can improve personalization, templates, quality, or retention.
- **Clear monetization**: ads, affiliate, credits, subscription, leads, or upgrade path is plausible.

If a candidate fails two or more, default to `observe` or `reject` even if the keyword looks searchable.

## Human Verification Handling
If Google Search, Google Trends, or another high-value public source triggers human verification:
1. Ask the user to complete verification in the visible browser.
2. Wait up to 3 minutes unless the user sets another timeout.
3. Continue the original workflow if verification succeeds.
4. If it times out or the user declines, use fallback sources and mark affected fields as `blocked_by_verification` or `[limited]`.

Do not silently skip Google SERP/Trends when central to the decision. Do not loop retries.

## Quality Standards
1. **Fidelity**: No fabricated volume or KD. Label heuristic data as `[estimated]`.
2. **Evidence-Driven**: Every decision needs one concrete `decision_rationale` based on current evidence. Do not fill both generic go and no-go boilerplate.
3. **Traceability**: Include source URLs for all web-derived findings.
4. **Actionability**: Recommendations must include a suggested Title Tag and H1 for the new page.
5. **People-First**: Do not recommend thin SEO pages; recommend the smallest useful page that satisfies intent.

## Relationship to Other Skills
- Use `seo-keyword-research` for broader content roadmaps after niche selection.
- Use `seo-backlink-research` when selected keywords require link-building to compete.
- Use `ai-hotspot-miner` for trend articles rather than SEO tool/page selection.

## Final Pass
- **Language**: Match user prompt language.
- **Chinese Typography**: No spaces between Chinese characters and English words/numbers.
