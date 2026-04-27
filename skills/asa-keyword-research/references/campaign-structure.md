# ASA Campaign Structure Guide

To achieve the highest conversion rate and the most precise cost control, ASA top strategists typically follow these account architecture guidelines:

## 1. Core Architecture: Multiple Campaigns, Lean Ad Groups

### Why choose this structure?
- **Budget Isolation**: The traffic value of brand keywords, generic keywords, and competitor keywords is entirely different. By splitting campaigns, you can lock in budgets for high-converting words (like brand words).
- **Bidding Precision**: Different clusters have vastly different conversion rates. Putting too many keywords in the same Ad Group makes it impossible to balance bids.
- **Exact Match First**: Exact Match is the primary driver for delivery and budget, used to capture validated brand, generic, and competitor keywords.
- **Manual Discovery Isolation**: Place Broad Match core seed words in an independent Discovery Campaign and turn off Search Match by default to prevent automated traffic from cannibalizing the weight of manual exact keywords.

## 2. Recommended Campaign Segmentation

| Campaign Type | Keyword Nature | Objective | Match Type |
| :--- | :--- | :--- | :--- |
| **Brand** | Own App name, company name, misspellings | Defend territory, protect brand traffic | Exact Match |
| **Generic** | Feature keywords (e.g., "Translator", "Scan") | Acquire high-intent new users | Exact Match |
| **Competitor** | Direct competitors' App names | Conquesting | Exact Match |
| **Discovery** | High-intent core seeds | Discover new commercial/long-tail keywords | Broad Match, Search Match OFF by default |

## 3. Ad Group Cluster Design Principles

**Golden Rule: One Ad Group should only contain one semantic Cluster.**

- **Highly Similar Semantics**: For example, "scanner", "scan software", and "HD scan" can be placed in one Ad Group.
- **Few Keywords**: It is recommended to place 1-10 keywords per Ad Group. For core keywords, the **SKAG (Single Keyword Ad Group)** strategy is highly recommended (one Ad Group has exactly one keyword) to achieve absolute bidding optimization.

## 4. Negative Keywords Management

- **Campaign-Level Blocking**: Block known low-quality words in Brand and Generic campaigns.
- **Cross-Blocking**: Block exact keywords already targeted in Brand/Generic campaigns from the Discovery Campaign, ensuring Discovery only "discovers new words".
- **Search Match Exception**: Only when the user explicitly requests automated exploration should you create an isolated Search Match experimental campaign, which must have a low budget cap and strict negative keywords.

## 5. Bidding Strategy

- **Brand**: High bids, ensuring Share of Voice (SOV) > 90%.
- **Generic**: Set Cost Per Tap (CPT) bids based on CPA targets.
- **Competitor**: Flexible bidding, adjust based on competitor heat and your own conversion rates.
