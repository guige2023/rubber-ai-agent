#!/bin/bash
# check-missed-crons.sh - 检查关键 cron 任务是否执行
# 用法:
#   ./check-missed-crons.sh           # 检查并报告
#   ./check-missed-crons.sh --run     # 检查并补执行错过的任务
#   ./check-missed-crons.sh --json    # JSON 格式输出
#
# 退出码:
#   0 = 所有关键任务都已执行
#   1 = 有任务未执行

OPENCLAW_DIR="$HOME/.openclaw"
CONFIG_FILE="$OPENCLAW_DIR/openclaw.json"
LOG_FILE="$OPENCLAW_DIR/logs/cron-check.log"
GATEWAY_PORT=18789

# 参数
RUN_MISSED=false
JSON_OUTPUT=false

for arg in "$@"; do
    case $arg in
        --run) RUN_MISSED=true ;;
        --json) JSON_OUTPUT=true ;;
    esac
done

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 关键任务列表 (name|job_id)
CRITICAL_JOBS=(
    "xiaohongshu-publish|6b0d101b-fbd9-49ca-b580-5ce3cf527a06"
    "yingshi-taifeng-report|12144d92-ccc2-40a5-a924-e776f80f5e67"
    "moltbook-report|2c2668dd-b985-4ed0-ba99-147e7781e3fd"
)

# 获取 gateway token
get_token() {
    grep -oE '"token":\s*"[^"]+' "$CONFIG_FILE" | head -1 | sed 's/"token":\s*"//'
}

# 调用 cron API
call_cron_api() {
    local action="$1"
    local job_id="$2"
    local token=$(get_token)
    
    if [ -z "$token" ]; then
        echo "ERROR: Could not find gateway token" >&2
        return 1
    fi
    
    local url="http://127.0.0.1:$GATEWAY_PORT/api/cron"
    local data="{\"action\":\"$action\""
    
    if [ -n "$job_id" ]; then
        data="${data},\"jobId\":\"$job_id\""
    fi
    data="${data}}"
    
    curl -s -X POST "$url" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "$data" 2>/dev/null
}

# 检查任务是否今天执行过
check_job_ran_today() {
    local job_id="$1"
    local today_start=$(date -v0H -v0M -v0S +%s)000  # 今天 00:00:00 的毫秒时间戳
    
    # 获取任务运行历史
    local runs=$(call_cron_api "runs" "$job_id")
    
    if [ -z "$runs" ] || echo "$runs" | grep -q '"error"'; then
        echo "error"
        return
    fi
    
    # 检查是否有今天的运行记录
    local last_run=$(echo "$runs" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    runs = data.get('runs', [])
    if runs:
        last = max(runs, key=lambda x: x.get('startedAtMs', 0))
        print(last.get('startedAtMs', 0))
    else:
        print(0)
except:
    print(0)
" 2>/dev/null)
    
    if [ "$last_run" -ge "$today_start" ]; then
        echo "ok"
    else
        echo "missed"
    fi
}

# 触发任务执行
trigger_job() {
    local job_id="$1"
    call_cron_api "run" "$job_id" > /dev/null 2>&1
}

# 主检查逻辑
main() {
    local missed_count=0
    local ok_count=0
    local error_count=0
    local missed_jobs=""
    local results=""
    
    # 检查 gateway 是否运行
    if ! curl -s "http://127.0.0.1:$GATEWAY_PORT/health" > /dev/null 2>&1; then
        if ! $JSON_OUTPUT; then
            echo -e "${RED}✗${NC} Gateway 未运行，无法检查 cron 任务"
        fi
        exit 1
    fi
    
    if ! $JSON_OUTPUT; then
        echo "🕐 Cron 任务检查 ($(date '+%Y-%m-%d %H:%M'))"
        echo ""
    fi
    
    for job_entry in "${CRITICAL_JOBS[@]}"; do
        local name="${job_entry%%|*}"
        local job_id="${job_entry##*|}"
        local status=$(check_job_ran_today "$job_id")
        
        case $status in
            ok)
                ((ok_count++))
                if ! $JSON_OUTPUT; then
                    echo -e "${GREEN}✓${NC} $name"
                fi
                results="${results}{\"name\":\"$name\",\"status\":\"ok\"},"
                ;;
            missed)
                ((missed_count++))
                missed_jobs="$missed_jobs $job_id"
                if ! $JSON_OUTPUT; then
                    echo -e "${YELLOW}⚠${NC} $name - 今日未执行"
                fi
                results="${results}{\"name\":\"$name\",\"status\":\"missed\"},"
                ;;
            error)
                ((error_count++))
                if ! $JSON_OUTPUT; then
                    echo -e "${RED}?${NC} $name - 无法检查"
                fi
                results="${results}{\"name\":\"$name\",\"status\":\"error\"},"
                ;;
        esac
    done
    
    # 补执行错过的任务
    if $RUN_MISSED && [ $missed_count -gt 0 ]; then
        if ! $JSON_OUTPUT; then
            echo ""
            echo "🔄 补执行错过的任务..."
        fi
        
        for job_id in $missed_jobs; do
            trigger_job "$job_id"
            if ! $JSON_OUTPUT; then
                echo "  - 已触发: $job_id"
            fi
        done
    fi
    
    # 输出结果
    if $JSON_OUTPUT; then
        results="${results%,}"
        echo "{\"ok\":$ok_count,\"missed\":$missed_count,\"error\":$error_count,\"jobs\":[$results]}"
    else
        echo ""
        if [ $missed_count -eq 0 ]; then
            echo -e "${GREEN}✓ 所有关键任务今日已执行${NC}"
        else
            echo -e "${YELLOW}⚠ $missed_count 个任务今日未执行${NC}"
            if ! $RUN_MISSED; then
                echo "  使用 --run 参数可以补执行"
            fi
        fi
    fi
    
    # 记录日志
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checked: ok=$ok_count missed=$missed_count error=$error_count" >> "$LOG_FILE"
    
    # 退出码
    if [ $missed_count -gt 0 ]; then
        exit 1
    fi
    exit 0
}

main
