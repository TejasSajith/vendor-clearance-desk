# Probe: registry aggregator pages and news (Delhivery, Everest Fleet, Xtrans Logistics)

Run 2026-11-22. Scripts: `probe/step6*.py` (every call goes through `core.cached_call`). Raw responses are in `probe/raw/` (gitignored). The calls are in `probe/calls.jsonl` (tag prefix `step6`). **19 calls, 13.0 credits** (cap 40); the core ledger and `calls.jsonl` agree. No call errored or timed out; the slowest was 28.8s. Searches that return nothing are billed 0.

## (a) Registry aggregators via Web Search + Web Fetch

**Result: no CIN, status, incorporation date, director with DIN, or filing date could be cited for any of the 3 companies.** Fill-rate 0/3 for every field. I did not fill gaps from memory; a CIN I could not source from a retrieved page is not used.

| Step | What happened |
|---|---|
| Search `<name> CIN directors DIN zaubacorp OR tofler` | 0 aggregator URLs for all 3. Delhivery gave a Tofler Facebook page and a stock-tips post, Everest gave `craft.co` and `growjo.com` profiles, Xtrans gave 0 results. |
| Search `site:zaubacorp.com <name>` and `site:tofler.in <name>` (6 searches) | Results are mostly opaque `google.com/goto?url=` links. Resolved (see below), the targets were not aggregator pages: AfterShip reviews, `everestfleet.com`, JustDial. Xtrans gave 0 results both times. |
| Fetch `https://www.zaubacorp.com/` and `/companysearchresults/Delhivery` directly | HTTP success, but the content is a Cloudflare "Just a moment... Performing security verification" page (about 44KB). **Blocked.** |
| Fetch `https://www.tofler.in/` and `/search?q=Delhivery` directly | The home page fetches (144KB) but holds no company data. The search URL returns a Tofler "Error" page. Company pages need a CIN in the URL (`/<slug>/company/<CIN>`), and we don't have one without a registry. |

- **Fields citable today:** none, from the aggregators.
- **Cost:** 6 search credits plus 4 fetch credits for these attempts.
- **Reliability:** poor. Search seldom surfaces aggregator pages, Cloudflare blocks one of the two, and the other needs the CIN we are trying to find.

## (b) News: Web Search `sources:["news"]`

| Query | Results | Notes |
|---|---|---|
| `Delhivery fraud OR default OR FIR` | 9 | All about generic delivery-fraud stories (LPG cylinders, Zomato, OTP scams), in Hindi. **None is about Delhivery.** 8 of 9 URLs are `google.com/goto`. |
| `Everest Fleet fraud OR default OR FIR` | 0 | |
| `Xtrans Logistics fraud OR default OR FIR` | 0 | |
| Same 3, with the company name quoted | 0, 0, 0 | |

- **Date field:** none. Result objects carry `position, snippet, source, title, url` only. No snippet in the 9 had a date prefix.
- **Direct URLs:** 1 of 9. The rest are Google redirects.
- **Decoding `google.com/goto?url=`:** the token is opaque (encrypted); it does not decode locally and contains no URL. A plain `GET` with redirects disabled returns `302` with a `Location:` header holding the real URL. That is free, but it is a direct request to google.com, outside Crustdata and outside our cost ledger. It resolved all 18 links I tried (hosts: bhaskar.com, abplive.com, jansatta.com, patrika.com, aftership, growjo, facebook, linkedin, everestfleet.com).
- **Fetching resolved targets:** 2 news pages fetched fine (375KB and 465KB of HTML). Each carries a publish date (`article:published_time` and `datePublished` in JSON-LD: 2026-03-25 and 2026-06-23), so a date is citable from the page, not from search. Neither page mentions the target company.
- **Fill-rate for "dated adverse report naming the target":** 0/3.
- **Cost:** 1 credit per search with results, 1 per fetched page.

## Options (not chosen)

**D9: registry source (CIN, status, directors, filings)**

| Option | For | Against |
|---|---|---|
| A. Aggregator pages via Web Search + Fetch | No extra vendor; the pages show CIN, DIN and filing data when reachable | 0/3 here. Search doesn't surface the pages, Cloudflare blocks one site, the other needs the CIN first. Scraping terms and personal data (director names) need review. |
| B. A KYC or MCA data API (separate vendor) | Returns CIN, status, DIN and filings as structured fields with a date | New dependency, cost and key (needs your decision under AGENTS.md); not probed here |
| C. No registry source: report `CANNOT_VERIFY` for existence and directors of record | Honest, nothing new to build, no scraping risk | Exists and director checks stay capped at "partial"; most vendors end as `CANNOT_VERIFY` |

**D10: news source for adverse media**

| Option | For | Against |
|---|---|---|
| A. Crustdata Web Search `sources:["news"]` | Already integrated, cheap (1 credit) | 0 to 9 results, mostly off-target, no date field, opaque redirect links |
| B. A news API | Likely dated, direct URLs and a company filter | New dependency and cost; not probed |
| C. RSS or specific feeds (e.g. eCourts, NCLT, SEBI orders) | Primary records with dates; also covers legal events | Narrow coverage, per-source work; not probed |
| Add-on to A: resolve `google.com/goto` links via a plain GET | Free, gives real URLs and page dates | Contacts google.com outside the ledger; Google may rate-limit or block it |

## Caveats

- 3 companies and a handful of queries: this shows a pattern, not a rate.
- Web Search results varied by query wording; other phrasing might surface aggregator pages.
