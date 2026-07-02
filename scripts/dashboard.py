#!/usr/bin/env python3
"""
多店铺 数据仪表盘 — HTTP 服务
支持 store 参数切换店铺 + 登录认证
"""
import json
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import urlparse, parse_qs
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stores_db as sdb
import config
from dashboard_login import verify_login, create_session, validate_session, destroy_session, get_cookie_value

HOST = '0.0.0.0'
PORT = 8899

# 店铺映射
STORES = {k: v['name'] for k, v in config.OZON_STORE_KEYS.items()}
DEFAULT_STORE = 'store6'

# 不需要登录就能访问的路径
PUBLIC_PATHS = {'/api/login', '/login', '/api/logout'}


def _load_login_html():
    """读取 login.html 模板"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'login.html')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
    # 内嵌默认登录页
    return _default_login_page().encode('utf-8')


def _default_login_page():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Ozon 数据日报 — 登录</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',system-ui,sans-serif;background:#0f1923;color:#e0e6ed;min-height:100vh;display:flex;align-items:center;justify-content:center}
.login-box{background:#1a2d3d;border-radius:16px;padding:40px;border:1px solid #2a3f52;width:380px;max-width:90vw}
.login-box h1{text-align:center;margin-bottom:8px;font-size:22px}
.login-box .sub{text-align:center;color:#8899aa;font-size:13px;margin-bottom:28px}
.form-group{margin-bottom:18px}
.form-group label{display:block;font-size:13px;color:#8899aa;margin-bottom:6px}
.form-group input{width:100%;padding:10px 14px;border-radius:8px;border:1px solid #2a3f52;background:#0f1923;color:#e0e6ed;font-size:15px;outline:none;transition:border-color .2s}
.form-group input:focus{border-color:#ff8c00}
.btn-login{width:100%;padding:12px;border-radius:8px;border:none;background:#ff8c00;color:#fff;font-size:15px;font-weight:600;cursor:pointer;transition:background .2s}
.btn-login:hover{background:#e67e00}
.error{color:#ff5252;font-size:13px;text-align:center;margin-top:12px;display:none}
</style>
</head>
<body>
<div class="login-box">
<h1>🧡 Ozon 数据日报</h1>
<div class="sub">店铺运营仪表盘</div>
<form id="loginForm" onsubmit="return doLogin(event)">
<div class="form-group"><label>账号</label><input type="text" id="username" placeholder="请输入账号" autocomplete="username" required></div>
<div class="form-group"><label>密码</label><input type="password" id="password" placeholder="请输入密码" autocomplete="current-password" required></div>
<button type="submit" class="btn-login">登 录</button>
<div class="error" id="loginError">账号或密码错误</div>
</form>
</div>
<script>
async function doLogin(e){e.preventDefault();const u=document.getElementById('username').value;const p=document.getElementById('password').value;const err=document.getElementById('loginError');err.style.display='none';try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});const d=await r.json();if(d.ok){window.location.href='/';}else{err.textContent=d.message||'登录失败';err.style.display='block'}}catch(e){err.textContent='网络错误';err.style.display='block'}return false}
</script>
</body>
</html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    _login_html = None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # 公开路径：无需登录
        if path in PUBLIC_PATHS:
            if path == '/login':
                self._serve_login()
            else:
                self._json_response({'error': 'method not allowed'}, 405)
            return

        # 需要登录 — 检查 session
        session = self._check_session()
        if not session:
            # 返回 401 或重定向
            accept = self.headers.get('Accept', '')
            if 'json' in accept or path.startswith('/api/'):
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'unauthorized', 'login': True}).encode())
                return
            # 浏览器直接访问，重定向到登录页
            self.send_response(302)
            self.send_header('Location', '/login')
            self.end_headers()
            return

        # 已认证 — 正常处理

        # 总览 API（跨店铺聚合）
        if path == '/api/overview/trend':
            self._json_response(self._get_overview_trend())
            return
        if path == '/api/overview':
            date = params.get('date', [None])[0]
            self._json_response(self._get_overview(date))
            return

        store = params.get('store', [DEFAULT_STORE])[0]
        if store not in STORES:
            self._json_response({'error': f'未知店铺: {store}', 'stores': STORES}, 400)
            return

        if path == '/api/summary':
            self._json_response(sdb.get_all_summary(store))
        elif path == '/api/dates':
            mind, maxd = sdb.get_date_range(store)
            self._json_response({'min_date': mind, 'max_date': maxd})
        elif path == '/api/sku':
            date = params.get('date', [None])[0]
            if not date:
                self._send_error(400, '缺少 date 参数')
                return
            self._json_response(sdb.get_sku_daily(store, date))
        elif path == '/api/stores':
            self._json_response(STORES)
        elif path == '/api/session':
            self._json_response({'username': session['username']})
        elif path == '/':
            self._serve_html()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/login':
            self._handle_login()
        elif path == '/api/logout':
            self._handle_logout()
        else:
            self._json_response({'error': 'not found'}, 404)

    # ---- 认证 ----

    def _check_session(self):
        cookie = self.headers.get('Cookie', '')
        token = get_cookie_value(cookie, 'session')
        return validate_session(token)

    def _handle_login(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length > 0 else b'{}'
            data = json.loads(body)
        except:
            self._json_response({'ok': False, 'message': '请求格式错误'}, 400)
            return

        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if verify_login(username, password):
            token, expires_at = create_session(username)
            # 设置cookie，24h过期
            expires_gmt = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(expires_at))
            cookie_value = f'session={token}; Path=/; Expires={expires_gmt}; HttpOnly; SameSite=Lax'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Set-Cookie', cookie_value)
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'username': username}).encode())
        else:
            self._json_response({'ok': False, 'message': '账号或密码错误'}, 401)

    def _handle_logout(self):
        cookie = self.headers.get('Cookie', '')
        token = get_cookie_value(cookie, 'session')
        destroy_session(token)
        # 清除cookie
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', 'session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax')
        self.end_headers()
        self.wfile.write(json.dumps({'ok': True}).encode())

    # ---- 总览数据 ----

    def _get_overview(self, target_date=None):
        """聚合所有店铺的最新数据，或指定日期的数据"""
        latest_date = None
        stores_data = []

        for sid in STORES:
            summary = sdb.get_all_summary(sid)
            if not summary:
                continue

            if target_date:
                entries = [s for s in summary if s['date'] == target_date]
                if not entries:
                    continue
                entry = entries[0]
            else:
                entry = summary[-1]

            d = entry['date']
            if latest_date is None or d > latest_date:
                latest_date = d

            # analytics 为空时兜底使用 FBO 数据
            orders = entry.get('analytics_units') or 0
            revenue = entry.get('analytics_revenue') or 0
            if orders == 0 and revenue == 0:
                fbo_orders = entry.get('fbo_orders') or 0
                fbo_revenue = entry.get('fbo_revenue') or 0
                if fbo_orders > 0 or fbo_revenue > 0:
                    orders = fbo_orders
                    revenue = fbo_revenue

            stores_data.append({
                'store_id': sid,
                'name': STORES[sid],
                'date': d,
                'orders': orders,
                'revenue': revenue,
                'ad_cost': entry.get('ad_total_cost', 0) or 0,
                'ad_orders': entry.get('ad_total_orders', 0) or 0,
                'ad_revenue': entry.get('ad_total_revenue', 0) or 0,
            })

        # 只保留最新日期的数据
        if latest_date:
            stores_data = [s for s in stores_data if s['date'] == latest_date]

        # 聚合
        total_orders = sum(s['orders'] for s in stores_data)
        total_revenue = sum(s['revenue'] for s in stores_data)
        total_ad_cost = sum(s['ad_cost'] for s in stores_data)
        total_ad_orders = sum(s['ad_orders'] for s in stores_data)
        ad_ratio = total_ad_cost / total_revenue * 100 if total_revenue > 0 else 0

        # 给每个店铺计算占比
        for s in stores_data:
            s['revenue_pct'] = round(s['revenue'] / total_revenue * 100, 1) if total_revenue > 0 else 0
            s['ad_ratio'] = round(s['ad_cost'] / s['revenue'] * 100, 2) if s['revenue'] > 0 else 0

        return {
            'date': latest_date,
            'total_orders': total_orders,
            'total_revenue': total_revenue,
            'total_ad_cost': total_ad_cost,
            'total_ad_orders': total_ad_orders,
            'ad_ratio': round(ad_ratio, 2),
            'store_count': len(stores_data),
            'stores': stores_data,
        }

    def _get_overview_trend(self):
        """每日跨店铺聚合趋势数据"""
        from collections import defaultdict
        daily = defaultdict(lambda: {'total_revenue': 0, 'total_orders': 0, 'total_ad_cost': 0, 'total_ad_orders': 0, 'store_count': 0})

        for sid in STORES:
            summary = sdb.get_all_summary(sid)
            for s in summary:
                d = s['date']
                # analytics 为空时兜底使用 FBO 数据
                rev = s.get('analytics_revenue') or 0
                ords = s.get('analytics_units') or 0
                if ords == 0 and rev == 0:
                    rev = s.get('fbo_revenue') or 0
                    ords = s.get('fbo_orders') or 0
                daily[d]['total_revenue'] += rev
                daily[d]['total_orders'] += ords
                daily[d]['total_ad_cost'] += s.get('ad_total_cost', 0) or 0
                daily[d]['total_ad_orders'] += s.get('ad_total_orders', 0) or 0
                daily[d]['store_count'] += 1

        result = []
        for date in sorted(daily.keys()):
            entry = daily[date]
            entry['date'] = date
            entry['total_ad_ratio'] = round(entry['total_ad_cost'] / entry['total_revenue'] * 100, 2) if entry['total_revenue'] > 0 else 0
            result.append(entry)

        return result

    # ---- 页面渲染 ----

    def _serve_login(self):
        html = _load_login_html()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html)

    def _serve_html(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.html')
        if not os.path.exists(html_path):
            self._send_error(404, 'dashboard.html not found')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        with open(html_path, 'rb') as f:
            self.wfile.write(f.read())

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode('utf-8'))

    def _send_error(self, code, msg):
        self._json_response({'error': msg}, code)

    def log_message(self, format, *args):
        """减少日志输出"""
        pass


if __name__ == '__main__':
    # 初始化所有店铺数据库
    for sid in STORES:
        sdb.init_db(sid)

    # 确保 login.html 存在
    login_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'login.html')
    if not os.path.exists(login_path):
        with open(login_path, 'w', encoding='utf-8') as f:
            f.write(_default_login_page())
        print(f'📄 已创建 {login_path}')

    print(f'🔐 Ozon 多店铺仪表盘 (需登录)')
    print(f'   http://localhost:{PORT}')
    print(f'   账号: OZON')
    print(f'   店铺: {STORES}')

    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer((HOST, PORT), DashboardHandler)
    server.timeout = 30
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
