# SIH demo script

All numbers below are what the app computes from the synthetic demo dataset. Say so once, early: "demand, costs and yields here are illustrative; the qualification data is real."

## Before you start

```bash
docker compose up --build      # or run the backend and open http://localhost:8000
```

Works offline. Open http://localhost:8000.

## Two minutes

| # | Do | Say |
|---|---|---|
| 1 | **Shortage Explorer.** Maharashtra → Pune → Electric Vehicle Service Technician are preselected. | "The forecast says Pune needs 1,543 EV service technicians over 18 months and the existing pipeline gives 288. Shortage 1,255, and it could be anywhere from 629 to 1,640." |
| 2 | Click **Resolve gap →**. Point at the left box. | "The usual answer is seats. Closing this with seats alone needs 3,923 seats and ₹23.5 crore. Capacity allows 800, so we get 256 workers, and the first one arrives in month 13." |
| 3 | Point at the right box and the four cards. | "Same ₹6 crore. The optimiser mixes four interventions and delivers 900 workers, 650 of them by month 4." |
| 4 | Point at the timeline chart. | "Green is our plan, grey is seats only." |
| 5 | Click **LOW**. | "Now suppose demand comes in low. New seats drop to zero. The gap closes for ₹1.27 crore." |
| 6 | Point at **What to commit now, what to defer**. | "So the system tells the planner: launch the bridge course, neighbouring supply and apprenticeships now, because they are needed in every scenario. Hold the seat sanction. If we had committed to seats and demand came in low, that is ₹4.7 crore of regret." |
| 7 | Click **Why these trades? →** on the bridge card. | "Why can a four-wheeler technician bridge into EV servicing? From the real qualification register: four service standards match, and one does not, high-voltage safety, 180 hours. That unmatched part is the bridge course." |
| 8 | Back to the resolver, **Export plan (CSV)**. | "This is the line that goes into the district skill plan." |

## If there is time

- Tick **Service Technician (Heavy Motor Vehicle)** under "Plan together". Both shortages now compete for the same four-wheeler graduates and the same budget.
- Open **Assumptions**, change the new-seat cost or the adjacency threshold, and the plan re-solves. Every value shows whether it is synthetic, modelled or estimated.
- Set the horizon to 12: new seats disappear because they need 13 months, and the explanation says so.

## Likely questions

| Question | Answer |
|---|---|
| "Skill India already has data." | It has registrations and certificates. The CAG's PMKVY audit found no job-role-level skill-gap information and training not aligned to gap studies. We turn a gap into an allocation. |
| "This is just a dashboard." | The optimiser runs without the UI: `POST /api/resolve` returns the plan. The UI shows a decision, not a chart of the gap. |
| "Forecasting already exists." | Agreed, and it is not our claim. Our claim starts after the forecast. |
| "Why not Excel?" | One shortage is fine in Excel. Several shortages sharing one budget and the same surplus graduates, across four intervention types, is a linear programme. |
| "What is the AI?" | Sentence embeddings match occupational standards between qualifications; a back-tested forecast gives the scenarios; a linear programme chooses the plan. No language model writes any number. |
| "What if the forecast is wrong?" | That is the point of the no-regret split. Short interventions are launched; the slow, irreversible one waits for the next demand update. |
| "Where is the data from?" | Qualifications: the public National Qualifications Register, 480 of them. Demand, costs, yields, surplus: synthetic and labelled, because no official source publishes them at district-trade level. |
| "Is the adjacency right?" | It is an estimate from standard titles. A desk review of 51 pairs agreed on 42 and found nine real neighbours the model missed. It needs expert review, and the UI says so. |
| "Is this unique?" | Skill adjacency and optimisation are both established. We found no public system or SIH repository in our search that optimises a mix of intervention types for a district-trade shortage. |

## Do not say

First in the world; nobody has done this; we invented skill adjacency; real-time NCS or SIDH data; official district demand; observed mobility; validated bridge durations; "900 versus 256" as a real-world result.

## A note on trade names

The register has no trade called "Motor Vehicle Mechanic" among the scraped trainee qualifications (the *Mechanic Motor Vehicle* record there is the instructor qualification). The demo's bridge source is the register's **Four Wheeler Service Technician**.
