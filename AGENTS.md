# AGENTS.md

Guidance for coding agents (Claude Code, Codex, etc.) working in this repo.

## What this is

**Hedge Desk**: an agent that measures a small business's weather/game-day revenue exposure, finds a matching Kalshi market, sizes a hedge, and proposes it to the owner, who decides. Built for CalHacks; hard deadlines are the gates in `docs/PLAN.md`.

## Read first

| File | Why |
|---|---|
| `docs/SPEC.md` | The spec (copy of issue #1). Source of truth for behavior. |
| `docs/CONTRACTS.md` | Resolves conflicts between chunk docs. **Wins over every `ACCEPTANCE.md`.** |
| `docs/PLAN.md` | Chunks C1–C8, dependencies, gates, conventions. |
| `<chunk>/ACCEPTANCE.md` | Automated tests (`Cn-A*`) and human checks (`Cn-H*`) for the chunk you're touching. |

Before changing a chunk, read its `ACCEPTANCE.md` and the relevant `CONTRACTS.md` rows. Don't silently resolve a `needs-decision` item (D1–D5); use the proposed default only if the issue says so, and say which one you used.

## Layout

```
backend/app/
  main.py config.py models.py db.py   C6 API & contracts (models.py is the contract hub)
  data/     C1  taxi, dewey, weather, sports, features
  stats/    C2  exposure, modelcheck, backtest
  markets/  C3  kalshi, polymarket, match, sizing, rules, quote
  agent/    C4  tools, desk, prompts, policy, log, memory
  books/    C5  ledger, reconcile, close, benchmark
frontend/   C7  Next.js, Tailwind, Recharts, SWR
fixtures/   example JSON, business configs, kalshi_cache/
data/       raw Dewey exports (gitignored, never commit)
```

Stack: Python 3.12, FastAPI, DuckDB/pandas/statsmodels, httpx, `anthropic` SDK, Beancount, SQLite via sqlmodel.

## Invariants (spec §1): never break these

- **I1** Contracts bought ≤ measured exposure ÷ $1; hedge ratio ≤ 1.0 (`markets/sizing.py`).
- **I2** Every dollar figure, price, or probability shown comes from a tool result. Claude's text is never the source of a number (`agent/log.py` validates).
- **I3** Hedges are proposed only if they pass every decline rule. Declined hedges are shown with reasons, never hidden.
- **I4** The desk never approves its own hedge. Only `actor: "owner"` can approve or reject. A premium above `Thresholds.materiality_usd` also needs the controller's co-sign (`actor: "controller"`), and only the controller co-signs, sets materiality or closes the books (`agent/policy.py`, `main.py`; CONTRACTS R23).
- **I5** Every proposal, decline, approval, rejection, booking, and reconciliation is appended to the decision log.
- **I6** Anything estimated or simulated is visibly labeled.

## Conventions

- **Money, price, probability are `Decimal`**, serialized as strings (`"1240.00"`). Stats like `p_value`, `r2_*`, `coverage` stay numbers. The frontend formats; it never calculates.
- Error body for every non-2xx: `{"error": {"code", "message", "detail"}}`.
- Shared shapes live in `backend/app/models.py` with one example per object in `fixtures/examples/`. Changing a contract needs review from the consuming chunk's owner.
- The examples in `backend/fixtures/examples/` (and `fixtures/businesses/`) are **hand-maintained**: there is no generator (the old `scripts/gen_examples.py` drifted from the models and was removed). When you add or change a field, edit the example JSON by hand; `backend/tests/contract/` validates every example against its model and checks it round-trips byte-for-byte, and `frontend/scripts/validate-fixtures.py` does the same for the frontend fixtures.
- Thresholds live in one `Thresholds` dataclass in `config.py`.
- Must run offline: with `DEMO_OFFLINE=1`, Kalshi reads come from `fixtures/kalshi_cache/` and raise `CacheMiss` on a miss; Polymarket reads come from `fixtures/polymarket_cache/`, and a miss there only means "no Polymarket candidates". Claude failures fall back; chat never 5xxs.
- Secrets in `.env` only (`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `KALSHI_BASE_URL`, `DEMO_OFFLINE`, `DATABASE_URL`, `WEEKLY_BUDGET_DEFAULT`, `AVG_CHECK_USD`, `OWNER_TOKEN`, `CONTROLLER_TOKEN`). Never commit `.env` or raw data. Tests run with `POLYMARKET_ENABLED=0` unless they mock it.

## Work and PRs

- Work from a GitHub issue. Each task issue is labeled `area:*` / `role:*` and tied to a milestone (gate).
- **Stage gates, in strict order (M1 → M5):** everyone finishes their task issues for the milestone, then a human signs off in that milestone's `[Review]` issue (#30, #33, #36, #39, #42), and only then does the next stage start. GitHub "blocked by" links enforce this. **Don't start an issue that's still blocked**; check its *Blocked by* list first.
- Task issues get **automated tests**; human review happens only in the `[Review]` issues.
- Reference stable test IDs in PRs ("passes C3-A4–A9"). Human checks are signed off in the `[Review]` issue with name and time.
- Watch the `cut-list` label: if the 9 PM gate slips, cut in the order listed in spec §16. Never cut the decline moment, the payoff table with premium, the model check, the decision log, or ledger booking.
- Branch off `main`; don't push to `main` directly.

## Owners

| Role | Chunks | GitHub |
|---|---|---|
| Data | C1 | @Brocoliman |
| Stats & markets | C2, C3 | @whyeric |
| Agent & books (+ C6 integration) | C4, C5, C6 | @frenchbaguetteman |
| Frontend & story | C7, C8 | @acs-c |
