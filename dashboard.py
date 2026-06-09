#!/usr/bin/env python3
"""
多店铺 数据仪表盘 — HTTP 服务
支持 store 参数切换店铺
"""
import json
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import urlparse, parse_qs
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store6_db
import config

HOST = '0.0.0.0'
PORT = 8899

# 店铺映射
STORES = {k: v['name'] for k, v in config.OZON_STORE_KEYS.items()}
DEFAULT_STORE = 'store6'

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # 获取 store 参数（默认 store6）
        store = params.get('store', [DEFAULT_STORE])[0]
        if store not in STORES:
            self._json_response({'error': f'未知店铺: {store}', 'stores': STORES}, 400)
            return

        if path == '/api/summary':
            self._json_response(store6_db.get_all_summary(store))
        elif path == '/api/dates':
            mind, maxd = store6_db.get_date_range(store)
            self._json_response({'min_date': mind, 'max_date': maxd})
        elif path == '/api/sku':
            date = params.get('date', [None])[0]
            if not date:
                self._send_error(400, '缺少 date 参数')
                return
            self._json_response(store6_db.get_sku_daily(store, date))
        elif path == '/api/stores':
            # 返回店铺列表
            self._json_response(STORES)
        elif path == '/':
            self._serve_html()
        else:
            super().do_GET()

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode('utf-8'))

    def _send_error(self, code, msg):
        self._json_response({'error': msg}, code)

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

if __name__ == '__main__':
    # 初始化所有店铺数据库
    for sid in STORES:
        store6_db.init_db(sid)
    print(f'📊 多店铺仪表盘: http://localhost:{PORT}')
    print(f'   店铺: {STORES}')

    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer((HOST, PORT), DashboardHandler)
    server.timeout = 30
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
