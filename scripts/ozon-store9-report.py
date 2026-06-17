#!/usr/bin/env python3
"""
Ozon 店铺1 每日报告：出单 + 推广数据综合分析
每天08:40 由系统cron执行

流程:
1. Ozon Performance API → 广告统计 + 推广商品
2. Ozon Seller API → FBO/FBS订单数据
3. 综合分析 → 各商品出单和广告占比
4. 发飞书群
"""
import json
import subprocess
import sys
import os
import csv
import io
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from lib.feishu import get_tenant_token, send_text, send_text_to_user

LOG_FILE = f"{config.LOG_DIR}/ozon-store7-report.log"

# ===== 常量 =====
PERF_CLIENT_ID = "95727144-1781662366653@advertising.performance.ozon.ru"
PERF_CLIENT_SECRET = "gxXfl53xu_w4Q1i8s5f_39Vu89XfPIJacw1qk1Xz7FddXbFW88kmwuUHbc3FLxyWlkLcCh6ufDx58KS1pw"
PERF_BASE = "https://api-performance.ozon.ru"
SELLER_CLIENT_ID = str(config.OZON_STORE_KEYS['store9']['client_id'])
SELLER_API_KEY = config.OZON_STORE_KEYS['store9']['api_key']
SELLER_BASE = "https://api-seller.ozon.ru"
OZON_GROUP_ID = "oc_4d130dc369f8ea8ef3e5aaf88ba70f16"  # 当前Ozon群


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f'[{ts}] {msg}\n')
    print(f'[{ts}] {msg}', flush=True)


def curl(method, url, headers=None, data=None, timeout=20):
    """通用curl调用"""
    cmd = ['curl', '-s', '-X', method, url, '--connect-timeout', '10', '--max-time', str(timeout)]
    if headers:
        for k, v in headers.items():
            cmd += ['-H', f'{k}: {v}']
    if data:
        cmd += ['-d', data]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout+5)
    try:
        return json.loads(r.stdout)
    except:
        return {"_raw": r.stdout[:500], "_error": r.stderr[:200]}


def curl_text(method, url, headers=None, data=None, timeout=20):
    """返回文本"""
    cmd = ['curl', '-s', '-X', method, url, '--connect-timeout', '10', '--max-time', str(timeout)]
    if headers:
        for k, v in headers.items():
            cmd += ['-H', f'{k}: {v}']
    if data:
        cmd += ['-d', data]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout+5)
    return r.stdout


# ========== 1. Performance API → 广告数据 ==========

def get_perf_token():
    """获取Performance API access token（最多重试3次）"""
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        r = curl("POST", f"{PERF_BASE}/api/client/token", 
                 {"Content-Type": "application/json"},
                 json.dumps({
                     "client_id": PERF_CLIENT_ID,
                     "client_secret": PERF_CLIENT_SECRET,
                     "grant_type": "client_credentials"
                 }))
        token = r.get('access_token', '')
        if token:
            log(f"Performance API ✅ token获取成功（第{attempt}次）")
            return token
        log(f"Performance API ⚠️ 第{attempt}次失败: {r.get('error', str(r)[:100])}")
        if attempt < max_attempts:
            import time
            time.sleep(3)
    raise Exception(f"Performance API token获取失败（重试{max_attempts}次）: {r}")


def get_perf_daily_stats(token, date_from, date_to):
    """获取广告日报数据"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{PERF_BASE}/api/client/statistics/daily?date_from={date_from}&date_to={date_to}"
    text = curl_text("GET", url, headers)
    if not text or text.startswith('{'):
        log(f"广告日报获取失败: {text[:200]}")
        return []
    reader = csv.DictReader(io.StringIO(text), delimiter=';')
    rows = []
    for row in reader:
        rows.append({
            'id': row.get('ID', ''),
            'name': row.get('Название', ''),
            'date': row.get('Дата', ''),
            'impressions': int(row.get('Показы', '0')),
            'clicks': int(row.get('Клики', '0')),
            'cost': float(row.get('Расход, ₽', '0').replace(',', '.')),
            'orders': int(row.get('Заказы, шт.', '0')),
            'revenue': float(row.get('Заказы, ₽', '0').replace(',', '.')),
        })
    log(f"广告日报 ✅ {len(rows)}条活动数据")
    return rows


def get_campaign_products(token):
    """获取所有推广活动及其商品列表"""
    headers = {"Authorization": f"Bearer {token}"}
    # 获取所有活动
    text = curl_text("GET", f"{PERF_BASE}/api/client/campaign?adv_page_type=", headers)
    try:
        camps = json.loads(text).get('list', [])
    except:
        camps = []
    
    # 获取每个活动的商品
    campaign_skus = {}  # sku -> campaign_id
    campaign_names = {}  # campaign_id -> name
    products_by_campaign = {}
    
    for camp in camps:
        cid = camp.get('id', '')
        cname = camp.get('title', '')
        cstate = camp.get('state', '')
        campaign_names[cid] = cname
        
        # 只获取running和非archived的商品
        if cstate != 'CAMPAIGN_STATE_ARCHIVED':
            prod_text = curl_text("GET", 
                f"{PERF_BASE}/api/client/campaign/{cid}/v2/products?offset=0&limit=100",
                headers)
            try:
                prods = json.loads(prod_text).get('products', [])
            except:
                prods = []
            products_by_campaign[cid] = prods
            for p in prods:
                campaign_skus[str(p.get('sku', ''))] = cid
    
    log(f"推广活动 ✅ {len(camps)}个活动, {len(campaign_skus)}个推广商品")
    return campaign_skus, campaign_names, products_by_campaign


# ========== 2. Ozon Seller API → 订单数据 ==========

def get_analytics(date_str):
    """获取Ozon Analytics官方统计数据（排除取消/退货）"""
    headers = {
        "Client-Id": SELLER_CLIENT_ID,
        "Api-Key": SELLER_API_KEY,
        "Content-Type": "application/json"
    }
    payload = json.dumps({
        "date_from": date_str,
        "date_to": date_str,
        "metrics": ["ordered_units", "revenue"],
        "dimension": ["day"],
        "limit": 100,
        "offset": 0
    })
    r = curl("POST", f"{SELLER_BASE}/v1/analytics/data", headers, payload, timeout=30)
    result = r.get('result', {})
    data = result.get('data', [])
    if data:
        metrics = data[0].get('metrics', [])
        if len(metrics) >= 2:
            ordered_units = metrics[0]
            ordered_money = metrics[1]
            log(f"Analytics ✅ {ordered_units}件, {ordered_money:,.0f}₽")
            return ordered_units, ordered_money
    log(f"Analytics ⚠️ 未获取到完整数据: {r.get('result', {})}")
    return None, None


def get_fbo_orders(date_str):
    """获取FBO订单数据（排除取消，使用MSK日界）"""
    # MSK日界：00:00 MSK = UTC+3
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    since_dt = dt - timedelta(hours=3)  # 当天00:00 MSK → UTC
    to_dt = dt + timedelta(days=1) - timedelta(hours=3)  # 次日00:00 MSK → UTC
    since = f"{since_dt.strftime('%Y-%m-%dT%H:%M:%S')}.000Z"
    to = f"{to_dt.strftime('%Y-%m-%dT%H:%M:%S')}.000Z"
    
    headers = {
        "Client-Id": SELLER_CLIENT_ID,
        "Api-Key": SELLER_API_KEY,
        "Content-Type": "application/json"
    }
    payload = json.dumps({
        "dir": "desc",
        "filter": {"since": since, "to": to, "status": ""},
        "limit": 1000, "offset": 0
    })
    
    r = curl("POST", f"{SELLER_BASE}/v2/posting/fbo/list", headers, payload, timeout=60)
    posts = r.get('result', [])
    
    # 排除取消订单
    active_posts = [p for p in posts if p.get('status') != 'cancelled']
    
    # 按SKU汇总（仅活跃订单）
    sku_orders = {}
    for p in active_posts:
        for prod in p.get('products', []):
            sku = str(prod.get('sku', '0'))
            name = prod.get('name', '?')
            price = float(prod.get('price', 0) or 0)
            qty = int(prod.get('quantity', 1) or 1)
            if sku not in sku_orders:
                sku_orders[sku] = {'name': name, 'qty': 0, 'revenue': 0, 'orders': 0}
            sku_orders[sku]['qty'] += qty
            sku_orders[sku]['revenue'] += price * qty
            sku_orders[sku]['orders'] += 1
    
    cancelled = len(posts) - len(active_posts)
    log(f"FBO订单 ✅ 活跃{len(active_posts)}单(取消{cancelled}单), {len(sku_orders)}个SKU")
    return active_posts, sku_orders


# ========== 3. 综合分析 ==========

def analyze(date_str, posts, sku_orders, ad_stats, campaign_skus, campaign_names,
             analytics_units=None, analytics_money=None):
    """综合分析"""
    # 优先用Analytics官方数据，兜底用FBO汇总
    if analytics_units is not None and analytics_money is not None:
        total_orders = analytics_units
        total_revenue = analytics_money
    else:
        total_orders = len(posts)
        total_revenue = sum(d['revenue'] for d in sku_orders.values())
    
    # 广告汇总
    ad_total = {'cost': 0, 'orders': 0, 'revenue': 0}
    for s in ad_stats:
        ad_total['cost'] += s['cost']
        ad_total['orders'] += s['orders']
        ad_total['revenue'] += s['revenue']
    
    # 广告商品vs非广告
    ad_sku_count = sum(1 for s in sku_orders if s in campaign_skus)
    ad_order_count = sum(d['orders'] for s, d in sku_orders.items() if s in campaign_skus)
    ad_revenue = sum(d['revenue'] for s, d in sku_orders.items() if s in campaign_skus)
    
    # TOP排名
    sku_sorted = sorted(sku_orders.items(), key=lambda x: x[1]['revenue'], reverse=True)
    
    # 按推广活动汇总
    ad_by_camp = {}
    for s in ad_stats:
        ad_by_camp[s['id']] = s
    
    # 生成文本报告
    lines = [f"📊 店铺1 {date_str} 数据日报"]
    lines.append("")
    lines.append(f"📦 【销售概况】")
    source = "Ozon Analytics" if analytics_units is not None else "FBO"
    lines.append(f"  下单件数：{total_orders} 件 ({source})")
    lines.append(f"  下单金额：{total_revenue:,.0f} ₽")
    lines.append(f"  出单SKU数：{len(sku_orders)} 个 (不含取消)")
    lines.append("")
    lines.append(f"📢 【推广消耗】")
    for s in ad_stats:
        cname = campaign_names.get(s['id'], s['name'])
        lines.append(f"  • {cname}：{s['cost']:,.0f}₽ → {s['orders']}单 → {s['revenue']:,.0f}₽")
    if ad_total['cost'] > 0:
        roas = ad_total['revenue'] / ad_total['cost']
        lines.append(f"  ─────────────────")
        lines.append(f"  合计花费 {ad_total['cost']:,.0f}₽ | ROAS {roas:.2f}")
    lines.append("")
    lines.append(f"📋 【商品出单TOP】")
    
    for i, (sku, d) in enumerate(sku_sorted[:10]):
        ad_flag = "📢" if sku in campaign_skus else "  "
        lines.append(f"  {i+1}. {ad_flag} SKU {sku} | {d['qty']}件 | {d['revenue']:,.0f}₽")
        # truncate name
        name = d['name'][:40]
        lines[-1] += f" | {name}"
    
    lines.append("")
    lines.append("📊 【推广效果】")
    pct = f"{ad_revenue/total_revenue*100:.0f}" if total_revenue > 0 else "0"
    lines.append(f"  推广商品 {ad_sku_count}个 → {ad_order_count}单, {ad_revenue:,.0f}₽ ({pct}%销售额)")
    lines.append(f"  非推广 {len(sku_orders)-ad_sku_count}个 → {(total_revenue-ad_revenue):,.0f}₽")
    
    if ad_total['orders'] > 0:
        rev_per_order = ad_total['revenue'] / ad_total['orders']
        cost_per_order = ad_total['cost'] / ad_total['orders']
        lines.append(f"  广告订单均价：{rev_per_order:,.0f}₽")
        lines.append(f"  广告获客成本：{cost_per_order:,.0f}₽/单")
    
    return "\n".join(lines)


# ========== Main ==========

def main():
    log("=== 店铺1每日报告开始 ===")
    
    try:
        # 昨天MSK日期
        msk_today = datetime.now(timezone.utc) + timedelta(hours=3)
        yesterday = (msk_today - timedelta(days=1)).strftime('%Y-%m-%d')
        date_from = yesterday
        date_to = yesterday
        
        # 1. Performance API
        perf_token = get_perf_token()
        ad_stats = get_perf_daily_stats(perf_token, date_from, date_to)
        campaign_skus, campaign_names, _ = get_campaign_products(perf_token)
        
        # 2. Ozon Analytics API（官方统计数据，已排除取消/退货）
        analytics_units, analytics_money = get_analytics(yesterday)
        
        # 3. Ozon Seller API → FBO订单（用于商品明细）
        posts, sku_orders = get_fbo_orders(yesterday)
        
        # 4. 分析（总数据用Analytics，商品明细用FBO）
        report = analyze(yesterday, posts, sku_orders, ad_stats, campaign_skus, campaign_names,
                        analytics_units, analytics_money)
        
        log(f"\n{report}")
        
        # 4. 发飞书
        feishu_token = get_tenant_token()
        
        # 发到当前Ozon群
        send_text(feishu_token, OZON_GROUP_ID, report, 'chat_id')
        log("飞书消息已发送 ✅")
        
        # 也发给林总
        send_text_to_user(feishu_token, report)
        log("林总私聊已发送 ✅")
        
        log("=== 店铺1每日报告完成 ✅ ===")
        
    except Exception as e:
        log(f"❌ 失败: {e}")
        import traceback
        log(traceback.format_exc())
        try:
            tk = get_tenant_token()
            send_text(tk, OZON_GROUP_ID, f"❌ 店铺1日报执行失败: {str(e)[:200]}", 'chat_id')
        except:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
