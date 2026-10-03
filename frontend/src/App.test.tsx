import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";
import type { ResolveResult } from "./api";
import { planCsv, toOverrides } from "./pages/Resolver";

const EV = "Electric Vehicle Service Technician";
const by = (low: number, median: number, high: number) => ({ LOW: low, MEDIAN: median, HIGH: high });

const meta = {
  states: ["Maharashtra"],
  districts: [{ state: "Maharashtra", district: "Pune" }],
  trades: [{ trade: EV, nqr_id: 13239, sector: "Automotive" }],
  demo: { state: "Maharashtra", district: "Pune", trade: EV, budget: 6e7, horizon: 18 },
  assumptions: [],
};
const gap = {
  state: "Maharashtra", district: "Pune", trade: EV, horizon: 18,
  demand: by(900, 1500, 1900), baseline_supply: 300, shortage: by(600, 1200, 1600), surplus: 0,
};
const detail = { ...gap, history: [{ month: "2026-09", openings: 80 }], forecast_monthly: [82, 84], band: [-0.4, 0.25], method: "damped Holt", status: "SYNTHETIC" };

const kinds = [
  ["new_seats", "New training seats", 780, 13, "CONTINGENT"],
  ["bridge", "Bridge course", 400, 4, "NO_REGRET"],
  ["neighbour", "Neighbouring-district supply", 250, 2, "NO_REGRET"],
  ["apprenticeship", "Apprenticeship", 250, 3, "MIXED"],
] as const;

const result = {
  cell: { state: "Maharashtra", district: "Pune", trade: EV },
  scenario: "MEDIAN", horizon: 18, budget: 6e7,
  forecast: { demand: by(900, 1500, 1900), method: "damped Holt", band: [-0.4, 0.25] },
  baseline_supply: 300, shortage: by(600, 1200, 1600),
  seats_only: {
    seats_required: 3750, cost_required: 2.25e8, capacity: 800, lead_time_months: 13, seats_feasible: 800, cost: 4.8e7,
    workers_delivered: 256, residual_gap: 944, binding: ["capacity"], timeline: [0, 0, 256],
  },
  plan: {
    interventions: kinds.map(([kind, label, starters, lead, cls]) => ({
      kind, label, starters, workers_delivered: starters / 2, cost: starters * 1000, lead_time_months: lead, capacity: 800,
      class: cls, no_regret_starters: cls === "CONTINGENT" ? 0 : starters, contingent_starters: cls === "CONTINGENT" ? starters : 0,
      status: "SYNTHETIC", available: true,
    })),
    pathways: [{
      id: "bridge:Four Wheeler Service Technician", kind: "bridge", label: "Bridge course", district: "Pune", trade: EV, starters: 400,
      workers_delivered: 300, cost: 6160000, cost_per_worker: 20533, lead_time_months: 4, capacity: 400, class: "NO_REGRET",
      no_regret_starters: 400, contingent_starters: 0, starters_by_scenario: by(400, 400, 400), status: 'SYNTHETIC, "quoted"',
    }],
    total_cost: 5.99e7, cost_this_cell: 5.99e7, workers_delivered: 898, residual_gap: 302, timeline: [0, 150, 898], binding_constraints: [],
  },
  scenarios: Object.fromEntries(["LOW", "MEDIAN", "HIGH"].map((s) => [s, {
    total_cost: 1e7, workers_delivered: 600, starters_by_kind: { new_seats: 0, bridge: 400, neighbour: 250, apprenticeship: 200 },
  }])),
  regret: { LOW: by(0, 3e7, 3e7), MEDIAN: by(4.7e7, 0, 0) },
  actions: { launch_now: [], defer: [], recommendation: "Launch now: bridge course. Defer until the next demand update: new training seats." },
  explanation: ["Bridge course: 400 starters deliver about 300 workers in month 4."],
  other_cells: [], assumptions: [], data_status: "SYNTHETIC",
} as unknown as ResolveResult;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url.startsWith("/api/meta") ? meta
      : url.startsWith("/api/resolve") ? result
      : url.includes("trade=") ? detail
      : { cells: [gap] };
    return { ok: true, json: async () => body } as Response;
  }));
});
afterEach(() => vi.unstubAllGlobals());

test("explorer shows the shortage for the demo cell, then the resolver shows the plan", async () => {
  render(<App />);
  expect(await screen.findByText("Projected shortage")).toBeInTheDocument();
  expect(screen.getAllByText("1,200").length).toBeGreaterThan(0);
  expect(screen.getByText(/synthetic \/ illustrative/i)).toBeInTheDocument();

  fireEvent.click(screen.getByText("Resolve gap →"));
  expect(await screen.findByText("Recommended intervention mix")).toBeInTheDocument();
  expect(screen.getByText("3,750")).toBeInTheDocument(); // seats-only requirement
  expect(screen.getByText(/Defer until the next demand update/)).toBeInTheDocument();
  expect(screen.getAllByText("No-regret: launch now").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Contingent: defer").length).toBeGreaterThan(0);

  // switching scenario re-runs the optimiser with that scenario
  fireEvent.click(screen.getByRole("button", { name: /LOW/ }));
  await waitFor(() => {
    const calls = (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls;
    expect(calls.some(([url, init]) => url === "/api/resolve" && JSON.parse(String(init?.body)).scenario === "LOW")).toBe(true);
  });
});

test("API errors are shown, not swallowed", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, statusText: "Not Found", json: async () => ({ detail: "unknown district 'X'" }) }) as Response));
  render(<App />);
  expect(await screen.findByText(/unknown district 'X'/)).toBeInTheDocument();
});

test("assumption edits become nested overrides", () => {
  expect(toOverrides({ "interventions.bridge.cost": 12000, "interventions.bridge.yield": 0.7, unmet_penalty: 5 })).toEqual({
    interventions: { bridge: { cost: 12000, yield: 0.7 } },
    unmet_penalty: 5,
  });
  expect(toOverrides({})).toEqual({});
});

test("plan export is valid CSV with one row per used pathway", () => {
  const lines = planCsv(result).split("\n");
  expect(lines).toHaveLength(2);
  expect(lines[0]).toContain('"state","district","trade","forecast_gap"');
  expect(lines[1]).toContain('"Pune"');
  expect(lines[1]).toContain('"SYNTHETIC, ""quoted"""'); // quotes escaped
});
