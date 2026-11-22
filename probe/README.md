# probe/

Crustdata audit scripts and reports (`REPORT.md`, `REPORT_registry_news.md`). Raw responses go to `probe/raw/` and are gitignored.

The probe scripts `client.py` and `step2.py` to `step5.py` call the API directly and **bypass the core ledger** (`core.cached_call`). Their spend is **not** in the core ledger; it is reported separately from `calls.jsonl` (see `REPORT.md`, section 5). `step6*.py` use `core.cached_call`, but their plain `requests.get` calls to google.com for redirect resolving are in no ledger.

Run them from the repo root with `CRUSTDATA_API_KEY` set in the environment. They never store the key.
