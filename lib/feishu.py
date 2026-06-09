"""
Ozon Agent 专用 飞书 API 封装
"""
import json
import subprocess
import sys
sys.path.insert(0, '/Users/san/.openclaw/workspace/ozon/scripts')
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID, FEISHU_GROUP_ID, LOG_DIR


def get_tenant_token():
    """获取飞书 tenant_access_token"""
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST',
         'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps({"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15
    )
    data = json.loads(r.stdout)
    if 'tenant_access_token' not in data:
        raise Exception(f"获取Feishu token失败: {data}")
    return data['tenant_access_token']


def send_text(token, receive_id, text, receive_type='open_id'):
    """发送文字消息"""
    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False)
    }
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST',
         f'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_type}',
         '-H', f'Authorization: Bearer {token}',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(payload, ensure_ascii=False)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15
    )
    result = json.loads(r.stdout)
    if result.get('code') != 0:
        _log(f"发送文字消息失败: {result}")
        return False
    _log(f"文字消息已发送到 {receive_id}")
    return True


def upload_image(token, image_path):
    """上传图片，返回 image_key"""
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST',
         'https://open.feishu.cn/open-apis/im/v1/images',
         '-H', f'Authorization: Bearer {token}',
         '-F', 'image_type=message',
         '-F', f'image=@{image_path}'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30
    )
    data = json.loads(r.stdout)
    if 'data' not in data or 'image_key' not in data['data']:
        raise Exception(f"上传图片失败: {data}")
    return data['data']['image_key']


def send_image(token, receive_id, image_key, receive_type='open_id'):
    """发送图片消息"""
    payload = {
        "receive_id": receive_id,
        "msg_type": "image",
        "content": json.dumps({"image_key": image_key})
    }
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST',
         f'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_type}',
         '-H', f'Authorization: Bearer {token}',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(payload)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15
    )
    result = json.loads(r.stdout)
    if result.get('code') != 0:
        raise Exception(f"发送图片消息失败: {result}")
    _log(f"图片消息已发送")
    return True


def send_text_to_user(token, text):
    """发送文字到林总私聊"""
    return send_text(token, FEISHU_USER_ID, text, 'open_id')


def send_text_to_group(token, text):
    """发送文字到Ozon群"""
    return send_text(token, FEISHU_GROUP_ID, text, 'chat_id')


def _log(msg):
    with open(f'{LOG_DIR}/feishu.log', 'a') as f:
        f.write(f'{msg}\n')
