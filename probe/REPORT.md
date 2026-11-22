# Crustdata probe: what the API returns for Indian 3PL vendors

Run 2026-11-22. 10 Indian logistics companies chosen via Company Search. Raw responses are in `probe/raw/` (gitignored); every call is logged in `probe/calls.jsonl` (profile URLs redacted); code is `probe/client.py` and `probe/step{2..5}.py`. Person names are omitted on purpose.

**Sample.** Large: Delhivery, Ecom Express Ltd, DTDC Express Ltd. Mid: Everest Fleet, Future Supply Chain Solutions, ProConnect. Small (founded 2021): Xtrans Logistics, LorryCare. Lookalikes: Ecom Express Delivery Center (vs Ecom Express Ltd), Rapid Delivery (vs Delhivery).

**Step 1 notes.**
- Filters that worked: `locations.country="India"`, `basic_info.industries in [...]`, `headcount.total` ranges, `basic_info.year_founded`, fuzzy `basic_info.name (.)`.
- Autocomplete exact values: `"Transportation, Logistics, Supply Chain and Storage"`, `"Logistics & Supply Chain"`, `"Truck Transportation"`, `"Freight and Package Transportation"`, `"Transportation/Trucking/Railroad"`; category `"Freight Service"`. The country value is the full name `"India"`. It is free, but counts came back null.
- The industry filter is noisy (airlines, Indian Railways and airport services ranked high).
- Account limits are 5 requests/min for company, person and job endpoints and 10/min for web, stricter than the 30/15/10 in the brief. I followed the account's numbers. 4 early calls got 429 and succeeded on retry.

## 1. Field → endpoint → populated (of 10)

| Field needed | Endpoint / field | Populated | Notes |
|---|---|---|---|
| Legal name | `basic_info.name` | 10 | No separate legal-name field. |
| Domain | `basic_info.primary_domain` | 8 | Empty for DTDC and the lookalike delivery centre. |
| HQ city/state | `locations.city/state` | 10 | Messy: `city` is often a locality or junk ("DLF QE"). |
| Founding year | `basic_info.year_founded` | 9 | |
| Status | `basic_info.status` | 10 | `active`, or `deleted` (Rapid Delivery). The only "still exists" flag. |
| Headcount now | `headcount.total` | 10 | |
| Headcount history | `headcount.timeseries[]` | 10 | 155 to 365 dated points. Latest is 2026-11-02 to 11-16 for live firms; the deleted firm ends 2025-04. |
| Funding | `funding.total_investment_usd` | 4 | Zero or null for the other 6. |
| Leadership names/titles | `people.cxos/founders` | 6 (8 with any people) | Delhivery's `decision_makers` has 300 entries incl. recruiters. Small firms have 0 to 1. |
| Web traffic | `web_traffic.domain_traffic.*.monthly_visitors` | 5 | |
| Registry IDs (CIN/GSTIN) | none | **0** | I regex-searched the raw JSON. The only CIN hit was another firm's, inside a person's bio. |
| Last-refreshed date | none at company level | **0** | `metadata` is null. Only the last `timeseries` date, and `people[].basic_profile.last_updated` (null in Person Enrich). |
| Revenue | `revenue.estimated` | 10, useless | Ranges like $1B to $1T, or $0 to $0. |

**Identify.**
- It returns `basic_info` only, at 0.2 credits per match.
- By name, the top-1 was correct 9 of 10. Rapid Delivery had 3 records tied at 1.0 and the right one ranked 3rd, and DTDC had 2 tied at 1.0.
- Most name lookups return 25 candidates. The confidence score is therefore **not** an auto-accept signal.
- By domain (8 tried): 6 gave one correct match; Ecom Express gave 2 (both 1.0); `rapiddelivery.co` resolved to a **different company**. The right record is `status=deleted`.
- The lookalike scored 1.0 for itself and 0.6 for the real Ecom Express Ltd, which is correct.

**Jobs.**
- 90-day postings: Delhivery 59 (790 all-time), DTDC 5 (73), 0 for the other 8.
- Any postings ever: 6 of 10.
- `metadata.date_added` was present on every row returned, though older rows show `T00:00:00`. `total_count` gives the count.
- Small firms show nothing, so "no jobs" does not mean inactive.

**Directors.** 6 leaders (1 per company) were run through Person Enrich at 1 credit each.
- Titles, `start_date` and the employer name were populated 6/6. `current[].crustdata_company_id` matched the company ID 6/6, so the person-to-company link is machine-checkable. `end_date` is null for all.
- Currency is not reliable. For one Ecom Express CEO entry, the headline names a different firm while a 2015 role at Ecom Express is still "current".
- Embedded people inside Company Enrich lack titles and start dates in `experience`. You need Person Enrich for those.
- Same-name case: "Person F" in India returned 372 matches (8 retrieved, all different people; the LorryCare CEO is another). They are told apart by `crustdata_person_id`, `current[].crustdata_company_id`/`name`, `title`, `start_date`, `headline` and `location.raw`. `last_updated` is null.

**Adverse media.** 6 searches (5 companies, 1 director) and 11 fetches, with 0 timeouts.
- Search took 5.4s to 7.3s (one 40s outlier); fetch took 2.5s to 17.9s.
- **Most result URLs are Google redirects** (`google.com/goto?...`). Fetching them returned a Google "Verifying your request" page in 8 of 11 fetches. One fetch failed, and 2 returned real pages: a generic Facebook post not about the target, and a US court docket for a different person with a similar surname. A direct (non-redirect) LinkedIn post URL fetched fine but behind a login wall, with no parseable date.
- There is no date field. A date appears as a snippet prefix in only 13 of 41 results (e.g. "10 अप्रैल 2024 —"), sometimes in Hindi.
- Relevance: mostly customer complaints and scam warnings, not FIRs, court orders or regulator notices. "Everest Fleet" returned Everest Group consulting and an unrelated person. LorryCare returned 1 unrelated profile.
- A snippet is an excerpt, not a verified passage. Nothing was confirmed against a fetched page about the target.

## 2. Verdict per check

| Check | Verdict | Fallback |
|---|---|---|
| Exists | **Partial** | Crustdata gives a profile, `status`, headcount history and domain, but no legal registration. Use MCA21 or the GST portal, or a KYC-API vendor, keyed on the resolved name or domain. Human review when Identify has ties. |
| Active | **Partial** | Good for mid and large firms (headcount series, jobs with dates, traffic, `status`). Weak for small firms and there is no refresh stamp. Use GST filing status as a second signal. |
| Director match | **Partial** | Title, start date and a company-ID link are available for 6/10 companies, but there is no director-of-record (DIN) and current roles can be stale. Use MCA director master data. |
| Adverse media | **Partial, close to not possible as shipped** | Relevant complaints surface, but no dates, opaque redirect URLs, namesakes, and no court or FIR data. Use a news API or eCourts/NCLT/SEBI feeds for resolvable sources; use Crustdata Web Search only for discovery. |

## 3. Five call recipes

All use `POST https://api.crustdata.com<path>` with `authorization: Bearer $CRUSTDATA_API_KEY` and `x-api-version: 2025-11-01`.

1. **Resolve a name (0.2)** `/company/identify` `{"names":["Delhivery"]}` returns `[{"matched_on":"Delhivery","match_type":"name","matches":[{"confidence_score":1.0,"company_data":{"basic_info":{"crustdata_company_id":5798,"name":"Delhivery","primary_domain":"delhivery.com","year_founded":2011}}}]}]` (up to 25 matches). Review when 2 or more are at 1.0.
2. **Company profile (2)** `/company/enrich` `{"crustdata_company_ids":[5798],"fields":["basic_info","headcount","locations","funding","people","web_traffic"]}` returns `[0].matches[0].company_data` with `basic_info.status:"active"`, `headcount.total:35300`, `headcount.timeseries[-1]:{"date":"2026-11-16","employee_count":35295}` and `people.cxos[]`.
3. **Jobs in the last 90 days (0.03 per row)** `/job/search` `{"filters":{"op":"and","conditions":[{"field":"company.basic_info.company_id","type":"=","value":5798},{"field":"metadata.date_added","type":"=>","value":"2026-08-24"}]},"fields":["job_details.title","job_details.url","metadata.date_added"],"limit":3}` returns `{"total_count":59,"job_listings":[{"job_details":{"title":"Financial Analyst Internship"},"metadata":{"date_added":"2026-11-17T10:49:30"}}]}`.
4. **Director (1)** `/person/enrich` `{"professional_network_profile_urls":["<people.cxos[].social_handles.professional_network_identifier.profile_url>"],"fields":["basic_profile","experience"]}` returns `person_data.experience.employment_details.current[]` with `{"name":"Delhivery","title":"Co-Founder","start_date":"2011-04-01T00:00:00+00:00","end_date":null,"crustdata_company_id":5798}`.
5. **Adverse media (1 per search, 1 per URL)** `/web/search/live` `{"query":"<company> fraud OR scam OR default OR FIR OR blacklisted","sources":["web"],"location":"IN"}` returns `{"results":[{"position":1,"source":"web","title":"...","url":"https://www.google.com/goto?url=...","snippet":"..."}],"metadata":{"total_results":10}}`. Fetch is `/web/enrich/live` `{"urls":[...]}` returning `[{"success":true,"url":"...","title":"...","content":"<html>..."}]`. Skip `google.com/goto` URLs.

## 4. Gaps, ranked by impact on the "cannot verify" rate

1. **No registry IDs (CIN, GSTIN, DIN):** 0/10, so "exists" and "director match" cannot be fully verified from Crustdata alone.
2. **Adverse-media URLs are opaque and undated:** 8/11 fetches were blocked, and 28 of 41 snippets carry no date.
3. **Thin data for small and new firms:** no funding, jobs or traffic, 0 to 1 people, and 2 of 10 had no domain. These are the vendors a 3PL most needs to clear.
4. **Ambiguous entity resolution:** ties at 1.0, 25 candidates, and one domain pointing to the wrong company.
5. **No refresh timestamps, and stale "current" roles.**
6. Messy HQ strings, a noisy industry filter, and revenue ranges with no information.

## 5. Spend

**85 calls, 61.35 credits** (cap 150), from `probe/calls.jsonl`.

| Endpoint | Calls | Credits |
|---|---|---|
| `/company/enrich` | 10 | 20 |
| `/web/enrich/live` | 7 | 12 |
| `/company/search` | 7 | 11.35 |
| `/web/search/live` | 7 | 7 |
| `/person/enrich` | 6 | 6 |
| `/company/identify` | 18 | 3.6 |
| `/person/search` | 1 | 1.04 |
| `/job/search` | 20 | 0.36 |
| autocomplete | 9 | 0 |

4 calls were 429 (billed 0) and retried. 0 timed out. The `/company/search` spend was high because my first three queries requested the premium `headcount` group.
