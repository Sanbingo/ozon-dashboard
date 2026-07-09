#!/usr/bin/env python3
"""
企业店-1 每日订单报告
逻辑同 store6-report-format.py，但面向 store7
"""
import json, subprocess, sys, os, csv, io
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import store6_db

STORE_ID = 'store7'
LOG_FILE = f'{config.LOG_DIR}/ozon-store7-report.log'
SELLER_CLIENT_ID = str(config.OZON_STORE_KEYS[STORE_ID]['client_id'])
SELLER_API_KEY = config.OZON_STORE_KEYS[STORE_ID]['api_key']
PERF_CLIENT_ID = config.OZON_STORE_KEYS[STORE_ID]['perf_client_id']
PERF_CLIENT_SECRET = config.OZON_STORE_KEYS[STORE_ID]['perf_client_secret']
PERF_BASE = 'https://api-performance.ozon.ru'
SELLER_BASE = 'https://api-seller.ozon.ru'

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
    except: return {'_raw': r.stdout[:500], '_error': r.stderr[:200]}

def curl_text(method, url, headers=None, data=None, timeout=30):
    cmd = ['curl', '-s', '-X', method, url, '--connect-timeout', '10', '--max-time', str(timeout)]
    if headers:
        for k,v in headers.items(): cmd += ['-H', f'{k}: {v}']
    if data: cmd += ['-d', data]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout+5)
    return r.stdout

def get_perf_token():
    for attempt in range(3):
        r = curl('POST', f'{PERF_BASE}/api/client/token',
                 {'Content-Type': 'application/json'},
                 json.dumps({'client_id': PERF_CLIENT_ID, 'client_secret': PERF_CLIENT_SECRET, 'grant_type': 'client_credentials'}))
        token = r.get('access_token', '')
        if token: return token
        log(f'Performance ⚠️ 第{attempt+1}次失败')
        import time; time.sleep(3)
    return None

def get_perf_daily_stats(token, date_from, date_to):
    h = {'Authorization': f'Bearer {token}'}
    text = curl_text('GET', f'{PERF_BASE}/api/client/statistics/daily?date_from={date_from}&date_to={date_to}', h)
    if not text or text.startswith('{'): return []
    reader = csv.DictReader(io.StringIO(text), delimiter=';')
    rows = []
    for row in reader:
        rows.append({'id': row.get('ID',''), 'name': row.get('ID',''),
            'cost': float(row.get('Расход, ₽','0').replace(',','.')),
            'orders': int(row.get('Заказы, шт.','0')),
            'revenue': float(row.get('Заказы, ₽','0').replace(',','.'))})
    return rows


def get_perf_sku_stats(token, date, campaign_ids):
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
    h = {'Authorization': f'Bearer {token}'}
    text = curl_text('GET', f'{PERF_BASE}/api/client/campaign?adv_page_type=', h)
    try: camps = json.loads(text).get('list',[])
    except: return {}, {}
    campaign_skus, campaign_names = {}, {}
    for camp in camps:
        cid, cname, cstate = camp.get('id',''), camp.get('title',''), camp.get('state','')
        campaign_names[cid] = cname
        if cstate != 'CAMPAIGN_STATE_ARCHIVED':
            prod_text = curl_text('GET', f'{PERF_BASE}/api/client/campaign/{cid}/v2/products?offset=0&limit=100', h)
            try: prods = json.loads(prod_text).get('products',[])
            except: prods = []
            for p in prods: campaign_skus[str(p.get('sku',''))] = cid
    return campaign_skus, campaign_names

def get_analytics(date_str):
    headers = {'Client-Id': SELLER_CLIENT_ID, 'Api-Key': SELLER_API_KEY, 'Content-Type': 'application/json'}
    payload = json.dumps({'date_from': date_str, 'date_to': date_str,
        'metrics': ['ordered_units', 'revenue'], 'dimension': ['day'], 'limit': 100, 'offset': 0})
    r = curl('POST', f'{SELLER_BASE}/v1/analytics/data', headers, payload, timeout=30)
    data = r.get('result',{}).get('data',[])
    if data:
        m = data[0].get('metrics',[])
        if len(m) >= 2: return int(m[0]), float(m[1])
    return None, None

def get_fbo_orders(date_str):
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    since = (dt - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'
    to = (dt + timedelta(days=1) - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'
    h = {'Client-Id': SELLER_CLIENT_ID, 'Api-Key': SELLER_API_KEY, 'Content-Type': 'application/json'}
    all_posts = []
    for endpoint in ['v2/posting/fbo/list', 'v3/posting/fbs/list']:
        offset = 0
        while True:
            payload = json.dumps({'dir':'desc','filter':{'since':since,'to':to,'status':''},'limit':1000,'offset':offset})
            r = curl('POST', f'{SELLER_BASE}/{endpoint}', h, payload, timeout=60)
            if not isinstance(r, dict): break
            result = r.get('result',[])
            if not isinstance(result, list) or not result: break
            all_posts.extend(result)
            if len(result) < 1000: break
            offset += 1000
    active = [p for p in all_posts if isinstance(p, dict) and p.get('status') != 'cancelled']
    sku_data = {}
    for p in active:
        for prod in p.get('products',[]):
            sku = str(prod.get('sku','0')); name = prod.get('name','?')
            price = float(prod.get('price',0) or 0); qty = int(prod.get('quantity',1) or 1)
            if sku not in sku_data: sku_data[sku] = {'name':name, 'orders':0, 'units':0, 'revenue':0.0}
            sku_data[sku]['orders'] += 1; sku_data[sku]['units'] += qty
            sku_data[sku]['revenue'] += price * qty
    return sku_data, len(active)

def main():
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)
    yesterday = (msk_now - timedelta(days=1)).strftime('%Y-%m-%d')
    log(f'=== 企业店-1 日报（{yesterday}）===')

    analytics_units, analytics_revenue = get_analytics(yesterday)
    log(f'Analytics: {analytics_units}件, {analytics_revenue:,.0f}₽')

    sku_data, fbo_orders = get_fbo_orders(yesterday)
    log(f'FBO/FBS: {fbo_orders}单, {len(sku_data)}个SKU')

    perf_token = get_perf_token()
    ad_stats, campaign_skus, campaign_names = [], {}, {}
    if perf_token:
        ad_stats = get_perf_daily_stats(perf_token, yesterday, yesterday)
        campaign_skus, campaign_names = get_campaign_skus(perf_token)
        log(f'广告: {len(ad_stats)}个活动, {len(campaign_skus)}个推广SKU')

    sorted_skus = sorted(sku_data.items(), key=lambda x: x[1]['orders'], reverse=True)
    ad_total_cost = sum(s['cost'] for s in ad_stats)
    camp_sku_count = {}
    for sku, cid in campaign_skus.items(): camp_sku_count[cid] = camp_sku_count.get(cid, 0) + 1
    ad_by_campaign = {s['id']: s for s in ad_stats}

    sku_ad_expenses = {}
    if perf_token and ad_stats:
        running_cids = [s['id'] for s in ad_stats]
        sku_ad_expenses = get_perf_sku_stats(perf_token, yesterday, running_cids)

    store6_db.init_db(STORE_ID)
    store6_db.save_summary(STORE_ID, yesterday, analytics_units, analytics_revenue,
        fbo_orders, sum(d['units'] for _, d in sorted_skus),
        sum(d['revenue'] for _, d in sorted_skus), len(sorted_skus),
        ad_total_cost, sum(s['orders'] for s in ad_stats),
        sum(s['revenue'] for s in ad_stats), sum(1 for s in sku_data if s in campaign_skus))
    store6_db.save_sku_list(STORE_ID, yesterday, sorted_skus, campaign_skus, ad_by_campaign, camp_sku_count, sku_ad_expenses)
    store6_db.save_campaigns(STORE_ID, yesterday, ad_stats, campaign_names, camp_sku_count)
    log('✅ 数据已存入数据库')
    log('=== 完成 ===')

if __name__ == '__main__':
    main()
