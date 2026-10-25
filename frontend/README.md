# Dashboard development

Issue #24 owns the header, exposures, model check, hedge cards and decision log.
Backtest, books, chat and settings remain in #28.

Run `npm ci`, then `npm run dev`. Set `NEXT_PUBLIC_API_URL` to the API origin
(default `http://localhost:8000`). The API must allow the frontend origin via CORS.
Set `NEXT_PUBLIC_MOCK=1` before starting Next to use the same components with
contract-validated JSON fixtures. The page visibly labels this mode MOCK DATA.
Scenarios: `?scenario=default|empty|error|slow|longtext|negative`.
Mock changes are in memory, isolated by business, and reset on page reload.

Checks: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`,
and `npm run test:e2e` (install Chromium with `npx playwright install chromium`).
The Playwright server sets mock mode itself. Screenshot baselines are platform-specific.

Types in `lib/schema.ts` are generated from Pydantic serialization schemas,
using `python scripts/contracts.py` followed by
`npx openapi-typescript fixtures/contracts.json -o lib/schema.ts`.
Use the backend Python environment with Pydantic installed. Run
`python scripts/validate-fixtures.py` to check fixture parity. The optional local
`.python-tools` directory is ignored. `python scripts/fixtures.py` refreshes the
copied examples and explicit mock variants; budget snapshots are computed there,
never in browser code.

Financial formatting preserves exact decimal digits with string operations.
`chartScale.ts` may convert values solely for geometry. ESLint enforces this in
application code. Enable the shared pre-commit hook with
`git config core.hooksPath .githooks`; CI runs the same lint rule.

Per issue #24's explicit D1 default, both `proposed` and `pending_approval`
require an owner decision. Approve/reject sends `{actor: "owner"}` and refetches
hedges, businesses (including budget), and decisions. Nothing is booked locally.
Run desk polls `/runs/{run_id}` until done, failed, or a visible timeout.
