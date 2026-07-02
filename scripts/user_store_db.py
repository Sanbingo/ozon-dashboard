#!/usr/bin/env python3
"""
用户-店铺管理数据库模块
每个用户独立管理自己的店铺密钥和定时配置
"""
import sqlite3
import os
import json
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

def _db_path():
    os.makedirs(DB_DIR, exist_ok=True)
    return os.path.join(DB_DIR, 'users.db')


def get_conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """创建表结构（幂等），并初始化默认用户"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username    TEXT PRIMARY KEY,
            password    TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT (datetime('now','localtime')),
            updated_at  TIMESTAMP DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS user_stores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT NOT NULL,
            store_id        TEXT NOT NULL,
            name            TEXT NOT NULL,
            client_id       TEXT NOT NULL,
            api_key         TEXT NOT NULL,
            perf_client_id  TEXT DEFAULT '',
            perf_client_secret TEXT DEFAULT '',
            schedule_time   TEXT DEFAULT '08:40',  -- 定时时间 HH:MM
            enabled         INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT (datetime('now','localtime')),
            updated_at      TIMESTAMP DEFAULT (datetime('now','localtime')),
            UNIQUE(username, store_id),
            FOREIGN KEY (username) REFERENCES users(username)
        );

        CREATE INDEX IF NOT EXISTS idx_user_stores_username ON user_stores(username);
    """)
    
    # 初始化默认用户 OZON（密码 000111）
    conn.execute("""
        INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)
    """, ("OZON", "000111"))
    
    conn.commit()
    conn.close()


def get_user(username):
    """获取用户信息"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def verify_user(username, password):
    """验证用户登录"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, password)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(username, password):
    """创建新用户"""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, password)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_user_stores(username):
    """获取用户的所有店铺配置"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM user_stores WHERE username = ? ORDER BY store_id",
        (username,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_store(username, store_id):
    """获取用户指定店铺配置"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM user_stores WHERE username = ? AND store_id = ?",
        (username, store_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_store(username, store_id, name, client_id, api_key,
              perf_client_id='', perf_client_secret='', schedule_time='08:40'):
    """添加店铺配置"""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO user_stores
                (username, store_id, name, client_id, api_key,
                 perf_client_id, perf_client_secret, schedule_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, store_id, name, client_id, api_key,
              perf_client_id, perf_client_secret, schedule_time))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def update_store(store_row_id, username, **kwargs):
    """更新店铺配置（只更新提供的字段）"""
    allowed = {'name', 'client_id', 'api_key', 'perf_client_id',
               'perf_client_secret', 'schedule_time', 'enabled'}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    
    updates['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    set_clause = ', '.join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [store_row_id, username]
    
    conn = get_conn()
    conn.execute(
        f"UPDATE user_stores SET {set_clause} WHERE id = ? AND username = ?",
        values
    )
    conn.commit()
    conn.close()
    return True


def delete_store(store_row_id, username):
    """删除店铺配置"""
    conn = get_conn()
    conn.execute(
        "DELETE FROM user_stores WHERE id = ? AND username = ?",
        (store_row_id, username)
    )
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def get_stores_dict(username):
    """获取用户店铺的 {store_id: name} 映射"""
    stores = get_user_stores(username)
    return {s['store_id']: s['name'] for s in stores if s['enabled']}


if __name__ == '__main__':
    init_db()
    print("✅ 用户-店铺数据库初始化完成")
    
    # 创建 HF 用户
    if create_user("HF", "000111"):
        print("✅ 用户 HF 已创建")
    else:
        print("⚠️ 用户 HF 已存在")
    
    print(f"\n📋 OZON 店铺: {get_stores_dict('OZON')}")
    print(f"📋 HF 店铺: {get_stores_dict('HF')}")
