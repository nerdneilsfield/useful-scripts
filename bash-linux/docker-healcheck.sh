#!/bin/bash

# Docker Compose 服务健康检查和自动重启脚本
# 用法: ./health_check.sh <docker-compose-directory> <test-url>

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# 显示使用说明
show_usage() {
    echo "使用方法："
    echo "  $0 <docker-compose-directory> <test-url>"
    echo ""
    echo "参数说明："
    echo "  docker-compose-directory : Docker Compose 项目目录路径"
    echo "  test-url                 : 用于健康检查的 URL"
    echo ""
    echo "示例："
    echo "  $0 /opt/myapp http://localhost:8080/health"
    exit 1
}

# 检查参数数量
if [ $# -ne 2 ]; then
    log_error "参数数量错误！需要提供 2 个参数。"
    show_usage
fi

# 获取参数
COMPOSE_DIR="$1"
TEST_URL="$2"

# 配置
MAX_RETRIES=3              # 最大重试次数
RETRY_DELAY=5              # 重试延迟（秒）
TIMEOUT=10                 # HTTP 请求超时时间（秒）
RESTART_WAIT=30            # 重启后等待时间（秒）

# 验证 Docker Compose 目录
if [ ! -d "$COMPOSE_DIR" ]; then
    log_error "目录不存在: $COMPOSE_DIR"
    exit 1
fi

# 检查 docker-compose.yml 或 docker-compose.yaml 文件是否存在
if [ ! -f "$COMPOSE_DIR/docker-compose.yml" ] && [ ! -f "$COMPOSE_DIR/docker-compose.yaml" ]; then
    log_error "在目录 $COMPOSE_DIR 中找不到 docker-compose.yml 或 docker-compose.yaml 文件"
    exit 1
fi

# 检查必要的命令是否存在
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "命令 '$1' 未安装，请先安装该命令"
        exit 1
    fi
}

check_command curl
check_command docker

# 检查 docker compose 命令（支持新版和旧版）
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    log_error "未找到 docker compose 或 docker-compose 命令"
    exit 1
fi

log_info "使用的 Docker Compose 命令: $DOCKER_COMPOSE_CMD"

# 执行健康检查
perform_health_check() {
    local retry_count=0
    local http_code
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        log_info "执行健康检查 (尝试 $((retry_count + 1))/$MAX_RETRIES): $TEST_URL"
        
        # 使用 curl 获取 HTTP 状态码
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout $TIMEOUT --max-time $TIMEOUT "$TEST_URL" 2>/dev/null)
        curl_exit_code=$?
        
        # 检查 curl 命令是否成功执行
        if [ $curl_exit_code -ne 0 ]; then
            log_warning "无法连接到 $TEST_URL (curl 退出码: $curl_exit_code)"
            http_code=0
        fi
        
        log_info "HTTP 状态码: $http_code"
        
        # 检查状态码是否在 200-299 范围内
        if [ "$http_code" -ge 200 ] && [ "$http_code" -le 299 ]; then
            log_info "服务健康检查通过 (HTTP $http_code)"
            return 0
        fi
        
        retry_count=$((retry_count + 1))
        
        if [ $retry_count -lt $MAX_RETRIES ]; then
            log_warning "健康检查失败，$RETRY_DELAY 秒后重试..."
            sleep $RETRY_DELAY
        fi
    done
    
    return 1
}

# 重启 Docker Compose 服务
restart_docker_compose() {
    log_warning "服务健康检查失败，准备重启 Docker Compose 服务..."
    
    # 切换到 Docker Compose 目录
    cd "$COMPOSE_DIR" || {
        log_error "无法切换到目录: $COMPOSE_DIR"
        exit 1
    }
    
    log_info "当前工作目录: $(pwd)"
    
    # 获取服务状态（可选）
    log_info "当前服务状态:"
    $DOCKER_COMPOSE_CMD ps
    
    # 重启服务
    log_info "执行重启命令..."
    if $DOCKER_COMPOSE_CMD restart; then
        log_info "Docker Compose 服务重启命令执行成功"
        
        # 等待服务启动
        log_info "等待 $RESTART_WAIT 秒让服务完全启动..."
        sleep $RESTART_WAIT
        
        # 重新检查服务状态
        log_info "重启后服务状态:"
        $DOCKER_COMPOSE_CMD ps
        
        # 执行重启后的健康检查
        log_info "执行重启后的健康检查..."
        if perform_health_check; then
            log_info "服务重启成功，健康检查通过！"
            return 0
        else
            log_error "服务重启后健康检查仍然失败"
            return 1
        fi
    else
        log_error "Docker Compose 重启命令执行失败"
        return 1
    fi
}

# 主函数
main() {
    log_info "========================================="
    log_info "开始 Docker Compose 服务健康检查"
    log_info "Docker Compose 目录: $COMPOSE_DIR"
    log_info "测试 URL: $TEST_URL"
    log_info "========================================="
    
    # 执行健康检查
    if perform_health_check; then
        log_info "服务运行正常，无需重启"
        exit 0
    else
        log_warning "健康检查失败，需要重启服务"
        if restart_docker_compose; then
            exit 0
        else
            log_error "服务重启失败或重启后仍不健康"
            exit 1
        fi
    fi
}

# 执行主函数
main
