"""
check_vpn.py
────────────
檢查目前的對外 IP 與國家，確認 VPN 是否生效
"""
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import requests

def check_vpn():
    try:
        r = requests.get("https://ipinfo.io/json", timeout=5)
        data = r.json()
        ip      = data.get("ip", "?")
        country = data.get("country", "?")
        city    = data.get("city", "?")
        org     = data.get("org", "?")
        print(f"IP      : {ip}")
        print(f"國家    : {country}")
        print(f"城市    : {city}")
        print(f"ISP/VPN : {org}")
        if country == "TW":
            print("\n⚠ 目前是台灣 IP，VPN 未生效！")
        else:
            print(f"\n✓ VPN 已生效（{country}）")
    except Exception as e:
        print(f"查詢失敗：{e}")

if __name__ == "__main__":
    check_vpn()