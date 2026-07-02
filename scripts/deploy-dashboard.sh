#!/bin/bash
# Ozon 数据仪表盘 部署脚本
# 将本地开发文件同步到阿里云服务器
# 用法: ./deploy-dashboard.sh

SERVER="root@8.129.75.222"
REMOTE_DIR="/opt/ozon-dashboard"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🔧 Ozon Dashboard 部署工具"
echo "=========================="
echo ""

# 需要上传的文件
FILES=(
  "config.py"
  "dashboard.py"
  "dashboard.html"
  "dashboard_login.py"
  "stores_db.py"
)

# 创建远程目录
echo "📁 创建远程目录..."
ssh "$SERVER" "mkdir -p $REMOTE_DIR/logs"

# 数据目录指向日报脚本的数据库（symlink），避免重复
# 日报脚本保存在 /root/scripts/ozon/data/ 下
echo "🔗 确保数据目录 symlink..."
ssh "$SERVER" "rm -rf $REMOTE_DIR/data && ln -sf /root/scripts/ozon/data $REMOTE_DIR/data && echo '  ✅ symlink: $REMOTE_DIR/data → /root/scripts/ozon/data'" 2>/dev/null || echo '  ⚠️ symlink 创建失败（可能首次部署时忽略）'

# 上传文件
echo "📤 上传文件..."
for f in "${FILES[@]}"; do
  if [ -f "$LOCAL_DIR/$f" ]; then
    scp "$LOCAL_DIR/$f" "$SERVER:$REMOTE_DIR/$f"
    echo "  ✅ $f"
  else
    echo "  ⚠️  $f 不存在，跳过"
  fi
done

# 上传 login.html（如存在）
if [ -f "$LOCAL_DIR/login.html" ]; then
  scp "$LOCAL_DIR/login.html" "$SERVER:$REMOTE_DIR/login.html"
  echo "  ✅ login.html"
fi

# 数据库已在 /root/scripts/ozon/data/ 中存在，无需重新初始化

# 重启服务
echo ""
echo "🔄 重启仪表盘服务..."
ssh "$SERVER" "pkill -f 'dashboard.py' 2>/dev/null; sleep 1; cd $REMOTE_DIR && nohup python3 dashboard.py > logs/dashboard.log 2>&1 &"
sleep 2

# 验证
echo ""
echo "📡 验证服务..."
ssh "$SERVER" "curl -s -o /dev/null -w '%{http_code}' http://localhost:8899/api/stores && echo ' ✅ 仪表盘正常'"

echo ""
echo "✅ 部署完成！"
