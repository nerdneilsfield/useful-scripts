#!/usr/bin/env bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH
# --------------------------------------------------------------
#	项目: CloudflareSpeedTest 自动更新 Hosts (增强版)
#	版本: 2.0.0
#	作者: Enhanced by Claude
#	说明: 支持多IP负载均衡，从前N个速度相近的IP中随机选择
# --------------------------------------------------------------

# 默认配置
NOWIP_FILE="nowip_hosts.txt"
CFST_BIN="./cfst"
TOP_N=3
THRESHOLD_M=10  # 速度差值阈值（单位与cfst输出一致，通常是Mbps或ms）
CFST_ARGS=()    # 传递给 CFST 的额外参数

# 显示使用说明
_USAGE() {
    cat << EOF
用法: $0 [选项] [-- CFST参数...]

选项:
    -n, --nowip <文件路径>     指定保存当前IP的文件 (默认: nowip_hosts.txt)
    -c, --cfst <执行文件>      指定CFST执行文件路径 (默认: ./cfst)
    -t, --top <数量>           选择前N个最快的IP (默认: 3)
    -m, --threshold <值>       速度差值阈值 (默认: 10)
    -h, --help                 显示此帮助信息
    --                         之后的参数将直接传递给CFST

示例:
    # 基础用法
    $0 -n /path/to/nowip.txt -c /usr/local/bin/cfst -t 5 -m 20

    # 传递参数给CFST（在 -- 之后）
    $0 -t 3 -m 10 -- -n 200 -t 4 -sl 5.0
    # 等价于执行: cfst -o result_hosts.txt -n 200 -t 4 -sl 5.0

    # 更复杂的例子
    $0 -c /usr/bin/cfst -t 5 -- -n 500 -t 10 -dn 20 -tl 300 -sl 10

常用CFST参数:
    -n          测速次数 (默认10次)
    -t          延迟测速线程数 (默认200)
    -dn         下载测速数量 (默认10)
    -dt         下载测速时间 (秒, 默认10)
    -tp         端口 (默认443)
    -tl         延迟上限 (ms, 默认9999)
    -tll        延迟下限 (ms, 默认0)
    -sl         下载速度下限 (MB/s)
    -p          指定端口 (可重复)

说明:
    - 脚本会从前N个IP中筛选速度差距小于M的IP
    - 然后将hosts中所有使用旧IP的条目均匀分配给新IP
    - 实现简单的负载均衡效果
EOF
    exit 0
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--nowip)
            NOWIP_FILE="$2"
            shift 2
            ;;
        -c|--cfst)
            CFST_BIN="$2"
            shift 2
            ;;
        -t|--top)
            TOP_N="$2"
            shift 2
            ;;
        -m|--threshold)
            THRESHOLD_M="$2"
            shift 2
            ;;
        -h|--help)
            _USAGE
            ;;
        --)
            # 之后的所有参数传递给 CFST
            shift
            CFST_ARGS=("$@")
            break
            ;;
        *)
            echo "未知参数: $1"
            echo "提示: 如果要传递参数给CFST，请在参数前加 --"
            echo "例如: $0 -t 3 -- -n 200 -sl 5"
            _USAGE
            ;;
    esac
done

# 检查 CFST 是否存在
_CHECK_CFST() {
    if [[ ! -x "${CFST_BIN}" ]]; then
        echo "错误: 找不到CFST执行文件: ${CFST_BIN}"
        echo "请使用 -c 参数指定正确的路径，或确保文件存在且可执行"
        exit 1
    fi
}

# 初始化检查
_CHECK() {
    while true; do
        if [[ ! -e "${NOWIP_FILE}" ]]; then
            echo -e "该脚本的作用为 CFST 测速后获取最快 IP 并替换 Hosts 中的 Cloudflare CDN IP。"
            echo -e "使用前请先阅读：https://github.com/XIU2/CloudflareSpeedTest/issues/42#issuecomment-768273848\n"
            echo -e "第一次使用，请输入当前 Hosts 中所有 Cloudflare CDN IP（每行一个）："
            echo -e "输入完成后，输入空行结束\n"

            > "${NOWIP_FILE}"
            while true; do
                read -e -p "输入 IP（或直接回车结束）: " IP
                if [[ -z "${IP}" ]]; then
                    break
                fi
                # 简单验证IP格式
                if [[ ${IP} =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
                    echo "${IP}" >> "${NOWIP_FILE}"
                    echo "已添加: ${IP}"
                else
                    echo "警告: IP格式不正确，请重新输入"
                fi
            done

            if [[ ! -s "${NOWIP_FILE}" ]]; then
                echo "错误: 至少需要输入一个IP！"
                rm -f "${NOWIP_FILE}"
            else
                echo -e "\n已保存 $(wc -l < ${NOWIP_FILE}) 个IP到 ${NOWIP_FILE}"
                break
            fi
        else
            echo "发现现有IP配置文件: ${NOWIP_FILE}"
            echo "当前使用的IP列表:"
            cat -n "${NOWIP_FILE}"
            break
        fi
    done
}

# 从结果中筛选满足条件的IP
_SELECT_IPS() {
    local result_file="$1"
    local selected_ips=()

    # 跳过第一行表头，读取数据
    local line_num=0
    local fastest_speed=""

    while IFS=, read -r ip speed latency _; do
        ((line_num++))

        # 跳过表头
        [[ ${line_num} -eq 1 ]] && continue

        # 只考虑前 TOP_N 个
        if [[ ${line_num} -gt $((TOP_N + 1)) ]]; then
            break
        fi

        # 记录最快速度
        if [[ -z "${fastest_speed}" ]]; then
            fastest_speed="${speed}"
        fi

        # 计算速度差值（使用bc进行浮点数运算）
        local speed_diff=$(echo "${fastest_speed} - ${speed}" | bc 2>/dev/null || echo "0")

        # 如果差值小于阈值，加入候选列表
        # 注意：这里假设速度越大越好（下载速度），如果是延迟则需要反过来
        local threshold_check=$(echo "${speed_diff} <= ${THRESHOLD_M}" | bc 2>/dev/null || echo "1")

        if [[ "${threshold_check}" -eq 1 ]]; then
            selected_ips+=("${ip}")
            echo "  ✓ ${ip} (速度: ${speed}, 与最快差距: ${speed_diff})"
        else
            echo "  ✗ ${ip} (速度: ${speed}, 与最快差距: ${speed_diff}, 超过阈值)"
        fi
    done < "${result_file}"

    # 返回选中的IP列表（通过输出）
    printf '%s\n' "${selected_ips[@]}"
}

# 主更新流程
_UPDATE() {
    echo -e "\n=========================================="
    echo "开始测速..."
    echo "=========================================="

    # 读取当前IP池
    mapfile -t OLD_IPS < "${NOWIP_FILE}"
    echo "当前IP池包含 ${#OLD_IPS[@]} 个IP: ${OLD_IPS[*]}"

    # 执行CFST测速
    if [[ ${#CFST_ARGS[@]} -gt 0 ]]; then
        echo -e "\n执行测速命令: ${CFST_BIN} -o result_hosts.txt ${CFST_ARGS[*]}"
        "${CFST_BIN}" -o "result_hosts.txt" "${CFST_ARGS[@]}"
    else
        echo -e "\n执行测速命令: ${CFST_BIN} -o result_hosts.txt"
        "${CFST_BIN}" -o "result_hosts.txt"
    fi

    # 检查结果文件
    if [[ ! -e "result_hosts.txt" ]] || [[ ! -s "result_hosts.txt" ]]; then
        echo "错误: CFST 测速结果为空，跳过更新..."
        exit 0
    fi

    # 显示结果文件前几行
    echo -e "\n测速结果预览:"
    head -$((TOP_N + 1)) result_hosts.txt

    # 筛选满足条件的IP
    echo -e "\n=========================================="
    echo "筛选前 ${TOP_N} 个且速度差距小于 ${THRESHOLD_M} 的IP:"
    echo "=========================================="

    mapfile -t NEW_IPS < <(_SELECT_IPS "result_hosts.txt")

    if [[ ${#NEW_IPS[@]} -eq 0 ]]; then
        echo -e "\n错误: 没有找到满足条件的IP，跳过更新..."
        exit 0
    fi

    echo -e "\n共筛选出 ${#NEW_IPS[@]} 个符合条件的新IP: ${NEW_IPS[*]}"

    # 分析 hosts 文件中使用旧IP的条目
    echo -e "\n=========================================="
    echo "分析 /etc/hosts 文件..."
    echo "=========================================="

    # 创建正则表达式匹配所有旧IP
    local old_ip_pattern=$(IFS='|'; echo "${OLD_IPS[*]}")

    # 找出所有使用旧IP的行号
    local temp_matches=$(mktemp)
    grep -n -E "^[[:space:]]*(${old_ip_pattern})[[:space:]]" /etc/hosts > "${temp_matches}" || true

    local total_entries=$(wc -l < "${temp_matches}")

    if [[ ${total_entries} -eq 0 ]]; then
        echo "警告: 在 hosts 文件中没有找到使用旧IP的条目"
        rm -f "${temp_matches}"
        exit 0
    fi

    echo "找到 ${total_entries} 个使用旧IP的条目"
    echo -e "\n当前条目预览:"
    head -5 "${temp_matches}"
    [[ ${total_entries} -gt 5 ]] && echo "... (还有 $((total_entries - 5)) 个条目)"

    # 计算每个新IP应该分配多少个条目
    local new_ip_count=${#NEW_IPS[@]}
    local base_count=$((total_entries / new_ip_count))
    local remainder=$((total_entries % new_ip_count))

    echo -e "\n=========================================="
    echo "分配策略:"
    echo "=========================================="
    echo "总条目数: ${total_entries}"
    echo "新IP数量: ${new_ip_count}"
    echo "基础分配: 每个IP ${base_count} 个条目"
    [[ ${remainder} -gt 0 ]] && echo "余数分配: 前 ${remainder} 个IP各多分配1个"

    # 为每个新IP计算分配数量
    declare -a allocation_count
    for ((i=0; i<new_ip_count; i++)); do
        if [[ $i -lt ${remainder} ]]; then
            allocation_count[$i]=$((base_count + 1))
        else
            allocation_count[$i]=${base_count}
        fi
        echo "  ${NEW_IPS[$i]} -> ${allocation_count[$i]} 个条目"
    done

    # 备份 Hosts 文件
    if [[ "${DRY_RUN}" == true ]]; then
        echo -e "\n=========================================="
        echo "【干运行模式】跳过备份和实际修改"
        echo "=========================================="
    else
        echo -e "\n备份 Hosts 文件..."
        \cp -f /etc/hosts "/etc/hosts_backup_$(date +%Y%m%d_%H%M%S)"
    fi

    # 开始替换
    echo -e "\n=========================================="
    if [[ "${DRY_RUN}" == true ]]; then
        echo "【预览】将要进行的替换操作:"
    else
        echo "开始替换 hosts 条目..."
    fi
    echo "=========================================="

    # 读取需要替换的所有行
    mapfile -t match_lines < "${temp_matches}"

    # 打乱顺序以实现随机分配
    local shuffled_lines=($(shuf -e "${!match_lines[@]}"))

    # 创建临时文件或准备预览数据
    local temp_hosts=$(mktemp)
    cp /etc/hosts "${temp_hosts}"

    # 用于存储预览信息
    declare -A preview_changes

    # 按分配计划替换IP
    local line_idx=0
    for ((ip_idx=0; ip_idx<new_ip_count; ip_idx++)); do
        local new_ip="${NEW_IPS[$ip_idx]}"
        local count="${allocation_count[$ip_idx]}"

        if [[ "${DRY_RUN}" == true ]]; then
            echo -e "\n分配给 ${new_ip} 的条目 (${count} 个):"
        else
            echo "正在分配 ${new_ip} (${count} 个条目)..."
        fi

        for ((c=0; c<count; c++)); do
            if [[ ${line_idx} -ge ${#shuffled_lines[@]} ]]; then
                break
            fi

            # 获取原始行内容
            local array_idx=${shuffled_lines[$line_idx]}
            local line_info="${match_lines[$array_idx]}"
            local line_num=$(echo "${line_info}" | cut -d: -f1)
            local line_content=$(echo "${line_info}" | cut -d: -f2-)

            # 提取旧IP和域名部分
            local old_ip=$(echo "${line_content}" | grep -oE "^[[:space:]]*[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | tr -d '[:space:]')
            local domain_part=$(echo "${line_content}" | sed -E "s/^[[:space:]]*(${old_ip_pattern})[[:space:]]+//")

            # 新的行内容
            local new_line="${new_ip} ${domain_part}"

            if [[ "${DRY_RUN}" == true ]]; then
                # 预览模式：显示详细的变更信息
                echo "  [$((c+1))/${count}] 行 ${line_num}:"
                echo "      旧: ${old_ip} ${domain_part}"
                echo "      新: ${new_line}"
            else
                # 实际替换该行
                sed -i "${line_num}s|.*|${new_line}|" "${temp_hosts}"
            fi

            ((line_idx++))
        done
    done

    if [[ "${DRY_RUN}" == true ]]; then
        # 干运行模式：清理临时文件，不应用更改
        rm -f "${temp_hosts}"

        echo -e "\n=========================================="
        echo "【预览】将要更新的 nowip_hosts.txt:"
        echo "=========================================="
        echo "当前内容:"
        cat -n "${NOWIP_FILE}"
        echo -e "\n将要替换为:"
        printf '%s\n' "${NEW_IPS[@]}" | cat -n

        echo -e "\n=========================================="
        echo "【干运行模式】预览完成"
        echo "=========================================="
        echo "提示: 移除 --dry-run 参数以实际执行更改"

    else
        # 实际模式：应用更改
        mv "${temp_hosts}" /etc/hosts

        # 更新 nowip_hosts.txt 为新的IP池
        printf '%s\n' "${NEW_IPS[@]}" > "${NOWIP_FILE}"

        echo -e "\n=========================================="
        echo "更新完成！"
        echo "=========================================="
        echo "新的IP池:"
        cat -n "${NOWIP_FILE}"

        # 验证替换结果
        echo -e "\n验证替换结果 (每个IP的使用情况):"
        for ip in "${NEW_IPS[@]}"; do
            local count=$(grep -c "^${ip}[[:space:]]" /etc/hosts || echo "0")
            echo "  ${ip}: ${count} 个条目"
        done

        echo -e "\nHosts 中新IP条目预览:"
        local new_ip_pattern=$(IFS='|'; echo "${NEW_IPS[*]}")
        grep -E "^(${new_ip_pattern})[[:space:]]" /etc/hosts | head -10
        [[ $(grep -c -E "^(${new_ip_pattern})[[:space:]]" /etc/hosts) -gt 10 ]] && echo "..."
    fi

    # 清理临时文件
    rm -f "${temp_matches}"
}

# 主程序
main() {
    echo "CloudflareSpeedTest Hosts 更新工具 (增强版)"
    echo "配置: nowip文件=${NOWIP_FILE}, cfst=${CFST_BIN}, top=${TOP_N}, 阈值=${THRESHOLD_M}"

    if [[ ${#CFST_ARGS[@]} -gt 0 ]]; then
        echo "CFST参数: ${CFST_ARGS[*]}"
    fi
    echo ""

    _CHECK_CFST
    _CHECK
    _UPDATE
}

main
