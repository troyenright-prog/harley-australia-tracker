# Australian Harley listing tracker

Tracks **Iron 1200 / XL1200NS (2018–2021)** and **Seventy-Two / XL1200V (2012–2016)**, with no price ceiling or state filter. Python standard library only. This is a limited discovery monitor, not a complete Australia-wide market census.

- [Live report](https://troyenright-prog.github.io/harley-australia-tracker/)
- [Daily runs and failure logs](https://github.com/troyenright-prog/harley-australia-tracker/actions)
- [CSV results](results.csv), [scan health](scan_status.json), [validation and coverage](VALIDATION.md)

## What changed

The original ZIP silently succeeded when feeds returned no useful results, never queried its dealer list, did not enforce model years, missed plain-number odometers, and suppressed Git persistence errors. The incremental update keeps Python + SQLite + daily Actions. It adds robots-aware dealer discovery, conservative model/year matching, observation status, location, duplicate grouping, price-reduction events, an HTML report and optional SMTP email.

Bing search RSS was removed: the baseline live scan found zero matching records and Bing's robots policy disallows `/search`. No search scraping, CAPTCHA bypass, login automation, session harvesting, paid APIs, proxies or paid hosting are used.

## Run locally

Install Python 3.12 or newer, then in this folder:

```sh
python -m unittest discover -s tests -v
python tracker.py
```

Open `docs/index.html` directly in a browser; it works offline, with model filters, price/year/kilometre sorting, search and direct listing links. Or open `results.csv` in a spreadsheet. No web server or third-party packages are necessary.

`python tracker.py --data-dir local-test` runs with separate history. A scan exits nonzero if a source fails or the complete run has no usable target observations. Healthy inventories with zero target URLs are reported individually; this never proves that Australia has no listings.

## Sources and coverage

Daily discovery reads public stock sitemaps for Bikebiz, Brisans and Harley-Heaven, then fetches only target-looking listing URLs and previously discovered listings. Robots is checked every run, requests are spaced by at least a second per host, and redirects/challenges/access errors are not bypassed. The iMotor adapter reads structured stock data embedded in the public page, not a private API. Only factual listing fields are republished, not photographs or dealer descriptions.

Bikesales, Gumtree and Facebook are supported as **optional Google Alerts leads and manual imports**, not direct automated scrapers. Their completeness and freshness are not verified. Unknown model years and ambiguous titles are rejected, so some genuine ads need manual review. Current default dealer coverage is NSW and the Harley-Heaven network; it does not cover every state or every dealer.

### Most effective free additions (manual account setup)

1. **Bikesales:** save two Australia-wide searches using the exact model and year filters. Leave maximum price blank. Enable its native new-listing notifications.
2. **Gumtree Australia:** save nationwide searches for `XL1200NS`, `Iron 1200`, `XL1200V`, `Seventy Two`, `Seventy-Two`, and `Sportster 72`; select motorcycles and leave maximum price blank. Check account notification settings and alert expiry.
3. **Facebook Marketplace:** use native saved searches/notifications in your own account, with several Australian locations/radii as necessary. There is no verified exhaustive nationwide feed. Import suitable public links manually; the tracker never signs into Facebook.
4. **Google Alerts:** create model-code and name-variant alerts, choose Australia and “All results”, then RSS delivery where available. Create site-specific alerts for `site:bikesales.com.au`, `site:gumtree.com.au`, and `site:facebook.com/marketplace/item/`. Use an additional broad Australian dealer alert for manual review. Feeds can miss listings or deliver stale prices.

Store each RSS URL on a separate line in repository secret **ALERT_FEEDS**. For local use, put the URLs in ignored `feeds.txt`. Never commit these URLs: they contain personal feed identifiers. Only Google Alerts feed URLs are accepted. The importer accepts individual Bikesales/Gumtree/Facebook listings and supported dealers, not search pages or overseas domains. Facebook snippets must explicitly establish Australian location. Broad alerts for other dealers need manual review/import; adding a direct dealer requires checking its current policy and verifying its parser.

Manual import CSV columns: `title,description,url,source,location` (optional `seller,stock_number,vin`). Put the year and exact model in the title, and price/km in the description. Only import Australian whole motorcycles, not parts. Run:

```sh
python tracker.py --import-csv leads.csv
```

Manual imports remain unverified. Do not commit private seller names/contact details or your manual input file to the public repository. To retain manually imported history on GitHub, commit the updated SQLite database and generated reports before the next daily run; pull the latest repository first to avoid replacing newer history.

## History and availability

`listings.sqlite3` is the persistent source of truth:

- `listings`: one row per canonical ad URL, model, year, price, kilometres, location, source, first and last observation, last check, last direct observation and duplicate parent.
- `prices`: every observed price change, including increases. Missing prices do not erase the last known asking price.
- `events`: new-listing and price-reduction events, plus email delivery receipts.
- `scans`: timestamped source health for every run.

A direct seller-page observation does not guarantee the bike is still for sale. Search results never mark a bike active. A 404/410 marks a known page unavailable; missing sitemap entries alone do not mark it sold. Blocked/failed checks retain history without advancing `last_seen`. Reports show their generation date and warn when over two days old.

Tracking parameters and Facebook mobile URLs are canonicalised. Ads with the same valid VIN or seller + stock number are grouped without deleting either URL; duplicate NEW emails are suppressed. Cross-platform duplicates lacking these identifiers remain separate. Price alerts are per ad. No fuzzy automatic merging based on price/year, because different motorcycles can share those values.

## GitHub deployment

The public repository uses standard `ubuntu-latest` GitHub-hosted runners and GitHub Pages. Standard runner usage is free for public repositories. No larger runners or paid services are configured. Small downloadable reports expire after three days; history is committed to Git, not dependent on artifact retention.

Workflow `.github/workflows/daily.yml` runs at approximately **07:15 Australia/Brisbane daily** (`21:15 UTC`), on source changes to `main`, and from **Actions → Harley listings daily → Run workflow**. Scheduled jobs can be delayed by GitHub; they run from the default branch. Concurrent runs are serialised. Failed scans still save health/history, then fail the job visibly. Commit/push errors are not suppressed. Optional email runs only after history persistence succeeds.

For a new installation:

1. Create a public repository, upload the project including `.github`, and set `main` as default.
2. Enable Actions; permit the workflow's `contents: write`. Branch rules must allow the Actions bot to commit data.
3. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
4. Run the workflow and check both `monitor` and `pages` jobs, then inspect the data commit and report timestamp.
5. Enable GitHub Actions failure notifications in your GitHub notification settings. Public scheduled workflows may be disabled after 60 days with no repository activity; successful daily commits normally provide activity, but monitor failures and re-enable a disabled schedule.

The workflow explicitly deploys Pages because commits made by `GITHUB_TOKEN` do not normally trigger other workflows. It does not assume a bot data commit will rebuild Pages.

## Free optional email

Email sending is implemented and mock-tested but is **disabled until you supply an SMTP account**. Use an existing provider that permits SMTP without an additional subscription. For personal Gmail: enable two-step verification and create an app password if available for your account. Some managed/Advanced Protection accounts cannot create app passwords; use provider-native listing alerts instead.

In Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `SMTP_HOST` | For Gmail: `smtp.gmail.com` |
| `SMTP_PORT` | `587` (STARTTLS, default) |
| `SMTP_USER` | Your SMTP login email |
| `SMTP_PASSWORD` | Provider app password, never your normal password |
| `MAIL_TO` | Your notification destination |
| `MAIL_FROM` | Optional; defaults to SMTP_USER |

After configuration, run the workflow. New matches and reductions are sent as one plain-text digest. The initial digest includes pending discoveries from before email was configured. No email is sent when there are no pending events. A failed send fails the workflow and leaves events pending for retry. SMTP acceptance and Git receipt persistence cannot be one atomic transaction: a rare crash after sending but before saving can produce a duplicate email on retry. Provider quotas/delivery/spam filtering still apply. Never put secrets in code, commits, CSV files or the report.

## Maintenance

Review red Actions runs and the report's source-health section. If a dealer changes HTML, blocks requests or changes robots, the monitor fails visibly; update or disable that adapter after review. Keep the original ZIP as backup. To extend sources, add only a verified public feed/sitemap and a tested parser. No unrelated systems were changed.
