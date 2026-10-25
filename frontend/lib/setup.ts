"use client";
import { useSyncExternalStore } from "react";
import type { Hedge } from "./types";

// First-run setup flag. Storage can be missing or throw (private windows,
// blocked site data); then setup simply shows again.
export const SETUP_KEY = "hedge-desk:setup-done";
const EVENT = "hedge-desk:setup";
function read(): boolean {
  try {
    return window.localStorage.getItem(SETUP_KEY) === "1";
  } catch {
    return false;
  }
}
function write(done: boolean) {
  try {
    if (done) window.localStorage.setItem(SETUP_KEY, "1");
    else window.localStorage.removeItem(SETUP_KEY);
  } catch {
    // Ignore: the flag only lasts for this page view.
  }
  memory = done;
  window.dispatchEvent(new Event(EVENT));
}
// Fallback when storage throws, so finishing setup still opens the dashboard.
let memory: boolean | null = null;
function subscribe(notify: () => void) {
  window.addEventListener(EVENT, notify);
  window.addEventListener("storage", notify);
  return () => {
    window.removeEventListener(EVENT, notify);
    window.removeEventListener("storage", notify);
  };
}
/** null while server rendering; then whether setup was completed. */
export function useSetupDone(): boolean | null {
  return useSyncExternalStore(
    subscribe,
    () => read() || memory === true,
    () => null,
  );
}
export const markSetupDone = () => write(true);
export const resetSetup = () => write(false);

// Desk run time of the newest hedge: hedges are priced from the Kalshi cache
// when the desk runs. A per-hedge `prices_fetched_at`, if the API adds one,
// is the exact cache time and wins.
type PriceStamp = { prices_fetched_at?: string | null };
export function newestPriceTime(hedges: Hedge[]): string | null {
  const stamps = hedges
    .map(
      (row) => (row as Hedge & PriceStamp).prices_fetched_at ?? row.created_at,
    )
    .filter((stamp): stamp is string => !!stamp)
    .sort();
  return stamps.length ? stamps[stamps.length - 1] : null;
}
export function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
