#!/bin/bash
# quick-diagnose.sh - 快速诊断 OpenClaw 问题
# 基于 BUG_TRACKER.md 中的问题排查清单
# 用法: ./quick-diagnose.sh [--json]

OPENCLAW_DIR="$HOME/.openclaw"
TODAY_LOG="/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log"
JSON_MODE=false

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --json) JSON_MODE=true; shift ;;
        *) shift ;;
    esac
done

# 辅助函数
print_status() {
    local status=$1
    local message=$2
    if $JSON_MODE; then
        return
    fi
    case $status in
        ok) echo -e "${GREEN}✓${NC} $message" ;;
        warn) echo -e "${YELLOW}⚠${NC} $message" ;;
        error) echo -e "${RED}✗${NC} $message" ;;
        info) echo "  $message" ;;
    esac
}

# 1. 检查 Gateway 进程
check_gateway() {
    local pids=$(ps aux | grep "[o]penclaw-gateway" | awk '{print $2}' | sort -n)
    local count=$(echo "$pids" | grep -c . 2>/dev/null || echo 0)
    
    if [[ $count -eq 0 ]]; then
        print_status error "Gateway 未运行"
        return 1
    elif [[ $count -gt 1 ]]; then
        print_status warn "发现 $count 个 Gateway 进程 (PIDs: $(echo $pids | tr '\n' ' '))"
        return 1
    else
        print_status ok "Gateway 运行中 (PID: $pids)"
        return 0
    fi
}

# 2. 检查 Session Lock 文件
check_session_locks() {
    local lock_count=0
    local stale_count=0
    local now=$(date +%s)
    local stale_list=""
    
    for lock_file in "$OPENCLAW_DIR"/agents/*/sessions/*.lock; do
        [[ -f "$lock_file" ]] || continue
        lock_count=$((lock_count + 1))
        
        local age_minutes=$(( (now - $(stat -f %m "$lock_file")) / 60 ))
        if [[ $age_minutes -gt 5 ]]; then
            stale_count=$((stale_count + 1))
            stale_list="$stale_list\n  - $(basename "$lock_file") (${age_minutes}min)"
        fi
    done
    
    if [[ $lock_count -eq 0 ]]; then
        print_status ok "无 session lock 文件"
        return 0
    elif [[ $stale_count -gt 0 ]]; then
        print_status warn "发现 $stale_count 个可能过期的 lock 文件:"
        echo -e "$stale_list"
        return 1
    else
        print_status ok "$lock_count 个活跃的 session lock"
        return 0
    fi
}

# 3. 检查飞书 WebSocket 连接
check_feishu_connection() {
    if [[ ! -f "$TODAY_LOG" ]]; then
        print_status warn "今日日志文件不存在"
        return 1
    fi
    
    local last_ws=$(grep "WebSocket client started" "$TODAY_LOG" 2>/dev/null | tail -1)
    
    if [[ -z "$last_ws" ]]; then
        print_status error "未找到飞书 WebSocket 连接记录"
        return 1
    fi
    
    local ws_time=$(echo "$last_ws" | grep -oE '"date":"[^"]+' | sed 's/"date":"//' | head -1)
    print_status ok "飞书 WebSocket 已连接 (最后连接: ${ws_time:-unknown})"
    return 0
}

# 4. 检查消息接收
check_message_receiving() {
    if [[ ! -f "$TODAY_LOG" ]]; then
        return 1
    fi
    
    local msg_count=$(grep -c "received message" "$TODAY_LOG" 2>/dev/null | tr -d '\n' || echo 0)
    local last_msg=$(grep "received message" "$TODAY_LOG" 2>/dev/null | tail -1 | grep -oE '"date":"[^"]+' | sed 's/"date":"//' | tr -d '\n')
    
    if [[ $msg_count -eq 0 ]]; then
        print_status warn "今日未收到任何消息"
    else
        print_status ok "今日收到 $msg_count 条消息 (最后: ${last_msg:-unknown})"
    fi
    return 0
}

# 5. 检查队列状态
check_queue_status() {
    if [[ ! -f "$TODAY_LOG" ]]; then
        return 1
    fi
    
    local enqueue_count=$(grep -c "lane enqueue" "$TODAY_LOG" 2>/dev/null | tr -d '\n' || echo 0)
    local done_count=$(grep -c "lane task done" "$TODAY_LOG" 2>/dev/null | tr -d '\n' || echo 0)
    local error_count=$(grep -c "lane task error" "$TODAY_LOG" 2>/dev/null | tr -d '\n' || echo 0)
    
    local pending=$((enqueue_count - done_count - error_count))
    [[ $pending -lt 0 ]] && pending=0
    
    if [[ $error_count -gt 0 ]]; then
        print_status warn "队列: $enqueue_count 入队, $done_count 完成, $error_count 错误"
    else
        print_status ok "队列: $enqueue_count 入队, $done_count 完成, $pending 待处理"
    fi
    
    # 检查是否有卡住的任务
    local last_dequeue=$(grep "lane dequeue" "$TODAY_LOG" 2>/dev/null | tail -1)
    if [[ -n "$last_dequeue" ]]; then
        local dequeue_time=$(echo "$last_dequeue" | grep -oE '"date":"[^"]+' | sed 's/"date":"//' | sed 's/\..*//')
        if [[ -n "$dequeue_time" ]]; then
            local dequeue_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$dequeue_time" +%s 2>/dev/null || echo 0)
            local now_epoch=$(date +%s)
            local age_seconds=$((now_epoch - dequeue_epoch))
            
            # 检查这个任务是否完成
            local lane=$(echo "$last_dequeue" | grep -oE 'lane=[^ ]+' | sed 's/lane=//')
            local has_done=$(grep -E "lane task (done|error).*$lane" "$TODAY_LOG" 2>/dev/null | tail -1)
            
            if [[ -z "$has_done" && $age_seconds -gt 180 ]]; then
                print_status warn "  可能有任务卡住: $lane (${age_seconds}s)"
            fi
        fi
    fi
    
    return 0
}

# 6. 检查 LLM 错误
check_llm_errors() {
    if [[ ! -f "$TODAY_LOG" ]]; then
        return 1
    fi
    
    local failover_errors=$(grep -c "FailoverError\|All models failed" "$TODAY_LOG" 2>/dev/null | tr -d '\n' || echo 0)
    local timeout_errors=$(grep -c "timed out" "$TODAY_LOG" 2>/dev/null | tr -d '\n' || echo 0)
    
    if [[ $failover_errors -gt 0 || $timeout_errors -gt 0 ]]; then
        print_status warn "LLM 错误: $failover_errors 次 failover, $timeout_errors 次超时"
        
        local last_error=$(grep -E "FailoverError|All models failed|timed out" "$TODAY_LOG" 2>/dev/null | tail -1)
        if [[ -n "$last_error" ]]; then
            local error_time=$(echo "$last_error" | grep -oE '"date":"[^"]+' | sed 's/"date":"//')
            print_status info "最后错误: ${error_time:-unknown}"
        fi
        return 1
    else
        print_status ok "无 LLM 错误"
        return 0
    fi
}

# 7. 检查磁盘空间
check_disk_space() {
    local usage=$(df -h "$OPENCLAW_DIR" | tail -1 | awk '{print $5}' | sed 's/%//')
    
    if [[ $usage -gt 90 ]]; then
        print_status error "磁盘使用率: $usage%"
        return 1
    elif [[ $usage -gt 80 ]]; then
        print_status warn "磁盘使用率: $usage%"
        return 1
    else
        print_status ok "磁盘使用率: $usage%"
        return 0
    fi
}

# 8. 检查健康检查脚本状态
check_health_script() {
    local health_log="$OPENCLAW_DIR/logs/health-check.log"
    if [[ ! -f "$health_log" ]]; then
        print_status warn "健康检查日志不存在"
        return 1
    fi
    
    local last_check=$(tail -1 "$health_log" | grep -oE '\[.*\]' | head -1)
    local last_result=$(tail -3 "$health_log" | grep -E "All checks passed|Fixed .* issue")
    
    if [[ -n "$last_result" ]]; then
        if echo "$last_result" | grep -q "All checks passed"; then
            print_status ok "健康检查正常 $last_check"
        else
            print_status warn "健康检查发现问题 $last_check"
        fi
    else
        print_status info "健康检查: $last_check"
    fi
    return 0
}

# 主函数
main() {
    local issues=0
    
    if ! $JSON_MODE; then
        echo "🔍 OpenClaw 快速诊断"
        echo "   $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
    fi
    
    check_gateway || ((issues++))
    check_session_locks || ((issues++))
    check_feishu_connection || ((issues++))
    check_message_receiving
    check_queue_status
    check_llm_errors || ((issues++))
    check_disk_space || ((issues++))
    check_health_script
    
    if ! $JSON_MODE; then
        echo ""
        if [[ $issues -eq 0 ]]; then
            echo -e "${GREEN}✓ 所有检查通过${NC}"
        else
            echo -e "${YELLOW}⚠ 发现 $issues 个潜在问题${NC}"
        fi
    fi
    
    return $issues
}

main
