import { useEffect, useState } from "react";
import { api, Meta } from "./api";
import Adjacency from "./pages/Adjacency";
import Explorer from "./pages/Explorer";
import Resolver from "./pages/Resolver";

export interface Selection {
  state: string;
  district: string;
  trade: string;
  horizon: number;
  budget: number;
}

type Tab = "explorer" | "resolver" | "adjacency";
const TABS: [Tab, string][] = [
  ["explorer", "1. Shortage Explorer"],
  ["resolver", "2. Skill Gap Resolver"],
  ["adjacency", "3. Bridgeability Graph"],
];

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState("");
  // the tab lives in the URL hash so a screen can be linked to directly
  const fromHash = () => (TABS.find(([id]) => id === window.location.hash.slice(1))?.[0] ?? "explorer") as Tab;
  const [tab, setTabState] = useState<Tab>(fromHash);
  const setTab = (t: Tab) => {
    window.location.hash = t;
    setTabState(t);
  };
  const [sel, setSel] = useState<Selection | null>(null);

  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m);
        setSel({ ...m.demo });
      })
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <header className="top">
        <div>
          <h1>KaushalNiti</h1>
          <p>From skill gap to the fastest fix · SIH PS 26246</p>
        </div>
        <nav>
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "tab active" : "tab"} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      <div className="notice">
        Demo mode, offline dataset. Demand, costs, yields, capacities and surplus pools are <b>synthetic / illustrative</b>, not
        government statistics. Qualification data is from the public National Qualifications Register.
      </div>
      <main>
        {error && <p className="error">Could not reach the API: {error}</p>}
        {!meta || !sel ? (
          !error && <p>Loading…</p>
        ) : tab === "explorer" ? (
          <Explorer meta={meta} sel={sel} onChange={setSel} onResolve={() => setTab("resolver")} />
        ) : tab === "resolver" ? (
          <Resolver meta={meta} sel={sel} onChange={setSel} onGraph={() => setTab("adjacency")} />
        ) : (
          <Adjacency sel={sel} />
        )}
      </main>
    </>
  );
}
