import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from client import call
RISK = "fraud OR scam OR default OR FIR OR blacklisted"
targets = [("delhivery", "Delhivery"), ("ecomexpress", "Ecom Express"), ("dtdc", "DTDC Express"),
           ("everestfleet", "Everest Fleet"), ("lorrycare", "LorryCare"), ("director_person_c", "Person C DTDC")]
for tag, q in targets:
    s, d, r = call("/web/search/live", {"query": f"{q} {RISK}", "sources": ["web"], "location": "IN"}, f"step5_search_{tag}", timeout=120)
    urls = [x["url"] for x in (d or {}).get("results", [])[:2]] if s == 200 and isinstance(d, dict) else []
    if urls:
        call("/web/enrich/live", {"urls": urls}, f"step5_fetch_{tag}", timeout=120)
print("done")
