import { useEffect, useMemo, useState } from "react";
import { api, csv, type Product } from "./api";
import { hasForecast, levelOrder, whole, type Row } from "./reorder";

const colomboToday = () => new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10);

type Item = Product & { location?: string | null };
type Forecast = { status: string; products: Row[] };
type Level = "out" | "low" | "ok";
type Line = { id: string; name: string; sku: string; shelf: string; stock: number; unit: string; level: Level; lasts: string; order: number };

const unitName = (u: string) => (u === "LITRE" ? "litres" : "pieces");

/** One plain verdict per item, from live stock and the nightly forecast. */
export function buildLines(items: Item[], forecast: Row[]): Line[] {
  const byId = new Map(forecast.map((r) => [r.id, r]));
  const lines = items.map((p): Line => {
    const f = byId.get(p.id);
    const stock = Number(p.quantity), usable = hasForecast(f);
    const perDay = usable ? (f!.next7 || 0) / 7 : 0;
    const days = perDay > 0 ? stock / perDay : Infinity;
    const order = usable ? f!.suggestedTopUp7 || 0 : levelOrder({ ...(f || { id: p.id, sku: p.sku, name: p.name, unit: p.unit, status: "no_forecast" }), availableNow: stock, reorderLevel: Number(p.reorder_level) });
    const level: Level = stock <= 0 ? "out" : stock <= Number(p.reorder_level) || days <= 3 || order > 0 ? "low" : "ok";
    const lasts = stock <= 0 ? "Finished" : !usable ? "Still learning" : !Number.isFinite(days) ? "Not being used" : days > 90 ? "More than 3 months" : "About " + Math.max(1, Math.round(days)) + (Math.round(days) <= 1 ? " day" : " days");
    return { id: p.id, name: p.name, sku: p.sku, shelf: p.location || "", stock, unit: p.unit, level, lasts, order };
  });
  const rank = { out: 0, low: 1, ok: 2 };
  return lines.sort((a, b) => rank[a.level] - rank[b.level] || a.name.localeCompare(b.name));
}

const LABEL: Record<Level, string> = { out: "Finished", low: "Order soon", ok: "Fine" };

export function StockReport() {
  const [items, setItems] = useState<Item[] | null>(null), [forecast, setForecast] = useState<Row[]>([]);
  const [error, setError] = useState(""), [search, setSearch] = useState(""), [filter, setFilter] = useState<Level | "all">("all");
  const load = async () => {
    try {
      setItems(await api<Item[]>("/api/inventory/products"));
      try { setForecast((await api<Forecast>("/api/forecast")).products || []); } catch { setForecast([]); }
    } catch (e) { setError((e as Error).message); }
  };
  useEffect(() => { void load(); }, []);
  const lines = useMemo(() => buildLines(items || [], forecast), [items, forecast]);
  const counts = { out: lines.filter((l) => l.level === "out").length, low: lines.filter((l) => l.level === "low").length, ok: lines.filter((l) => l.level === "ok").length };
  const shown = lines.filter((l) => (filter === "all" || l.level === filter) && (l.name + " " + l.sku + " " + l.shelf).toLowerCase().includes(search.trim().toLowerCase()));
  const today = colomboToday();
  if (!items) return <section className="stock-panel report"><p className="stock-help">{error || "Loading your stock…"}</p></section>;
  return (
    <section className="report" aria-label="Stock report">
      <div className="report-head">
        <div><p className="eyebrow">OWNER</p><h1>Stock report</h1><p className="stock-help">What you have, what is running out, and what to order. It updates by itself every night.</p></div>
        <button className="button secondary" onClick={() => csv("stock-" + today + ".csv", shown.map((l) => ({ Item: l.name, Code: l.sku, Shelf: l.shelf, "In stock": l.stock, Status: LABEL[l.level], "Will last": l.lasts, "Order this week": l.order || "" })))}>Download list</button>
      </div>
      {error && <p role="alert" className="stock-error">{error}</p>}
      <div className="report-filters" role="group" aria-label="Show">
        {([["all", "All", lines.length], ["out", "Finished", counts.out], ["low", "Order soon", counts.low], ["ok", "Fine", counts.ok]] as [Level | "all", string, number][]).map(([key, label, n]) => (
          <button key={key} className={"report-chip " + key + (filter === key ? " chosen" : "")} onClick={() => setFilter(key)}><b>{n}</b> {label}</button>
        ))}
        <input className="report-search" aria-label="Search items" placeholder="Search an item" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div className="stock-table-wrap">
        <table className="stock-table">
          <thead><tr><th>Item</th><th>In stock</th><th>Status</th><th>Will last</th><th>Order this week</th></tr></thead>
          <tbody>
            {shown.map((l) => (
              <tr key={l.id}>
                <td><strong>{l.name}</strong>{l.shelf && <small>{l.shelf}</small>}</td>
                <td>{whole(l.stock)} <small>{unitName(l.unit)}</small></td>
                <td><span className={"status-pill " + l.level}>{LABEL[l.level]}</span></td>
                <td>{l.lasts}</td>
                <td>{l.order > 0 ? <strong>{whole(l.order)}</strong> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <div className="stock-empty">{lines.length ? "No items match." : "No items yet. Add your first item at the Storeroom counter."}</div>}
      </div>
    </section>
  );
}
