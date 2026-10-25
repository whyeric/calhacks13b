import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { SETUP_KEY } from "@/lib/setup";
afterEach(cleanup);
// Dashboard tests start past the first-run wizard; wizard tests clear this.
beforeEach(() => window.localStorage.setItem(SETUP_KEY, "1"));
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: unknown }) => children,
  BarChart: () => null,
  LineChart: () => null,
  Line: () => null,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));
