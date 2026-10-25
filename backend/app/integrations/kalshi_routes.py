"""GET /integrations/kalshi/status: whether owner approvals place Kalshi DEMO orders.

Read-only. Calls the demo balance endpoint only when trading is fully configured and not
offline; otherwise nothing is sent and `reason` says why the mode is off.
"""

from decimal import ROUND_FLOOR, Decimal

from fastapi import APIRouter

from app.config import get_settings
from app.markets import trading
from app.models import KalshiStatus

router = APIRouter(tags=["integrations"])


@router.get("/integrations/kalshi/status", response_model=KalshiStatus)
def kalshi_status() -> KalshiStatus:
    s = get_settings()
    reason = trading.trading_off_reason(s)
    key = trading.private_key_file(s)
    reachable = balance = error = None
    if reason is None:
        try:
            with trading.make_client(s) as client:
                balance = client.balance().quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
            reachable = True
        except Exception as e:  # status never 5xxs because of the venue
            reachable, error = False, f"{type(e).__name__}: {e}"
    return KalshiStatus(
        mode="off" if reason else "demo",
        reason=reason,
        trading_enabled=s.kalshi_trading_enabled,
        offline=s.demo_offline,
        key_id_present=bool(s.kalshi_api_key_id and s.kalshi_api_key_id.strip()),
        private_key_present=bool(key and key.is_file()),
        base_url=s.kalshi_demo_base_url,
        host_allowed=trading.host_allowed(s),
        reachable=reachable,
        balance=balance,
        error=error,
    )
