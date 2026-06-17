# TOOLS.md — Ozon运营助手本地记录

## OAS系统

- 地址：https://oas.xmaquaman.com
- 账号：AKM
- 密码：***
- 登录：POST /api/login → 返回token
- 数据：GET /api/report/overview → 今日/昨日数据

## 飞书（Ozon专用Bot）

- 林总open_id：ou_676ea834120797575b86e9d87771d49b
- Ozon群chat_id：oc_4d130dc369f8ea8ef3e5aaf88ba70f16
- App ID：cli_aa904c0358b89cc6
- 获取token：POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
- 发消息：POST https://open.feishu.cn/open-apis/im/v1/messages
- 发图片：先上传获取image_key，再发image类型消息

## 脚本

- **Ozon日报**：`ozon/scripts/ozon-daily.py`（08:30）
- **店铺6日报**：`ozon/scripts/ozon-store6-report.py`（08:40）
- **配置**：`ozon/scripts/config.py`
- **日志**：`ozon/scripts/logs/`
- ⚠️ 注意：所有配置都指向Ozon飞书Bot，不是小艺（WB）的
