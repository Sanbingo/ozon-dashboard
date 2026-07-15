#!/usr/bin/env python3
"""
店铺6商品出单明细（按出单降序）：出单数、销售金额、推广费、推广费占比
- 总件数/金额用 Ozon Analytics（全部物流方式，排除取消）
- 商品明细用 FBO/FBS 订单数据
- 广告数据用 Performance API
"""
import json, subprocess, sys, os, csv, io
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
# from lib.feishu import get_tenant_token, send_text  # 飞书通知已关闭
import store6_db

LOG_FILE = f"{config.LOG_DIR}/ozon-store6-report.log"

PERF_CLIENT_ID = "95246837-1780157150806@advertising.performance.ozon.ru"
PERF_CLIENT_SECRET = "-Cia2L0YzzwzPbgxKeDJAOpTBKPRIpls6Un6kqq45Zh7UfMpFYg86AV8SyLEPi7lZFOlewXuNOnxe4tUHQ"
PERF_BASE = "https://api-performance.ozon.ru"
SELLER_CLIENT_ID = str(config.OZON_STORE_KEYS['store6']['client_id'])
SELLER_API_KEY = config.OZON_STORE_KEYS['store6']['api_key']
SELLER_BASE = "https://api-seller.ozon.ru"

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f: f.write(f'[{ts}] {msg}\n')
    print(f'[{ts}] {msg}', flush=True)

def curl(method, url, headers=None, data=None, timeout=30):
    cmd = ['curl', '-s', '-X', method, url, '--connect-timeout', '10', '--max-time', str(timeout)]
    if headers:
        for k,v in headers.items(): cmd += ['-H', f'{k}: {v}']
    if data: cmd += ['-d', data]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout+5)
    try: return json.loads(r.stdout)
    except: return {"_raw": r.stdout[:500], "_error": r.stderr[:200]}

def curl_text(method, url, headers=None, data=None, timeout=30):
    cmd = ['curl', '-s', '-X', method, url, '--connect-timeout', '10', '--max-time', str(timeout)]
    if headers:
        for k,v in headers.items(): cmd += ['-H', f'{k}: {v}']
    if data: cmd += ['-d', data]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout+5)
    return r.stdout

def get_perf_token():
    for attempt in range(3):
        r = curl("POST", f"{PERF_BASE}/api/client/token",
                 {"Content-Type": "application/json"},
                 json.dumps({"client_id": PERF_CLIENT_ID, "client_secret": PERF_CLIENT_SECRET, "grant_type": "client_credentials"}))
        token = r.get('access_token', '')
        if token: return token
        log(f"Performance ⚠️ 第{attempt+1}次失败: {r.get('error',str(r)[:100])}")
        import time; time.sleep(3)
    return None

def get_perf_daily_stats(token, date_from, date_to):
    h = {"Authorization": f"Bearer {token}"}
    text = curl_text("GET", f"{PERF_BASE}/api/client/statistics/daily?date_from={date_from}&date_to={date_to}", h)
    if not text or text.startswith('{'): return []
    reader = csv.DictReader(io.StringIO(text), delimiter=';')
    rows = []
    for row in reader:
        rows.append({
            'id': row.get('ID',''), 'name': row.get('Название',''),
            'cost': float(row.get('Расход, ₽','0').replace(',','.')),
            'orders': int(row.get('Заказы, шт.','0')),
            'revenue': float(row.get('Заказы, ₽','0').replace(',','.')),
        })
    return rows

def get_perf_sku_stats(token, date, campaign_ids):
    """获取SKU级的推广费数据（新接口）"""
    if not campaign_ids:
        return {}
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps({"date_from": date, "date_to": date, "campaignIds": campaign_ids})
    resp = curl("POST", f"{PERF_BASE}/api/client/statistics/products/sku", h, data, timeout=30)
    rows = resp.get('rows', []) if isinstance(resp, dict) else []
    if rows:
        log(f"SKU级推广费 ✅ {len(rows)}条")
    else:
        log(f"SKU级推广费 ⚠️ 无数据: {str(resp)[:100]}")
    return {r.get('sku',''): float(r.get('expense',0) or 0) for r in rows}


def get_campaign_skus(token):
    h = {"Authorization": f"Bearer {token}"}
    text = curl_text("GET", f"{PERF_BASE}/api/client/campaign?adv_page_type=", h)
    try: camps = json.loads(text).get('list',[])
    except: return {}, {}
    campaign_skus, campaign_names = {}, {}
    for camp in camps:
        cid, cname, cstate = camp.get('id',''), camp.get('title',''), camp.get('state','')
        campaign_names[cid] = cname
        if cstate != 'CAMPAIGN_STATE_ARCHIVED':
            prod_text = curl_text("GET", f"{PERF_BASE}/api/client/campaign/{cid}/v2/products?offset=0&limit=100", h)
            try: prods = json.loads(prod_text).get('products',[])
            except: prods = []
            for p in prods:
                campaign_skus[str(p.get('sku',''))] = cid
    return campaign_skus, campaign_names

def get_analytics(date_str):
    headers = {"Client-Id": SELLER_CLIENT_ID, "Api-Key": SELLER_API_KEY, "Content-Type": "application/json"}
    payload = json.dumps({"date_from": date_str, "date_to": date_str,
                          "metrics": ["ordered_units", "revenue"], "dimension": ["day"],
                          "limit": 100, "offset": 0})
    r = curl("POST", f"{SELLER_BASE}/v1/analytics/data", headers, payload, timeout=30)
    data = r.get('result', {}).get('data', [])
    if data:
        m = data[0].get('metrics', [])
        if len(m) >= 2: return int(m[0]), float(m[1])
    return None, None

def get_fbo_orders(date_str):
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    since = (dt - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'
    to = (dt + timedelta(days=1) - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'
    h = {"Client-Id": SELLER_CLIENT_ID, "Api-Key": SELLER_API_KEY, "Content-Type": "application/json"}

    all_posts = []
    for endpoint in ['v2/posting/fbo/list', 'v3/posting/fbs/list']:
        offset = 0
        while True:
            payload = json.dumps({"dir":"desc","filter":{"since":since,"to":to,"status":""},"limit":1000,"offset":offset})
            r = curl("POST", f"{SELLER_BASE}/{endpoint}", h, payload, timeout=60)
            if not isinstance(r, dict): break
            result = r.get('result', [])
            if not isinstance(result, list) or not result: break
            all_posts.extend(result)
            if len(result) < 1000: break
            offset += 1000

    active = [p for p in all_posts if isinstance(p, dict) and p.get('status') != 'cancelled']
    sku_data = {}
    for p in active:
        for prod in p.get('products',[]):
            sku = str(prod.get('sku','0'))
            name = prod.get('name','?')
            price = float(prod.get('price',0) or 0)
            qty = int(prod.get('quantity',1) or 1)
            if sku not in sku_data:
                sku_data[sku] = {'name':name, 'orders':0, 'units':0, 'revenue':0.0}
            sku_data[sku]['orders'] += 1
            sku_data[sku]['units'] += qty
            sku_data[sku]['revenue'] += price * qty
    return sku_data, len(active)

def main():
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)
    yesterday = (msk_now - timedelta(days=1)).strftime('%Y-%m-%d')

    log(f"=== 店铺6 商品明细（{yesterday}）===")

    # 1. Ozon Analytics（权威总件数/金额）
    log("📡 获取Analytics数据...")
    analytics_units, analytics_revenue = get_analytics(yesterday)
    if analytics_units is None:
        log("⚠️ Analytics返回空，重试一次...")
        import time; time.sleep(3)
        analytics_units, analytics_revenue = get_analytics(yesterday)
    if analytics_units is not None:
        log(f"Analytics: {analytics_units}件, {analytics_revenue:,.0f}₽")
    else:
        log("⚠️ Analytics多次失败，降级使用FBO/FBS汇总")

    # 2. FBO/FBS（商品明细）
    log("📡 获取FBO/FBS订单...")
    sku_data, fbo_orders = get_fbo_orders(yesterday)
    log(f"FBO/FBS: {fbo_orders}单, {len(sku_data)}个SKU")

    # 3. Performance API（广告数据）
    log("📡 获取广告数据...")
    perf_token = get_perf_token()
    ad_stats, campaign_skus, campaign_names = [], {}, {}
    if perf_token:
        ad_stats = get_perf_daily_stats(perf_token, yesterday, yesterday)
        campaign_skus, campaign_names = get_campaign_skus(perf_token)
        log(f"广告: {len(ad_stats)}个活动, {len(campaign_skus)}个推广SKU")
    else:
        log("⚠️ Performance API不可用，跳过广告数据")

    # 4. 按出单数降序排列
    sorted_skus = sorted(sku_data.items(), key=lambda x: x[1]['orders'], reverse=True)

    # 5. 汇总
    ad_total_cost = sum(s['cost'] for s in ad_stats)
    camp_sku_count = {}
    for sku, cid in campaign_skus.items():
        camp_sku_count[cid] = camp_sku_count.get(cid, 0) + 1
    ad_by_campaign = {s['id']: s for s in ad_stats}

    # 5b. 获取 SKU 级推广费（新接口，优先使用）
    sku_ad_expenses = {}
    if perf_token and ad_stats:
        running_cids = [s['id'] for s in ad_stats]
        sku_ad_expenses = get_perf_sku_stats(perf_token, yesterday, running_cids)

    # 6. 保存到数据库
    try:
        store6_db.init_db("store6")
        store6_db.save_summary("store6", yesterday, analytics_units, analytics_revenue,
                               fbo_orders, sum(d['units'] for _, d in sorted_skus),
                               sum(d['revenue'] for _, d in sorted_skus), len(sorted_skus),
                               ad_total_cost, sum(s['orders'] for s in ad_stats),
                               sum(s['revenue'] for s in ad_stats), sum(1 for s in sku_data if s in campaign_skus))
        store6_db.save_sku_list("store6", yesterday, sorted_skus, campaign_skus, ad_by_campaign, camp_sku_count, sku_ad_expenses)
        store6_db.save_campaigns("store6", yesterday, ad_stats, campaign_names, camp_sku_count)
        log("✅ 数据已存入数据库")
    except Exception as e:
        log(f"⚠️ 数据库写入失败: {e}")

    # 7. 构建输出
    lines = [f"📊 店铺6 | {yesterday} 商品出单明细"]
    lines.append("")

    # 汇总行
    if analytics_units is not None:
        lines.append(f"📦 总订单金额：{analytics_revenue:,.0f}₽ | 总件数：{analytics_units}件（Analytics，含RFBS）")
    fbo_units = sum(d['units'] for _, d in sorted_skus)
    fbo_rev = sum(d['revenue'] for _, d in sorted_skus)
    lines.append(f"   FBO/FBS：{fbo_orders}单, {fbo_units}件, {fbo_rev:,.0f}₽（{len(sku_data)}个SKU，不含取消）")
    if ad_stats:
        lines.append(f"📢 总推广费：{ad_total_cost:,.0f}₽")
    lines.append("")

    # 表头
    lines.append(f"{'商品名':<34} | {'单数':>4} | {'件数':>4} | {'销售金额':>10} | {'推广费':>8} | {'占比':>5}")
    lines.append("─" * 78)

    ad_sku_orders = ad_sku_revenue = ad_sku_count = 0
    for sku, d in sorted_skus:
        name = d['name'][:32]
        cid = campaign_skus.get(sku)
        if cid and cid in ad_by_campaign:
            if sku_ad_expenses and sku in sku_ad_expenses:
                ac = sku_ad_expenses[sku]
            else:
                n = camp_sku_count.get(cid, 1)
                ac = ad_by_campaign[cid]['cost'] / n
            pct = ac / d['revenue'] * 100 if d['revenue'] > 0 else 0
            lines.append(f"{name:<34} | {d['orders']:>4} | {d['units']:>4} | {d['revenue']:>9,.0f}₽ | {ac:>7,.0f}₽ | {pct:>4.1f}%")
            ad_sku_orders += d['orders']; ad_sku_revenue += d['revenue']; ad_sku_count += 1
        else:
            lines.append(f"{name:<34} | {d['orders']:>4} | {d['units']:>4} | {d['revenue']:>9,.0f}₽ | {'—':>7} | {'—':>4}")

    lines.append("─" * 78)
    lines.append(f"{'合计（FBO/FBS）':<34} | {fbo_orders:>4} | {fbo_units:>4} | {fbo_rev:>9,.0f}₽ | {ad_total_cost:>7,.0f}₽ | {ad_total_cost/fbo_rev*100:>4.1f}%")

    if ad_stats:
        lines.append("")
        lines.append(f"📢 推广活动详情：")
        for s in ad_stats:
            cname = campaign_names.get(s['id'], s['name'])
            n = camp_sku_count.get(s['id'], 0)
            roas = f"ROAS {s['revenue']/s['cost']:.2f}" if s['cost'] > 0 else "无花费"
            lines.append(f"  • {cname}：花费{s['cost']:,.0f}₽ | {n}个SKU | {s['orders']}单 | {s['revenue']:,.0f}₽ | {roas}")

        lines.append(f"")
        lines.append(f"📊 推广SKU {ad_sku_count}个 → {ad_sku_orders}单, {ad_sku_revenue:,.0f}₽（{ad_sku_revenue/fbo_rev*100:.1f}%销售额）")
        lines.append(f"   非推广 {len(sorted_skus)-ad_sku_count}个 → {fbo_orders-ad_sku_orders}单, {fbo_rev-ad_sku_revenue:,.0f}₽")
        lines.append(f"   推广费占总销售额：{ad_total_cost/fbo_rev*100:.2f}%")
        lines.append(f"")
        if sku_ad_expenses:
            lines.append(f"✅ 推广费来自Performance API SKU级接口（精确）")
        else:
            lines.append(f"⚠️ 推广费按活动SKU数量均摊（API不提供SKU级明细）")
        if analytics_units is not None:
            lines.append(f"   总件数以Ozon Analytics为准（含RFBS），商品明细仅含FBO/FBS")

    report = "\n".join(lines)
    log(f"\n{report}")

    # 7. 飞书通知已关闭（2026-07-14）

if __name__ == '__main__':
    main()
