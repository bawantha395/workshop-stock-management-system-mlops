/** Sales-history import files and the "whole weeks to yesterday" date alignment (same rule as mlops/real_data/online_retail.py). */
export type Sale = { date: string; quantity: number };
export type HistoryProduct = { sku: string; openingDate: string; openingQuantity: number; sales: Sale[]; [key: string]: unknown };
export type HistoryFile = { source: string; license: string; sourceUrl?: string; note?: string; dateAlignment?: string; products: HistoryProduct[]; [key: string]: unknown };
export const ALIGNMENT = "whole-weeks-to-yesterday";
const DAY = 86_400_000;
const parse = (value: string) => Date.parse(value + "T00:00:00Z");
const iso = (time: number) => new Date(time).toISOString().slice(0, 10);
export const colomboToday = (now = Date.now()) => iso(now + 330 * 60_000);

export function readHistory(text: string): HistoryFile {
  const file = JSON.parse(text) as HistoryFile;
  if (!file || typeof file.source !== "string" || typeof file.license !== "string" || !Array.isArray(file.products) || !file.products.length)
    throw new Error("This is not a Stocklane sales-history file");
  if (file.products.some((p) => !Array.isArray(p.sales) || typeof p.openingDate !== "string"))
    throw new Error("Every item needs an opening date and a sales list");
  return file;
}

/** Moves every date forward by whole weeks so the last sales day becomes yesterday; weekdays are kept. */
export function alignToYesterday(file: HistoryFile, today: string): { file: HistoryFile; shiftDays: number } {
  if (file.dateAlignment !== ALIGNMENT) return { file, shiftDays: 0 };
  const dates = file.products.flatMap((p) => p.sales.map((s) => parse(s.date)));
  if (!dates.length) throw new Error("The file has no sales days");
  const last = Math.max(...dates), yesterday = parse(today) - DAY;
  const weekday = (t: number) => new Date(t).getUTCDay();
  const end = last - ((((weekday(last) - weekday(yesterday)) % 7) + 7) % 7) * DAY;
  const shiftDays = Math.round((yesterday - end) / DAY);
  if (shiftDays < 0 || shiftDays % 7) throw new Error("Sales dates are later than yesterday");
  const move = (value: string) => iso(parse(value) + shiftDays * DAY);
  const products = file.products.map((p) => ({
    ...p,
    openingDate: move(p.openingDate),
    sales: p.sales.filter((s) => parse(s.date) <= end).map((s) => ({ date: move(s.date), quantity: s.quantity })),
  }));
  const note = `${file.note ?? ""} Dates moved forward ${shiftDays} days (${shiftDays / 7} whole weeks) at import so the last day is yesterday; source days after ${iso(end)} dropped to align weekdays.`.trim();
  const { dateAlignment: _ignored, ...rest } = file;
  return { file: { ...rest, products, note }, shiftDays };
}
