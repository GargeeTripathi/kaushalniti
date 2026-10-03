# Release notes

## v1.0.0 — SIH demo release

What is in it:

- **Skill Gap Resolver.** Scenario linear programme over new seats, bridge courses, neighbouring-district supply and apprenticeships, with budget, capacity, shared-surplus and deadline constraints. Seats-only baseline, regret, no-regret / contingent split, workers-by-month timeline, residual-gap explanation.
- **Bridgeability graph.** 93 edges into eight demo trades, built from 480 real qualifications scraped from the National Qualifications Register, using sentence embeddings of technical occupational standards.
- **Forecast.** Damped Holt forecast with LOW / MEDIAN / HIGH from a rolling-origin back-test.
- **API.** Seven FastAPI endpoints with validation and OpenAPI docs.
- **UI.** Shortage Explorer, Skill Gap Resolver, Bridgeability Graph; editable assumptions with provenance; CSV export.
- **Offline demo dataset.** Seven Maharashtra districts, eight trades, deterministic and labelled synthetic.

### Test report

| Suite | Result |
|---|---|
| Backend (`pytest`): optimiser 18, forecast 7, adjacency 9, API and end-to-end 26 | 60 passed |
| Frontend (`vitest`): screens, API integration, overrides, CSV export | 4 passed |
| Frontend production build (`tsc` + `vite build`) | passed |
| Manual: three screens rendered in headless Chrome against the live API | passed (screenshots in `docs/screenshots/`) |
| Docker image build | **not run locally** (Docker Desktop would not start on the development machine); covered by the `docker` job in CI |

### Known limitations

See the Limitations section of the README. In short: demo demand, costs, yields and surplus are synthetic; adjacency is title-based and not expert-validated; mobility is modelled; one state and eight trades.
