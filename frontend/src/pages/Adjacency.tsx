import { useEffect, useState } from "react";
import { Adjacency as Graph, api, Edge, num } from "../api";
import type { Selection } from "../App";

const SIZE = 560;
const MID = SIZE / 2;
const RADIUS = 205;
const MAX_NODES = 14;

const short = (s: string, n = 26) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

export default function Adjacency({ sel }: { sel: Selection }) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [picked, setPicked] = useState<Edge | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setGraph(null);
    setPicked(null);
    setError("");
    api
      .adjacency(sel.trade, sel.district)
      .then((g) => {
        setGraph(g);
        setPicked(g.edges.find((e) => e.used_by_optimiser) ?? g.edges[0] ?? null);
      })
      .catch((e) => setError(e.message));
  }, [sel.trade, sel.district]);

  if (error) return <p className="error">{error}</p>;
  if (!graph) return <p>Loading…</p>;

  // trades the optimiser can draw on first, then the strongest of the rest
  const edges = [...graph.edges].sort((a, b) => Number(b.used_by_optimiser) - Number(a.used_by_optimiser) || b.score - a.score).slice(0, MAX_NODES);

  return (
    <div>
      <section className="panel">
        <h2>Which trades can bridge into {graph.trade}?</h2>
        <p className="muted">
          Each line compares the technical occupational standards of two qualifications in the National Qualifications Register.
          Generic standards (employability, safety, teamwork) are removed first. Skill adjacency is an established idea; here it
          is applied to Indian qualification data and fed to the optimiser. <span className="badge">{graph.status}</span>
        </p>
        <div className="graph-layout">
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="graph" role="img" aria-label={`Source trades for ${graph.trade}`}>
            {edges.map((e, i) => {
              const angle = (2 * Math.PI * i) / edges.length - Math.PI / 2;
              const x = MID + RADIUS * Math.cos(angle);
              const y = MID + RADIUS * Math.sin(angle);
              const colour = e.used_by_optimiser ? "#1f7a4d" : e.eligible ? "#1f4e79" : "#b0b0b0";
              const active = picked?.source_id === e.source_id;
              return (
                <g key={e.source_id} className="click" onClick={() => setPicked(e)}>
                  <line x1={MID} y1={MID} x2={x} y2={y} stroke={colour} strokeWidth={1 + 9 * e.score} opacity={active ? 1 : 0.55} />
                  <circle cx={x} cy={y} r={active ? 11 : 8} fill={colour} />
                  <text x={x} y={y + (y > MID ? 24 : -14)} textAnchor="middle" fontSize="11" fontWeight={active ? 700 : 400}>
                    {short(e.demo_trade ?? e.source)}
                  </text>
                  <text x={(MID + x) / 2} y={(MID + y) / 2 - 4} textAnchor="middle" fontSize="10" fill="#333">
                    {Math.round(e.score * 100)}%
                  </text>
                </g>
              );
            })}
            <circle cx={MID} cy={MID} r={46} fill="#c0504d" />
            <text x={MID} y={MID - 4} textAnchor="middle" fontSize="11" fill="#fff" fontWeight={700}>
              {short(graph.trade, 16)}
            </text>
            <text x={MID} y={MID + 10} textAnchor="middle" fontSize="9" fill="#fff">
              shortage trade
            </text>
          </svg>

          {picked && (
            <div className="edge-detail">
              <h3>
                {picked.demo_trade ?? picked.source} → {graph.trade}
              </h3>
              <dl>
                <dt>Adjacency score</dt>
                <dd>
                  {Math.round(picked.score * 100)}% of the target's technical hours are covered (threshold {Math.round(graph.threshold * 100)}%)
                </dd>
                <dt>Estimated bridge hours</dt>
                <dd>{picked.bridge_hours === null ? "not published" : `${num(picked.bridge_hours)} of ${num(picked.target_technical_hours)} technical hours`}</dd>
                <dt>NSQF level</dt>
                <dd>
                  {picked.source_level ?? "?"} → {picked.target_level ?? "?"}
                </dd>
                <dt>Surplus in {sel.district}</dt>
                <dd>{picked.surplus ? `${num(picked.surplus)} (synthetic)` : picked.demo_trade ? "none" : "not in the demo dataset"}</dd>
                <dt>Eligible for the optimiser</dt>
                <dd>
                  {picked.used_by_optimiser
                    ? "Yes: above the threshold and surplus is available"
                    : picked.eligible
                    ? "Above the threshold, but no surplus pool to draw on"
                    : `No: ${picked.not_eligible_because.join("; ")}`}
                </dd>
              </dl>
              <h4>Matched standards ({picked.matched.length})</h4>
              <ul className="std">
                {picked.matched.map((m, i) => (
                  <li key={i}>
                    <b>{m.title}</b> {m.code && <code>{m.code}</code>} · {num(m.hours)} h
                    <div className="muted">
                      ≈ {m.source_title} {m.source_code && <code>{m.source_code}</code>} · similarity {m.similarity?.toFixed(2)}
                    </div>
                  </li>
                ))}
                {picked.matched.length === 0 && <li className="muted">None</li>}
              </ul>
              <h4>Unmatched standards: the bridge course ({picked.unmatched.length})</h4>
              <ul className="std">
                {picked.unmatched.map((u, i) => (
                  <li key={i}>
                    <b>{u.title}</b> {u.code && <code>{u.code}</code>} · {num(u.hours)} h
                    <div className="muted">closest source standard similarity {u.best_similarity?.toFixed(2)}</div>
                  </li>
                ))}
                {picked.unmatched.length === 0 && <li className="muted">None</li>}
              </ul>
              <a href={`https://nqr.gov.in/qualifications/${picked.source_id}`} target="_blank" rel="noreferrer">
                Source qualification on nqr.gov.in
              </a>
            </div>
          )}
        </div>
        <p className="muted">
          <span className="dot" style={{ background: "#1f7a4d" }} /> used by the optimiser ·{" "}
          <span className="dot" style={{ background: "#1f4e79" }} /> above threshold, no surplus ·{" "}
          <span className="dot" style={{ background: "#b0b0b0" }} /> not eligible. Line width and label show the adjacency score. Method:{" "}
          {graph.model}, match threshold {graph.match_threshold}. Register scraped on {graph.register_scraped_on}. Bridge hours are
          estimates and have not been validated by subject experts.{" "}
          <a href={graph.source_url} target="_blank" rel="noreferrer">
            Target qualification on nqr.gov.in
          </a>
        </p>
      </section>
    </div>
  );
}
