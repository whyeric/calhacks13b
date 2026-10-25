"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import type { Hedge, Settings, Thresholds } from "@/lib/types";
import { apiGet, apiPut } from "@/lib/api";
import { label } from "@/lib/labels";
import { Drawer } from "./ChatDrawer";
import { StateBoundary } from "./StateBoundary";
import { Button } from "@/components/ui/button";

type Kind = "unit" | "money" | "count";
type Field = {
  key: keyof Thresholds | "weekly_budget";
  name: string;
  kind: Kind;
  hint: string;
  advanced?: boolean;
};
export const FIELDS: Field[] = [
  {
    key: "overpay_max",
    name: "Most we’ll overpay vs. how often it happens",
    kind: "unit",
    hint: "0.15 = 15¢ above the historical rate per contract",
  },
  {
    key: "cost_ratio_max",
    name: "Most protection may cost, as a share of the swing",
    kind: "unit",
    hint: "0.35 = up to 35% of the swing it removes",
  },
  {
    key: "basis_r2_min",
    name: "How closely the weather source must track your revenue",
    kind: "unit",
    hint: "0 to 1; higher is stricter",
  },
  {
    key: "min_size_usd",
    name: "Smallest effect worth protecting ($)",
    kind: "money",
    hint: "Dollars per event day",
  },
  {
    key: "weekly_budget",
    name: "Weekly budget ($)",
    kind: "money",
    hint: "Premiums above this need your approval",
  },
  {
    key: "fill_decline",
    name: "Decline below this share of contracts filled",
    kind: "unit",
    hint: "0 to 1",
    advanced: true,
  },
  {
    key: "fill_full",
    name: "Share of contracts that counts as a full fill",
    kind: "unit",
    hint: "0 to 1",
    advanced: true,
  },
  {
    key: "max_slip",
    name: "Most price slippage accepted",
    kind: "unit",
    hint: "0 to 1",
    advanced: true,
  },
  {
    key: "min_support",
    name: "Fewest past event days needed",
    kind: "count",
    hint: "Whole number, 1 or more",
    advanced: true,
  },
  {
    key: "max_tool_calls",
    name: "Most lookups per desk run",
    kind: "count",
    hint: "Whole number, 1 or more",
    advanced: true,
  },
];
// Format checks only (no arithmetic): values go to the API as the typed strings.
const PATTERNS: Record<Kind, [RegExp, string]> = {
  unit: [
    /^(0(\.\d{1,4})?|1(\.0{1,4})?)$/,
    "Enter a number from 0 to 1 (up to 4 decimals).",
  ],
  money: [/^\d{1,7}(\.\d{1,2})?$/, "Enter a dollar amount like 250 or 250.00."],
  count: [/^[1-9]\d{0,3}$/, "Enter a whole number of 1 or more."],
};
type Values = Record<Field["key"], string>;
export function toValues(settings: Settings): Values {
  const values = { weekly_budget: settings.weekly_budget } as Values;
  for (const [key, value] of Object.entries(settings.thresholds))
    values[key as keyof Thresholds] = String(value);
  return values;
}
export function fieldError(field: Field, value: string): string {
  if (!value.trim()) return "Required.";
  const [pattern, message] = PATTERNS[field.kind];
  return pattern.test(value.trim()) ? "" : message;
}
export type Flip = { id: string; title: string; from: string; to: string };
export function SettingsForm({
  initial,
  onSave,
}: {
  initial: Settings;
  onSave: (body: Settings) => Promise<void>;
}) {
  const [values, setValues] = useState<Values>(() => toValues(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => setValues(toValues(initial)), [initial]);
  const errors = Object.fromEntries(
    FIELDS.map((field) => [
      field.key,
      fieldError(field, values[field.key] ?? ""),
    ]),
  );
  const invalid = Object.values(errors).some(Boolean);
  async function save() {
    setSaving(true);
    setError("");
    const { weekly_budget, ...thresholds } = Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key, value.trim()]),
    ) as Values;
    try {
      // Strings only (CONTRACTS R14); the server re-runs the rules, the browser never re-decides.
      await onSave({
        thresholds: thresholds as unknown as Thresholds,
        weekly_budget,
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Settings were not saved. Retry.",
      );
    } finally {
      setSaving(false);
    }
  }
  const renderField = (field: Field) => {
    const id = `setting-${field.key}`;
    const value = values[field.key] ?? "";
    const message = errors[field.key];
    return (
      <div key={field.key} className="setting">
        <label htmlFor={id}>{field.name}</label>
        <div className="setting-input">
          {field.kind === "unit" && (
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              aria-label={`${field.name} slider`}
              value={message ? "0" : value}
              onChange={(e) =>
                setValues({ ...values, [field.key]: e.target.value })
              }
            />
          )}
          <input
            id={id}
            inputMode="decimal"
            value={value}
            aria-invalid={Boolean(message)}
            aria-describedby={`${id}-hint`}
            onChange={(e) =>
              setValues({ ...values, [field.key]: e.target.value })
            }
          />
        </div>
        <small id={`${id}-hint`} className={message ? "field-error" : ""}>
          {message || field.hint}
        </small>
      </div>
    );
  };
  return (
    <form
      className="settings-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!invalid) save();
      }}
    >
      {FIELDS.filter((field) => !field.advanced).map(renderField)}
      <details>
        <summary>More rules</summary>
        {FIELDS.filter((field) => field.advanced).map(renderField)}
      </details>
      {invalid && (
        <p role="alert" className="field-error">
          Fix the highlighted values to save.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <Button className="primary" type="submit" disabled={invalid || saving}>
        {saving ? "Saving…" : "Save and re-check hedges"}
      </Button>
    </form>
  );
}
export function SettingsDrawer({
  businessId,
  open,
  onClose,
  hedges,
  onSaved,
}: {
  businessId: string;
  open: boolean;
  onClose: () => void;
  hedges: Hedge[];
  onSaved: () => Promise<Hedge[] | undefined>;
}) {
  const path = `/businesses/${encodeURIComponent(businessId)}/settings`;
  const settings = useSWR<Settings>(
    open ? ["settings", businessId] : null,
    () => apiGet(path),
  );
  const [flips, setFlips] = useState<Flip[] | null>(null);
  async function save(body: Settings) {
    const before = new Map(hedges.map((row) => [row.id, row.status]));
    const saved = await apiPut<Settings>(path, body);
    await settings.mutate(saved, { revalidate: false });
    const after = (await onSaved()) ?? [];
    setFlips(
      after
        .filter(
          (row) => before.has(row.id) && before.get(row.id) !== row.status,
        )
        .map((row) => ({
          id: row.id,
          title: `${label(row.exposure_id.replace(/^exp_/, ""))} · ${row.market_title ?? row.id}`,
          from: label(before.get(row.id)!),
          to: label(row.status),
        })),
    );
  }
  return (
    <Drawer title="Desk settings" open={open} onClose={onClose}>
      <p className="muted">
        Change a rule and the desk re-checks this week’s hedges with the same
        deterministic rules. No new decisions are made in your browser.
      </p>
      {flips && (
        <div className="flips" role="status">
          {flips.length ? (
            <>
              <strong>
                {flips.length} decision{flips.length === 1 ? "" : "s"} changed
              </strong>
              <ul>
                {flips.map((flip) => (
                  <li key={flip.id}>
                    {flip.title}: <span className="flip-from">{flip.from}</span>{" "}
                    → <strong>{flip.to}</strong>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <strong>Saved. No decisions changed.</strong>
          )}
        </div>
      )}
      <StateBoundary
        loading={settings.isLoading}
        error={settings.error}
        retry={() => settings.mutate()}
      >
        {settings.data && (
          <SettingsForm initial={settings.data} onSave={save} />
        )}
      </StateBoundary>
    </Drawer>
  );
}
