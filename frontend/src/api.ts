// Typed client for the KaushalNiti API. All numbers shown in the UI come from these calls.

export type Scenario = "LOW" | "MEDIAN" | "HIGH";
export const SCENARIOS: Scenario[] = ["LOW", "MEDIAN", "HIGH"];
export type Kind = "new_seats" | "bridge" | "neighbour" | "apprenticeship";
export type ByScenario = Record<Scenario, number>;

export interface Assumption {
  key: string;
  label: string;
  value: number | string;
  unit: string;
  status: string;
  source: string;
  editable?: boolean;
}

export interface Meta {
  states: string[];
  districts: { state: string; district: string }[];
  trades: { trade: string; nqr_id: number; sector: string }[];
  demo: { state: string; district: string; trade: string; budget: number; horizon: number };
  assumptions: Assumption[];
}

export interface Gap {
  state: string;
  district: string;
  trade: string;
  horizon: number;
  demand: ByScenario;
  baseline_supply: number;
  shortage: ByScenario;
  surplus: number;
}

export interface GapDetail extends Gap {
  history: { month: string; openings: number }[];
  forecast_monthly: number[];
  band: [number, number];
  method: string;
  status: string;
}

export interface Card {
  kind: Kind;
  label: string;
  starters: number;
  workers_delivered: number;
  cost: number;
  lead_time_months: number | null;
  capacity: number;
  class: "NO_REGRET" | "CONTINGENT" | "MIXED" | "NOT_USED";
  no_regret_starters: number;
  contingent_starters: number;
  status: string;
  available: boolean;
}

export interface Pathway {
  id: string;
  kind: Kind;
  label: string;
  district: string;
  trade: string;
  starters: number;
  workers_delivered: number;
  cost: number;
  cost_per_worker: number;
  lead_time_months: number;
  capacity: number;
  class: Card["class"];
  no_regret_starters: number;
  contingent_starters: number;
  starters_by_scenario: ByScenario;
  status: string;
}

export interface SeatsOnly {
  seats_required: number;
  cost_required: number;
  capacity: number;
  lead_time_months: number;
  seats_feasible: number;
  cost: number;
  workers_delivered: number;
  residual_gap: number;
  binding: string[];
  timeline: number[];
}

export interface ResolveResult {
  cell: { state: string; district: string; trade: string };
  scenario: Scenario;
  horizon: number;
  budget: number;
  forecast: { demand: ByScenario; method: string; band: [number, number] };
  baseline_supply: number;
  shortage: ByScenario;
  seats_only: SeatsOnly;
  plan: {
    interventions: Card[];
    pathways: Pathway[];
    total_cost: number;
    cost_this_cell: number;
    workers_delivered: number;
    residual_gap: number;
    timeline: number[];
    binding_constraints: { constraint: string; detail: string }[];
  };
  scenarios: Record<Scenario, { total_cost: number; workers_delivered: number; starters_by_kind: Record<Kind, number> }>;
  regret: Record<string, ByScenario>;
  actions: { launch_now: { kind: Kind; label: string; starters: number }[]; defer: { kind: Kind; label: string; starters: number }[]; recommendation: string };
  explanation: string[];
  other_cells: { district: string; trade: string; shortage: number; workers_delivered: number; residual_gap: number }[];
  assumptions: Assumption[];
  data_status: string;
}

export interface Standard {
  code: string;
  title: string;
  hours: number;
  source_code?: string;
  source_title?: string;
  similarity?: number;
  best_similarity?: number;
}

export interface Edge {
  source_id: number;
  source: string;
  target: string;
  score: number;
  bridge_hours: number | null;
  target_technical_hours: number;
  matched: Standard[];
  unmatched: Standard[];
  source_level: number | null;
  target_level: number | null;
  demo_trade: string | null;
  surplus: number | null;
  eligible: boolean;
  not_eligible_because: string[];
  used_by_optimiser: boolean;
  status: string;
}

export interface Adjacency {
  trade: string;
  source_url: string;
  threshold: number;
  method: string;
  model: string;
  match_threshold: number;
  status: string;
  register_scraped_on: string;
  edges: Edge[];
}

export interface ResolveRequest {
  state?: string;
  district: string;
  trade: string;
  budget: number;
  horizon: number;
  scenario: Scenario;
  include_cells?: { district: string; trade: string }[];
  overrides?: Record<string, unknown>;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    // FastAPI puts the reason in `detail` (a string, or a list of validation errors)
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((d: { loc: string[]; msg: string }) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ")
      : detail ?? res.statusText;
    throw new Error(message);
  }
  return res.json();
}

const q = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString();

export const api = {
  meta: () => call<Meta>("/api/meta"),
  gaps: (state: string, district: string, horizon: number) => call<{ cells: Gap[] }>(`/api/gap?${q({ state, district, horizon })}`),
  gap: (district: string, trade: string, horizon: number) => call<GapDetail>(`/api/gap?${q({ district, trade, horizon })}`),
  resolve: (req: ResolveRequest) =>
    call<ResolveResult>("/api/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }),
  adjacency: (trade: string, district: string) => call<Adjacency>(`/api/adjacency/${encodeURIComponent(trade)}?${q({ district })}`),
};

// Indian-style money: lakh and crore.
export function rupees(v: number): string {
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} crore`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} lakh`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

export const num = (v: number) => Math.round(v).toLocaleString("en-IN");
