# Methodology

Three models, in the order data flows through them. The optimiser is the product; the forecast and the graph feed it.

## 1. Forecast and scenarios (`forecast.py`)

- **Model:** damped Holt linear trend on the monthly openings series (damping 0.95). The two smoothing weights are picked from a small grid by one-step-ahead squared error.
- **Median demand:** the sum of the forecast over the planning horizon.
- **Band:** forecast from every origin that has at least 24 months of history and a full horizon after it, and record `actual / forecast − 1` for the horizon total. LOW and HIGH are the median scaled by the 10th and 90th percentile of those errors. With fewer than five back-test origins a default ±25% band is used and labelled.
- **Gap:** `max(0, demand − pipeline supply)`, where pipeline supply is `annual seats × pipeline yield × horizon / 12`.

The demo series is synthetic, so the band describes that series only. It is not real-world forecast accuracy.

## 2. Bridgeability graph (`adjacency.py`)

Skill adjacency is prior art (Nesta Career Causeways, Jobs and Skills Australia's Skills Transitions data, SkillsFuture's CareersFinder and others). What is done here is applying it to the Indian qualification register so that it can drive the optimiser.

For a source qualification S and target qualification T:

1. **Technical standards.** A standard is dropped as generic if its title matches a generic pattern (employability, workplace health and safety, teamwork, communication, on-the-job training, introduction modules), if its code belongs to the cross-sector employability series, or if its code appears in more than 4% of all qualifications. Code series alone are not used: `ASC/N9846` "High voltage and fire safety practices" sits in a generic-looking series but is a core EV skill.
2. **Similarity.** Standard titles are embedded with `sentence-transformers/all-MiniLM-L6-v2`. Each target standard takes its best cosine similarity over the source's standards. An identical standard code counts as similarity 1.
3. **Match.** A target standard is matched if its best similarity is at least 0.60.
4. **Score** `a(S,T)` = matched target hours ÷ all target technical hours.
5. **Bridge hours** `h(S,T)` = hours of unmatched target standards + Σ over matched standards of `hours × (1 − similarity)`.
6. **Eligibility for the optimiser:** score ≥ adjacency threshold (0.6 in the demo), same sector, and source at most one NSQF level below the target. Text similarity alone gave false positives where standards are worded generically (a CNC programmer also "assists in routine maintenance"); the two guards remove those.

Trainer and assessor qualifications are excluded as sources. The graph is built once and cached in `data/processed/adjacency.json`; the running app never loads the embedding model. Without sentence-transformers installed, the builder falls back to TF-IDF (match threshold 0.35).

### Review of 51 pairs

`data/metadata/adjacency_validation.csv` lists, for each of the eight demo trades, its five strongest and two weakest stored sources, with a judgement and a reason. `scripts/validate_adjacency.py` compares the model with those judgements:

| | Reviewer accepts | Reviewer rejects |
|---|---|---|
| Model eligible | 22 | 0 |
| Model not eligible | 9 | 20 |

Read this with care:
- The judgements are an AI-assisted desk review, not a subject-expert review.
- The sector and level guards were added after false positives were seen in this same sample, so the zero in the top-right cell is optimistic.
- The nine misses are real weaknesses: for example *Assistant Electrician → Electrician* scores 0.47 because the two qualifications word their standards differently.

Bridge hours are estimates. They are not validated course lengths.

## 3. Skill Gap Resolver (`resolver.py`)

### Sets

- Shortage cells `c = (district, trade)`. One or several, planned together.
- Pathways `p`. Each supplies one cell and has a kind: new seats, apprenticeship, bridge from one source trade, or supply from one neighbouring district.
- Scenarios `s ∈ {LOW, MEDIAN, HIGH}`.

### Parameters

| Symbol | Meaning | Demo status |
|---|---|---|
| `D(c,s)` | Demand over the horizon | Modelled on synthetic series |
| `S0(c)` | Existing pipeline supply | Synthetic |
| `y(p)` | Yield: share of starters who become workers | Synthetic |
| `L(p)` | Lead time in months | Synthetic; estimated from bridge hours for bridges |
| `k(p)` | Cost per starter | Synthetic; bridge hours × cost per hour for bridges |
| `U(i,c)` | Capacity of intervention kind `i` for cell `c` | Synthetic |
| `P(j,d)` | Surplus graduates of trade `j` in district `d` | Synthetic |
| `a(j,k)`, `h(j,k)` | Adjacency score and bridge hours | Estimated from the register |
| `m(e,d)` | Reachable share of district `e`'s surplus from `d` = `exp(−distance / decay)` | Modelled |
| `B` | Budget | Planner input |
| `π` | Penalty per unmet worker | Synthetic |

### Decision variables

`x(p) ≥ 0` starters on pathway `p`; `u(c,s) ≥ 0` unmet demand.

### Objective

```
minimise   Σ_s w(s) · Σ_c π · u(c,s)   +   Σ_p k(p) · x(p)
```

`w` is 1 for a single scenario (the LOW, MEDIAN and HIGH plans) or the scenario probabilities (the probability-weighted plan).

### Constraints

```
residual gap   u(c,s) ≥ D(c,s) − S0(c) − Σ_{p for c} y(p) · x(p)
budget         Σ_p k(p) · x(p) ≤ B
capacity       Σ_{p of kind i for c} x(p) ≤ U(i,c)
shared pools   Σ_{p drawing on pool (j,d)} x(p) ≤ P(j,d)
reach          x(p) ≤ m(e,d) · P(k,e)          for neighbour pathways
deadline       x(p) = 0  if  L(p) > horizon
```

The pool constraint sums over every pathway that draws on the pool, across cells. A bridge from Four Wheeler Service Technician into EV servicing and another into heavy-vehicle servicing take from the same graduates, and so does another district drawing on them as neighbour supply. This coupling, with the single budget, is why the plan needs an optimiser rather than a ranking rule.

### Why a linear programme

- Min-cost flow does not fit: yields shrink the flow and the budget is a side constraint.
- Integer programming is not needed: the LP is solved in people, rounded down (always feasible), and a fractional pathway is rounded up when that breaks no constraint.
- Robust or multi-stage stochastic optimisation would be harder to explain and adds little with three scenarios.

Solver: HiGHS through `scipy.optimize.linprog`.

### Scenario comparison

- **Regret** of plan `x` in scenario `s` = `cost(x) + π · unmet(x, s)` − the LP optimum for `s`.
- **No-regret starters** of a pathway = the minimum it gets across the LOW, MEDIAN and HIGH plans. **Contingent starters** = maximum − minimum.
- The recommendation is: launch the no-regret part now, defer the contingent part to the next demand update.

### Seats-only baseline

Seats required = `⌈gap / yield⌉`. Seats possible = the least of that, the seat capacity and `⌊budget / cost⌋`, or zero if seats cannot deliver within the horizon. The baseline is given the whole budget.

### Timeline

Each pathway delivers `y · x` workers at month `L`. Intake batches are not modelled.

### Residual gap explanation

When demand is not fully met, the reasons shown are read from the solved plan: budget fully committed, a capacity reached, a surplus pool exhausted, or a pathway excluded by the deadline.
