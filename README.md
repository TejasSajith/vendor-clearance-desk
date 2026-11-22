# Unmask

**Know who you're doing business with.**

Unmask helps businesses make more informed decisions about the suppliers and carriers they work with. It brings together company information, activity checks, people searches and negative news reports to help assess a vendor before onboarding.

Built for the **Trust and Compliance** track at ContextCon, in collaboration with Crustdata.

## 1. The service

A mid-sized Indian logistics company works with multiple carriers, transport partners and suppliers. Before onboarding a new vendor, its procurement and compliance teams need to establish whether the business is genuine, whether it is still operating, who is associated with it and whether there are any concerning reports about it.

Today, this often means jumping between company databases, people searches, job listings and news articles, trying to piece together information that may be incomplete or inconsistent. The process takes time, depends heavily on manual research and can lead to important details being overlooked.

Unmask brings these checks together in one place. A team member enters a vendor's details, and the system gathers information from Crustdata, evaluates the findings using fixed rules and produces a recommendation with supporting reasons.

The aim is to reduce repetitive research, make vendor screening more consistent and give procurement teams a clearer basis for their decisions. Unmask is designed for organisations with recurring screening requirements, with a focus on logistics companies and their supplier networks.

## 2. What it does now

![Unmask workflow](<Unmask_ Vendor Trust Check.png>)

A user enters a vendor name. They can also provide a website, a claimed director and a risk level.

Unmask uses Crustdata to run four checks:

| Check | API / data | What it looks for |
|---|---|---|
| **Find the company** | Company Identify | Finds and matches the right company using its name and website |
| **Check the vendor** | Company Enrich + Job Search | Looks at company status, employee numbers, hiring and other signs of activity |
| **Check the claimed director** | Person Search / Enrich | Checks whether the person's profile is linked to the company |
| **Look for negative reports** | Web Search API | Searches for reports about fraud, legal issues and compliance concerns |

The findings are combined using fixed rules to produce one of four recommendations:

- `CLEARED` — available information supports clearing the vendor.
- `REJECTED` — evidence supports rejecting the vendor.
- `CANNOT_VERIFY` — there isn't enough information to reach a conclusion.
- `HOLD_FOR_APPROVAL` — a source could not be reached or the case needs review.

Each check can pass, fail, remain uncertain or be marked unreachable. Missing information is not automatically treated as a negative finding. If a source fails, the system holds the case rather than assuming everything is fine.

A person reviews and approves recommendations before any resulting action is carried out. This gives procurement teams a structured starting point for their decision, along with the ability to review uncertain or concerning findings.

## 3. What we're building

We're building Unmask into a service that helps organisations screen suppliers and carriers whenever they need to bring a new business partner onboard.

Our current priorities are:

- **Company records:** Add independent records to check company registration details, including CIN and GSTIN.
- **Evidence behind decisions:** Make it easier for reviewers to trace findings back to their original sources.
- **Reliable checks:** Ensure runs can recover from interruptions, actions aren't repeated and API usage stays within limits.

The intended business model is to offer vendor screening as a service, through per-screening or subscription-based pricing. Actual API costs, additional verification costs and the time spent by reviewers will help determine viable pricing.

## 4. How it runs

Unmask is built in Python. A central pipeline coordinates Crustdata API calls, collects the returned information and passes it through the decision rules.

```text
Vendor request
      |
      v
  pipeline.py
      |
      +-- Company Identify
      +-- Company Enrich + Job Search
      +-- Optional Person Search
      +-- Web Search
      |
      v
   policy.py
      |
      v
  decision.py
      |
      v
 Recommendation
      |
      v
 Human approval
```

The code is organised into a few main components:

| Component | What it does |
|---|---|
| `pipeline.py` | Validates the request and runs the checks |
| `checks/` | Connects to Crustdata and processes the returned information |
| `policy.py` | Applies fixed rules to each check |
| `decision.py` | Produces the final recommendation |
| `core.py` | Manages saved data, API usage, retries, recovery and approvals |
| `evaluation/` | Contains test cases and evaluation tools |

**Keeping runs reliable**

SQLite stores the progress of each request, allowing a run to continue from where it stopped after an interruption. API calls are tracked, cached and rate-limited. Each run has a limit of 50 Crustdata credits and 300 seconds.

Actions are also tracked to prevent the same action from being carried out twice. The core includes an evidence ledger that requires a source link and passage when recording a fact, providing the foundation for traceable recommendations.

### Run locally

**Requirements:** Python and a Crustdata API key.

```bash
git clone https://github.com/prishasinghal1/contextcon.git
cd contextcon
pip install -r requirements.txt
export CRUSTDATA_API_KEY="your_api_key"
```

Run the tests:

```bash
python -m pytest -q
```

Start the local development console:

```bash
python devconsole/app.py
```

Open `http://127.0.0.1:8765`.

The development console lets you experiment with decision rules, test cases and approval/recovery scenarios. It uses simulated information; live vendor checks run through the Python pipeline.

## 5. What we tried

We tested Crustdata against 10 Indian logistics companies of different sizes, including businesses with similar names.

- **Company search:** The correct company appeared as the top name match in 9 out of 10 cases. Similar names, tied results and incorrect domain matches required additional matching logic.
- **Company activity:** Employee history was available across the sample, but smaller companies often had no recent job postings. Missing job postings cannot establish that a company is inactive.
- **People search:** Person data provided employment titles, start dates and company IDs, allowing us to check employment links. These links do not establish legal directorship.
- **Web search:** We found potentially relevant reports alongside unrelated companies, redirect URLs and missing publication dates.

These experiments helped us understand the strengths and limitations of the available data and shaped how each check is evaluated.

## 6. Why this way

A vendor screening decision can have real financial and operational consequences. A wrong rejection can cost a business a supplier, while a false clearance can expose it to risk.

Our design choices reflect this:

- **Fixed rules:** Recommendations follow explicit conditions and remain consistent and inspectable.
- **Source tracking:** Findings are designed to be traceable to the information they came from.
- **Explicit uncertainty:** Missing, conflicting or inconclusive information has its own outcome.
- **Human approval:** A person remains responsible for consequential decisions.
- **Recovery:** SQLite persistence, retries and tracked actions help runs recover without repeating completed work.
- **Cost limits:** Every API call is tracked, with a fixed time and credit budget for each run.

Unmask aims to reduce the time teams spend gathering information, so they can focus on reviewing findings and making better decisions.

---
