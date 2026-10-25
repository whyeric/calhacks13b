# Controls: who may do what, what the desk remembers, and the record

Hedge Desk fills two seats: the **treasury analyst** who finds and sizes event-risk hedges, and
the **bookkeeper** who books, reconciles and closes them. It works under two people: the
**owner**, who decides on every hedge, and the **controller**, who signs off on material ones and
on the books. This page lists the limits the code enforces and where.

## Roles and segregation of duties

| Action | Who | Where | Refusal |
|---|---|---|---|
| Find, size and judge hedges; write the summary | the desk (Claude or the fallback) | `agent/desk.py`, `markets/` | — |
| Approve or reject a hedge | **owner** only | `POST /hedges/{id}/approve`, `/reject` | `403 owner_only` |
| Co-sign (or refuse) a hedge above materiality | **controller** only | `POST /hedges/{id}/cosign` | `403 controller_only` |
| Change the materiality threshold | **controller** only | `PUT /businesses/{id}/settings` with `X-Actor: controller` | `403 controller_only` |
| Close the books through a date | **controller** only | `POST /businesses/{id}/close` | `403 controller_only` |
| Other settings (budget, decline thresholds) | owner | `PUT /businesses/{id}/settings` | — |

- **Nobody does two halves of one action.** The controller can't approve, and the owner can't
  co-sign, raise materiality to skip the co-sign, or close the books. The desk holds neither
  role's token and can do none of these.
- **Materiality.** `Thresholds.materiality_usd` (default $200.00). A hedge whose premium is above
  it carries `needs_controller: true`; the owner's approval answers `409 needs_controller` until
  the controller co-signs, and `409 controller_refused` after a refusal, when the owner can only
  reject. A co-sign doesn't approve anything.
- **Tokens.** With `OWNER_TOKEN` / `CONTROLLER_TOKEN` set, each role's actions also need its
  `X-Owner-Token` / `X-Controller-Token`. `make demo` and `make dev` set demo values and give
  them to the frontend, whose header switch (**Acting as: Owner | Controller**) picks which one to
  send. Outside the demo, set your own.
- **Everything is on the record (I5).** Co-signs and refusals are logged as `cosign` /
  `cosign_refused` with actor `controller`. A held approval, a wrong-role attempt and a wrong
  token are logged as `refusal`.

## The desk's memory (time)

When the desk stores a hedge, `agent/memory.py` attaches `owner_history`, built from that
exposure's earlier real hedges for the business (sample-week examples excluded):

- counts of approved, rejected and expired-unapproved hedges;
- premium paid and payouts received;
- up to 5 recent outcomes with the owner's own note or rejection reason (`decision_note`).

If the owner rejected the last two decided hedges for this exposure, the pattern is
`rejected_recently`. The next proposal then opens with *"You rejected the last two rain hedges
(last reason: "…"); the rules pass again this week, so the desk asks once more, and you decide."*
Memory changes how the desk asks, never what the rules decide.

## Receipts: defending a decision

`GET /hedges/{id}/receipt` returns the record behind one decision, with no LLM involved:

- the hedge and every check with its metric, plus the thresholds in force;
- the exposure the hedge was measured from;
- who still has to sign (`approvals_required`) and where each input came from (`sources`);
- every log entry about the hedge, oldest first.

The **Challenge this decision** button on a card shows it.

## Period close

`POST /businesses/{id}/close {actor: "controller", through, acknowledge_exceptions, note}`
(`books/close.py`):

1. `through` must be a past day in New York and later than the previous close.
2. Reconciliation runs (read-only). Open mismatches block the close with `409 unreconciled`,
   unless the controller acknowledges them; then they're carried word for word as `exceptions`.
3. The trial balance as of `through` is taken from the ledger and must sum to zero.
4. The close is stored and logged (`period_close`). After that, the ledger dates nothing on or
   before the lock. A late payout, withdrawal or premium lands on the next open day, with
   *"[belongs to 2026-10-22; books closed through 2026-10-23]"* in its narration
   (`ledger.posting_date`).

Proposed and pending hedges have no ledger entries yet, so they don't block a close. The record
counts them so the controller can see what is still waiting on the owner.

## Two venues: Kalshi and Polymarket

The desk scans Polymarket next to Kalshi for every daily exposure (`markets/polymarket.py`). It
reads public data only and never trades.

| Exposure | Polymarket market | Settles on | Used? |
|---|---|---|---|
| rain | "Where will it rain on <date>?", New York, NY | NWS climate report, Central Park (≥ 0.01 in, trace = no) | Yes, same station as KXRAIN and our flags |
| home_win | NBA/NHL game moneyline (`nba-det-nyk-2026-10-27`) | official final result | Yes |
| hot | "Highest temperature in NYC on <date>?" | LaGuardia (KLGA, Wunderground), 2 °F buckets | **No**: a different station from the one we measured; the no_market check says so |
| playoff_home | — | — | Kalshi season futures only |

- **Same rules for both venues.** Polymarket outcome-token asks are folded into Kalshi's book
  shape, so sizing (I1), the book walk and all six decline rules run unchanged.
- **Fees.** Polymarket's are `rate × C × P × (1 − P)` from each market's `feeSchedule`: weather
  is currently 0 and NHL games 0.05. They are rounded up to the cent.
- **Which market wins.** The desk picks the deepest book within 5¢ on the side it buys, across
  both venues, and the card lists every market it scanned.
- **Booking.** An approved Polymarket hedge books to `Assets:Polymarket:Cash`.
- **Offline.** Replays `fixtures/polymarket_cache/`, which `make warm` fills. A cache miss means
  "no Polymarket candidates", never a failed desk run.
- **Eligibility caveat.** Whether a given business may trade on Polymarket depends on its
  jurisdiction. The desk only reads public prices and proposes; it never places an order on
  either venue.
