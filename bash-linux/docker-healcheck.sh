#!/bin/bash

# Docker Compose 服务健康检查和自动重启脚本
# 用法: ./health_check.sh <docker-compose-directory> <test-url> <log-file>
# 说明: 控制台输出所有日志，文件只记录 WARNING 和 ERROR 级别

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 全局变量
COMPOSE_DIR=""
TEST_URL=""
LOG_FILE=""

# 配置参数
MAX_RETRIES=3              # 最大重试次数
RETRY_DELAY=5              # 重试延迟（秒）
TIMEOUT=10                 # HTTP 请求超时时间（秒）
RESTART_WAIT=30            # 重启后等待时间（秒）

# 日志函数 - INFO 只输出到控制台
log_info() {
    local timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "${GREEN}[INFO]${NC} ${timestamp} - $1"
}

# 日志函数 - WARNING 输出到控制台和文件
log_warning() {
    local timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local message="$1"
    
    # 输出到控制台（带颜色）
    echo -e "${YELLOW}[WARNING]${NC} ${timestamp} - ${message}"
    
    # 写入日志文件（如果指定了日志文件）
    if [ -n "$LOG_FILE" ] && [ -w "$LOG_FILE" ]; then
        echo "[WARNING] ${timestamp} - ${message}" >> "$LOG_FILE"
    fi
}

# 日志函数 - ERROR 输出到控制台和文件
log_error() {
    local timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local message="$1"
    
    # 输出到控制台（带颜色）
    echo -e "${RED}[ERROR]${NC} ${timestamp} - ${message}"
    
    # 写入日志文件（如果指定了日志文件）
    if [ -n "$LOG_FILE" ] && [ -w "$LOG_FILE" ]; then
        echo "[ERROR] ${timestamp} - ${message}" >> "$LOG_FILE"
    fi
}

# 显示使用说明
show_usage() {
    cat << EOF
使用方法：
  $0 <docker-compose-directory> <test-url> <log-file>

参数说明：
  docker-compose-directory : Docker Compose 项目目录路径
  test-url                 : 用于健康检查的 URL
  log-file                 : 日志文件路径（只记录 WARNING 和 ERROR）

示例：
  $0 /opt/myapp http://localhost:8080/health /var/log/health_check.log

说明：
  - 控制台会显示所有级别的日志（INFO、WARNING、ERROR）
  - 日志文件只记录 WARNING 和 ERROR 级别的日志
  - 如果日志文件不可写，脚本仍会继续执行

EOF
    exit 1
}

# 初始化和验证参数
init_parameters() {
    # 检查参数数量
    if [ $# -ne 3 ]; then
        echo -e "${RED}[ERROR]${NC} 参数数量错误！需要提供 3 个参数。"
        show_usage
    fi
    
    # 设置参数
    COMPOSE_DIR="$1"
    TEST_URL="$2"
    LOG_FILE="$3"
    
    # 验证 Docker Compose 目录
    if [ ! -d "$COMPOSE_DIR" ]; then
        echo -e "${RED}[ERROR]${NC} 目录不存在: $COMPOSE_DIR"
        exit 1
    fi
    
    # 检查 docker-compose.yml 或 docker-compose.yaml
    if [ ! -f "$COMPOSE_DIR/docker-compose.yml" ] && [ ! -f "$COMPOSE_DIR/docker-compose.yaml" ] && [ ! -f "$COMPOSE_DIR/compose.yml" ] && [ ! -f "$COMPOSE_DIR/compose.yaml" ]; then
        echo -e "${RED}[ERROR]${NC} 在目录 $COMPOSE_DIR 中找不到 docker-compose.yml 或 docker-compose.yaml 文件"
        exit 1
    fi
    
    # 初始化日志文件
    init_log_file
}

# 初始化日志文件
init_log_file() {
    # 获取日志目录
    local log_dir=$(dirname "$LOG_FILE")
    
    # 创建日志目录（如果不存在）
    if [ ! -d "$log_dir" ]; then
        mkdir -p "$log_dir" 2>/dev/null
        if [ $? -ne 0 ]; then
            echo -e "${YELLOW}[WARNING]${NC} 无法创建日志目录: $log_dir，将只输出到控制台"
            LOG_FILE=""
            return 1
        fi
    fi
    
    # 尝试创建或写入日志文件
    touch "$LOG_FILE" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo -e "${YELLOW}[WARNING]${NC} 无法写入日志文件: $LOG_FILE，将只输出到控制台"
        LOG_FILE=""
        return 1
    fi
    
    # 写入会话开始标记（只在日志文件存在且可写时）
    if [ -n "$LOG_FILE" ] && [ -w "$LOG_FILE" ]; then
        echo "" >> "$LOG_FILE"
        # echo "=========================================" >> "$LOG_FILE"
        # echo "健康检查会话开始: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
        # echo "Docker Compose 目录: $COMPOSE_DIR" >> "$LOG_FILE"
        # echo "测试 URL: $TEST_URL" >> "$LOG_FILE"
        # echo "=========================================" >> "$LOG_FILE"
    fi
    
    return 0
}

# 检查必需的命令
check_requirements() {
    local missing_commands=()
    
    # 检查 curl
    if ! command -v curl &> /dev/null; then
        missing_commands+=("curl")
    fi
    
    # 检查 docker
    if ! command -v docker &> /dev/null; then
        missing_commands+=("docker")
    fi
    
    # 如果有缺失的命令，报错退出
    if [ ${#missing_commands[@]} -gt 0 ]; then
        log_error "缺少必需的命令: ${missing_commands[*]}"
        log_error "请先安装这些命令后再运行脚本"
        exit 1
    fi
    
    # 检查 docker compose 命令（新版和旧版）
    if docker compose version &> /dev/null; then
        DOCKER_COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        DOCKER_COMPOSE_CMD="docker-compose"
    else
        log_error "未找到 docker compose 或 docker-compose 命令"
        exit 1
    fi
    
    log_info "使用的 Docker Compose 命令: $DOCKER_COMPOSE_CMD"
}

# 执行 HTTP 健康检查
perform_health_check() {
    local retry_count=0
    local http_code
    local curl_output
    local curl_exit_code
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        retry_count=$((retry_count + 1))
        log_info "执行健康检查 (尝试 ${retry_count}/${MAX_RETRIES}): $TEST_URL"
        
        # 执行 curl 请求，捕获 HTTP 状态码
        curl_output=$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout $TIMEOUT \
            --max-time $TIMEOUT \
            "$TEST_URL" 2>&1)
        curl_exit_code=$?
        
        # 处理 curl 错误
        if [ $curl_exit_code -ne 0 ]; then
            case $curl_exit_code in
                6)  log_warning "无法解析主机: $TEST_URL" ;;
                7)  log_warning "无法连接到主机: $TEST_URL" ;;
                28) log_warning "请求超时: $TEST_URL" ;;
                *)  log_warning "curl 请求失败，退出码: $curl_exit_code" ;;
            esac
            http_code=0
        else
            http_code=$curl_output
            log_info "HTTP 状态码: $http_code"
        fi
        
        # 判断状态码是否正常 (200-299)
        if [ "$http_code" -ge 200 ] && [ "$http_code" -le 299 ]; then
            log_info "✓ 服务健康检查通过 (HTTP $http_code)"
            return 0
        fi
        
        # 如果还有重试机会
        if [ $retry_count -lt $MAX_RETRIES ]; then
            log_warning "健康检查失败 (HTTP $http_code)，${RETRY_DELAY} 秒后重试..."
            sleep $RETRY_DELAY
        else
            log_error "健康检查最终失败，所有重试已用尽 (最后的 HTTP 状态码: $http_code)"
        fi
    done
    
    return 1
}

# 获取 Docker Compose 服务状态
get_compose_status() {
    local status_output
    
    cd "$COMPOSE_DIR" || {
        log_error "无法切换到目录: $COMPOSE_DIR"
        return 1
    }
    
    status_output=$($DOCKER_COMPOSE_CMD ps 2>&1)
    if [ $? -eq 0 ]; then
        echo "$status_output"
    else
        log_warning "无法获取 Docker Compose 服务状态"
        return 1
    fi
}

# 重启 Docker Compose 服务
restart_docker_compose() {
    log_warning "准备重启 Docker Compose 服务..."
    
    # 切换到 Docker Compose 目录
    cd "$COMPOSE_DIR" || {
        log_error "无法切换到目录: $COMPOSE_DIR"
        return 1
    }
    
    log_info "当前工作目录: $(pwd)"
    
    # 显示重启前的服务状态
    log_info "重启前服务状态:"
    get_compose_status
    
    # 执行重启命令
    log_info "执行重启命令: $DOCKER_COMPOSE_CMD restart"
    restart_output=$($DOCKER_COMPOSE_CMD restart 2>&1)
    restart_exit_code=$?
    
    if [ $restart_exit_code -eq 0 ]; then
        log_info "✓ Docker Compose 重启命令执行成功"
        
        # 等待服务启动
        log_info "等待 ${RESTART_WAIT} 秒让服务完全启动..."
        for i in $(seq 1 $RESTART_WAIT); do
            echo -ne "\r进度: $i/$RESTART_WAIT 秒"
            sleep 1
        done
        echo ""
        
        # 显示重启后的服务状态
        log_info "重启后服务状态:"
        get_compose_status
        
        # 执行重启后的健康检查
        log_info "执行重启后的健康检查..."
        if perform_health_check; then
            log_warning "服务已成功重启并恢复正常！"
            return 0
        else
            log_error "服务重启后健康检查仍然失败"
            log_error "重启输出: $restart_output"
            return 1
        fi
    else
        log_error "Docker Compose 重启命令执行失败 (退出码: $restart_exit_code)"
        log_error "错误输出: $restart_output"
        return 1
    fi
}

# 清理函数
cleanup() {
    if [ -n "$LOG_FILE" ] && [ -w "$LOG_FILE" ]; then
        echo "健康检查会话结束: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
        echo "" >> "$LOG_FILE"
    fi
}

# 设置退出时的清理
trap cleanup EXIT

# 主函数
main() {
    # 初始化参数
    init_parameters "$@"
    
    # 检查必需的命令
    check_requirements
    
    # 显示启动信息
    log_info "========================================="
    log_info "Docker Compose 服务健康检查脚本"
    log_info "========================================="
    log_info "Docker Compose 目录: $COMPOSE_DIR"
    log_info "测试 URL: $TEST_URL"
    log_info "日志文件: ${LOG_FILE:-"未设置（仅控制台输出）"}"
    log_info "配置: 最大重试=${MAX_RETRIES}, 超时=${TIMEOUT}秒, 重启等待=${RESTART_WAIT}秒"
    log_info "========================================="
    
    # 执行健康检查
    if perform_health_check; then
        log_info "✓ 服务运行正常，无需重启"
        exit 0
    else
        log_error "服务健康检查失败，需要重启"
        
        # 尝试重启服务
        if restart_docker_compose; then
            log_info "✓ 服务重启流程完成"
            exit 0
        else
            log_error "✗ 服务重启失败或重启后仍不健康"
            exit 1
        fi
    fi
}

# 执行主函数
main "$@"
