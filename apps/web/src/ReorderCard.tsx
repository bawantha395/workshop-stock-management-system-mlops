import { useEffect, useState } from "react";
import { api, csv } from "./api";

import { reorderSuggestions, runsOut, whole, type Forecast } from "./reorder";

export function ReorderCard() {
  const [report, setReport] = useState<Forecast | null>(null), [error, setError] = useState("");
  useEffect(() => {
    api<Forecast>("/api/forecast").then(setReport).catch((e) => setError((e as Error).message));
  }, []);
  if (error) return <section className="stock-panel reorder-card"><p className="stock-help">Reorder suggestions are unavailable right now. {error}</p></section>;
  if (!report) return <section className="stock-panel reorder-card" aria-busy="true"><p className="stock-help">Checking what to reorder…</p></section>;
  if (report.status !== "ready")
    return <section className="stock-panel reorder-card"><p className="eyebrow">REORDER THIS WEEK</p><h2>Suggestions start after the first nightly run</h2><p className="stock-help">Every night at 2:00 AM the app learns from your stock movements and prepares this list. Nothing to do.</p></section>;
  const { reorder, soon, idle } = reorderSuggestions(report.products);
  const today = new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10);
  const download = () => csv("purchase-list-" + today + ".csv", reorder.map((r) => ({ SKU: r.sku, Item: r.name, "In stock": r.availableNow, "Order quantity": r.order, Unit: r.unit === "LITRE" ? "litres" : "units", Why: runsOut(r.daysLeft), Method: r.status === "trained_ml" ? "ML forecast" : "Weekday average" })));
  return (
    <section className="stock-panel reorder-card" aria-label="Reorder this week">
      <div className="section-heading">
        <div><p className="eyebrow">REORDER THIS WEEK</p><h2>{reorder.length ? reorder.length + (reorder.length === 1 ? " item to order" : " items to order") : "Nothing to order this week"}</h2></div>
        {reorder.length > 0 && <button className="button secondary" onClick={download}>Download purchase list</button>}
      </div>
      <div className="reorder-stats">
        <span><b>{reorder.length}</b> to reorder</span>
        <span className={soon ? "urgent" : ""}><b>{soon}</b> run out within 3 days</span>
        <span><b>{idle}</b> not moving</span>
      </div>
      {reorder.length > 0 && (
        <ul className="reorder-list">
          {reorder.slice(0, 8).map((r) => (
            <li key={r.id}>
              <span><strong>{r.name}</strong><small className={r.daysLeft <= 3 ? "urgent" : ""}>{runsOut(r.daysLeft)} · {whole(r.availableNow)} in stock</small></span>
              <span className="reorder-order"><strong>Order {whole(r.order)}</strong><small>{r.status === "trained_ml" ? "ML forecast" : "Weekday average"}</small></span>
            </li>
          ))}
        </ul>
      )}
      <p className="stock-help">Updated automatically every night{report.historyUntil ? " · sales through " + report.historyUntil : ""}. Suggestions never change stock.</p>
    </section>
  );
}
