/** Reorder suggestions from the nightly forecast and live stock (pure functions, no browser APIs). */
export type Row = { id: string; sku: string; name: string; unit: string; availableNow: number; status: string; next7?: number; next30?: number; suggestedTopUp7?: number };
export type Forecast = { status: string; message?: string; historyUntil?: string; trainedAt?: string; products: Row[] };
export type Suggestion = Row & { daysLeft: number; order: number };

export const whole = (n: number) => new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(n);

/** Items to reorder this week, most urgent first; computed from the nightly forecast and live stock. */
export function reorderSuggestions(products: Row[]): { reorder: Suggestion[]; soon: number; idle: number } {
  const usable = products.filter((p) => p.status === "trained_ml" || p.status === "weekday_baseline");
  const withCover = usable.map((p) => {
    const perDay = (p.next7 || 0) / 7;
    return { ...p, daysLeft: perDay > 0 ? p.availableNow / perDay : Infinity, order: p.suggestedTopUp7 || 0 };
  });
  const reorder = withCover.filter((p) => p.order > 0).sort((a, b) => a.daysLeft - b.daysLeft);
  return { reorder, soon: withCover.filter((p) => p.daysLeft <= 3).length, idle: withCover.filter((p) => (p.next30 || 0) === 0 && p.availableNow > 0).length };
}

export function runsOut(daysLeft: number) {
  if (daysLeft <= 0) return "Out of stock";
  if (!Number.isFinite(daysLeft)) return "No usage expected";
  if (daysLeft < 1) return "Runs out today";
  return "Runs out in ~" + Math.round(daysLeft) + (Math.round(daysLeft) === 1 ? " day" : " days");
}

