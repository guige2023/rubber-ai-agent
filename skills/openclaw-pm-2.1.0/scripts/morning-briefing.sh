#!/bin/bash

# morning-briefing.sh - 每日晨间简报
# 一键了解昨晚发生了什么，今天需要关注什么

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 获取日期
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)

echo -e "${CYAN}🌅 Morning Briefing - $TODAY${NC}"
echo "=================================================="

# 1. 系统健康状态
echo -e "\n${BLUE}📊 System Health${NC}"
echo "------------------"

# Gateway 状态
if pgrep -f "openclaw.*gateway" > /dev/null; then
    PID=$(pgrep -f "openclaw.*gateway")
    echo -e "✅ Gateway running (PID: $PID)"
else
    echo -e "❌ Gateway not running"
fi

# Session locks
LOCK_COUNT=$(find ~/.openclaw/agents/*/sessions/ -name "*.lock" 2>/dev/null | wc -l | tr -d ' ')
if [ "$LOCK_COUNT" -eq 0 ]; then
    echo -e "✅ No session locks"
else
    echo -e "⚠️  $LOCK_COUNT session lock(s) found"
fi

# 磁盘空间
DISK_USAGE=$(df -h ~/.openclaw | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 80 ]; then
    echo -e "✅ Disk usage: ${DISK_USAGE}%"
else
    echo -e "⚠️  Disk usage: ${DISK_USAGE}%"
fi

# 2. 昨夜活动摘要
echo -e "\n${PURPLE}🌙 Last Night Activity${NC}"
echo "------------------------"

LOG_FILE="/tmp/openclaw/openclaw-$YESTERDAY.log"
if [ -f "$LOG_FILE" ]; then
    # 消息统计
    RECEIVED=$(grep -c "received message" "$LOG_FILE" 2>/dev/null || true); RECEIVED=${RECEIVED:-0}
    COMPLETED=$(grep -c "task done" "$LOG_FILE" 2>/dev/null || true); COMPLETED=${COMPLETED:-0}
    ERRORS=$(grep -c "task error" "$LOG_FILE" 2>/dev/null || true); ERRORS=${ERRORS:-0}
    
    echo "📨 Messages: $RECEIVED received, $COMPLETED completed, $ERRORS errors"
    
    # 检查是否有重启
    RESTARTS=$(grep -c "Gateway.*start" "$LOG_FILE" 2>/dev/null || true); RESTARTS=${RESTARTS:-0}
    if [ "$RESTARTS" -gt 0 ] 2>/dev/null; then
        echo -e "🔄 Gateway restarts: $RESTARTS"
    fi
    
    # 检查错误
    if [ "$ERRORS" -gt 0 ] 2>/dev/null; then
        echo -e "\n${YELLOW}Recent errors:${NC}"
        grep "task error" "$LOG_FILE" | tail -3 | sed 's/^/  /'
    fi
else
    echo "📝 No log file found for $YESTERDAY"
fi

# 3. Cron 任务状态
echo -e "\n${GREEN}⏰ Cron Tasks${NC}"
echo "---------------"

# 调用现有的 cron 检查脚本
if [ -f "scripts/check-missed-crons.sh" ]; then
    ./scripts/check-missed-crons.sh --quiet
else
    echo "⚠️  Cron check script not found"
fi

# 4. 待办事项检查
echo -e "\n${YELLOW}📋 In Progress Tasks${NC}"
echo "----------------------"

# 检查昨天和今天的 memory 文件
for DATE in "$YESTERDAY" "$TODAY"; do
    MEMORY_FILE="memory/$DATE.md"
    if [ -f "$MEMORY_FILE" ]; then
        IN_PROGRESS=$(grep -A 20 "## In Progress" "$MEMORY_FILE" 2>/dev/null | grep -E "^### " | grep -v "✅" || true)
        if [ -n "$IN_PROGRESS" ]; then
            echo -e "${CYAN}$DATE:${NC}"
            echo "$IN_PROGRESS" | sed 's/^/  /'
        fi
    fi
done

if [ -z "$(find memory/ -name "*.md" -exec grep -l "## In Progress" {} \; -exec grep -A 20 "## In Progress" {} \; | grep -E "^### " | grep -v "✅")" ]; then
    echo "✅ No pending tasks"
fi

# 5. 今日建议
echo -e "\n${CYAN}💡 Today's Recommendations${NC}"
echo "----------------------------"

# 基于发现的问题给出建议
SUGGESTIONS=()

if [ "$LOCK_COUNT" -gt 0 ]; then
    SUGGESTIONS+=("🔧 Run cleanup-stale-locks.sh to clear session locks")
fi

if [ "$DISK_USAGE" -gt 80 ]; then
    SUGGESTIONS+=("🧹 Clean up old log files and temporary data")
fi

if [ "$ERRORS" -gt 5 ]; then
    SUGGESTIONS+=("🔍 Investigate recent errors with quick-diagnose.sh")
fi

# 检查是否需要 context 管理
CONTEXT_USAGE=$(openclaw session status 2>/dev/null | grep -o "[0-9]*%" | head -1 | sed 's/%//' || echo "0")
if [ "$CONTEXT_USAGE" -gt 80 ]; then
    SUGGESTIONS+=("🧠 Context usage ${CONTEXT_USAGE}% - consider archiving completed tasks")
fi

if [ ${#SUGGESTIONS[@]} -eq 0 ]; then
    echo "✨ All systems green! Ready for a productive day."
else
    for suggestion in "${SUGGESTIONS[@]}"; do
        echo "  $suggestion"
    done
fi

# 6. 快速操作
echo -e "\n${BLUE}🚀 Quick Actions${NC}"
echo "------------------"
echo "  ./scripts/quick-diagnose.sh     - Full system diagnosis"
echo "  ./scripts/daily-stats.sh        - Yesterday's detailed stats"
echo "  ./scripts/check-missed-crons.sh - Check and run missed crons"
echo "  openclaw session status         - Current session status"

echo -e "\n${GREEN}Have a great day! 🌟${NC}"