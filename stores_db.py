#!/usr/bin/env python3
"""
多店铺数据持久化模块 — 每店独立 SQLite 数据库
"""
import sqlite3
import os
from datetime import datetime

DB_DIR = "/root/scripts/ozon/data"

def _db_path(store_id):
    """每个店铺独立数据库文件"""
    os.makedirs(DB_DIR, exist_ok=True)
    return os.path.join(DB_DIR, f'{store_id}.db')


def get_conn(store_id):
    path = _db_path(store_id)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(store_id):
    """创建表结构（幂等）"""
    conn = get_conn(store_id)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            date            TEXT PRIMARY KEY,
            analytics_units INTEGER,
            analytics_revenue REAL,
            fbo_orders      INTEGER,
            fbo_units       INTEGER,
            fbo_revenue     REAL,
            fbo_sku_count   INTEGER,
            ad_total_cost   REAL,
            ad_total_orders INTEGER,
            ad_total_revenue REAL,
            ad_sku_count    INTEGER,
            created_at      TIMESTAMP DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS daily_sku (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            date      TEXT NOT NULL,
            sku       TEXT NOT NULL,
            name      TEXT,
            orders    INTEGER DEFAULT 0,
            units     INTEGER DEFAULT 0,
            revenue   REAL DEFAULT 0,
            ad_cost   REAL DEFAULT 0,
            ad_pct    REAL DEFAULT 0,
            is_ad     INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
            UNIQUE(date, sku)
        );

        CREATE TABLE IF NOT EXISTS daily_campaign (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            name        TEXT,
            cost        REAL DEFAULT 0,
            orders      INTEGER DEFAULT 0,
            revenue     REAL DEFAULT 0,
            sku_count   INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT (datetime('now','localtime')),
            UNIQUE(date, campaign_id)
        );

        CREATE INDEX IF NOT EXISTS idx_sku_date ON daily_sku(date);
        CREATE INDEX IF NOT EXISTS idx_camp_date ON daily_campaign(date);
    """)
    conn.commit()
    conn.close()


def save_summary(store_id, date, analytics_units, analytics_revenue,
                 fbo_orders, fbo_units, fbo_revenue, fbo_sku_count,
                 ad_total_cost, ad_total_orders, ad_total_revenue, ad_sku_count):
    conn = get_conn(store_id)
    conn.execute("""
        INSERT OR REPLACE INTO daily_summary
            (date, analytics_units, analytics_revenue,
             fbo_orders, fbo_units, fbo_revenue, fbo_sku_count,
             ad_total_cost, ad_total_orders, ad_total_revenue, ad_sku_count)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (date, analytics_units, analytics_revenue,
          fbo_orders, fbo_units, fbo_revenue, fbo_sku_count,
          ad_total_cost, ad_total_orders, ad_total_revenue, ad_sku_count))
    conn.commit()
    conn.close()


def save_sku_list(store_id, date, sku_data, campaign_skus, ad_by_campaign, camp_sku_count, sku_ad_expenses=None):
    """保存商品明细

    sku_ad_expenses: 可选，{sku: exact_expense} 来自 Performance API 的 SKU 级推广费。
                     传此参数时优先使用精确值，代替均摊。
    """
    conn = get_conn(store_id)
    for sku, d in sku_data:
        cid = campaign_skus.get(sku)
        if cid and cid in ad_by_campaign:
            if sku_ad_expenses and sku in sku_ad_expenses:
                ac = sku_ad_expenses[sku]  # 精确的 SKU 级推广费
            else:
                n = camp_sku_count.get(cid, 1)
                ac = ad_by_campaign[cid]['cost'] / n  # 回退：均摊
            pct = ac / d['revenue'] * 100 if d['revenue'] > 0 else 0
            is_ad = 1
        else:
            ac = 0
            pct = 0
            is_ad = 0
        conn.execute("""
            INSERT OR REPLACE INTO daily_sku (date, sku, name, orders, units, revenue, ad_cost, ad_pct, is_ad)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (date, sku, d['name'][:100], d['orders'], d['units'], d['revenue'], ac, pct, is_ad))
    conn.commit()
    conn.close()


def save_campaigns(store_id, date, ad_stats, campaign_names, camp_sku_count):
    conn = get_conn(store_id)
    for s in ad_stats:
        cname = campaign_names.get(s['id'], s['name'])
        n = camp_sku_count.get(s['id'], 0)
        conn.execute("""
            INSERT OR REPLACE INTO daily_campaign (date, campaign_id, name, cost, orders, revenue, sku_count)
            VALUES (?,?,?,?,?,?,?)
        """, (date, s['id'], cname, s['cost'], s['orders'], s['revenue'], n))
    conn.commit()
    conn.close()


def get_summary(store_id, days=30):
    conn = get_conn(store_id)
    rows = conn.execute("""
        SELECT * FROM daily_summary
        ORDER BY date DESC LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sku_daily(store_id, date):
    conn = get_conn(store_id)
    rows = conn.execute("""
        SELECT * FROM daily_sku WHERE date = ? ORDER BY orders DESC, revenue DESC
    """, (date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_date_range(store_id):
    conn = get_conn(store_id)
    row = conn.execute("SELECT MIN(date) as mind, MAX(date) as maxd FROM daily_summary").fetchone()
    conn.close()
    return row['mind'], row['maxd']


def get_all_summary(store_id):
    conn = get_conn(store_id)
    rows = conn.execute("SELECT * FROM daily_summary ORDER BY date ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == '__main__':
    # 初始化所有店铺数据库
    import config
    for sid in config.OZON_STORE_KEYS:
        init_db(sid)
        print(f"✅ {sid} 数据库初始化完成: {_db_path(sid)}")
