# Kalshi demo trading

Hedge Desk can place a **real order on Kalshi's demo exchange** when the owner approves a hedge, and read the demo account's real settlements back for reconciliation. The demo exchange uses fake money. Real-money trading is out of scope: the client refuses every host except the demo hosts.

Code: `backend/app/markets/trading.py` (client, order on approval, `KalshiVenueSource`), `backend/app/integrations/kalshi_routes.py` (`GET /integrations/kalshi/status`). Tests: `backend/tests/markets/test_trading.py`.

## Setup

1. Create a demo account at <https://demo.kalshi.co>. It is separate from a production Kalshi account, and demo funds are fake.
2. Go to **Account & security → API Keys → Create Key**. Save both values:
   - the **API Key ID** (a UUID shown on screen), and
   - the **private key**, downloaded once as a PEM file. Kalshi cannot show it again.
3. Put the PEM at `secrets/kalshi-demo.pem` in the repo root. `secrets/` and `*.pem` are gitignored. Never commit it.
4. In `.env`:

   ```
   KALSHI_TRADING_ENABLED=1
   KALSHI_DEMO_BASE_URL=https://demo-api.kalshi.co/trade-api/v2
   KALSHI_API_KEY_ID=<your key id>
   KALSHI_PRIVATE_KEY_PATH=secrets/kalshi-demo.pem
   DEMO_OFFLINE=0
   ```

   A relative key path resolves from the repo root.
5. Check `GET /integrations/kalshi/status`. It should say `mode: "demo"`, `reachable: true` and show your demo balance. If `mode` is `"off"`, `reason` says why.

Trading stays off when any of these hold: `KALSHI_TRADING_ENABLED` is off, `DEMO_OFFLINE=1`, the key id is missing, the key file is missing, or the base URL is not a demo host. In each of those cases nothing is sent, and approval works exactly as it did before this feature.

## What happens on approval

The owner approves; if the premium is above materiality, the controller has already co-signed. The approval books as before, at the approved figures. Then `trading.on_owner_approval` places **one** order:

| | |
|---|---|
| Endpoint | `POST /portfolio/events/orders` (Create Order V2) |
| Side | V2 quotes every order on the YES leg. A YES hedge sends `side: "bid"` at the YES price. A NO hedge sends `side: "ask"` (sell YES) at `1 − NO price`, which buys NO at no more than the cap. |
| Count | The hedge's filled contracts, which is never more than its target. Sizing already capped that at the measured exposure ÷ $1 (I1). |
| Price cap | The worst level of the hedge's quoted book walk, rounded down to the cent. |
| Time in force | `immediate_or_cancel`. It fills what it can now and cancels the rest, so no order is left resting. (`fill_or_kill` would turn every partial fill into a failure.) |
| `client_order_id` | A UUIDv5 of the hedge id. A retry reuses it. Kalshi answers 409 to a duplicate, and the desk then reads the existing order back instead of placing another. |

Every step goes into the decision log as `actor: "system"`, labeled "Kalshi demo (fake money)" with `numbers.venue = "kalshi_demo"` (I5, I6):

- `order_placed`: the order was accepted. Records order id, ticker, requested count, limit, and whether a stand-in was used.
- `order_filled`: everything filled. Records the actual count and average price.
- `order_partial`: some filled; the rest was canceled.
- `order_failed`: Kalshi rejected the order, nothing filled, the network failed, or there was any other error. The reason is recorded.
- `order_skipped`: no order was sent, for example because the market is not listed on demo, the hedge is a Polymarket hedge, or the hedge has no quoted price.

**The approval never fails because of the venue.** A failed order leaves the approval and the booking as they were. The failure is logged and shown on the hedge.

**The desk cannot trade.** Only the approve route calls `on_owner_approval`. That function re-checks `decided_by == "owner"`. Nothing under `app/agent/` references the trading module, and a test enforces this (I4).

## Booked figures vs the actual fill (for reconciliation)

The booking is **not** rewritten to match the fill. The actual fill lives in two places:

- **`Hedge.venue_order`** (`VenueOrder` in `models.py`). It holds `status`, `order_id`, `client_order_id`, `ticker` (where the order went), `production_ticker`, `stand_in`, `requested`, `limit_price`, `filled`, `avg_price` (on the hedge's own side), `cost`, `fee`, and `differs_from_booked`. Compare these with the hedge's `n_filled`, `avg_price` and `premium`, which are the booked figures.
- The `order_*` log entries. Their `numbers` include `filled`, `avg_price`, `cost`, `fee`, `booked_n` and `booked_avg_price`.

A fill that differs from the booking is the "sources disagree" case that reconciliation should flag.

## Settlements: `KalshiVenueSource`

`trading.KalshiVenueSource` implements `books.sources.VenueSource` with `origin = "kalshi_demo"`. It reads `GET /portfolio/settlements`. Kalshi settlement records carry the market ticker but **no order id**. To tie each settlement to a hedge, the source:

1. finds the hedges whose `venue_order.ticker` matches the settlement;
2. narrows them with the demo account's fills on that ticker, keeping only hedges where `fill.order_id == venue_order.order_id`.

Settlement `revenue` is integer cents and is converted to dollars. `fee_cost` is used as the fee. `settled_on` is the New York date of `settled_time`. A settlement that maps to no hedge, or to more than one, comes back with `hedge_id = None` for every business, so reconciliation flags it. When offline or with trading off, the source makes no calls and returns `[]`.

## What is on demo (checked 2026-10-25)

These checks used the public, unauthenticated endpoints at `https://demo-api.kalshi.co/trade-api/v2`. Demo mirrors production's series and ticker formats:

| Series | On demo | Notes |
|---|---|---|
| `KXRAIN` (incl. `KXRAIN-…-NYC`) | yes, 35 open | The NYC book was empty when checked |
| `KXRAINNYCM` | yes, 15 open | |
| `KXHIGHNY` | yes, 6 open | Some books have resting orders |
| `KXNBAGAME` | yes, 64 open | Includes Knicks games; about 16 of the first 40 books had orders |
| `KXNHLGAME` | yes, 94 open | The first 40 books were empty |
| `KXNBAPLAYOFF`, `KXNHLPLAYOFF` | yes, 30 / 32 open | Includes `-27-NYK` and `-27-NYR`; books were empty |
| `KXNBASERIES`, `KXNHLSERIES` | series exist, 0 open | Off-season |
| `KXRAINNYC` (retired) | series exists, 0 open | The sample week's `KXRAINNYC-26OCT28` is not listed |
| `KXSNOWSTORM` | series exists, 0 open | |

**Liquidity on demo is thin and differs from production.** Demo prices are not production prices. An immediate-or-cancel order capped at a production quote will often fill partially or not at all (`order_partial` / `order_failed`), and that is expected.

Ticker mapping:

1. If the hedge's own ticker is listed and open on demo (`status` `active`/`open`), the order uses that ticker.
2. Otherwise, if `backend/fixtures/kalshi_demo_stand_ins.json` maps the ticker's series (the prefix before the first `-`) to a demo market that is open, the order goes there. It is logged and labeled "demo stand-in, not the production contract", and `venue_order.stand_in` is `true`. The file ships empty because no stand-in was needed when checked. Daily and game tickers expire, so update the file before a demo.
3. Otherwise no order is sent, and the log records `order_skipped: not listed on demo`.

## Kalshi API facts verified (docs.kalshi.com, API 3.34.0)

- **Auth:** three headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` (milliseconds), and `KALSHI-ACCESS-SIGNATURE`. The signature is base64 RSA-PSS (MGF1-SHA256, salt length = digest length) with SHA-256, over `timestamp + METHOD + path`. The path is from the host root (`/trade-api/v2/...`) with the query string removed. Ed25519 keys are also accepted and sign the same message directly; both kinds are supported.
- **Demo hosts:** `demo-api.kalshi.co` and `external-api.demo.kalshi.co` both serve `/trade-api/v2`. Both are allowed; nothing else is.
- **Orders:** `POST /portfolio/events/orders` (V2). The legacy `/portfolio/orders` POST is being deprecated. Request: `ticker`, `side` (`bid`/`ask`), `count` (fixed-point string), `price` (fixed-point dollars), `time_in_force` (`fill_or_kill` | `good_till_canceled` | `immediate_or_cancel`), `self_trade_prevention_type` (required), and `client_order_id`. Response: `order_id`, `fill_count`, `remaining_count`, `average_fill_price`, `average_fee_paid`, `ts_ms`.
- **Order object** (`GET /portfolio/orders/{id}`, `GET /portfolio/orders?ticker=`): `fill_count_fp`, `remaining_count_fp`, `yes_price_dollars`/`no_price_dollars`, `taker_fill_cost_dollars`, `taker_fees_dollars`, `outcome_side`, `book_side`, and `client_order_id`.
- **Fills:** `GET /portfolio/fills?ticker=&order_id=` returns `order_id`, `count_fp`, `yes_price_dollars`/`no_price_dollars`, and `fee_cost`.
- **Settlements:** `GET /portfolio/settlements` returns `ticker`, `market_result`, `yes_count_fp`/`no_count_fp`, `revenue` (integer **cents**), `settled_time`, and `fee_cost`.
- **Balance:** `GET /portfolio/balance` returns `balance` (cents) and `balance_dollars`.

## Not yet verified (needs a real demo key)

No API key existed while this was built. Everything authenticated is tested against mocked HTTP only, so these points still need checking with a real key:

- that a real signed request is accepted (end to end);
- that `average_fill_price` on a V2 `ask` is the YES-leg price, so the desk's NO average is `1 −` that value;
- that `taker_fill_cost_dollars` on a read-back order is on the order's own outcome side;
- that a UUID `client_order_id` is accepted, and that a duplicate returns 409;
- how `fee_cost` on a settlement relates to the trading fees;
- whether a `linear_cent` market accepts the `0.4800`-style 4-decimal price string (the docs say 2–4 decimals are accepted).
