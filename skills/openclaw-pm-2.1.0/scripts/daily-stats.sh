#!/bin/bash
# daily-stats.sh - 显示今日 OpenClaw 活动统计
# 用法: ./daily-stats.sh [日期]
# 日期格式: YYYY-MM-DD (默认今天)

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# 配置
DATE="${1:-$(date +%Y-%m-%d)}"
GATEWAY_LOG="$HOME/.openclaw/logs/gateway.log"
TOOL_LOG="/tmp/openclaw/openclaw-${DATE}.log"

# 检查 gateway.log 是否存在
if [ ! -f "$GATEWAY_LOG" ]; then
    echo -e "${RED}Gateway 日志文件不存在: $GATEWAY_LOG${NC}"
    exit 1
fi

echo -e "${BOLD}📊 OpenClaw 活动统计 - ${DATE}${NC}"
echo ""

# 提取今天的日志
TODAY_LOGS=$(grep "^${DATE}" "$GATEWAY_LOG" 2>/dev/null || true)

if [ -z "$TODAY_LOGS" ]; then
    echo -e "${YELLOW}今日暂无日志记录${NC}"
    exit 0
fi

# 辅助函数：安全计数
safe_count() {
    local pattern="$1"
    local result
    result=$(echo "$TODAY_LOGS" | grep -c "$pattern" 2>/dev/null) || result=0
    printf '%d' "$result"
}

# 1. 消息统计
echo -e "${CYAN}━━━ 消息统计 ━━━${NC}"
msg_received=$(safe_count "received message")
msg_enqueued=$(safe_count "lane enqueue")
msg_completed=$(safe_count "lane task done")
msg_errors=$(safe_count "lane task error")

echo -e "  收到消息: ${GREEN}${msg_received}${NC}"
echo -e "  入队处理: ${GREEN}${msg_enqueued}${NC}"
echo -e "  成功完成: ${GREEN}${msg_completed}${NC}"
if [ "$msg_errors" -gt 0 ] 2>/dev/null; then
    echo -e "  处理失败: ${RED}${msg_errors}${NC}"
else
    echo -e "  处理失败: ${GREEN}0${NC}"
fi

# 计算成功率
if [ "$msg_enqueued" -gt 0 ] 2>/dev/null; then
    success_rate=$(echo "scale=1; $msg_completed * 100 / $msg_enqueued" | bc 2>/dev/null || echo "N/A")
    echo -e "  成功率: ${GREEN}${success_rate}%${NC}"
fi
echo ""

# 2. 按小时分布
echo -e "${CYAN}━━━ 消息时段分布 ━━━${NC}"
for hour in $(seq -w 0 23); do
    count=$(echo "$TODAY_LOGS" | grep "received message" | grep -c "T${hour}:" 2>/dev/null || echo "0")
    if [ "$count" -gt 0 ] 2>/dev/null; then
        bar_len=$((count > 20 ? 20 : count))
        bar=$(printf '█%.0s' $(seq 1 $bar_len))
        echo -e "  ${hour}:00  ${BLUE}${bar}${NC} ${count}"
    fi
done
echo ""

# 3. 按 Agent 分布
echo -e "${CYAN}━━━ Agent 活动 ━━━${NC}"
for agent in main content business ops; do
    count=$(echo "$TODAY_LOGS" | grep "received message" | grep -c "feishu\[$agent\]" 2>/dev/null || echo "0")
    if [ "$count" -gt 0 ] 2>/dev/null; then
        echo -e "  ${agent}: ${GREEN}${count}${NC} 条消息"
    fi
done
echo ""

# 4. 错误分析（从 tool log）
echo -e "${CYAN}━━━ 错误分析 ━━━${NC}"
if [ -f "$TOOL_LOG" ]; then
    failover_errors=$(grep -c "FailoverError\|All models failed" "$TOOL_LOG" 2>/dev/null || echo "0")
    timeout_errors=$(grep -c "timed out" "$TOOL_LOG" 2>/dev/null || echo "0")
    tool_errors=$(grep -c '\[tools\].*failed' "$TOOL_LOG" 2>/dev/null || echo "0")
else
    failover_errors=0
    timeout_errors=0
    tool_errors=0
fi

lock_errors=$(safe_count "session file locked")

if [ "$failover_errors" -gt 0 ] 2>/dev/null; then
    echo -e "  Provider 错误: ${RED}${failover_errors}${NC}"
else
    echo -e "  Provider 错误: ${GREEN}0${NC}"
fi

if [ "$timeout_errors" -gt 0 ] 2>/dev/null; then
    echo -e "  超时错误: ${YELLOW}${timeout_errors}${NC}"
else
    echo -e "  超时错误: ${GREEN}0${NC}"
fi

if [ "$lock_errors" -gt 0 ] 2>/dev/null; then
    echo -e "  Session Lock: ${YELLOW}${lock_errors}${NC}"
else
    echo -e "  Session Lock: ${GREEN}0${NC}"
fi

if [ "$tool_errors" -gt 0 ] 2>/dev/null; then
    echo -e "  工具调用失败: ${YELLOW}${tool_errors}${NC}"
else
    echo -e "  工具调用失败: ${GREEN}0${NC}"
fi
echo ""

# 5. Gateway 状态
echo -e "${CYAN}━━━ Gateway 状态 ━━━${NC}"
restarts=$(safe_count "Gateway started")
echo -e "  重启次数: ${restarts}"

ws_connects=$(safe_count "WebSocket client started")
echo -e "  飞书连接: ${ws_connects} 次"
echo ""

# 6. 响应时间估算
echo -e "${CYAN}━━━ 响应时间 ━━━${NC}"
typing_added=$(safe_count "added typing")
typing_removed=$(safe_count "removed typing")

echo -e "  开始处理: ${typing_added} 次"
echo -e "  完成处理: ${typing_removed} 次"
echo ""

# 7. 最近的错误
if [ -f "$TOOL_LOG" ]; then
    recent_errors=$(grep -E "ERROR|error.*failed" "$TOOL_LOG" 2>/dev/null | tail -3 || true)
    if [ -n "$recent_errors" ]; then
        echo -e "${CYAN}━━━ 最近的错误 ━━━${NC}"
        echo "$recent_errors" | while IFS= read -r line; do
            # 提取时间和消息
            time=$(echo "$line" | grep -oE 'T[0-9]{2}:[0-9]{2}:[0-9]{2}' | head -1 | sed 's/T//')
            msg=$(echo "$line" | grep -oE '\[tools\][^"]+' | head -c 50 || echo "")
            if [ -n "$time" ] && [ -n "$msg" ]; then
                echo -e "  ${YELLOW}${time}${NC} ${msg}..."
            fi
        done
        echo ""
    fi
fi

# 8. 总结
echo -e "${CYAN}━━━ 总结 ━━━${NC}"
total_issues=$((msg_errors + failover_errors + lock_errors))
if [ "$total_issues" -eq 0 ] 2>/dev/null; then
    echo -e "  ${GREEN}✓ 今日运行正常，无重大错误${NC}"
else
    echo -e "  ${YELLOW}⚠ 今日共 ${total_issues} 个问题需要关注${NC}"
fi

# 显示日志文件大小
gateway_size=$(du -h "$GATEWAY_LOG" 2>/dev/null | cut -f1)
echo -e "  Gateway 日志: ${gateway_size}"
if [ -f "$TOOL_LOG" ]; then
    tool_size=$(du -h "$TOOL_LOG" 2>/dev/null | cut -f1)
    echo -e "  工具日志: ${tool_size}"
fi
