#!/usr/bin/env python3
"""
店铺6 数据持久化模块 — SQLite
初始化数据库，保存/查询每日数据
"""
import sqlite3
import os
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DB_PATH = os.path.join(DB_DIR, 'store6.db')

def get_conn():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """创建表结构（幂等）"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            date            TEXT PRIMARY KEY,  -- YYYY-MM-DD
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

def save_summary(date, analytics_units, analytics_revenue,
                 fbo_orders, fbo_units, fbo_revenue, fbo_sku_count,
                 ad_total_cost, ad_total_orders, ad_total_revenue, ad_sku_count):
    """保存每日汇总"""
    conn = get_conn()
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

def save_sku_list(date, sku_data, campaign_skus, ad_by_campaign, camp_sku_count):
    """保存商品明细"""
    conn = get_conn()
    for sku, d in sku_data:
        cid = campaign_skus.get(sku)
        if cid and cid in ad_by_campaign:
            n = camp_sku_count.get(cid, 1)
            ac = ad_by_campaign[cid]['cost'] / n
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

def save_campaigns(date, ad_stats, campaign_names, camp_sku_count):
    """保存广告活动数据"""
    conn = get_conn()
    for s in ad_stats:
        cname = campaign_names.get(s['id'], s['name'])
        n = camp_sku_count.get(s['id'], 0)
        conn.execute("""
            INSERT OR REPLACE INTO daily_campaign (date, campaign_id, name, cost, orders, revenue, sku_count)
            VALUES (?,?,?,?,?,?,?)
        """, (date, s['id'], cname, s['cost'], s['orders'], s['revenue'], n))
    conn.commit()
    conn.close()

def get_summary(days=30):
    """获取最近N天汇总"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM daily_summary
        ORDER BY date DESC LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_sku_daily(date):
    """获取某天的商品明细"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM daily_sku WHERE date = ? ORDER BY orders DESC, revenue DESC
    """, (date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_date_range():
    """获取有数据的日期范围"""
    conn = get_conn()
    row = conn.execute("SELECT MIN(date) as mind, MAX(date) as maxd FROM daily_summary").fetchone()
    conn.close()
    return row['mind'], row['maxd']

def get_all_summary():
    """获取全部汇总数据"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM daily_summary ORDER BY date ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

if __name__ == '__main__':
    init_db()
    print(f"✅ 数据库初始化完成: {DB_PATH}")
