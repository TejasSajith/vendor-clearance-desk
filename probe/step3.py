import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from client import call
S = json.load(open(pathlib.Path(__file__).parent / "sample.json"))
F = ["job_details.title","job_details.url","company.basic_info.name","location.raw","metadata.date_added"]
for c in S:
    k = c["id"]
    cid = {"field":"company.basic_info.company_id","type":"=","value":k}
    call("/job/search", {"filters":{"op":"and","conditions":[cid,{"field":"metadata.date_added","type":"=>","value":"2026-08-24"}]},
                         "fields":F,"sorts":[{"field":"metadata.date_added","order":"desc"}],"limit":3}, f"step3_jobs90_{k}")
    call("/job/search", {"filters":cid,"fields":F,"sorts":[{"field":"metadata.date_added","order":"desc"}],"limit":1}, f"step3_jobsall_{k}")
print("done")
