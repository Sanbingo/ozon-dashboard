# ozon-dashboard

🧡 Ozon 多店铺数据日报仪表盘

## 功能

- 多店铺数据管理（店铺6、企业店-1等）
- Ozon Analytics / FBO/FBS 订单数据采集
- Performance API 广告数据采集
- SQLite 本地持久化
- Web 仪表盘（深色主题）
  - 店铺切换
  - 日期切换
  - 汇总卡片
  - 趋势图表（Chart.js）
  - 商品明细 / 推广活动 / 趋势一览 Tab
- 飞书机器人日报推送
- 每日 08:30~08:50 定时自动更新（crontab）

## 技术栈

- Python 3 (标准库 HTTP 服务器 + SQLite)
- Chart.js 前端图表
- Ozon Seller API / Performance API
- 飞书开放平台 API

## 目录结构

```
/root/scripts/ozon/
├── config.py              # 配置（店铺密钥、飞书、OAS）
├── dashboard.py           # Web 仪表盘 HTTP 服务
├── dashboard.html         # 前端页面
├── store6_db.py           # SQLite 数据库层（多店铺）
├── store6-report-format.py  # 店铺6 日报采集
├── store7-report.py       # 企业店-1 日报采集
├── backfill_store7.py     # 企业店-1 历史数据回填
├── ozon-daily.py          # Ozon 总览日报（旧）
├── lib/feishu.py          # 飞书 API 封装
├── data/                  # SQLite 数据库（每店铺独立文件）
│   ├── store6.db
│   └── store7.db
└── logs/                  # 日志
```
