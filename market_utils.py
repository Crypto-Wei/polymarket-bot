"""
market_utils.py
───────────────
Polymarket 共用函式庫。
提供 API 連線、帳戶查詢、市場掃描、訂單簿查詢等功能。
所有需要 wallet 認證的操作皆透過 make_client() 回傳的 ClobClient 執行。
"""

import os
import sys
import json
import time

import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

# ── API 端點 ──────────────────────────────────────────────────────────────────

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"
DATA_API  = "https://data-api.polymarket.com"

# ── 環境變數 ──────────────────────────────────────────────────────────────────

_KEY    = os.getenv("key")
_CHAIN  = 137
_FUNDER = os.getenv("POLYMARKET_PROXY_ADDRESS")


# ════════════════════════════════════════════════════════════════════════════
# 連線 / 帳戶
# ════════════════════════════════════════════════════════════════════════════

def make_client() -> ClobClient:
    """建立並回傳已認證的 ClobClient。"""
    client = ClobClient(CLOB_API, key=_KEY, chain_id=_CHAIN,
                        signature_type=1, funder=_FUNDER)
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def get_usdc_balance(client: ClobClient) -> float:
    """回傳 USDC 餘額（單位：USDC）。"""
    bal = client.get_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    return float(bal.get("balance", 0)) / 1e6


def get_open_orders(client: ClobClient) -> list:
    """回傳所有未成交掛單（空串列表示無掛單或查詢失敗）。"""
    try:
        return client.get_orders() or []
    except Exception:
        return []


def get_positions(size_threshold: float = 0.0) -> list:
    """
    回傳持倉列表。
    size_threshold > 0 時透過 API 過濾，避免傳回零股 dust。
    """
    try:
        params: dict = {"user": _FUNDER}
        if size_threshold > 0:
            params["sizeThreshold"] = size_threshold
        resp = requests.get(f"{DATA_API}/positions", params=params, timeout=15)
        return resp.json() if resp.status_code == 200 else []
    except Exception:
        return []


# ════════════════════════════════════════════════════════════════════════════
# 市場掃描
# ════════════════════════════════════════════════════════════════════════════

def get_candidate_markets(price_prefilter: float = 0.08,
                          page_limit: int = 100) -> tuple:
    """
    分頁取得所有活躍市場，並以 outcomePrices 預篩：
    至少有一個 outcome 隱含價格 < price_prefilter 才保留。
    回傳 (candidates, total_seen)。
    """
    candidates: list = []
    offset     = 0
    total_seen = 0

    while True:
        resp = requests.get(f"{GAMMA_API}/markets", params={
            "active": "true",
            "closed": "false",
            "limit":  page_limit,
            "offset": offset,
        }, timeout=15)

        if resp.status_code != 200:
            print(f"  Gamma API 錯誤 {resp.status_code}，停止分頁")
            break

        batch = resp.json()
        if not batch:
            break

        for m in batch:
            total_seen += 1
            prices = m.get("outcomePrices", [])
            if isinstance(prices, str):
                try:    prices = json.loads(prices)
                except: prices = []
            if prices and any(float(p) < price_prefilter for p in prices):
                candidates.append(m)

        print(f"  掃描 {total_seen} 個市場，候選 {len(candidates)} 個...", end="\r")

        if len(batch) < page_limit:
            break
        offset += page_limit
        time.sleep(0.05)

    return candidates, total_seen


def build_token_meta(candidates: list, price_prefilter: float = 0.08) -> dict:
    """
    從候選市場列表建立 token_id → meta 索引。
    只保留隱含價格 < price_prefilter 的 token。
    meta 包含：question, outcome, slug, implied, end_date。
    """
    token_to_meta: dict = {}

    for m in candidates:
        token_ids = m.get("clobTokenIds", [])
        outcomes  = m.get("outcomes",     [])
        prices    = m.get("outcomePrices", [])
        question  = m.get("question", m.get("title", ""))
        slug      = m.get("slug", "")

        if isinstance(token_ids, str):
            try:    token_ids = json.loads(token_ids)
            except: continue
        if isinstance(outcomes, str):
            try:    outcomes = json.loads(outcomes)
            except: outcomes = []
        if isinstance(prices, str):
            try:    prices = json.loads(prices)
            except: prices = []

        if not m.get("enableOrderBook", True):
            continue

        for i, tid in enumerate(token_ids):
            implied = float(prices[i]) if i < len(prices) else None
            if implied is not None and implied >= price_prefilter:
                continue
            label = outcomes[i] if i < len(outcomes) else f"Outcome {i}"
            token_to_meta[tid] = {
                "question": question,
                "outcome":  label,
                "slug":     slug,
                "implied":  implied,
                "end_date": m.get("endDate") or m.get("gameStartTime"),
            }

    return token_to_meta


# ════════════════════════════════════════════════════════════════════════════
# 訂單簿
# ════════════════════════════════════════════════════════════════════════════

def batch_get_books(token_ids: list, batch_size: int = 50) -> dict:
    """
    批次查詢訂單簿（POST /books），自動分頁。
    回傳 {token_id: book} dict。
    """
    result: dict = {}

    for i in range(0, len(token_ids), batch_size):
        chunk   = token_ids[i : i + batch_size]
        payload = [{"token_id": tid} for tid in chunk]
        try:
            resp = requests.post(f"{CLOB_API}/books", json=payload, timeout=15)
            if resp.status_code == 200:
                for book in resp.json():
                    tid = (book.get("asset_id") or
                           book.get("token_id") or
                           book.get("tokenID"))
                    if tid:
                        result[tid] = book
        except Exception:
            pass

        if i + batch_size < len(token_ids):
            time.sleep(0.05)

    return result


def best_bid(book: dict):
    """回傳訂單簿的最高買價 (price, size)，無掛單時回傳 None。"""
    bids = book.get("bids", [])
    if not bids:
        return None
    top = max(bids, key=lambda x: float(x["price"]))
    return float(top["price"]), float(top["size"])


def best_ask(book: dict):
    """回傳訂單簿的最低賣價 (price, size)，無掛單時回傳 None。"""
    asks = book.get("asks", [])
    if not asks:
        return None
    top = min(asks, key=lambda x: float(x["price"]))
    return float(top["price"]), float(top["size"])
