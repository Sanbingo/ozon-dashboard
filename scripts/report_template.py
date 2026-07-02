#!/usr/bin/env python3
"""
__STORE_NAME__ 每日报告：自动生成
店铺: __STORE_ID__ | 用户: __USERNAME__
"""
import json, subprocess, sys, os, csv, io
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from lib.feishu import get_tenant_token, send_text, send_text_to_user

LOG_FILE = "__LOG_FILE__"

PERF_CLIENT_ID = "__PERF_CID__"
PERF_CLIENT_SECRET = "__PERF_SECRET__"
PERF_BASE = "https://api-performance.ozon.ru"
SELLER_CLIENT_ID = "__CLIENT_ID__"
SELLER_API_KEY = "__API_KEY__"
SELLER_BASE = "https://api-seller.ozon.ru"
OZON_GROUP_ID = "oc_4d130dc369f8ea8ef3e5aaf88ba70f16"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}", flush=True)


def curl(method, url, headers=None, data=None, timeout=20):
    cmd = ["curl", "-s", "-X", method, url, "--connect-timeout", "10", "--max-time", str(timeout)]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    if data:
        cmd += ["-d", data]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout+5)
    try:
        return json.loads(r.stdout)
    except:
        return {}


def get_perf_token():
    for attempt in range(1, 4):
        r = curl("POST", f"{PERF_BASE}/api/client/token",
                 {"Content-Type": "application/json"},
                 json.dumps({"client_id": PERF_CLIENT_ID,
                           "client_secret": PERF_CLIENT_SECRET,
                           "grant_type": "client_credentials"}))
        if r.get("access_token"):
            log(f"Performance API ✅ 第{attempt}次")
            return r["access_token"]
        log(f"Performance API ⚠️ 第{attempt}次失败")
        if attempt < 3:
            import time; time.sleep(3)
    raise Exception("Performance token获取失败")


def get_analytics(date_str, max_retries=3, retry_delay=60):
    headers = {"Client-Id": SELLER_CLIENT_ID, "Api-Key": SELLER_API_KEY, "Content-Type": "application/json"}
    payload = json.dumps({
        "date_from": date_str, "date_to": date_str,
        "metrics": ["ordered_units", "revenue"],
        "dimension": ["day"], "limit": 100, "offset": 0
    })
    for attempt in range(1, max_retries + 1):
        r = curl("POST", f"{SELLER_BASE}/v1/analytics/data", headers, payload, timeout=30)
        data = r.get("result", {}).get("data", [])
        if data:
            metrics = data[0].get("metrics", [])
            if len(metrics) >= 2:
                log(f"Analytics ✅ {metrics[0]}件, {metrics[1]:,.0f}₽ 第{attempt}次")
                return metrics[0], metrics[1]
        if attempt < max_retries:
            log(f"Analytics ⚠️ 第{attempt}次无数据，{retry_delay}秒后重试...")
            import time; time.sleep(retry_delay)
    log("Analytics ❌ 重试失败")
    return None, None


def get_fbo_orders(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    since = (dt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"
    to = (dt + timedelta(days=1) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"
    headers = {"Client-Id": SELLER_CLIENT_ID, "Api-Key": SELLER_API_KEY, "Content-Type": "application/json"}
    payload = json.dumps({
        "dir": "desc",
        "filter": {"since": since, "to": to, "status": ""},
        "limit": 1000, "offset": 0
    })
    r = curl("POST", f"{SELLER_BASE}/v2/posting/fbo/list", headers, payload, timeout=60)
    posts = r.get("result", [])
    active = [p for p in posts if p.get("status") != "cancelled"]
    sku_data = {}
    for p in active:
        for prod in p.get("products", []):
            sku = str(prod.get("sku", "0"))
            price = float(prod.get("price", 0) or 0)
            qty = int(prod.get("quantity", 1) or 1)
            if sku not in sku_data:
                sku_data[sku] = {"name": prod.get("name", "?"), "qty": 0, "revenue": 0, "orders": 0}
            sku_data[sku]["qty"] += qty
            sku_data[sku]["revenue"] += price * qty
            sku_data[sku]["orders"] += 1
    log(f"FBO ✅ {len(active)}活跃单(取消{len(posts)-len(active)}单), {len(sku_data)}SKU")
    return len(active), sku_data


def main():
    log("=== __STORE_NAME__ 每日报告开始 ===")
    import store6_db
    msk_today = datetime.now(timezone.utc) + timedelta(hours=3)
    yesterday = (msk_today - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        analytics_units, analytics_money = get_analytics(yesterday)
        orders, sku_orders = get_fbo_orders(yesterday)
        total_rev = sum(d["revenue"] for d in sku_orders.values())
        store6_db.save_summary("__STORE_ID__", yesterday,
            analytics_units, analytics_money,
            orders, orders if orders else 0,
            total_rev, len(sku_orders),
            0, 0, 0, 0)
        log(f"✅ 已保存 {yesterday} 数据")
        try:
            tk = get_tenant_token()
            send_text(tk, OZON_GROUP_ID, f"📊 __STORE_NAME__ {yesterday} 数据已更新", "chat_id")
        except Exception as e:
            log(f"飞书发送失败: {e}")
    except Exception as e:
        log(f"❌ 失败: {e}")
        import traceback; log(traceback.format_exc())


if __name__ == "__main__":
    main()
