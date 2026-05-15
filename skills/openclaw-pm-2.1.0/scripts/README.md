# OpenClaw 健康检查脚本

这些脚本用于监控和维护 OpenClaw Gateway 的健康状态。

## 脚本列表

### 1. gateway-health-check.sh
**自动检查和修复 Gateway 问题**

功能：
- 检测多个 Gateway 进程（保留最新的）
- 清理过期的 session lock 文件
- 检测 Gateway 崩溃并自动重启
- 检测消息队列卡住
- 检测飞书 WebSocket 断连
- 自动恢复机制（最多重试 5 次）

用法：
```bash
# 手动运行
./scripts/gateway-health-check.sh

# 通过 launchd 定时运行（推荐）
# 见下方"自动化运行"章节
```

### 2. check-unanswered.sh
**检测未回复的用户消息**

功能：
- 扫描所有 agent 的 session 文件
- 检查最后一条消息是否是用户消息（未回复）
- 默认只检查 24 小时内活跃的 session
- 支持 JSON 输出

用法：
```bash
# 检查未回复消息
./scripts/check-unanswered.sh

# 显示详细信息（包括消息预览）
./scripts/check-unanswered.sh --verbose

# 包括所有 session（不限 24h）
./scripts/check-unanswered.sh --all

# JSON 格式输出
./scripts/check-unanswered.sh --json
```

### 3. heartbeat-check.sh
**统一执行 HEARTBEAT.md 检查**

功能：
- Context Health 检查
- 进行中任务检查（读取 memory/YYYY-MM-DD.md）
- Cron 任务检查
- 支持 JSON 输出

用法：
```bash
# 运行所有检查
./scripts/heartbeat-check.sh

# JSON 格式输出
./scripts/heartbeat-check.sh --json
```

### 4. check-missed-crons.sh
**检查关键 cron 任务是否今日执行过**

功能：
- 查询 cron API 获取任务运行历史
- 检查每个关键任务的最后运行时间
- 支持自动补执行错过的任务

用法：
```bash
# 检查并报告
./scripts/check-missed-crons.sh

# 检查并补执行错过的任务
./scripts/check-missed-crons.sh --run

# JSON 格式输出
./scripts/check-missed-crons.sh --json
```

### 5. quick-diagnose.sh
**一键检查 OpenClaw 常见问题**

功能：
- Gateway 进程状态
- Session lock 文件
- 飞书 WebSocket 连接
- 消息接收情况
- 队列状态（是否卡住）
- LLM 错误
- 磁盘空间
- 健康检查脚本状态

用法：
```bash
# 运行诊断
./scripts/quick-diagnose.sh
```

### 6. morning-briefing.sh
**每日晨间一键了解系统状态和昨夜活动**

功能：
- 系统健康状态（Gateway/Session locks/磁盘空间）
- 昨夜活动摘要（消息统计/错误/重启）
- Cron 任务执行状态
- 待办事项检查（In Progress 任务）
- 基于发现问题的今日建议
- 快速操作命令提示

用法：
```bash
# 运行晨间简报
./scripts/morning-briefing.sh
```

### 7. daily-stats.sh
**一键查看指定日期的 OpenClaw 活动统计**

功能：
- 消息收发统计（收到/入队/完成/失败）
- 按小时分布的消息量柱状图
- 按 Agent 分布的消息量
- 错误分析（Provider/超时/Lock/工具调用）
- Gateway 状态（重启次数/飞书连接）
- 响应时间估算（typing indicator）

用法：
```bash
# 查看今天的统计
./scripts/daily-stats.sh

# 查看指定日期
./scripts/daily-stats.sh 2026-02-17
```

## 安装

### 前置要求

- OpenClaw Gateway 已安装并运行
- Bash shell（macOS/Linux）
- jq（JSON 处理工具）

```bash
# macOS
brew install jq

# Linux
sudo apt-get install jq  # Debian/Ubuntu
sudo yum install jq      # CentOS/RHEL
```

### 手动安装

1. 复制脚本到 OpenClaw workspace：

```bash
cp scripts/*.sh ~/.openclaw/workspace/scripts/
chmod +x ~/.openclaw/workspace/scripts/*.sh
```

2. 验证安装：

```bash
~/.openclaw/workspace/scripts/quick-diagnose.sh
```

## 自动化运行

### 使用 launchd（macOS）

创建 `~/Library/LaunchAgents/ai.openclaw.health-check.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.openclaw.health-check</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/YOUR_USERNAME/.openclaw/workspace/scripts/gateway-health-check.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/openclaw-health-check.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/openclaw-health-check-error.log</string>
</dict>
</plist>
```

加载服务：

```bash
launchctl load ~/Library/LaunchAgents/ai.openclaw.health-check.plist
```

### 使用 cron（Linux）

编辑 crontab：

```bash
crontab -e
```

添加：

```cron
# 每 5 分钟运行健康检查
*/5 * * * * /home/YOUR_USERNAME/.openclaw/workspace/scripts/gateway-health-check.sh

# 每天早上 8 点运行晨间简报
0 8 * * * /home/YOUR_USERNAME/.openclaw/workspace/scripts/morning-briefing.sh
```

## 配置

### 关键 Cron 任务列表

编辑 `check-missed-crons.sh`，修改 `CRITICAL_JOBS` 数组：

```bash
CRITICAL_JOBS=(
    "your-job-name-1"
    "your-job-name-2"
    "your-job-name-3"
)
```

### 健康检查参数

编辑 `gateway-health-check.sh`：

```bash
LOCK_TIMEOUT_MINUTES=5              # Session lock 超时时间
LOCK_FORCE_REMOVE_MINUTES=15        # 强制删除 lock 的时间
QUEUE_STUCK_MINUTES=3               # 队列卡住阈值
MAX_RETRIES=5                       # 最大重试次数
RETRY_INTERVAL_SECONDS=120          # 重试间隔（秒）
```

## 故障排查

### 脚本无法运行

1. 检查权限：
```bash
chmod +x ~/.openclaw/workspace/scripts/*.sh
```

2. 检查 shebang：
```bash
head -1 ~/.openclaw/workspace/scripts/gateway-health-check.sh
# 应该输出: #!/bin/bash
```

### 找不到 jq

```bash
# macOS
brew install jq

# Linux
sudo apt-get install jq
```

### Gateway token 错误

确保 `~/.openclaw/openclaw.json` 包含有效的 token：

```json
{
  "token": "your-gateway-token-here"
}
```

### 日志位置

- 健康检查日志：`~/.openclaw/logs/health-check.log`
- Gateway 日志：`/tmp/openclaw/openclaw-YYYY-MM-DD.log`
- launchd 日志：`/tmp/openclaw-health-check.log`

## 贡献

欢迎提交 issue 和 PR！

## 许可证

MIT License
