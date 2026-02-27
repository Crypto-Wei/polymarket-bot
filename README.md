# polymarket-bot

Polymarket 自動交易機器人，掃描預測市場並自動管理買賣單。

## 功能

- **市場掃描**：透過 Gamma API 分頁掃描所有活躍市場，篩選低隱含機率的 token
- **自動買單**（Part A）：在符合條件的市場掛限價買單（GTD，24 小時有效）
- **自動賣單**（Part B）：持倉補掛賣單，並自動取消過期的高價賣單
- **帳戶查詢**：查看 USDC 餘額、持倉損益、未成交掛單

## 檔案說明

| 檔案 | 說明 |
|------|------|
| `auto_trade.py` | 主交易腳本，執行 Part A / Part B |
| `market_utils.py` | 共用工具函式（API 連線、訂單簿查詢、市場掃描） |
| `my_positions.py` | 查詢帳戶狀態（餘額、持倉、掛單） |
| `check_vpn.py` | 確認對外 IP 與 VPN 狀態 |

## 環境需求

```
python >= 3.10
py-clob-client
requests
python-dotenv
```

安裝依賴：

```bash
pip install py-clob-client requests python-dotenv
```

## 設定

複製 `.env.example` 為 `.env` 並填入私鑰：

```env
key=0x你的私鑰
POLYMARKET_PROXY_ADDRESS=0x你的代理錢包地址
```

> ⚠ `.env` 已加入 `.gitignore`，請勿將私鑰上傳至任何公開位置。

## 執行

```bash
# 查詢帳戶狀態
python my_positions.py

# 執行自動交易（買單掃描 + 賣單補掛）
python auto_trade.py

# 確認 VPN 狀態
python check_vpn.py
```

## 交易策略（auto_trade.py）

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `PRICE_PREFILTER` | 0.08 | Gamma outcomePrices 預篩門檻 |
| `BID_MIN` | 0.045 | 掛買下限 |
| `BID_THRESHOLD` | 0.050 | 掛買上限 |
| `MIN_SPREAD` | 0.01 | 隱含價與 best bid 最小價差 |
| `MIN_DAYS_LEFT` | 30 | 距到期最少天數 |
| `SPEND_PER_ORDER` | 3.0 | 每筆買單花費（USDC） |
| `MIN_SELL_SIZE` | 1.0 | 低於此 size 不掛賣單 |

## API 端點

- **Gamma API** `https://gamma-api.polymarket.com` — 市場資訊（免認證）
- **CLOB API** `https://clob.polymarket.com` — 訂單簿 / 下單（下單需 wallet 認證）
- **Data API** `https://data-api.polymarket.com` — 持倉 / 分析（免認證）
