"""
auto_trade.py
─────────────
啟動時：顯示帳戶狀態（USDC 餘額、持倉、掛單）

Part A：掃描市場 → 掛買單（bid_price，每筆 SPEND_PER_ORDER USDC）
         · 已有掛買單 or 已有倉位的 token 跳過

Part B：檢查持倉 → 補掛賣單（best ask）
         · 已有掛賣單的 token 跳過
"""

import sys
import time
import logging
from datetime import datetime, timezone, timedelta

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from market_utils import (
    make_client, get_usdc_balance, get_open_orders, get_positions,
    get_candidate_markets, build_token_meta, batch_get_books,
    best_bid, best_ask,
)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

TZ_TAIPEI = timezone(timedelta(hours=8))

# ── 設定 ──────────────────────────────────────────────────────────────────────

PRICE_PREFILTER = 0.08    # Gamma outcomePrices 預篩
BID_MIN         = 0.045   # 掛買下限
BID_THRESHOLD   = 0.050   # 掛買上限
MIN_SPREAD      = 0.01    # implied 與 best bid 最小價差（1¢）
MIN_DAYS_LEFT   = 30      # 距到期最少天數

SPEND_PER_ORDER = 3.0     # 每筆買單花費（USDC）
MIN_SELL_SIZE   = 1.0     # 低於此 size 不掛賣單（dust）

LOG_FILE        = "auto_trade.log"

# ── 日誌設定 ──────────────────────────────────────────────────────────────────

_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger = logging.getLogger("auto_trade")
logger.setLevel(logging.INFO)
logger.addHandler(_fh)
log = logger.info


# ════════════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════════════

def main():
    now_str = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'═'*65}")
    print(f"  auto_trade  {now_str}")
    print(f"{'═'*65}\n")
    log(f"── RUN START  {now_str} ──")

    # ── 連線 ──────────────────────────────────────────────────────────────────
    client = make_client()

    # ── USDC 餘額 ──────────────────────────────────────────────────────────────
    try:
        usdc = get_usdc_balance(client)
        log(f"USDC 餘額: {usdc:.2f}")
    except Exception as e:
        usdc = 0.0
        log(f"USDC 餘額: 取得失敗 {e}")

    # ── 持倉 ──────────────────────────────────────────────────────────────────
    positions_raw = get_positions()
    for p in sorted(positions_raw, key=lambda x: float(x.get("currentValue", 0)), reverse=True):
        title      = p.get("title", p.get("question", ""))
        outcome    = p.get("outcome", "")
        size       = float(p.get("size", 0))
        avg_price  = float(p.get("avgPrice", 0))
        cur_price  = float(p.get("curPrice", p.get("currentPrice", 0)))
        cur_value  = float(p.get("currentValue", size * cur_price))
        init_value = float(p.get("initialValue", size * avg_price))
        pnl        = cur_value - init_value
        pnl_pct    = (pnl / init_value * 100) if init_value else 0
        log(f"持倉  [{outcome}]  size={size:.2f}  avg={avg_price:.4f}  cur={cur_price:.4f}  "
            f"PnL={pnl:+.2f} ({pnl_pct:+.1f}%)  {title[:60]}")

    # ── 掛單 ──────────────────────────────────────────────────────────────────
    open_orders = get_open_orders(client)
    buy_tokens  = {o["asset_id"] for o in open_orders
                   if o.get("side", "").upper() == "BUY" and o.get("status") == "LIVE"}
    sell_size_map:   dict[str, float]      = {}
    sell_orders_map: dict[str, list[dict]] = {}
    for o in open_orders:
        if o.get("side", "").upper() == "SELL" and o.get("status") == "LIVE":
            tid  = o["asset_id"]
            orig = float(o.get("original_size", o.get("size", 0)))
            sell_size_map[tid] = sell_size_map.get(tid, 0.0) + orig
            sell_orders_map.setdefault(tid, []).append(o)
    for o in open_orders:
        side      = o.get("side", "").upper()
        price     = float(o.get("price", 0))
        orig_size = float(o.get("original_size", o.get("size", 0)))
        log(f"掛單  [{side}]  price={price:.4f}  size={orig_size:.2f}  "
            f"status={o.get('status','')}  token={o.get('asset_id','')[:16]}")

    print(f"  USDC: {usdc:.2f}  ·  持倉 {len(positions_raw)} 筆  ·  掛買 {len(buy_tokens)} 筆  ·  掛賣 {len(sell_size_map)} token\n")

    # 持倉 map（供 Part A/B 過濾用）
    position_map    = {p["asset"]: p for p in positions_raw
                       if float(p.get("size", 0)) >= MIN_SELL_SIZE}
    position_tokens = set(position_map.keys())

    # ════════════════════════════════════════════════════════════════════════
    # Part A：掃描市場 → 掛買單
    # ════════════════════════════════════════════════════════════════════════
    print(f"── Part A {'─'*55}")

    candidates, total_seen = get_candidate_markets(PRICE_PREFILTER)
    token_to_meta = build_token_meta(candidates, PRICE_PREFILTER)
    scan_tokens   = [tid for tid in token_to_meta
                     if tid not in buy_tokens and tid not in position_tokens]
    books = batch_get_books(scan_tokens)

    buy_candidates = []
    for tid, book in books.items():
        bid = best_bid(book)
        if bid is None:
            continue
        bid_price, bid_size = bid
        if not (BID_MIN < bid_price < BID_THRESHOLD):
            continue

        meta    = token_to_meta.get(tid, {})
        implied = meta.get("implied")
        if implied is None or (implied - bid_price) < MIN_SPREAD:
            continue

        end_date_raw = meta.get("end_date")
        if end_date_raw:
            try:
                raw = end_date_raw.replace(" ", "T").rstrip("Z")
                if "+" in raw:
                    raw = raw[:raw.index("+")]
                dt_end = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
                if (dt_end - datetime.now(timezone.utc)).days <= MIN_DAYS_LEFT:
                    continue
            except Exception:
                pass

        buy_candidates.append({
            "token_id":  tid,
            "bid_price": bid_price,
            "bid_size":  bid_size,
            "outcome":   meta.get("outcome", ""),
            "question":  meta.get("question", ""),
            "slug":      meta.get("slug", ""),
            "implied":   implied,
            "end_date":  end_date_raw,
        })

    print(f"  掃描 {total_seen} → 候選 {len(candidates)} → 查 {len(scan_tokens)} tokens → 符合 {len(buy_candidates)} 個")
    log(f"Part A  total={total_seen}  candidates={len(candidates)}  scan={len(scan_tokens)}  books={len(books)}  hits={len(buy_candidates)}")

    ok_b = err_b = 0
    if buy_candidates:
        buy_candidates.sort(key=lambda x: x["bid_price"])
        for r in buy_candidates:
            size = round(SPEND_PER_ORDER / r["bid_price"], 2)
            try:
                buy_expiry = int(time.time()) + 86400
                signed = client.create_order(
                    OrderArgs(price=r["bid_price"], size=size,
                              side=BUY, token_id=r["token_id"],
                              expiration=buy_expiry)
                )
                resp   = client.post_order(signed, OrderType.GTD)
                status = resp.get("status", resp) if isinstance(resp, dict) else resp
                print(f"  [BUY]  @{r['bid_price']:.4f} x{size}  {r['question'][:48]}  ✓")
                log(f"BUY  token={r['token_id'][:16]}  @{r['bid_price']}  x{size}  [{status}]  {r['question'][:60]}")
                ok_b += 1
                buy_tokens.add(r["token_id"])
            except Exception as e:
                print(f"  [BUY]  @{r['bid_price']:.4f} x{size}  {r['question'][:48]}  ✗ {e}")
                log(f"BUY FAIL  token={r['token_id'][:16]}  @{r['bid_price']}  x{size}  {e}")
                err_b += 1
        print(f"  買單：成功 {ok_b}，失敗 {err_b}")
        log(f"Part A 完成  buy_ok={ok_b}  buy_err={err_b}")
    print()

    # ════════════════════════════════════════════════════════════════════════
    # Part B：持倉補掛賣單
    # ════════════════════════════════════════════════════════════════════════
    print(f"── Part B {'─'*55}")

    if not position_map:
        print("  （無持倉）\n")
    else:
        books_sell = batch_get_books(list(position_map.keys()))

        to_cancel       = []
        sell_candidates = []

        for token, pos in position_map.items():
            pos_size        = float(pos.get("size", 0))
            existing_orders = sell_orders_map.get(token, [])
            ask             = best_ask(books_sell.get(token, {}))

            if ask is None:
                log(f"⚠ 無 ask  token={token[:16]}  {pos.get('title','')[:50]}")
                continue
            ask_price, _ = ask

            cancel_size = 0.0
            for o in existing_orders:
                o_price = float(o.get("price", 0))
                o_size  = float(o.get("original_size", o.get("size", 0)))
                if o_price <= ask_price:
                    continue
                to_cancel.append({
                    "order_id":  o.get("id"),
                    "token_id":  token,
                    "size":      o_size,
                    "old_price": o_price,
                    "new_price": ask_price,
                    "title":     pos.get("title", ""),
                })
                cancel_size += o_size

            valid_sell_size = sell_size_map.get(token, 0.0) - cancel_size
            shortfall       = round(pos_size - valid_sell_size, 4)

            if shortfall >= MIN_SELL_SIZE:
                sell_candidates.append({
                    "token_id":   token,
                    "ask_price":  ask_price,
                    "size":       shortfall,
                    "valid_sell": valid_sell_size,
                    "outcome":    pos.get("outcome", ""),
                    "title":      pos.get("title", ""),
                })

        # 取消低價賣單
        ok_c = err_c = 0
        for c in to_cancel:
            try:
                client.cancel(c["order_id"])
                print(f"  [CANCEL]  @{c['old_price']:.4f}→{c['new_price']:.4f}  x{c['size']:.2f}  ✓")
                log(f"CANCEL  token={c['token_id'][:16]}  @{c['old_price']}→{c['new_price']}  x{c['size']:.2f}  ✓  {c['title'][:50]}")
                ok_c += 1
            except Exception as e:
                print(f"  [CANCEL]  @{c['old_price']:.4f}  x{c['size']:.2f}  ✗ {e}")
                log(f"CANCEL FAIL  token={c['token_id'][:16]}  {e}")
                err_c += 1
        if to_cancel:
            print(f"  取消：成功 {ok_c}，失敗 {err_c}")

        # 補掛賣單
        ok_s = err_s = 0
        for r in sell_candidates:
            try:
                signed = client.create_order(
                    OrderArgs(price=r["ask_price"], size=r["size"],
                              side=SELL, token_id=r["token_id"])
                )
                resp   = client.post_order(signed, OrderType.GTC)
                status = resp.get("status", resp) if isinstance(resp, dict) else resp
                print(f"  [SELL]  @{r['ask_price']:.4f} x{r['size']:.2f}  {r['title'][:48]}  ✓")
                log(f"SELL  token={r['token_id'][:16]}  @{r['ask_price']}  x{r['size']:.2f}  [{status}]  {r['title'][:60]}")
                ok_s += 1
            except Exception as e:
                print(f"  [SELL]  @{r['ask_price']:.4f} x{r['size']:.2f}  {r['title'][:48]}  ✗ {e}")
                log(f"SELL FAIL  token={r['token_id'][:16]}  @{r['ask_price']}  x{r['size']:.2f}  {e}")
                err_s += 1
        if sell_candidates:
            print(f"  賣單：成功 {ok_s}，失敗 {err_s}")

        if not to_cancel and not sell_candidates:
            print("  （無需操作）")
        print()
        log(f"Part B 完成  cancel_ok={ok_c}  cancel_err={err_c}  sell_ok={ok_s}  sell_err={err_s}")

    log("── RUN END ──")
    print(f"{'═'*65}\n")


if __name__ == "__main__":
    main()