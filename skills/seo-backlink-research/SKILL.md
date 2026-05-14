---
name: seo-backlink-research
description: >
  Discover free or replicable SEO backlink opportunities, verify submission paths,
  create structured follow-up tasks, and save a concise research report.
version: 0.2.1
author: Ferryman
created: 2026-03-19
updated: 2026-05-14
---

# Skill: SEO Backlink Research

Find practical backlink opportunities, not a complete backlink database. Prefer targets that are relevant, free or freemium, replicable, and likely to accept submissions.

Do not perform submissions in this skill. Create follow-up tasks for submission agents.

Match the user's input language for reports, task notes, summaries, and generated submission copy unless the user asks for another language. Keep field names stable when they are part of a schema.

## Workflow

1. Build the Product Submission Profile first.
2. Discover competitors and comparable products.
3. Mine backlink footprints and direct submission opportunities.
4. Verify candidates with `verify_submit_targets.py` before browser checks.
5. Classify submission readiness.
6. Create tasks only for viable targets.
7. Save a markdown report.

## Product Submission Profile

Create this before research and reuse it for queries, target fit, task bodies, and report output.

Required schema fields; use `unknown` when a field is not visible or user-provided:

- `tool_or_product_name`
- `alternative_name`
- `website_url` (root URL unless user says otherwise)
- `short_description`
- `long_description_factual`
- `long_description_marketing`
- `keywords_or_tags`
- `target_categories`
- `pricing_model` (`free`, `freemium`, `paid`, `unknown`)
- `logo_url`
- `image_urls`
- `contact_email`
- `preferred_founder_or_contact_name`
- `preferred_location`

Use the product homepage, metadata, visible copy, pricing page, logo/favicon assets, examples, and obvious navigation links. Do not invent metrics, model names, pricing, founder info, locations, awards, endorsements, or other claims unless visible on the site or provided by the user.

## Discovery

If competitors are not provided, find up to 5 from search intent. Start with 2 competitor queries and use at most 5.

Use compact query sets based on the Product Submission Profile:

- `"competitor.com" -site:competitor.com`
- `"competitor.com" "submit your tool"`
- `"competitor.com" "add tool"`
- `"<category keyword>" "submit your tool"`
- `"<category keyword>" "submit product"`
- `"<category keyword>" "submit startup"`
- `"<category keyword>" "add product"`
- `"<category keyword>" "get listed"`
- `"<category keyword>" "launch product"`
- `"<category keyword>" directory`
- `"best <category keyword> tools"`

Budgets:

- Use 1-2 footprint queries per competitor, max 10-12 total.
- Use 4-6 direct niche searches.
- Stop once you have enough strong candidates. Do not exhaust budgets for completeness.

## Verification

Use `run_skill_script(script_name="verify_submit_targets.py", args=[url1, url2, ...])`.

Parse the JSON array. Each result contains:

- `url`
- `accessible`
- `submit_signal_found`
- `submit_signal_snippet`
- `failure_reason`
- `final_url`
- `verification_method`
- `browser_fallback_recommended`
- `browser_fallback_reason`

The script is HTTP-first and must not launch browsers. Use browser tools only for unusually valuable candidates when HTTP verification is blocked, anti-bot gated, or likely client-rendered.

## Classification

For each final candidate, set:

- `priority`: `P0`, `P1`, `P2`
- `submission_url`: direct submit/listing URL if found
- `free_status`: `free`, `freemium`, `likely_paid`, `unknown`
- `paid_or_credit_required`: `yes`, `no`, `credits_required`, `unknown`
- `requires_account`: `yes`, `no`, `unknown`
- `requires_backlink_badge`: `yes`, `no`, `unknown`
- `replicable_status`: `replicable`, `possibly_replicable`, `not_replicable`
- `entry_path`: `direct_submit`, `contact_or_suggest`, `github_pr`, `editorial_outreach`, `unknown_path`
- `confidence`: `high`, `medium`, `low`

Create submission tasks only when the target is actionable and not `likely_paid`. For promising unresolved targets, create a review task instead.

## Task Format

Title:

```text
[Backlink Submit] <product_domain> -> <target_domain>
```

Review title:

```text
[Backlink Review] <product_domain> -> <target_domain>
```

Body:

```md
## Target
Product domain: <product_domain>
Target domain: <target_domain>
Target URL: <target_url>
Submission URL: <submission_url>
Entry path: <entry_path>
Priority: <P0/P1/P2>
Free status: <free_status>
Paid or credit required: <paid_or_credit_required>
Requires account: <yes/no/unknown>
Requires backlink badge: <yes/no/unknown>
Replicable status: <replicable_status>
Confidence: <high/medium/low>
Evidence: <snippet or URL>

## Product Submission Profile
Tool/Product name: <name>
Alternative name: <name>
Website URL: <root URL>
Short description: <tagline>
Long description factual: <neutral copy>
Long description marketing: <polished factual copy>
Keywords/tags: <tags>
Target categories: <categories>
Pricing model: <free/freemium/paid/unknown>
Logo URL: <logo URL>
Image URLs:
- <image URL>
Contact email: <email>
Founder/name: <name>
Location: <location>

## Submission Notes
Preferred URL policy: use root domain unless the platform asks for a deep link.
Platform-specific notes: <notes>
Manual review needed: <yes/no>
```

## Report

Save reports as `reports/backlink-research-<domain>-<current_date>.md`.

Use `assets/report-template.md` and include:

1. Target Summary
2. Product Submission Profile
3. Competitors Observed
4. High-Value Free Submission Targets
5. Worth Reviewing But Verification Failed
6. Query Patterns That Worked
7. Tasks Created For Execution
8. Recommended Next Step

Final response must include the report path, task IDs created, verified targets, unresolved targets, and any browser fallback recommendations.
