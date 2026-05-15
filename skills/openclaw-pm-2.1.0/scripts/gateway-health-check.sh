#!/bin/bash
# Gateway Health Check Script
# 检查并修复常见的 Gateway 问题
# 由 launchd 定时运行

LOG_FILE="$HOME/.openclaw/logs/health-check.log"
OPENCLAW_DIR="$HOME/.openclaw"
LOCK_TIMEOUT_MINUTES=5
LOCK_FORCE_REMOVE_MINUTES=15  # 即使 PID 还在，超过这个时间也强制删除
RETRY_STATE_FILE="$HOME/.openclaw/retry-state.json"
TODAY_LOG="/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log"
QUEUE_STUCK_MINUTES=3  # 队列卡住阈值

# 重试配置
MAX_RETRIES=5
RETRY_INTERVAL_SECONDS=120  # 2 分钟

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# 辅助函数：获取 gateway 进程 PID（macOS pgrep 有时找不到进程，用 ps + grep 代替）
get_gateway_pids() {
    ps aux | grep "[o]penclaw-gateway" | awk '{print $2}' | sort -n
}

# 辅助函数：检查 gateway 是否在运行
is_gateway_running() {
    [ -n "$(get_gateway_pids)" ]
}

# 1. 检查多个 gateway 进程
check_multiple_gateways() {
    local pids=$(get_gateway_pids)
    local count=$(echo "$pids" | wc -l | tr -d ' ')
    
    if [ "$count" -gt 1 ]; then
        log "WARNING: Found $count gateway processes, killing old ones"
        # 保留最新的进程（最大的 PID）
        local newest=$(echo "$pids" | tail -1)
        for pid in $pids; do
            if [ "$pid" != "$newest" ]; then
                log "Killing old gateway process: $pid"
                kill "$pid" 2>/dev/null
            fi
        done
        return 1
    fi
    return 0
}

# 2. 检查 stale lock 文件
check_stale_locks() {
    local fixed=0
    
    # 检查所有 agent 目录下的 lock 文件
    for lock_file in "$OPENCLAW_DIR"/agents/*/sessions/*.lock; do
        [ -f "$lock_file" ] || continue
        
        # 检查 lock 文件的年龄
        local age_minutes=$(( ($(date +%s) - $(stat -f %m "$lock_file")) / 60 ))
        
        if [ "$age_minutes" -gt "$LOCK_TIMEOUT_MINUTES" ]; then
            # 检查 lock 文件中的 PID 是否还在运行
            local lock_pid=$(cat "$lock_file" 2>/dev/null | grep -oE '"pid":\s*[0-9]+' | grep -oE '[0-9]+')
            
            if [ -n "$lock_pid" ]; then
                if ! ps -p "$lock_pid" > /dev/null 2>&1; then
                    log "Removing stale lock file (pid $lock_pid not running): $lock_file"
                    rm -f "$lock_file"
                    fixed=1
                elif [ "$age_minutes" -gt "$LOCK_FORCE_REMOVE_MINUTES" ]; then
                    # 如果超过 LOCK_FORCE_REMOVE_MINUTES，即使进程还在也删除
                    log "Removing very old lock file (${age_minutes}min, pid $lock_pid still running): $lock_file"
                    rm -f "$lock_file"
                    fixed=1
                fi
            fi
        fi
    done
    
    return $fixed
}

# 3. 检查 gateway 是否在运行
check_gateway_running() {
    if ! is_gateway_running; then
        log "WARNING: Gateway not running, attempting to start"
        # 尝试启动 gateway
        openclaw gateway start >> "$LOG_FILE" 2>&1
        sleep 5
        
        if is_gateway_running; then
            log "Gateway started successfully"
            
            # 等待 Gateway 完全启动
            sleep 10
            
            # 发送 wake 通知 agent 检查任务状态
            local gateway_token=$(grep -oE '"token":\s*"[^"]+' "$OPENCLAW_DIR/openclaw.json" | head -1 | sed 's/"token":\s*"//')
            if [ -n "$gateway_token" ]; then
                curl -s -X POST "http://127.0.0.1:18789/api/cron/wake" \
                    -H "Authorization: Bearer $gateway_token" \
                    -H "Content-Type: application/json" \
                    -d '{"text":"[Gateway 重启通知] Gateway 刚被健康检查脚本重启。请：1) 汇报重启情况 2) 检查之前的任务状态 3) 继续推进未完成的任务","mode":"now"}' \
                    >> "$LOG_FILE" 2>&1
                log "Wake notification sent after gateway restart"
            fi
        else
            log "ERROR: Failed to start gateway"
            return 1
        fi
    fi
    return 0
}

# 4. 检查 provider 错误并自动重试
check_provider_errors() {
    [ -f "$TODAY_LOG" ] || return 0
    
    # 检查最近 5 分钟内是否有 "All models failed" 错误
    local recent_errors=$(grep -E "All models failed|FailoverError" "$TODAY_LOG" 2>/dev/null | tail -20)
    
    if [ -z "$recent_errors" ]; then
        # 没有错误，清除重试状态
        rm -f "$RETRY_STATE_FILE"
        return 0
    fi
    
    # 提取最近的错误时间和 session 信息
    local last_error_line=$(echo "$recent_errors" | tail -1)
    local last_error_time=$(echo "$last_error_line" | grep -oE '"date":"[^"]+' | sed 's/"date":"//')
    
    # 检查错误是否在最近 5 分钟内
    if [ -n "$last_error_time" ]; then
        local error_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${last_error_time%%.*}" +%s 2>/dev/null || echo 0)
        local now_epoch=$(date +%s)
        local age_seconds=$((now_epoch - error_epoch))
        
        if [ "$age_seconds" -gt 300 ]; then
            # 错误超过 5 分钟，不需要重试
            rm -f "$RETRY_STATE_FILE"
            return 0
        fi
    fi
    
    # 提取失败的 session 信息
    local failed_lane=$(grep -E "lane task error.*All models failed|lane task error.*FailoverError" "$TODAY_LOG" 2>/dev/null | tail -1 | grep -oE 'lane=[^ ]+' | sed 's/lane=//')
    
    if [ -z "$failed_lane" ]; then
        return 0
    fi
    
    log "Detected provider error for lane: $failed_lane"
    
    # 检查重试状态
    local retry_count=0
    local last_retry_time=0
    
    if [ -f "$RETRY_STATE_FILE" ]; then
        retry_count=$(cat "$RETRY_STATE_FILE" | grep -oE '"count":\s*[0-9]+' | grep -oE '[0-9]+' || echo 0)
        last_retry_time=$(cat "$RETRY_STATE_FILE" | grep -oE '"lastRetry":\s*[0-9]+' | grep -oE '[0-9]+' || echo 0)
        local stored_lane=$(cat "$RETRY_STATE_FILE" | grep -oE '"lane":"[^"]+' | sed 's/"lane":"//')
        
        # 如果是不同的 lane，重置计数
        if [ "$stored_lane" != "$failed_lane" ]; then
            retry_count=0
            last_retry_time=0
        fi
    fi
    
    # 检查是否超过最大重试次数
    if [ "$retry_count" -ge "$MAX_RETRIES" ]; then
        log "Max retries ($MAX_RETRIES) reached for lane: $failed_lane"
        return 0
    fi
    
    # 检查是否需要等待
    local now=$(date +%s)
    local time_since_last=$((now - last_retry_time))
    
    if [ "$time_since_last" -lt "$RETRY_INTERVAL_SECONDS" ]; then
        log "Waiting for retry interval (${time_since_last}s < ${RETRY_INTERVAL_SECONDS}s)"
        return 0
    fi
    
    # 更新重试状态
    retry_count=$((retry_count + 1))
    echo "{\"lane\":\"$failed_lane\",\"count\":$retry_count,\"lastRetry\":$now,\"lastError\":\"$last_error_time\"}" > "$RETRY_STATE_FILE"
    
    log "Triggering retry $retry_count/$MAX_RETRIES for lane: $failed_lane"
    
    # 触发 cron wake 来唤醒 agent
    # 使用 curl 调用 OpenClaw API
    local gateway_port=18789
    local gateway_token=$(grep -oE '"token":\s*"[^"]+' "$OPENCLAW_DIR/openclaw.json" | head -1 | sed 's/"token":\s*"//')
    
    if [ -n "$gateway_token" ]; then
        # 发送 wake 事件
        curl -s -X POST "http://127.0.0.1:$gateway_port/api/cron/wake" \
            -H "Authorization: Bearer $gateway_token" \
            -H "Content-Type: application/json" \
            -d "{\"text\":\"[自动重试] Provider 错误恢复检查 (第 $retry_count 次)。失败的 session: $failed_lane\",\"mode\":\"now\"}" \
            >> "$LOG_FILE" 2>&1
        
        log "Wake event sent for retry"
    else
        log "ERROR: Could not find gateway token"
    fi
    
    return 1
}

# 5. 检查队列是否卡住
check_queue_stuck() {
    [ -f "$TODAY_LOG" ] || return 0
    
    local now_epoch=$(date +%s)
    local stuck_threshold=$((QUEUE_STUCK_MINUTES * 60))
    local stuck_lanes=""
    
    # 获取所有正在处理的任务（有 dequeue 但没有 done/error）
    # 提取最近 10 分钟的日志
    local recent_log=$(tail -2000 "$TODAY_LOG")
    
    # 找到所有 dequeue 事件
    local dequeue_events=$(echo "$recent_log" | grep "lane dequeue" | grep -oE '"date":"[^"]+"|lane=[^ ]+' | paste - - | sed 's/"date":"//g' | sed 's/"//g')
    
    while IFS=$'\t' read -r timestamp lane_info; do
        [ -z "$timestamp" ] && continue
        [ -z "$lane_info" ] && continue
        
        local lane=$(echo "$lane_info" | sed 's/lane=//')
        
        # 解析时间戳
        local event_time="${timestamp%%.*}"
        local event_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$event_time" +%s 2>/dev/null || echo 0)
        
        [ "$event_epoch" -eq 0 ] && continue
        
        local age_seconds=$((now_epoch - event_epoch))
        
        # 只检查最近 10 分钟内的事件
        [ "$age_seconds" -gt 600 ] && continue
        
        # 检查这个 lane 是否有对应的 done/error
        local has_done=$(echo "$recent_log" | grep -E "lane task (done|error).*$lane" | grep -E "\"date\":\"[^\"]*\"" | tail -1 | grep -oE '"date":"[^"]+' | sed 's/"date":"//')
        
        if [ -n "$has_done" ]; then
            # 检查 done 时间是否在 dequeue 之后
            local done_time="${has_done%%.*}"
            local done_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$done_time" +%s 2>/dev/null || echo 0)
            
            if [ "$done_epoch" -gt "$event_epoch" ]; then
                # 任务已完成，跳过
                continue
            fi
        fi
        
        # 任务还在运行，检查是否超时
        if [ "$age_seconds" -gt "$stuck_threshold" ]; then
            log "WARNING: Queue stuck for lane: $lane (${age_seconds}s > ${stuck_threshold}s)"
            stuck_lanes="$stuck_lanes $lane"
        fi
    done <<< "$dequeue_events"
    
    if [ -n "$stuck_lanes" ]; then
        log "Detected stuck queues:$stuck_lanes"
        log "Restarting gateway to clear stuck queues"
        
        # 重启 gateway
        openclaw gateway restart >> "$LOG_FILE" 2>&1
        sleep 10
        
        # 发送通知
        local gateway_token=$(grep -oE '"token":\s*"[^"]+' "$OPENCLAW_DIR/openclaw.json" | head -1 | sed 's/"token":\s*"//')
        if [ -n "$gateway_token" ]; then
            curl -s -X POST "http://127.0.0.1:18789/api/cron/wake" \
                -H "Authorization: Bearer $gateway_token" \
                -H "Content-Type: application/json" \
                -d "{\"text\":\"[队列卡住自动恢复] 检测到以下 session 队列卡住超过 ${QUEUE_STUCK_MINUTES} 分钟，已自动重启 Gateway：$stuck_lanes。请检查所有 session 的任务状态，继续推进未完成的任务。\",\"mode\":\"now\"}" \
                >> "$LOG_FILE" 2>&1
            log "Wake notification sent after queue stuck recovery"
        fi
        
        return 1
    fi
    
    return 0
}

# 6. 检查飞书连接（通过日志）
check_feishu_connection() {
    local gateway_log="$OPENCLAW_DIR/logs/gateway.log"
    
    if [ -f "$gateway_log" ]; then
        # 检查最近 5 分钟内是否有飞书连接断开的日志
        local recent_disconnect=$(tail -100 "$gateway_log" | grep -E "abort signal received|WebSocket.*closed|connection.*lost" | tail -1)
        
        if [ -n "$recent_disconnect" ]; then
            # 检查是否有重新连接
            local reconnect=$(tail -50 "$gateway_log" | grep -E "WebSocket client started" | tail -1)
            
            if [ -z "$reconnect" ]; then
                log "WARNING: Feishu connection may be down, restarting gateway"
                openclaw gateway restart >> "$LOG_FILE" 2>&1
                return 1
            fi
        fi
    fi
    return 0
}

# 7. 检查卡死的 session（thinking-only 或 synthetic error toolResult）
check_stuck_thinking_sessions() {
    local fixed=0

    for session_file in "$OPENCLAW_DIR"/agents/*/sessions/*.jsonl; do
        [ -f "$session_file" ] || continue
        # 跳过有 lock 文件的（已由 check_stale_locks 处理）
        [ -f "${session_file}.lock" ] && continue

        # 检查最后一条消息是否是卡死状态：
        # 1. thinking-only assistant 消息（生成中断）
        # 2. toolResult 结尾（tool 失败后 session 没有继续）
        local is_stuck
        is_stuck=$(tail -1 "$session_file" | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read().strip())
    msg = d.get('message', {})
    role = msg.get('role', '')
    content = msg.get('content', [])
    # Case 1: assistant with only thinking (generation interrupted)
    if role == 'assistant':
        types = [c.get('type') for c in content if isinstance(c, dict)]
        if types == ['thinking']:
            print('stuck')
    # Case 2: toolResult ending (session stopped after tool error)
    elif role == 'toolResult':
        text = ' '.join(c.get('text','') for c in content if isinstance(c,dict) and c.get('type')=='text')
        if 'synthetic error' in text or 'missing tool result' in text:
            print('stuck')
except:
    pass
" 2>/dev/null)

        if [ "$is_stuck" = "stuck" ]; then
            # 检查文件修改时间，超过 5 分钟才清理（避免误删正在运行的）
            local age_minutes=$(( ($(date +%s) - $(stat -f %m "$session_file")) / 60 ))
            if [ "$age_minutes" -gt 5 ]; then
                log "Removing thinking-only stuck session (${age_minutes}min old): $session_file"
                rm -f "$session_file"
                fixed=$((fixed + 1))
            fi
        fi
    done

    return $fixed
}

# 8. 检查 session 状态（systemSent=false 和 stopReason=aborted）
check_session_states() {
    local script="$HOME/.openclaw/workspace/scripts/fix-sessions.py"
    if [ -f "$script" ]; then
        python3 "$script" >> "$LOG_FILE" 2>&1
        return $?
    fi
    return 0
}

# 9. 检测 dispatch 卡住（消息被 dispatch 但没有触发 LLM，65ms 内 dispatch complete）
check_stuck_dispatch() {
    local detect_script="$HOME/.openclaw/workspace/scripts/detect-stuck-dispatch.py"
    [ -f "$detect_script" ] || return 0

    # 防止短时间内重复重启（检查最近 30 分钟是否已因此重启过）
    local stuck_state_file="$HOME/.openclaw/stuck-dispatch-state.json"
    if [ -f "$stuck_state_file" ]; then
        local last_restart=$(cat "$stuck_state_file" | grep -oE '"lastRestart":\s*[0-9]+' | grep -oE '[0-9]+' || echo 0)
        local now_epoch=$(date +%s)
        local elapsed=$(( now_epoch - last_restart ))
        if [ "$elapsed" -lt 1800 ]; then
            log "Stuck dispatch: skipping (last restart was ${elapsed}s ago)"
            return 0
        fi
    fi

    local stuck_sessions
    stuck_sessions=$(python3 "$detect_script" 2>/dev/null)
    local exit_code=$?

    [ "$exit_code" -eq 0 ] && return 0

    log "WARNING: Stuck dispatch detected for sessions: $stuck_sessions"

    # 保存所有 session 状态
    local recovery_file
    recovery_file=$(python3 "$HOME/.openclaw/workspace/scripts/save-session-states.py" $stuck_sessions 2>/dev/null)
    log "Saved recovery state to: $recovery_file"

    # 记录本次重启时间
    echo "{\"lastRestart\":$(date +%s),\"stuckSessions\":\"$stuck_sessions\"}" > "$stuck_state_file"

    # 重启 gateway
    log "Restarting gateway due to stuck dispatch"
    openclaw gateway restart >> "$LOG_FILE" 2>&1
    sleep 10

    # 发送 wake 通知（包含恢复文件路径和卡住的 session）
    local gateway_token
    gateway_token=$(grep -oE '"token":\s*"[^"]+' "$OPENCLAW_DIR/openclaw.json" | head -1 | sed 's/"token":\s*"//')
    if [ -n "$gateway_token" ]; then
        local stuck_escaped=$(echo "$stuck_sessions" | tr '\n' ',' | sed 's/,$//')
        curl -s -X POST "http://127.0.0.1:18789/api/cron/wake" \
            -H "Authorization: Bearer $gateway_token" \
            -H "Content-Type: application/json" \
            -d "{\"text\":\"[Stuck Dispatch 自动恢复] 检测到 session dispatch 卡住（消息被 dispatch 但无 LLM 调用），已自动重启 Gateway。卡住的 session：$stuck_escaped。恢复文件：$recovery_file。请读取恢复文件，用 sessions_send 主动联系卡住的 session 用户，告知消息可能未收到，请重新发送。\",\"mode\":\"now\"}" \
            >> "$LOG_FILE" 2>&1
        log "Wake notification sent after stuck dispatch recovery"
    fi

    return 1
}

# 主函数
main() {
    log "=== Health check started ==="
    
    local issues=0
    
    check_gateway_running || ((issues++))
    check_multiple_gateways || ((issues++))
    check_stale_locks || ((issues++))
    check_stuck_thinking_sessions || ((issues++))
    check_session_states || ((issues++))
    check_stuck_dispatch || ((issues++))
    check_queue_stuck || ((issues++))
    check_provider_errors || ((issues++))
    # check_feishu_connection || ((issues++))  # 暂时禁用，可能误判
    
    if [ "$issues" -gt 0 ]; then
        log "Fixed $issues issue(s)"
    else
        log "All checks passed"
    fi
    
    log "=== Health check completed ==="
}

main
