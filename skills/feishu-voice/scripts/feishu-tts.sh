#!/bin/bash
# feishu-tts.sh - 飞书语音消息发送脚本

# ===== 配置开始 =====
# 替换为你的飞书应用凭证
APP_ID="cli_a90a9cfc11fa9bef"
APP_SECRET="si7XYEbzvgk7HIv7StH2TcKKfaWpHVj6"

# 目标用户ID（飞书open_id）
# 默认发给贵哥
TARGET_USER=${2:-"ou_15fec0b35b57b1d05a210172c0adb2d1"}
# ===== 配置结束 =====

AUDIO_FILE=$1

if [ -z "$AUDIO_FILE" ]; then
    echo "用法: feishu-tts.sh <音频文件.ogg> [用户ID]"
    exit 1
fi

if [ ! -f "$AUDIO_FILE" ]; then
    echo "错误: 音频文件不存在: $AUDIO_FILE"
    exit 1
fi

# 1. 获取 tenant_access_token
TOKEN=$(curl -s -X POST "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal" \
    -H "Content-Type: application/json" \
    -d "{\"app_id\":\"$APP_ID\",\"app_secret\":\"$APP_SECRET\"}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tenant_access_token',''))")

if [ -z "$TOKEN" ]; then
    echo "错误: 获取token失败"
    exit 1
fi

# 2. 上传opus音频文件
FILE_KEY=$(curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/files" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file_type=opus" \
    -F "file_name=voice.ogg" \
    -F "file=@${AUDIO_FILE}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',{}).get('file_key',''))")

if [ -z "$FILE_KEY" ]; then
    echo "错误: 上传文件失败"
    exit 1
fi

# 3. 发送语音消息
RESULT=$(curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"receive_id\":\"$TARGET_USER\",\"msg_type\":\"audio\",\"content\":\"{\\\"file_key\\\":\\\"$FILE_KEY\\\"}\"}")

echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print('发送成功!' if d.get('code')==0 else '发送失败: '+d.get('msg'))"
