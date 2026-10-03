import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Gap, GapDetail, Meta, num } from "../api";
import type { Selection } from "../App";

interface Props {
  meta: Meta;
  sel: Selection;
  onChange: (s: Selection) => void;
  onResolve: () => void;
}

export default function Explorer({ meta, sel, onChange, onResolve }: Props) {
  const [cells, setCells] = useState<Gap[]>([]);
  const [detail, setDetail] = useState<GapDetail | null>(null);
  const [error, setError] = useState("");

  const districts = meta.districts.filter((d) => d.state === sel.state);

  useEffect(() => {
    setError("");
    api
      .gaps(sel.state, sel.district, sel.horizon)
      .then((r) => setCells(r.cells))
      .catch((e) => {
        setCells([]);
        setError(e.message);
      });
  }, [sel.state, sel.district, sel.horizon]);

  useEffect(() => {
    setDetail(null);
    api
      .gap(sel.district, sel.trade, sel.horizon)
      .then(setDetail)
      .catch((e) => setError(e.message));
  }, [sel.district, sel.trade, sel.horizon]);

  // history and forecast on one axis; the forecast starts where the history ends
  const chart = detail
    ? [
        ...detail.history.map((h) => ({ label: h.month, history: h.openings })),
        ...detail.forecast_monthly.map((v, i) => ({ label: `+${i + 1}`, forecast: v })),
      ]
    : [];

  return (
    <div>
      <section className="panel controls">
        <label>
          State
          <select
            value={sel.state}
            onChange={(e) => {
              const state = e.target.value;
              const first = meta.districts.find((d) => d.state === state);
              onChange({ ...sel, state, district: first ? first.district : sel.district });
            }}
          >
            {meta.states.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          District
          <select value={sel.district} onChange={(e) => onChange({ ...sel, district: e.target.value })}>
            {districts.map((d) => (
              <option key={d.district}>{d.district}</option>
            ))}
          </select>
        </label>
        <label>
          Trade
          <select value={sel.trade} onChange={(e) => onChange({ ...sel, trade: e.target.value })}>
            {meta.trades.map((t) => (
              <option key={t.trade}>{t.trade}</option>
            ))}
          </select>
        </label>
        <label>
          Horizon (months)
          <input
            type="number"
            min={1}
            max={60}
            value={sel.horizon}
            onChange={(e) => onChange({ ...sel, horizon: Math.min(60, Math.max(1, Number(e.target.value) || 1)) })}
          />
        </label>
      </section>

      {error && <p className="error">{error}</p>}

      {detail && (
        <section className="panel">
          <h2>
            {detail.trade} in {detail.district}
          </h2>
          <div className="tiles">
            <Tile label={`Forecast demand, next ${detail.horizon} months`} value={num(detail.demand.MEDIAN)} />
            <Tile label="Existing pipeline supply" value={num(detail.baseline_supply)} />
            <Tile label="Projected shortage" value={num(detail.shortage.MEDIAN)} strong />
            <Tile label="Shortage range (low – high)" value={`${num(detail.shortage.LOW)} – ${num(detail.shortage.HIGH)}`} />
          </div>
          <div className="chart">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" minTickGap={30} />
                <YAxis label={{ value: "openings / month", angle: -90, position: "insideLeft" }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="history" name="History (synthetic)" stroke="#1f4e79" dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#c0504d" strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="muted">
            {detail.method}. <span className="badge">{detail.status}</span>
          </p>
          <button className="primary" disabled={detail.shortage.HIGH === 0} onClick={onResolve}>
            Resolve gap →
          </button>
          {detail.shortage.HIGH === 0 && <span className="muted"> No shortage is forecast for this cell.</span>}
        </section>
      )}

      <section className="panel">
        <h2>All trades in {sel.district}</h2>
        <table>
          <thead>
            <tr>
              <th>Trade</th>
              <th className="r">Demand</th>
              <th className="r">Pipeline supply</th>
              <th className="r">Shortage</th>
              <th className="r">Range</th>
              <th className="r">Surplus</th>
            </tr>
          </thead>
          <tbody>
            {cells.map((c) => (
              <tr key={c.trade} className={c.trade === sel.trade ? "selected click" : "click"} onClick={() => onChange({ ...sel, trade: c.trade })}>
                <td>{c.trade}</td>
                <td className="r">{num(c.demand.MEDIAN)}</td>
                <td className="r">{num(c.baseline_supply)}</td>
                <td className="r">{c.shortage.MEDIAN ? <b>{num(c.shortage.MEDIAN)}</b> : "–"}</td>
                <td className="r">
                  {num(c.shortage.LOW)} – {num(c.shortage.HIGH)}
                </td>
                <td className="r">{c.surplus ? num(c.surplus) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">Click a row to select that trade. Figures cover the next {sel.horizon} months.</p>
      </section>
    </div>
  );
}

function Tile({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={strong ? "tile strong" : "tile"}>
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
    </div>
  );
}
