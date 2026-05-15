#!/bin/bash

# check-unanswered.sh - 检测未回复的用户消息
# 用于 GatewayRestart 恢复、晨间检查、heartbeat 检查

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 配置
OPENCLAW_DIR="$HOME/.openclaw"
AGENTS_DIR="$OPENCLAW_DIR/agents"
MAX_AGE_HOURS=24  # 只检查最近 24 小时内有活动的 session

# 参数解析
JSON_OUTPUT=false
VERBOSE=false
INCLUDE_OLD=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --json)
            JSON_OUTPUT=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --all)
            INCLUDE_OLD=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "检测未回复的用户消息"
            echo ""
            echo "Options:"
            echo "  --json      JSON 格式输出"
            echo "  --verbose   显示详细信息"
            echo "  --all       包括旧 session（默认只检查 24h 内活跃的）"
            echo "  --help      显示帮助"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# 检查 agents 目录
if [ ! -d "$AGENTS_DIR" ]; then
    if $JSON_OUTPUT; then
        echo '{"error": "agents directory not found", "unanswered": []}'
    else
        echo -e "${RED}Error: agents directory not found${NC}"
    fi
    exit 1
fi

# 收集未回复的 session
declare -a UNANSWERED_SESSIONS
declare -a UNANSWERED_DETAILS

check_session() {
    local session_file="$1"
    local agent_id="$2"
    
    # 跳过 .deleted 和 .lock 文件
    [[ "$session_file" == *.deleted ]] && return
    [[ "$session_file" == *.lock ]] && return
    
    # 检查文件修改时间（除非 --all）
    if ! $INCLUDE_OLD; then
        local mod_time=$(stat -f %m "$session_file" 2>/dev/null || stat -c %Y "$session_file" 2>/dev/null)
        local now=$(date +%s)
        local age_hours=$(( (now - mod_time) / 3600 ))
        if [ $age_hours -gt $MAX_AGE_HOURS ]; then
            return
        fi
    fi
    
    # 读取 session 文件，找最后一条消息
    # Session 文件是 JSON，每行一个消息对象
    local last_line=$(tail -1 "$session_file" 2>/dev/null)
    
    # 检查是否是有效的 JSON
    if ! echo "$last_line" | jq -e . >/dev/null 2>&1; then
        return
    fi
    
    # 获取最后一条消息的 role
    local last_role=$(echo "$last_line" | jq -r '.role // empty' 2>/dev/null)
    
    # 如果最后一条是 user 消息，说明没有回复
    if [ "$last_role" = "user" ]; then
        local session_name=$(basename "$session_file" .json)
        local session_key="agent:${agent_id}:${session_name}"
        
        # 获取消息内容预览
        local content=$(echo "$last_line" | jq -r '.content // empty' 2>/dev/null | head -c 100)
        
        # 获取时间戳
        local timestamp=$(echo "$last_line" | jq -r '.timestamp // empty' 2>/dev/null)
        if [ -z "$timestamp" ]; then
            timestamp=$(stat -f %Sm -t "%Y-%m-%d %H:%M" "$session_file" 2>/dev/null || stat -c %y "$session_file" 2>/dev/null | cut -d. -f1)
        fi
        
        UNANSWERED_SESSIONS+=("$session_key")
        UNANSWERED_DETAILS+=("$session_key|$timestamp|$content")
    fi
}

# 遍历所有 agent 的 session
for agent_dir in "$AGENTS_DIR"/*/; do
    [ -d "$agent_dir" ] || continue
    
    agent_id=$(basename "$agent_dir")
    sessions_dir="$agent_dir/sessions"
    
    [ -d "$sessions_dir" ] || continue
    
    for session_file in "$sessions_dir"/*.json; do
        [ -f "$session_file" ] || continue
        check_session "$session_file" "$agent_id"
    done
done

# 输出结果
if $JSON_OUTPUT; then
    # JSON 格式输出
    echo -n '{"unanswered": ['
    first=true
    for detail in "${UNANSWERED_DETAILS[@]}"; do
        IFS='|' read -r key timestamp content <<< "$detail"
        if $first; then
            first=false
        else
            echo -n ','
        fi
        # 转义 JSON 字符串
        content_escaped=$(echo "$content" | jq -Rs '.' | sed 's/^"//;s/"$//')
        echo -n "{\"session_key\": \"$key\", \"timestamp\": \"$timestamp\", \"preview\": \"$content_escaped\"}"
    done
    echo '], "count": '${#UNANSWERED_SESSIONS[@]}'}'
else
    # 人类可读格式
    if [ ${#UNANSWERED_SESSIONS[@]} -eq 0 ]; then
        echo -e "${GREEN}✓ 没有未回复的消息${NC}"
        exit 0
    fi
    
    echo -e "${YELLOW}⚠ 发现 ${#UNANSWERED_SESSIONS[@]} 个未回复的 session${NC}"
    echo ""
    
    for detail in "${UNANSWERED_DETAILS[@]}"; do
        IFS='|' read -r key timestamp content <<< "$detail"
        echo -e "${CYAN}Session:${NC} $key"
        echo -e "${BLUE}Time:${NC} $timestamp"
        if $VERBOSE && [ -n "$content" ]; then
            echo -e "${BLUE}Preview:${NC} ${content:0:80}..."
        fi
        echo ""
    done
    
    echo -e "${YELLOW}提示: 使用 sessions_send 发送消息触发恢复${NC}"
    exit 1
fi
