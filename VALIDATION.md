# Validation and coverage — 13 October 2026 (Australia/Brisbane)

## Real public discovery

The supplied tracker ran against its 15 Bing RSS searches and returned zero matching records, zero errors and exit code 0. This demonstrates why passing the original tests was insufficient. Bing robots disallows `/search`; that adapter has been removed.

The updated tracker performed a live, unauthenticated dealer scan at 2026-10-13T01:03:04Z (11:03 Brisbane), using robots-allowed stock sitemaps and listing pages:

| Source | Inventory URLs | Target candidates | Direct observations |
|---|---:|---:|---:|
| Bikebiz | 122 | 1 | 1 |
| Brisans | 212 | 1 | 1 |
| Harley-Heaven | 264 | 0 | 0 |

The two discovered records were:

| Model/year | Asking price AUD | Kilometres | Location | Listing |
|---|---:|---:|---|---|
| Seventy-Two, 2012 | 13,790 | 36,345 | Granville, NSW | [Bikebiz](https://www.bikebiz.com.au/used-bikes/harley-davidson-seventy-two-xl1200v-2012-cnshd72) |
| Seventy-Two, 2015 | 16,490 excluding government charges | 12,044 | Islington, NSW | [Brisans](https://www.stock.brisans.com.au/used-bikes/for-sale/harley-davidson/seventy-two-xl1200v/2015/sportster/4128206/) |

These are observations of seller pages, not seller-confirmed availability. No current Iron 1200 listing was discovered in these three inventories. This does not establish that none are for sale elsewhere.

The Brisans page's embedded public stock data and rendered seller details agree on the price and odometer. The Bikebiz rendered bike section supplies the same price, odometer and location recorded in CSV. No synthetic records were inserted into the live database. Raw pages were inspected locally but are excluded from publication; only listing facts and source links are retained.

## Other sources investigated

| Source/method | Finding | Free alternative |
|---|---|---|
| Bikesales public search index | Target model results exist, but returned search snapshots were roughly a year old and mixed multiple bikes. They were not imported as individual active ads. | Native saved-search alerts; optional Google Alerts RSS with individual detail URLs. |
| Gumtree public search index | Focused model-code/name searches did not yield a verifiable individual target listing in this investigation. This is not evidence of an empty marketplace. | Australia-wide native saved searches/notifications; manual links or Google Alerts. |
| Public Facebook Marketplace indexing | Focused Australian target searches did not yield verifiable public target ads. No login/session collection attempted. Meta restricts unauthorised automated collection. | Native saved searches with multiple locations/radii; manually checked public links. |
| Richardson's Harley-Davidson | Search indexing exposed a Seventy-Two; direct sitemap returned 403. No retry using altered identity, proxy or session. | Native website/manual review, dealer stock alerts if offered, Google Alerts. |
| Just Bikes | Search result exposed a 2019 Iron 1200, but opening the result did not yield verifiable listing details. Not counted as current inventory. | Saved searches/manual review and Google Alerts. |
| Central Coast / Sy's Harley-Davidson | Public indexed exact-model pages reported zero bikes; category URLs were not treated as listings. Additional adapters remain unverified. | Manual/native alerts, or verify their dealer sitemap adapter before enabling. |
| General search-engine HTML scraping | Not implemented; not an authorised replacement for removed/free search APIs. | User-created Google Alerts RSS. |
| eBay/general shopping indexes | Frequently return seats, brakes and other fitment parts; .com.au alone does not establish an Australian whole-bike listing. | Native saved searches with vehicle/category/location filters; manual import only. |

## Automated validation

23 regression tests pass locally: model variants and exclusions, year boundaries, high prices without a ceiling, plain-digit odometers, exact URL/VIN deduplication, persistent first/last observations and price history, reductions vs increases, missing-price preservation, stale-index protection, RSS/Atom parsing, invalid/search/foreign URLs, robots denial, changed page structure, email retry/receipts, and report script escaping.

Email uses mocks only: no SMTP credentials or destination were supplied, so real delivery has not been verified. No Google Alerts feed was supplied, so the RSS adapter has parsing tests but no user-feed end-to-end verification.

## Evidence references

- [Bing robots](https://www.bing.com/robots.txt)
- [Bikebiz robots](https://www.bikebiz.com.au/robots.txt) and [used-bike sitemap](https://www.bikebiz.com.au/used-bikes-sitemap.xml)
- [Brisans robots](https://www.stock.brisans.com.au/robots.txt), [stock sitemap](https://www.stock.brisans.com.au/sitemap-stock.xml) and [terms](https://www.brisans.com.au/terms)
- [Harley-Heaven robots](https://www.stock.harleyheaven.com.au/robots.txt), [stock sitemap](https://www.stock.harleyheaven.com.au/sitemap-stock.xml) and [website terms](https://www.stock.harleyheaven.com.au/website-terms-of-use/)
- [Bikesales target-model search and Save search](https://www.bikesales.com.au/bikes/used/used-subcondition/harley-davidson/iron-1200-xl1200ns/)
- [Gumtree Australia search/filter guidance](https://help.gumtree.com.au/articles/en_US/KB_Article/How-to-search-and-filter-results-AU/?c=PKB%3ATechnical_Issue&fs=RelatedArticle&l=en_US)
- [Facebook on authorised and unauthorised scraping](https://www.facebook.com/help/463983701520800)
- [GitHub free standard public runners](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)
- [GitHub scheduled-workflow inactivity rule](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)

## Deployment verification

Repository created: https://github.com/troyenright-prog/harley-australia-tracker

- [First hosted run, triggered automatically by push](https://github.com/troyenright-prog/harley-australia-tracker/actions/runs/38330766205): successful tests, live scan, data commit, report artifact and Pages deployment.
- [Second hosted run, workflow_dispatch](https://github.com/troyenright-prog/harley-australia-tracker/actions/runs/38330853191): successful on a fresh runner, using the previous committed database.
- Data commits: `342bab1` and `2383476`. Both retain two listing rows and the original discovery timestamp `2026-10-13T01:03:04.480914+00:00`; last-observed timestamps advance. No duplicate NEW events were generated. The database contains two initial NEW events and two initial price observations.
- The live Pages report was opened and its listing fields checked. Browser validation found a missing opening option tag in the Iron 1200 filter; this was corrected and covered by a regression test.
- Daily workflow cron is `15 21 * * *`, approximately 07:15 Brisbane. Scheduled workflow is enabled. A push-triggered run verifies automatic execution, but no future cron occurrence is claimed to have completed during this session.
- SMTP credentials and Google Alerts feeds are not configured. Email step safely reported not configured; real email delivery remains unverified.
