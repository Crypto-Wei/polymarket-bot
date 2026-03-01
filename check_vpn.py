"""
check_vpn.py
────────────
檢查目前的對外 IP 與國家，確認 VPN 是否生效
"""
import sys
if sys.platform == "win32" and sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

import requests

def check_vpn(silent: bool = False) -> bool:
    """回傳 True 代表 VPN 已生效（非台灣 IP）；False 代表未生效或查詢失敗。"""
    try:
        r = requests.get("https://ipinfo.io/json", timeout=5)
        data = r.json()
        ip      = data.get("ip", "?")
        country = data.get("country", "?")
        city    = data.get("city", "?")
        org     = data.get("org", "?")
        if not silent:
            print(f"IP      : {ip}")
            print(f"國家    : {country}")
            print(f"城市    : {city}")
            print(f"ISP/VPN : {org}")
        if country == "TW":
            if not silent:
                print("\n⚠ 目前是台灣 IP，VPN 未生效！")
            return False
        else:
            if not silent:
                print(f"\n✓ VPN 已生效（{country}）")
            return True
    except Exception as e:
        if not silent:
            print(f"查詢失敗：{e}")
        return False

if __name__ == "__main__":
    check_vpn()