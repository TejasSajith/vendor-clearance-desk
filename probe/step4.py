import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from client import call
# leaders picked from the leadership (people.cxos / people.founders) in Step 2 company enrich output
L = [(5798,"Person A","<redacted-profile-url>"),
     (5967,"Person B","<redacted-profile-url>"),
     (2037562,"Person C","<redacted-profile-url>"),
     (8276,"Person D","<redacted-profile-url>"),
     (20487,"Person E","<redacted-profile-url>"),
     (3917119,"Person F","<redacted-profile-url>")]
for cid, name, url in L:
    call("/person/enrich", {"professional_network_profile_urls": [url], "fields": ["basic_profile","experience"]}, f"step4_person_enrich_{cid}")
# same-name case: two different people called Person F in India
call("/person/search", {"filters": {"op":"and","conditions":[
        {"field":"basic_profile.name","type":"=","value":"Person F"},
        {"field":"professional_network.location.raw","type":"(.)","value":"India"}]},
     "fields": ["crustdata_person_id","basic_profile","experience.employment_details.current"], "limit": 8}, "step4_person_search_person_f")
print("done")
