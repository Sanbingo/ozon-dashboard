#!/usr/bin/env python3
"""
Ozon 每日订单报告脚本
每天08:30 由系统cron执行
1. 登录OAS获取昨日数据
2. 生成HTML图表
3. Chrome截图
4. 记录日志（飞书通知已关闭）
"""
import json
import subprocess
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

LOG_FILE = f"{config.LOG_DIR}/ozon-daily.log"


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f'[{ts}] {msg}\n')
    print(f'[{ts}] {msg}')


def get_oas_token():
    """登录OAS获取token"""
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST', f'{config.OAS_BASE}/api/login',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps({"username": config.OAS_USERNAME, "password": config.OAS_PASSWORD})],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15
    )
    data = json.loads(r.stdout)
    token = data.get('token', '')
    if not token:
        raise Exception(f"OAS登录失败: {data}")
    log("OAS登录成功")
    return token


def get_report_data(token):
    """获取报告数据"""
    r = subprocess.run(
        ['curl', '-s', f'{config.OAS_BASE}/api/report/overview',
         '-H', f'Authorization: Bearer {token}'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15
    )
    data = json.loads(r.stdout)
    log(f"获取到昨日数据: {data.get('yesterday', {})}")
    return data


def generate_html(data):
    """生成深色主题HTML图表"""
    y = data.get('yesterday', {})
    today = data.get('today', {})
    hourly = data.get('yesterdayHourly', [])
    
    y_amount = y.get('amount', 0)
    y_count = y.get('count', 0)
    y_avg = round(y_amount / y_count) if y_count else 0
    t_amount = today.get('amount', 0)
    t_count = today.get('count', 0)
    
    max_h = max(hourly) if hourly else 1
    bars = ''.join(
        f"<div class='bar' style='height:{v/max_h*100:.1f}%' title='{i}:00 - {v:,}₽'>"
        f"<span class='bar-label'>{i}</span></div>"
        for i, v in enumerate(hourly)
    )
    
    # 昨天的MSK日期
    msk_yesterday = (datetime.now(timezone.utc) - timedelta(hours=5, days=1)).strftime('%Y-%m-%d')
    
    html = f'''<!DOCTYPE html>
<html lang='zh-CN'>
<head><meta charset='UTF-8'>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0f1923; color:#e0e6ed; font-family:-apple-system,'SF Pro Display','PingFang SC',sans-serif; width:1200px; padding:40px; }}
.header {{ display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:36px; }}
.header h1 {{ font-size:28px; font-weight:600; color:#fff; }}
.header .date {{ color:#6c8a9e; font-size:14px; }}
.grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:20px; margin-bottom:36px; }}
.card {{ background:#1a2d3d; border-radius:16px; padding:24px; position:relative; overflow:hidden; }}
.card::after {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; }}
.card:nth-child(1)::after {{ background:linear-gradient(90deg,#4fc3f7,#29b6f6); }}
.card:nth-child(2)::after {{ background:linear-gradient(90deg,#66bb6a,#43a047); }}
.card:nth-child(3)::after {{ background:linear-gradient(90deg,#ffa726,#ff8f00); }}
.card .label {{ font-size:13px; color:#6c8a9e; margin-bottom:8px; }}
.card .value {{ font-size:32px; font-weight:700; color:#fff; }}
.card .value .currency {{ font-size:18px; color:#6c8a9e; }}
.card .sub {{ font-size:12px; color:#4a6a80; margin-top:6px; }}
.chart-box {{ background:#1a2d3d; border-radius:16px; padding:24px; }}
.chart-box h3 {{ font-size:14px; color:#6c8a9e; margin-bottom:16px; }}
.bar-chart {{ display:flex; align-items:flex-end; height:160px; gap:6px; }}
.bar {{ flex:1; min-width:4px; border-radius:4px 4px 0 0; background:linear-gradient(180deg,#4fc3f7,rgba(79,195,247,0.2)); position:relative; }}
.bar-label {{ position:absolute; bottom:-18px; left:50%; transform:translateX(-50%); font-size:9px; color:#4a6a80; }}
</style></head>
<body>
<div class='header'>
<div><h1>📊 Ozon 昨日数据报告</h1><div class='date'>{msk_yesterday} MSK</div></div>
</div>
<div class='grid'>
<div class='card'><div class='label'>昨日总金额</div><div class='value'>{y_amount:,}<span class='currency'> ₽</span></div><div class='sub'>今日 {t_amount:,} ₽</div></div>
<div class='card'><div class='label'>昨日订单数</div><div class='value'>{y_count:,}<span class='currency'> 单</span></div><div class='sub'>今日 {t_count} 单</div></div>
<div class='card'><div class='label'>客单价</div><div class='value'>{y_avg:,}<span class='currency'> ₽</span></div><div class='sub'>每单平均</div></div>
</div>
<div class='chart-box'>
<h3>昨日时段分布（每小时间销售额）</h3>
<div class='bar-chart'>{bars}</div>
</div>
</body></html>'''
    
    with open('/tmp/ozon_daily_report.html', 'w') as f:
        f.write(html)
    log("HTML报告已生成")


def screenshot():
    """Chrome headless截图（服务器无Chrome则跳过）"""
    chrome_path = getattr(config, 'CHROME_PATH', None)
    if not chrome_path or not os.path.exists(chrome_path):
        log("Chrome不可用，跳过截图")
        return False
    r = subprocess.run(
        [chrome_path, '--headless', '--disable-gpu',
         f'--screenshot=/tmp/ozon_daily_report.png',
         '--window-size=1200,800',
         f'file:///tmp/ozon_daily_report.html'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30
    )
    if os.path.exists('/tmp/ozon_daily_report.png'):
        size = os.path.getsize('/tmp/ozon_daily_report.png')
        log(f"截图成功: {size} bytes")
        return True
    log(f"截图失败: {r.stderr[:200]}")
    return False


def main():
    log("=== Ozon日报开始 ===")
    
    try:
        # 1. 获取数据
        token = get_oas_token()
        data = get_report_data(token)
        
        # 2. 生成HTML+截图
        generate_html(data)
        screenshot()
        
        log("=== Ozon日报完成 ✅ ===")
        
    except Exception as e:
        log(f"❌ 失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
