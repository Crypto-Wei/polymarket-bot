import sys
from datetime import datetime, timezone, timedelta

from market_utils import make_client, get_usdc_balance, get_open_orders, get_positions

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

TZ_TAIPEI = timezone(timedelta(hours=8))

# ── 建立 Client ───────────────────────────────────────────────────────────────

print("\n  連線中...")
client = make_client()
print("  連線成功\n")

# ── USDC 餘額 ─────────────────────────────────────────────────────────────────

try:
    usdc = get_usdc_balance(client)
    print(f"{'═'*65}")
    print(f"  USDC 餘額: {usdc:.2f} USDC")
    print(f"{'═'*65}\n")
except Exception as e:
    print(f"  （無法取得餘額: {e}）\n")

# ── 持有倉位 (Positions) ───────────────────────────────────────────────────────

print(f"{'═'*65}")
print("  持有倉位")
print(f"{'═'*65}\n")

positions = get_positions(size_threshold=0.01)

if not positions:
    print("  （目前無持倉）\n")
else:
    positions.sort(key=lambda x: float(x.get("currentValue", 0)), reverse=True)
    for p in positions:
        title      = p.get("title", p.get("question", ""))
        outcome    = p.get("outcome", "")
        size       = float(p.get("size", 0))
        avg_price  = float(p.get("avgPrice", 0))
        cur_price  = float(p.get("curPrice", p.get("currentPrice", 0)))
        cur_value  = float(p.get("currentValue", size * cur_price))
        init_value = float(p.get("initialValue", size * avg_price))
        pnl        = cur_value - init_value
        pnl_pct    = (pnl / init_value * 100) if init_value else 0

        pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        print(f"  [{outcome}]  size={size:.2f}  avg={avg_price:.4f}  cur={cur_price:.4f}")
        print(f"    價值: {cur_value:.2f} USDC  PnL: {pnl_str} USDC ({pnl_pct:+.1f}%)")
        print(f"    市場: {title[:65]}")
        print()

# ── 掛單 (Open Orders) ────────────────────────────────────────────────────────

print(f"{'═'*65}")
print("  未成交掛單")
print(f"{'═'*65}\n")

orders = get_open_orders(client)

if not orders:
    print("  （目前無掛單）\n")
else:
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    for o in orders:
        side        = o.get("side", "")
        price       = float(o.get("price", 0))
        orig_size   = float(o.get("original_size", o.get("size", 0)))
        remain_size = float(o.get("size_matched", 0))
        filled_size = orig_size - remain_size if remain_size else 0
        status      = o.get("status", "")
        order_type  = o.get("type", "")
        asset_id    = o.get("asset_id", "")
        created_raw = o.get("created_at", "")
        order_id    = o.get("id", "")[:12]

        try:
            ts = float(created_raw) if created_raw else 0
            dt = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, tz=timezone.utc)
            time_str = dt.astimezone(TZ_TAIPEI).strftime("%m/%d %H:%M:%S")
        except Exception:
            time_str = created_raw

        cost = round(price * orig_size, 4)
        print(f"  [{side.upper():4}] price={price:.4f}  size={orig_size:.2f}  cost≈{cost:.2f} USDC")
        print(f"    狀態: {status}  類型: {order_type}  成交: {filled_size:.2f}")
        print(f"    下單: {time_str}  ID: {order_id}...")
        print(f"    Token: {asset_id}")
        print()

print(f"{'═'*65}\n")
