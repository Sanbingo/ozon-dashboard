#!/usr/bin/env python3
"""
多店铺 数据仪表盘 — HTTP 服务
支持多用户、每用户独立管理店铺
"""
import json
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import urlparse, parse_qs
import os, sys, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import stores_db as sdb
import user_store_db as usdb
from dashboard_login import verify_login, create_session, validate_session, destroy_session, get_cookie_value

HOST = '0.0.0.0'
PORT = 8899
DEFAULT_STORE = None  # 不再有全局默认店铺

PUBLIC_PATHS = {'/api/login', '/login', '/api/logout'}


class DashboardHandler(SimpleHTTPRequestHandler):
    _login_html = None

    def _user_stores(self, username):
        """获取用户启用的店铺映射 {store_id: name}"""
        return usdb.get_stores_dict(username)

    # ==================== GET ====================

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path in PUBLIC_PATHS:
            if path == '/login':
                self._serve_login()
            else:
                self._json_response({'error': 'method not allowed'}, 405)
            return

        session = self._check_session()
        if not session:
            self._send_unauthorized()
            return

        username = session['username']
        stores = self._user_stores(username)

        # 店铺管理页面
        if path == '/settings':
            self._serve_settings_html()
            return

        # 店铺管理 API
        if path == '/api/user/stores':
            self._json_response(self._list_user_stores(username))
            return

        # 获取用户信息（含是否为新用户无店铺）
        if path == '/api/user/info':
            store_list = usdb.get_user_stores(username)
            self._json_response({
                'username': username,
                'store_count': len(store_list),
                'has_stores': len(store_list) > 0,
            })
            return

        # 销售/广告数据相关 API
        if path == '/api/overview/trend':
            self._json_response(self._get_overview_trend(username, stores))
            return
        if path == '/api/overview':
            date = params.get('date', [None])[0]
            self._json_response(self._get_overview(username, stores, date))
            return

        # 即使没有店铺也能访问的端点
        if path == '/api/stores':
            self._json_response(stores)
            return
        if path == '/api/session':
            self._json_response({'username': session['username']})
            return
        if path == '/':
            self._serve_html()
            return

        # 如果用户没有店铺，返回友好提示（非错误）
        if not stores:
            self._json_response({'message': 'no stores', 'stores': {}})
            return

        store = params.get('store', [list(stores.keys())[0]])[0]
        if store not in stores:
            self._json_response({'error': f'未知店铺: {store}', 'stores': stores}, 400)
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
        else:
            super().do_GET()

    # ==================== POST ====================

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/login':
            self._handle_login()
        elif path == '/api/logout':
            self._handle_logout()
        elif path == '/api/user/store/add':
            self._handle_add_store()
        elif path == '/api/user/store/update':
            self._handle_update_store()
        elif path == '/api/user/store/delete':
            self._handle_delete_store()
        else:
            self._json_response({'error': 'not found'}, 404)

    # ==================== 认证 ====================

    def _check_session(self):
        cookie = self.headers.get('Cookie', '')
        token = get_cookie_value(cookie, 'session')
        return validate_session(token)

    def _send_unauthorized(self):
        accept = self.headers.get('Accept', '')
        if 'json' in accept or self.path.startswith('/api/'):
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'unauthorized', 'login': True}).encode())
        else:
            self.send_response(302)
            self.send_header('Location', '/login')
            self.end_headers()

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
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', 'session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax')
        self.end_headers()
        self.wfile.write(json.dumps({'ok': True}).encode())

    # ==================== 店铺管理 API ====================

    def _list_user_stores(self, username):
        """列出用户所有店铺配置（含密钥等敏感信息，仅本人可见）"""
        stores = usdb.get_user_stores(username)
        return {'stores': stores}

    # ==================== Cron 同步 ====================

    # 已知的店铺报告脚本映射 {store_id: script_file}
    # 新店铺会自动推测脚本名，脚本不存在时会跳过并在警告中提示
    STORE_SCRIPTS = {
        'store6': 'store6-report-format.py',
        'store7': 'ozon-store7-report.py',
        'store8': 'ozon-store8-report.py',
        'store9': 'ozon-store9-report.py',
        'store10': 'ozon-store10-report.py',
    }

    _REPORT_SCRIPT_DIR = '/root/scripts/ozon'  # 报告脚本存放目录

    def _sync_cron(self, username=None):
        """同步所有用户店铺的定时任务到系统 crontab"""
        import subprocess
        import re

        try:
            # 读取当前 crontab
            r = subprocess.run(['crontab', '-l'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            current = r.stdout.decode('utf-8', errors='replace') if r.returncode == 0 else ''

            # 剔除旧版 ozon 定时条目 + 标记块，保留其他内容
            lines = current.split('\n')
            kept = []
            in_ozon_block = False
            for line in lines:
                if line.strip() == '# === ozon-managed ===':
                    in_ozon_block = True
                    continue
                if line.strip() == '# === end ozon-managed ===':
                    in_ozon_block = False
                    continue
                if in_ozon_block:
                    continue
                # 跳过旧的 store-report 条目（避免重复）
                if re.search(r'store\d+-report', line) and 'python3' in line:
                    continue
                kept.append(line)

            # 获取所有店铺（不局限于已知映射），有新店铺自动推测脚本名
            import os as _os
            new_entries = []
            skipped_stores = []  # 记录无脚本的店铺

            # 收集所有用户的启用店铺
            all_stores = {}
            for uname in ('OZON', 'HF', username) if username else ('OZON', 'HF'):
                for s in usdb.get_user_stores(uname):
                    if not s.get('enabled', 1):
                        continue
                    sid = s['store_id']
                    if sid not in all_stores:
                        all_stores[sid] = s

            for sid, store_info in sorted(all_stores.items()):
                # 先查已知映射
                script = self.STORE_SCRIPTS.get(sid)
                if not script:
                    # 自动推测脚本名：ozon-{sid}-report.py
                    guessed = f"ozon-{sid}-report.py"
                    script_path = _os.path.join(self._REPORT_SCRIPT_DIR, guessed)
                    if _os.path.exists(script_path):
                        script = guessed
                    else:
                        # 也试试 {sid}-report-format.py
                        guessed2 = f"{sid}-report-format.py"
                        script_path2 = _os.path.join(self._REPORT_SCRIPT_DIR, guessed2)
                        if _os.path.exists(script_path2):
                            script = guessed2
                        else:
                            skipped_stores.append(f'{sid} ({store_info["name"]})')
                            continue

                t = store_info.get('schedule_time', '08:40')
                try:
                    hour, minute = t.strip().split(':')
                    hour = str(int(hour))
                    minute = str(int(minute))
                except:
                    hour, minute = '8', '40'

                log_file = f"/root/scripts/logs/{sid}-report.log"
                entry = f"{minute} {hour} * * * cd /root/scripts && python3 /root/scripts/ozon/{script} >> {log_file} 2>&1"
                new_entries.append(entry)

            # 组装新 crontab
            new_cron = '\n'.join(kept)
            if kept and kept[-1] != '':
                new_cron += '\n'
            new_cron += '# === ozon-managed ===\n'
            for e in new_entries:
                new_cron += e + '\n'
            new_cron += '# === end ozon-managed ===\n'

            # 写入 crontab
            p = subprocess.run(['crontab', '-'], input=new_cron.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            if p.returncode != 0:
                return f'crontab 写入失败: {p.stderr.decode()[:200]}'

            # 如有跳过的店铺，返回警告
            if skipped_stores:
                return f'以下店铺无报告脚本，未添加定时任务: {", ".join(skipped_stores)}'

            return None  # 成功
        except Exception as e:
            return f'cron 同步异常: {str(e)[:200]}'

    def _handle_add_store(self):
        session = self._check_session()
        if not session:
            self._send_unauthorized()
            return
        username = session['username']

        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length > 0 else b'{}'
            data = json.loads(body)
        except:
            self._json_response({'ok': False, 'message': '请求格式错误'}, 400)
            return

        store_id = data.get('store_id', '').strip()
        name = data.get('name', '').strip()
        client_id = data.get('client_id', '').strip()
        api_key = data.get('api_key', '').strip()
        perf_client_id = data.get('perf_client_id', '').strip()
        perf_client_secret = data.get('perf_client_secret', '').strip()
        schedule_time = data.get('schedule_time', '08:40').strip()

        # 自动生成 store_id（如未提供）
        if not store_id:
            existing = usdb.get_user_stores(username)
            import re
            max_num = 0
            for s in existing:
                m = re.match(r'store(\d+)', s.get('store_id', ''))
                if m:
                    max_num = max(max_num, int(m.group(1)))
            store_id = f'store{max_num + 1}'

        if not store_id or not name or not client_id or not api_key:
            self._json_response({'ok': False, 'message': 'store_id, name, client_id, api_key 为必填'}, 400)
            return
        if not perf_client_id or not perf_client_secret:
            self._json_response({'ok': False, 'message': '广告API的Client ID和Secret为必填'}, 400)
            return

        ok = usdb.add_store(username, store_id, name, client_id, api_key,
                            perf_client_id, perf_client_secret, schedule_time)
        if ok:
            # 为新店铺初始化数据库
            sdb.init_db(store_id)
            # 同步定时任务
            cron_err = self._sync_cron(username)
            resp = {'ok': True, 'message': '店铺已添加'}
            if cron_err:
                resp['cron_warning'] = f'定时任务同步失败: {cron_err}'
            self._json_response(resp)
        else:
            self._json_response({'ok': False, 'message': '店铺ID已存在'}, 409)

    def _handle_update_store(self):
        session = self._check_session()
        if not session:
            self._send_unauthorized()
            return
        username = session['username']

        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length > 0 else b'{}'
            data = json.loads(body)
        except:
            self._json_response({'ok': False, 'message': '请求格式错误'}, 400)
            return

        row_id = data.get('id')
        if not row_id:
            self._json_response({'ok': False, 'message': '缺少 id'}, 400)
            return

        updates = {}
        for field in ('name', 'client_id', 'api_key', 'perf_client_id',
                      'perf_client_secret', 'schedule_time', 'enabled'):
            if field in data:
                updates[field] = data[field]

        ok = usdb.update_store(row_id, username, **updates)
        resp = {'ok': ok, 'message': '已更新' if ok else '更新失败'}
        if ok:
            # 同步定时任务（如果涉及 schedule_time 或 enabled 变更）
            if any(k in updates for k in ('schedule_time', 'enabled')):
                cron_err = self._sync_cron(username)
                if cron_err:
                    resp['cron_warning'] = f'定时任务同步失败: {cron_err}'
        self._json_response(resp)

    def _handle_delete_store(self):
        session = self._check_session()
        if not session:
            self._send_unauthorized()
            return
        username = session['username']

        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length > 0 else b'{}'
            data = json.loads(body)
        except:
            self._json_response({'ok': False, 'message': '请求格式错误'}, 400)
            return

        row_id = data.get('id')
        if not row_id:
            self._json_response({'ok': False, 'message': '缺少 id'}, 400)
            return

        ok = usdb.delete_store(row_id, username)
        resp = {'ok': ok, 'message': '已删除' if ok else '删除失败'}
        if ok:
            cron_err = self._sync_cron(username)
            if cron_err:
                resp['cron_warning'] = f'定时任务同步失败: {cron_err}'
        self._json_response(resp)

    # ==================== 总览数据 ====================

    def _get_overview(self, username, stores, target_date=None):
        """聚合用户所有店铺的最新数据"""
        latest_date = None
        stores_data = []

        for sid in stores:
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
                'name': stores[sid],
                'date': d,
                'orders': orders,
                'revenue': revenue,
                'ad_cost': entry.get('ad_total_cost', 0) or 0,
                'ad_orders': entry.get('ad_total_orders', 0) or 0,
                'ad_revenue': entry.get('ad_total_revenue', 0) or 0,
            })

        if latest_date:
            stores_data = [s for s in stores_data if s['date'] == latest_date]

        total_orders = sum(s['orders'] for s in stores_data)
        total_revenue = sum(s['revenue'] for s in stores_data)
        total_ad_cost = sum(s['ad_cost'] for s in stores_data)
        total_ad_orders = sum(s['ad_orders'] for s in stores_data)
        ad_ratio = total_ad_cost / total_revenue * 100 if total_revenue > 0 else 0

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

    def _get_overview_trend(self, username, stores):
        """每日跨店铺聚合趋势数据"""
        from collections import defaultdict
        daily = defaultdict(lambda: {'total_revenue': 0, 'total_orders': 0,
                                      'total_ad_cost': 0, 'total_ad_orders': 0,
                                      'store_count': 0})

        for sid in stores:
            summary = sdb.get_all_summary(sid)
            for s in summary:
                d = s['date']
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

    # ==================== 页面渲染 ====================

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

    def _serve_settings_html(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.html')
        if not os.path.exists(html_path):
            self._send_error(404, 'settings.html not found')
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
        pass


def _load_login_html():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'login.html')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
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


def _migrate_ozon_stores(cfg_module):
    """将 config.py 中的 OZON 店铺配置迁移到 user_store_db"""
    existing = {s['store_id'] for s in usdb.get_user_stores('OZON') if s}
    for sid, cfg in cfg_module.OZON_STORE_KEYS.items():
        if sid not in existing:
            usdb.add_store(
                username='OZON',
                store_id=sid,
                name=cfg['name'],
                client_id=str(cfg['client_id']),
                api_key=cfg['api_key'],
                perf_client_id=cfg.get('perf_client_id', ''),
                perf_client_secret=cfg.get('perf_client_secret', ''),
                schedule_time='08:40',
            )
            print(f'  ✅ 迁移 {sid} ({cfg["name"]})')


if __name__ == '__main__':
    # 初始化用户-店铺数据库
    usdb.init_db()
    
    # 迁移 OZON 现有店铺配置
    print('🔄 迁移 OZON 店铺配置...')
    _migrate_ozon_stores(config)
    
    # 初始化所有店铺的数据库
    for sid in usdb.get_stores_dict('OZON'):
        sdb.init_db(sid)
    for sid in usdb.get_stores_dict('HF'):
        sdb.init_db(sid)
    
    # 初始化 HF 用户（如不存在）
    usdb.create_user('HF', '000111')
    print('  ✅ HF 用户已就绪')

    login_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'login.html')
    if not os.path.exists(login_path):
        with open(login_path, 'w', encoding='utf-8') as f:
            f.write(_default_login_page())
        print(f'📄 已创建 {login_path}')

    print(f'🔐 Ozon 多用户仪表盘')
    print(f'   http://localhost:{PORT}')
    print(f'   默认账号: OZON / 000111')
    print(f'   新用户:  HF / 000111（无店铺，需在 /settings 配置）')

    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer((HOST, PORT), DashboardHandler)
    server.timeout = 30
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
