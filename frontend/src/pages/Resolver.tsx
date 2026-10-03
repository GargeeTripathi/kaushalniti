import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Card, Gap, Meta, num, ResolveResult, rupees, Scenario, SCENARIOS } from "../api";
import type { Selection } from "../App";

interface Props {
  meta: Meta;
  sel: Selection;
  onChange: (s: Selection) => void;
  onGraph: () => void;
}

const CLASS_TEXT: Record<Card["class"], string> = {
  NO_REGRET: "No-regret: launch now",
  CONTINGENT: "Contingent: defer",
  MIXED: "Part no-regret, part contingent",
  NOT_USED: "Not used",
};

// "interventions.bridge.cost" -> { interventions: { bridge: { cost } } }; other keys stay flat
export function toOverrides(edits: Record<string, number>) {
  const out: Record<string, unknown> = {};
  const iv: Record<string, Record<string, number>> = {};
  for (const [key, value] of Object.entries(edits)) {
    const [head, kind, field] = key.split(".");
    if (head === "interventions") (iv[kind] ??= {})[field] = value;
    else out[key] = value;
  }
  if (Object.keys(iv).length) out.interventions = iv;
  return out;
}

export function planCsv(r: ResolveResult): string {
  const head = [
    "state", "district", "trade", "forecast_gap", "budget_inr", "horizon_months", "scenario", "intervention", "pathway",
    "starters", "expected_workers", "cost_inr", "lead_time_months", "class", "no_regret_starters", "contingent_starters", "source_status",
  ];
  const rows = r.plan.pathways
    .filter((p) => p.starters > 0 || p.contingent_starters > 0)
    .map((p) => [
      r.cell.state, p.district, p.trade, r.shortage[r.scenario], r.budget, r.horizon, r.scenario, p.label, p.id,
      p.starters, p.workers_delivered, p.cost, p.lead_time_months, p.class, p.no_regret_starters, p.contingent_starters, p.status,
    ]);
  const cell = (v: unknown) => `"${String(v).replace(/"/g, '""')}"`;
  return [head, ...rows].map((row) => row.map(cell).join(",")).join("\n");
}

function download(name: string, text: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function Resolver({ meta, sel, onChange, onGraph }: Props) {
  const [scenario, setScenario] = useState<Scenario>("MEDIAN");
  const [edits, setEdits] = useState<Record<string, number>>({});
  const [coplan, setCoplan] = useState<string[]>([]);
  const [others, setOthers] = useState<Gap[]>([]);
  const [result, setResult] = useState<ResolveResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [crore, setCrore] = useState(String(sel.budget / 1e7));

  // other shortages in the same district that could be planned together
  useEffect(() => {
    setCoplan([]);
    api
      .gaps(sel.state, sel.district, sel.horizon)
      .then((r) => setOthers(r.cells.filter((c) => c.trade !== sel.trade && c.shortage.MEDIAN > 0)))
      .catch(() => setOthers([]));
  }, [sel.state, sel.district, sel.trade, sel.horizon]);

  // every input change re-runs the optimiser on the server
  useEffect(() => {
    let stale = false;
    setBusy(true);
    api
      .resolve({
        state: sel.state, district: sel.district, trade: sel.trade, budget: sel.budget, horizon: sel.horizon, scenario,
        include_cells: coplan.map((trade) => ({ district: sel.district, trade })),
        overrides: toOverrides(edits),
      })
      .then((r) => {
        if (stale) return;
        setResult(r);
        setError("");
      })
      .catch((e) => !stale && setError(e.message))
      .finally(() => !stale && setBusy(false));
    return () => {
      stale = true;
    };
  }, [sel, scenario, edits, coplan]);

  const applyBudget = () => {
    const v = Number(crore);
    if (v > 0) onChange({ ...sel, budget: v * 1e7 });
  };

  if (!result) return error ? <p className="error">{error}</p> : <p>Running optimiser…</p>;

  const r = result;
  const gap = r.shortage[r.scenario];
  const seats = r.seats_only;
  const timeline = r.plan.timeline.map((v, m) => ({ month: m, resolver: v, seats: seats.timeline[m] }));
  const perWorker = (cost: number, workers: number) => (workers > 0 ? rupees(cost / workers) : "–");

  return (
    <div className={busy ? "busy" : ""}>
      <section className="panel controls">
        <div>
          <div className="muted">Shortage cell</div>
          <b>
            {r.cell.trade}, {r.cell.district}
          </b>
        </div>
        <label>
          Budget (₹ crore)
          <input type="number" min={0.01} step={0.5} value={crore} onChange={(e) => setCrore(e.target.value)} onBlur={applyBudget}
            onKeyDown={(e) => e.key === "Enter" && applyBudget()} />
        </label>
        <label>
          Horizon (months)
          <input type="number" min={1} max={60} value={sel.horizon}
            onChange={(e) => onChange({ ...sel, horizon: Math.min(60, Math.max(1, Number(e.target.value) || 1)) })} />
        </label>
        <div>
          <div className="muted">Demand scenario</div>
          <div className="segmented" role="group" aria-label="Demand scenario">
            {SCENARIOS.map((s) => (
              <button key={s} className={s === scenario ? "active" : ""} onClick={() => setScenario(s)}>
                {s} · {num(r.shortage[s])}
              </button>
            ))}
          </div>
        </div>
      </section>

      {error && <p className="error">{error}</p>}

      <section className="panel">
        <h2>
          Shortage: {num(gap)} workers <span className="muted">({r.scenario} scenario; range {num(r.shortage.LOW)}–{num(r.shortage.HIGH)})</span>
        </h2>
        <p className="muted">
          Forecast demand {num(r.forecast.demand[r.scenario])} minus existing pipeline supply {num(r.baseline_supply)}, over {r.horizon} months.
        </p>
        <div className="compare">
          <div className="side">
            <h3>Seats only</h3>
            <dl>
              <dt>Seats needed to close the gap</dt>
              <dd>{num(seats.seats_required)}</dd>
              <dt>Cost of that many seats</dt>
              <dd>{rupees(seats.cost_required)}</dd>
              <dt>First workers</dt>
              <dd>month {seats.lead_time_months}</dd>
              <dt>Seat capacity available</dt>
              <dd>{num(seats.capacity)}</dd>
              <dt>Seats actually possible{seats.binding.length ? ` (limited by ${seats.binding.join(", ")})` : ""}</dt>
              <dd>{num(seats.seats_feasible)}</dd>
              <dt>Cost</dt>
              <dd>{rupees(seats.cost)}</dd>
              <dt>Workers delivered</dt>
              <dd className="big">{num(seats.workers_delivered)}</dd>
              <dt>Cost per worker</dt>
              <dd>{perWorker(seats.cost, seats.workers_delivered)}</dd>
              <dt>Residual shortage</dt>
              <dd>{num(seats.residual_gap)}</dd>
            </dl>
          </div>
          <div className="side win">
            <h3>Skill Gap Resolver</h3>
            <dl>
              <dt>Interventions used</dt>
              <dd>{r.plan.interventions.filter((c) => c.starters > 0).length} of 4</dd>
              <dt>Budget</dt>
              <dd>{rupees(r.budget)}</dd>
              <dt>First workers</dt>
              <dd>{r.plan.timeline.findIndex((v) => v > 0) >= 0 ? `month ${r.plan.timeline.findIndex((v) => v > 0)}` : "–"}</dd>
              <dt>Cost</dt>
              <dd>{rupees(r.plan.cost_this_cell)}</dd>
              <dt>Workers delivered</dt>
              <dd className="big">{num(r.plan.workers_delivered)}</dd>
              <dt>Cost per worker</dt>
              <dd>{perWorker(r.plan.cost_this_cell, r.plan.workers_delivered)}</dd>
              <dt>Residual shortage</dt>
              <dd>{num(r.plan.residual_gap)}</dd>
            </dl>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Recommended intervention mix</h2>
        <div className="cards">
          {r.plan.interventions.map((c) => (
            <div key={c.kind} className={`card ${c.class.toLowerCase()}`}>
              <h3>{c.label}</h3>
              <div className="big">{num(c.workers_delivered)} workers</div>
              <dl>
                <dt>Starters</dt>
                <dd>{num(c.starters)}</dd>
                <dt>Cost</dt>
                <dd>{rupees(c.cost)}</dd>
                <dt>Lead time</dt>
                <dd>{c.lead_time_months === null ? "–" : `${c.lead_time_months} mo`}</dd>
                <dt>Capacity</dt>
                <dd>{num(c.capacity)}</dd>
              </dl>
              <div className="tag">{CLASS_TEXT[c.class]}</div>
              {!c.available && <div className="muted">No eligible pathway for this cell.</div>}
              <div className="badge">{c.status}</div>
              {c.kind === "bridge" && (
                <button className="link" onClick={onGraph}>
                  Why these trades? →
                </button>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Workers delivered by month</h2>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={timeline}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" label={{ value: "month", position: "insideBottomRight", offset: -4 }} />
            <YAxis />
            <Tooltip />
            <Legend />
            <Line type="stepAfter" dataKey="seats" name="Seats only" stroke="#8c8c8c" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line type="stepAfter" dataKey="resolver" name="Skill Gap Resolver" stroke="#1f7a4d" strokeWidth={3} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
        <p className="muted">Additional workers on top of the existing pipeline. Each pathway delivers its cohort at its lead time.</p>
      </section>

      <section className="panel">
        <h2>What to commit now, what to defer</h2>
        <p className="recommend">{r.actions.recommendation}</p>
        <table>
          <thead>
            <tr>
              <th>Intervention (starters)</th>
              {SCENARIOS.map((s) => (
                <th key={s} className={s === r.scenario ? "r selected" : "r"}>
                  {s}
                </th>
              ))}
              <th className="r">No-regret</th>
              <th className="r">Contingent</th>
            </tr>
          </thead>
          <tbody>
            {r.plan.interventions.map((c) => (
              <tr key={c.kind}>
                <td>{c.label}</td>
                {SCENARIOS.map((s) => (
                  <td key={s} className={s === r.scenario ? "r selected" : "r"}>
                    {num(r.scenarios[s].starters_by_kind[c.kind])}
                  </td>
                ))}
                <td className="r">{num(c.no_regret_starters)}</td>
                <td className="r">{num(c.contingent_starters)}</td>
              </tr>
            ))}
            <tr className="total">
              <td>Plan cost</td>
              {SCENARIOS.map((s) => (
                <td key={s} className="r">
                  {rupees(r.scenarios[s].total_cost)}
                </td>
              ))}
              <td colSpan={2} />
            </tr>
          </tbody>
        </table>
        <h3>Regret if a plan is chosen and a different scenario happens</h3>
        <table>
          <thead>
            <tr>
              <th>Plan chosen</th>
              {SCENARIOS.map((s) => (
                <th key={s} className="r">
                  if {s} happens
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(r.regret).map(([plan, row]) => (
              <tr key={plan}>
                <td>{plan === "EXPECTED" ? "Probability-weighted plan" : `Plan for ${plan}`}</td>
                {SCENARIOS.map((s) => (
                  <td key={s} className="r">
                    {rupees(row[s])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">Regret = plan cost + unmet-demand penalty, minus the best achievable for that scenario.</p>
      </section>

      <section className="panel">
        <h2>Why this plan</h2>
        <ul className="explain">
          {r.explanation.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
        <p className="muted">Generated from the optimiser output by fixed templates; no language model.</p>
      </section>

      {others.length > 0 && (
        <section className="panel">
          <h2>Plan together with other shortages in {sel.district}</h2>
          <p className="muted">Co-planned shortages share the budget and compete for the same surplus pools.</p>
          {others.map((o) => (
            <label key={o.trade} className="check">
              <input type="checkbox" checked={coplan.includes(o.trade)}
                onChange={(e) => setCoplan(e.target.checked ? [...coplan, o.trade] : coplan.filter((t) => t !== o.trade))} />
              {o.trade} (shortage {num(o.shortage.MEDIAN)})
            </label>
          ))}
          {r.other_cells.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Co-planned shortage</th>
                  <th className="r">Shortage</th>
                  <th className="r">Workers delivered</th>
                  <th className="r">Residual</th>
                </tr>
              </thead>
              <tbody>
                {r.other_cells.map((c) => (
                  <tr key={c.trade}>
                    <td>{c.trade}</td>
                    <td className="r">{num(c.shortage)}</td>
                    <td className="r">{num(c.workers_delivered)}</td>
                    <td className="r">{num(c.residual_gap)}</td>
                  </tr>
                ))}
                <tr className="total">
                  <td colSpan={3}>Total cost across all planned shortages</td>
                  <td className="r">{rupees(r.plan.total_cost)}</td>
                </tr>
              </tbody>
            </table>
          )}
        </section>
      )}

      <section className="panel">
        <h2>Pathways</h2>
        <table>
          <thead>
            <tr>
              <th>Pathway</th>
              <th>For</th>
              <th className="r">Starters</th>
              <th className="r">Workers</th>
              <th className="r">Cost</th>
              <th className="r">₹ / worker</th>
              <th className="r">Lead</th>
              <th className="r">Limit</th>
              <th>Class</th>
            </tr>
          </thead>
          <tbody>
            {r.plan.pathways.map((p) => (
              <tr key={`${p.id}|${p.trade}`}>
                <td>{p.id.replace(":", ": ").replace("_", " ")}</td>
                <td>{p.trade}</td>
                <td className="r">{num(p.starters)}</td>
                <td className="r">{num(p.workers_delivered)}</td>
                <td className="r">{rupees(p.cost)}</td>
                <td className="r">{rupees(p.cost_per_worker)}</td>
                <td className="r">{p.lead_time_months} mo</td>
                <td className="r">{num(p.capacity)}</td>
                <td>{CLASS_TEXT[p.class]}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="primary" onClick={() => download(`kaushalniti_plan_${r.cell.district}_${r.scenario}.csv`.replace(/\s+/g, "_"), planCsv(r))}>
          Export plan (CSV)
        </button>
      </section>

      <details className="panel">
        <summary>
          <h2>Assumptions {Object.keys(edits).length > 0 && <span className="tag">{Object.keys(edits).length} edited</span>}</h2>
        </summary>
        <p className="muted">Every number the plan depends on, with its provenance. Edit a value to re-run the optimiser.</p>
        <table>
          <thead>
            <tr>
              <th>Assumption</th>
              <th className="r">Value</th>
              <th>Unit</th>
              <th>Status</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {r.assumptions.map((a) => (
              <tr key={a.key} className={a.key in edits ? "selected" : ""}>
                <td>{a.label}</td>
                <td className="r">
                  {a.editable ? (
                    <AssumptionInput value={Number(a.value)} onCommit={(v) => setEdits({ ...edits, [a.key]: v })} />
                  ) : typeof a.value === "number" && a.unit === "INR" ? (
                    rupees(a.value)
                  ) : (
                    a.value
                  )}
                </td>
                <td>{a.unit}</td>
                <td>
                  <span className="badge">{a.key in edits ? "PLANNER EDIT" : a.status}</span>
                </td>
                <td>{a.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {Object.keys(edits).length > 0 && (
          <button onClick={() => setEdits({})}>Reset to dataset values</button>
        )}
        <p className="muted">{r.data_status}</p>
      </details>
    </div>
  );
}

// Commits on blur or Enter so the optimiser is not re-run on every keystroke.
function AssumptionInput({ value, onCommit }: { value: number; onCommit: (v: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const v = Number(text);
    if (text !== "" && Number.isFinite(v) && v !== value) onCommit(v);
    else setText(String(value));
  };
  return (
    <input className="num" type="number" value={text} onChange={(e) => setText(e.target.value)} onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()} />
  );
}
