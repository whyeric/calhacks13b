# Build owner-controlled hedge dashboard (#24)

The dashboard now renders measured exposures, confidence intervals, dropped risks,
the planted-effect Model check, every hedge status, visible decline reasons and
metrics, payoff charts and tables with premium, owner controls, and the decision
log. Business labels and budgets come from backend contract fields. Mock and live
requests share the same components and generated serialization types.

Approve/reject sends `actor: owner` and refetches hedges, businesses and decisions.
Run desk polls `/runs/{run_id}`. Per the default explicitly allowed by #24, D1
permits owner actions from both `proposed` and `pending_approval`. No financial
arithmetic runs in the frontend; ESLint enforces this in CI and pre-commit.

Verified locally:

- Lint and TypeScript pass.
- 38 unit and HTTP integration tests pass.
- 9 Chromium browser checks pass, including axe, 1280px screenshot comparison,
  1024px stacking, owner actions and all mock scenarios.
- Production build passes.
- 30 fixture objects validate against backend Pydantic contracts.
- Test coverage: C7-A1–A7, A9–A15, A17, A20–A26, A30–A34 and A36.

Live API verification remains pending: #15 is open and `backend/app/main.py` is
absent from main. MSW tests verify the HTTP client contract, not a running backend.
Keep #24 open until the live API acceptance is checked. Human review belongs in
#36; no human check was signed off here. #28 was not started.

Branch: `issue-24-dashboard`, based on `main`.
Open a draft PR at:
https://github.com/whyeric/calhacks13b/compare/main...issue-24-dashboard?expand=1

Automatic PR creation was attempted but the GitHub connector returned
`403: Resource not accessible by integration`.
