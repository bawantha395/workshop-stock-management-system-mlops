/** Reorder suggestions from the nightly forecast and live stock (pure functions, no browser APIs). */
export type Row = { id: string; sku: string; name: string; unit: string; availableNow: number; reorderLevel?: number; status: string; next7?: number; next30?: number; suggestedTopUp7?: number };
export type Forecast = { status: string; forecast?: string; message?: string; historyUntil?: string; generatedAt?: string; products: Row[] };
export type Suggestion = Row & { daysLeft: number; order: number; basis: "forecast" | "level" };

export const whole = (n: number) => new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(n);

/** An item has a usable forecast only when the nightly model passed its own back-test. */
export const hasForecast = (r?: Row) => !!r && (r.status === "forecast" || r.status === "not_moving");

/** Without a forecast the plain rule applies: at or below the reorder level, top up to double that level. */
export function levelOrder(r: Row): number {
  const level = r.reorderLevel || 0;
  if (r.availableNow > level) return 0;
  if (level <= 0 && r.availableNow > 0) return 0;
  return Math.max(level * 2 - r.availableNow, 1);
}

/** Items to reorder this week, most urgent first. Uses the forecast where it exists and the reorder level everywhere else. */
export function reorderSuggestions(products: Row[]): { reorder: Suggestion[]; soon: number; idle: number } {
  const all = products.map((p): Suggestion => {
    if (hasForecast(p)) {
      const perDay = (p.next7 || 0) / 7;
      return { ...p, basis: "forecast", daysLeft: perDay > 0 ? p.availableNow / perDay : Infinity, order: p.suggestedTopUp7 || 0 };
    }
    return { ...p, basis: "level", daysLeft: p.availableNow <= 0 ? 0 : Infinity, order: levelOrder(p) };
  });
  const reorder = all.filter((p) => p.order > 0).sort((a, b) => a.daysLeft - b.daysLeft || a.availableNow - b.availableNow);
  return { reorder, soon: all.filter((p) => p.basis === "forecast" && p.daysLeft <= 3).length + all.filter((p) => p.basis === "level" && p.order > 0).length, idle: all.filter((p) => p.basis === "forecast" && (p.next30 || 0) === 0 && p.availableNow > 0).length };
}

/** Why an item is on the list, in plain words. */
export function why(r: Suggestion) {
  return r.basis === "forecast" ? runsOut(r.daysLeft) : r.availableNow <= 0 ? "Out of stock" : "Order soon";
}

export function runsOut(daysLeft: number) {
  if (daysLeft <= 0) return "Out of stock";
  if (!Number.isFinite(daysLeft)) return "No usage expected";
  if (daysLeft < 1) return "Runs out today";
  return "Runs out in ~" + Math.round(daysLeft) + (Math.round(daysLeft) === 1 ? " day" : " days");
}

