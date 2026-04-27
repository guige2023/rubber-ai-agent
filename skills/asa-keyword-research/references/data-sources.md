# ASA Data Sources & Query Guide

To ensure the accuracy of keyword research, the agent should acquire data according to the following priorities and techniques:

## 1. Core Data Source Priorities

### Tier 1: Official & Authoritative Tools (Global)

- **Apple Search Ads Dashboard**: The most authoritative source for SP scores.
  - _Technique_: Navigate to `searchads.apple.com`. If unauthenticated, pause and wait up to 120 seconds for the user to manually log in via the visible browser. Once logged in, navigate to a draft campaign's `Add Keywords` module to retrieve the exact popularity bar.
- **AppFollow / MobileAction**: Provides global estimates for keyword popularity.
  - _Query Pattern_: `keyword popularity site:appfollow.io` or `site:mobileaction.co <keyword> search volume`.

### Tier 2: China-Specific Tools (China)

- **QiMai**: The most accurate source for "Search Index" in the CN region.
  - _Path_: Access the keyword details page on `qimai.cn`.
- **DianDian / ASO100**: Backup references.

### Tier 3: Algorithmic Estimation (Fallback)

- **App Store Search Hints**: Utilize `scripts/app_store_suggester.py`.
  - _Logic_: If the autocomplete keyword ranks 1st and contains the core seed, estimate SP > 50. If it ranks 5th or lower with moderate relevance, estimate SP < 30.

## 2. Browser Scraping Techniques

When executing `google_search` or visiting webpages directly, focus on the following information:

1. **Search Index**: For the CN region, this is typically in the 4605-9999 range. It should be converted or directly noted.
2. **Popularity (SP)**: For international regions, this is typically 0-100.
3. **Search Results**: The number of Apps returned when searching the keyword, representing the level of competition.

## 3. Important Notes

- **Data Recency**: Prioritize using data from the past 30 days.
- **Cross-Validation**: Compare data from at least two different sources to reduce error margins.
- **No Fabrication**: If an accurate SP cannot be acquired, it must be labeled as `[Estimated]` and the estimation logic must be explained (e.g., Estimated based on autocomplete ranking).
