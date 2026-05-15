---
name: feishu-voice
description: "飞书语音交互系统 - 语音识别(语音→文字)、语音生成(文字→语音)、发送opus语音到飞书。支持 edge-tts 生成语音、whisper 识别语音、ffeishu-tts.sh 发送语音到飞书。"
metadata:
  {
    "openclaw": {
      "emoji": "🎙️",
      "requires": {
        "bins": ["ffmpeg", "edge-tts", "whisper"],
        "os": ["darwin", "linux"]
      },
      "install": [
        {
          "id": "deps",
          "kind": "brew",
          "formula": "ffmpeg",
          "label": "Install ffmpeg"
        },
        {
          "id": "edge-tts",
          "kind": "pip",
          "formula": "edge-tts",
          "label": "Install edge-tts"
        },
        {
          "id": "whisper",
          "kind": "pip",
          "formula": "openai-whisper",
          "label": "Install whisper"
        }
      ]
    }
  }
---

# 飞书语音交互系统

## 概述
- 语音识别：用户语音 → 文字 (whisper)
- 语音生成：文字 → 语音 (edge-tts)
- 飞书发送：发送 opus 格式语音到飞书

## 依赖
- `ffmpeg` - 音频格式转换
- `edge-tts` - 语音生成
- `openai-whisper` - 语音识别

## 配置

### 飞书凭证
在脚本中配置以下凭证：
- `APP_ID`: 飞书应用 ID
- `APP_SECRET`: 飞书应用密钥
- `TARGET_USER`: 目标用户 open_id

## 使用方法

### 1. 生成语音 (文字 → MP3)
```bash
edge-tts --text "你好，这是测试语音" --voice "zh-CN-XiaoxiaoNeural" --write-media /tmp/voice.mp3
```

### 2. 转换格式 (MP3 → Opus)
```bash
ffmpeg -y -i /tmp/voice.mp3 -acodec libopus -b:a 24k -ar 48000 /tmp/voice.ogg
```

### 3. 发送语音到飞书
```bash
./feishu-tts.sh /tmp/voice.ogg [用户ID]
```

### 4. 语音识别 (语音 → 文字)
```bash
whisper audio.ogg --model tiny --language Chinese --output_format txt
```

## 完整流程示例

### 语音对话流程
1. 用户发送语音消息
2. 下载语音文件
3. 用 whisper 识别为文字
4. 处理文字，生成回复
5. 用 edge-tts 生成语音
6. 转换为 opus 格式
7. 发送语音到飞书

### 发送语音命令
```bash
# 1. 生成语音
edge-tts --text "你好，我是小谨言" --voice "zh-CN-XiaoxiaoNeural" --write-media /tmp/reply.mp3

# 2. 转换格式
ffmpeg -y -i /tmp/reply.mp3 -acodec libopus -b:a 24k -ar 48000 /tmp/reply.ogg

# 3. 发送 (使用脚本)
# feishu-tts.sh <音频文件> [用户ID]
```

## 注意事项

1. **必须转换为 opus 格式** - 飞书只支持 opus 格式 (48kHz, 24kbps)
2. **不要直接发送 mp3** - 飞书不支持
3. **使用 feishu-tts.sh 脚本** - 自动处理上传和发送

## 脚本位置
- 飞书语音发送脚本: `./scripts/feishu-tts.sh`

## 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| 400 错误 | 发送 mp3 而非 opus | 转换格式 |
| token 失败 | 凭证错误 | 检查 APP_ID/SECRET |
| 上传失败 | 文件格式不对 | 确保是 opus 格式 |
