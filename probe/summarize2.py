import json, pathlib, re
P = pathlib.Path(__file__).parent; R = P / "raw"
S = json.load(open(P / "sample.json"))
CIN = re.compile(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b"); GST = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
def L(x): return len(x) if isinstance(x, (list, dict)) else (0 if x in (None, "") else 1)
for c in S:
    k = c["id"]; raw_t = (R / f"step2_enrich_{k}.json").read_text()
    cd = json.loads(raw_t)[0]["matches"][0]["company_data"]
    b = cd.get("basic_info") or {}; l = cd.get("locations") or {}; h = cd.get("headcount") or {}; f = cd.get("funding") or {}
    pe = cd.get("people") or {}; w = cd.get("web_traffic") or {}; hi = cd.get("hiring") or {}; ts = h.get("timeseries") or []
    print(f"## {k} {c['name']} [{c['bucket']}]")
    print(f"  name={b.get('name')!r} domain={b.get('primary_domain')!r} web={b.get('website')!r} status={b.get('status')} type={b.get('company_type')} founded={b.get('year_founded')} range={b.get('employee_count_range')}")
    print(f"  loc: city={l.get('city')!r} state={l.get('state')!r} country={l.get('country')!r} hq={str(l.get('headquarters'))[:50]!r} street={bool(l.get('street_address'))}")
    print(f"  headcount.total={h.get('total')} timeseries_n={len(ts)} first={ts[0] if ts else None} last={ts[-1] if ts else None}")
    print(f"  funding: total_inv={f.get('total_investment_usd')} rounds={f.get('num_funding_rounds')} last={f.get('last_round_type')} {f.get('last_fundraise_date')} investors={L(f.get('investors'))}")
    print(f"  people: " + ", ".join(f"{g}={L(v)}" for g, v in pe.items()))
    print(f"  web_traffic keys={list(w.keys()) if isinstance(w, dict) else w} hiring.openings={hi.get('openings_count')} titles={str(hi.get('recent_titles_csv'))[:60]!r}")
    print(f"  top-level keys with metadata: updated_at? {[x for x in cd if x in ('metadata','updated_at','indexed_at')]} meta={cd.get('metadata')}")
    print(f"  registry: CIN={sorted(set(CIN.findall(raw_t)))} GSTIN={sorted(set(GST.findall(raw_t)))} liname={b.get('professional_network_url')}")
