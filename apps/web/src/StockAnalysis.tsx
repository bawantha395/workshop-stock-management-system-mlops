import { useEffect, useRef, useState } from "react";
import { Download, Filter, ChevronLeft, ChevronRight } from "lucide-react";
import { api, csv } from "./api";
import { StockForecast } from "./StockForecast";

type Row = {
  id: string;
  sku: string;
  name: string;
  brand: string;
  part_number: string | null;
  category: string;
  location: string;
  unit: string;
  archived: boolean;
  opening_quantity: number;
  added_quantity: number;
  taken_quantity: number;
  closing_quantity: number;
  available_now: number;
};
type Report = {
  rows: Row[];
  total: number;
  page: number;
  pageSize: number;
  from: string;
  until: string;
  asOf: string;
};
const local = (date: Date) =>
  new Date(date.getTime() + 330 * 60000).toISOString().slice(0, 16);
const utc = (value: string) => new Date(value + ":00+05:30").toISOString();
const amount = (value: number) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: 3 }).format(
    Number(value),
  );

export function StockAnalysis() {
  const [from, setFrom] = useState(() =>
      local(new Date(Date.now() - 30 * 86400000)),
    ),
    [until, setUntil] = useState(() => local(new Date()));
  const [search, setSearch] = useState(""),
    [category, setCategory] = useState(""),
    [archived, setArchived] = useState(true);
  const [report, setReport] = useState<Report | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [exporting, setExporting] = useState(false);
  const serial = useRef(0);
  const applied = useRef({ from, until, search, category, archived });
  const load = async (page = 0, range?: { from: string; until: string }) => {
    const selected =
      page > 0
        ? applied.current
        : {
            from: range?.from || from,
            until: range?.until || until,
            search,
            category,
            archived,
          };
    const begin = selected.from,
      end = selected.until;
    if (!begin || !end || begin >= end) {
      setError("Choose an end time after the start time.");
      return;
    }
    const request = ++serial.current;
    setBusy(true);
    setError("");
    try {
      const q = new URLSearchParams({
        from: utc(begin),
        until: utc(end),
        search: selected.search,
        category: selected.category,
        archived: String(selected.archived),
        page: String(page),
      });
      const data = await api<Report>("/api/inventory/analysis?" + q);
      if (request === serial.current) {
        setReport(data);
        applied.current = selected;
      }
    } catch (e) {
      if (request === serial.current) setError((e as Error).message);
    } finally {
      if (request === serial.current) setBusy(false);
    }
  };
  useEffect(() => {
    void load();
    return () => {
      serial.current++;
    };
  }, []);
  const preset = (days: number) => {
    const end = local(new Date()),
      begin = local(new Date(Date.now() - days * 86400000));
    setFrom(begin);
    setUntil(end);
    void load(0, { from: begin, until: end });
  };
  const daily = async () => {
    if (!report) return;
    setExporting(true);
    setError("");
    try {
      const q = new URLSearchParams({ from: report.from, until: report.until });
      const rows = await api<Record<string, unknown>[]>(
        "/api/inventory/analysis/daily?" + q,
      );
      if (!rows.length) {
        setError("No ledger activity exists in this range.");
        return;
      }
      csv("stock-daily-usage.csv", rows);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExporting(false);
    }
  };
  return (
    <>
      <StockForecast />
      <div className="stock-title">
        <div>
          <p className="eyebrow">OWNER REPORTS</p>
          <h1>Stock analysis</h1>
          <p>Past balances, movements and what is available now.</p>
        </div>
      </div>
      <section className="stock-panel analysis-filters">
        <div className="analysis-presets">
          {[7, 30, 90, 365].map((days) => (
            <button
              className="button secondary small"
              disabled={busy}
              key={days}
              onClick={() => preset(days)}
            >
              Last {days} days
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void load();
          }}
        >
          <label className="stock-field">
            From (Sri Lanka time)
            <input
              type="datetime-local"
              required
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label className="stock-field">
            Until (Sri Lanka time)
            <input
              type="datetime-local"
              required
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </label>
          <label className="stock-field">
            Find an item
            <input
              placeholder="Name, SKU, part number or shelf"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="stock-field">
            Category
            <input
              placeholder="All categories"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            />
          </label>
          <label className="stock-check">
            <input
              type="checkbox"
              checked={archived}
              onChange={(e) => setArchived(e.target.checked)}
            />{" "}
            Include archived items
          </label>
          <button className="button primary" disabled={busy}>
            <Filter size={17} />
            {busy ? "Loading…" : "Apply filters"}
          </button>
        </form>
        <p className="stock-help">
          Start time is included; end time is excluded. Historical quantities
          come from the stock ledger. Item names and shelf details reflect the
          current catalogue.
        </p>
      </section>
      {error && (
        <p className="stock-error" role="alert">
          {error}
        </p>
      )}
      {report && (
        <section className="stock-panel analysis-report">
          <div className="section-heading">
            <div>
              <h2>{report.total} matching items</h2>
              <p className="stock-help">
                Report:{" "}
                {new Date(report.from).toLocaleString("en-GB", {
                  timeZone: "Asia/Colombo",
                })}{" "}
                to{" "}
                {new Date(report.until).toLocaleString("en-GB", {
                  timeZone: "Asia/Colombo",
                })}
                <br />
                Available now checked at{" "}
                {new Date(report.asOf).toLocaleString("en-GB", {
                  timeZone: "Asia/Colombo",
                })}
              </p>
            </div>
            <div className="analysis-exports">
              <button
                className="button secondary small"
                disabled={!report.rows.length || busy}
                onClick={() => csv("stock-analysis-page.csv", report.rows)}
              >
                <Download size={16} /> Export this page
              </button>
              <button
                className="button secondary small"
                disabled={busy || exporting}
                onClick={() => void daily()}
              >
                <Download size={16} />{" "}
                {exporting ? "Exporting…" : "Daily usage (all items)"}
              </button>
            </div>
          </div>
          <div className="stock-table-wrap">
            <table className="stock-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Category / shelf</th>
                  <th>Unit</th>
                  <th>At start</th>
                  <th>Added</th>
                  <th>Taken out</th>
                  <th>At end</th>
                  <th>Available now</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.name}</strong>
                      <small>
                        {row.sku} · {row.part_number || row.brand}
                        {row.archived ? " · Archived" : ""}
                      </small>
                    </td>
                    <td>
                      {row.category}
                      <small>{row.location || "Shelf not set"}</small>
                    </td>
                    <td>{row.unit === "LITRE" ? "L" : "units"}</td>
                    <td>{amount(row.opening_quantity)}</td>
                    <td>{amount(row.added_quantity)}</td>
                    <td>{amount(row.taken_quantity)}</td>
                    <td>
                      <strong>{amount(row.closing_quantity)}</strong>
                    </td>
                    <td>
                      <strong>{amount(row.available_now)}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!report.rows.length && (
              <div className="stock-empty">No items match these filters.</div>
            )}
          </div>
          <p className="stock-help">
            Added includes receipts, opening counts and returned items. Taken
            out includes stock-out and legacy job issues. Quantities of
            different units are not combined.
          </p>
          <div className="analysis-pagination">
            <button
              className="button secondary small"
              disabled={busy || report.page === 0}
              onClick={() => void load(report.page - 1)}
            >
              <ChevronLeft size={16} /> Previous
            </button>
            <span>
              Page {report.page + 1} of{" "}
              {Math.max(1, Math.ceil(report.total / report.pageSize))}
            </span>
            <button
              className="button secondary small"
              disabled={
                busy || (report.page + 1) * report.pageSize >= report.total
              }
              onClick={() => void load(report.page + 1)}
            >
              Next <ChevronRight size={16} />
            </button>
          </div>

        </section>
      )}
    </>
  );
}
