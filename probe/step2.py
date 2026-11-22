import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from client import call
S = json.load(open(pathlib.Path(__file__).parent / "sample.json"))
FIELDS = ["basic_info","headcount","funding","locations","taxonomy","revenue","hiring","followers","seo",
          "competitors","social_profiles","web_traffic","employee_reviews","people","news","software_reviews",
          "public_launches","market_intel","reviews"]
for c in S:
    k = c["id"]
    call("/company/identify", {"names": [c["name"]]}, f"step2_identify_name_{k}")
    if c["domain"]:
        call("/company/identify", {"domains": [c["domain"]]}, f"step2_identify_domain_{k}")
    call("/company/enrich", {"crustdata_company_ids": [k], "fields": FIELDS}, f"step2_enrich_{k}")
print("done")
