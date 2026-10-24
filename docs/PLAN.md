# Hedge Desk · Work plan

Spec: [`docs/SPEC.md`](SPEC.md) (copy of issue #1). Repo root = `hedge-desk/` in spec §12.
Each chunk has an `ACCEPTANCE.md` at its location with **automated acceptance tests** (`Cn-A*`) and a **human review checklist** (`Cn-H*`). No code yet.

## Chunks

| Chunk | Location | Spec | Owner role | Acceptance doc |
|---|---|---|---|---|
| C1 Data | `backend/app/data/` | §2–4 | Data | [ACCEPTANCE.md](../backend/app/data/ACCEPTANCE.md) |
| C2 Stats | `backend/app/stats/` | §5, §10 | Stats & markets | [ACCEPTANCE.md](../backend/app/stats/ACCEPTANCE.md) |
| C3 Markets | `backend/app/markets/` | §6–8 | Stats & markets | [ACCEPTANCE.md](../backend/app/markets/ACCEPTANCE.md) |
| C4 Agent, policy, log | `backend/app/agent/` | §1, §11 | Agent & books | [ACCEPTANCE.md](../backend/app/agent/ACCEPTANCE.md) |
| C5 Books | `backend/app/books/` | §9 | Agent & books | [ACCEPTANCE.md](../backend/app/books/ACCEPTANCE.md) |
| C6 API & contracts | `backend/app/` (main, config, models, db) | §12 | Integration | [ACCEPTANCE.md](../backend/app/ACCEPTANCE.md) |
| C7 Frontend | `frontend/` | §13 | Frontend & story | [ACCEPTANCE.md](../frontend/ACCEPTANCE.md) |
| C8 Demo ops | repo root, `notebooks/` | §14–17 | Frontend & story | [ACCEPTANCE-demo.md](ACCEPTANCE-demo.md) |

## Dependencies

```
C6 contracts (example JSON, 3:30 PM) ──► everyone can start against fixtures
C1 Data ──► C2 Stats ──► C3 Markets ──► C4 Agent ──► C5 Books
                 ▲            │
                 └── backtest uses C3 sizing/rules
C1–C5 ──► C6 API ──► C7 Frontend ──► C8 Demo
```

Critical path: **C6 contracts → C1 → C2 → C3 → C6 API → C7 → C8**. C4 and C5 can build against example JSON in parallel.

## Gates (spec §16)

| Time | Must be green |
|---|---|
| 3:30 PM | C1 confirm-checks C1–C6 answered; C6 example JSON + model contract tests |
| 6:00 PM | C1 feature tables; C2 exposure fit + model check |
| 9:00 PM | C3, C4, C5 booking, C6 API end to end on live Kalshi; C7 on real API; Devpost draft |
| Midnight | C2 real-priced backtest; C5 reconciliation; C4 chat "why?"; decline moment live |
| 2:00 AM | C8 offline demo + video |

## Contracts

[`CONTRACTS.md`](CONTRACTS.md) resolves 19 interface conflicts between chunk docs and lists 5 decisions (D1–D5) that need a human.

## Stage gates

Milestones run strictly in sequence: **M1 → M2 → M3 → M4 → M5**.

1. Every owner finishes their task issues in the milestone (closed, automated tests green).
2. Human sign-off happens in that milestone's `[Review]` issue (#30, #33, #36, #39, #42), recorded with name + time, and the issue is closed.
3. Only then do next-stage tasks start.

This is enforced with GitHub "blocked by" links: each review issue is blocked by its milestone's tasks, and each next-stage task is blocked by the previous review. If a gate slips, use the cut list (spec §16). Don't start the next stage early.

## Conventions

- Test IDs are stable: reference them in PRs ("passes C3-A4–A9").
- Human checks are signed off in the milestone's `[Review]` issue with name + time, not in task PRs.
- Raw Dewey exports live in repo-root `data/` (gitignored); code lives in `backend/app/data/`.
