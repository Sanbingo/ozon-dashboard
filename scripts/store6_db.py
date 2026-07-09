#!/usr/bin/env python3
"""
店铺6 数据持久化模块 — 转发到根目录 store6_db
所有函数直接委派给上级目录的 store6_db，统一使用根目录的 data/
"""
import sys, os, importlib.util

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_path = os.path.join(_root, 'store6_db.py')

# 直接按文件路径加载根目录的 store6_db 模块
_spec = importlib.util.spec_from_file_location('_root_store6_db', _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# 覆盖 DB_DIR 指向根目录 data/
DB_DIR = os.path.join(_root, 'data')

# 重导出（仅导出脚本实际使用的函数）
init_db = _mod.init_db
save_summary = _mod.save_summary
save_sku_list = _mod.save_sku_list
save_campaigns = _mod.save_campaigns
get_all_summary = _mod.get_all_summary
