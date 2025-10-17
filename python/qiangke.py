import requests
import time
import configparser
import argparse
import os
from datetime import datetime
import logging
from bs4 import BeautifulSoup, Tag
from typing import Optional, Any, cast



# 从配置文件读取用户名和密码
def read_config(config_file: str):
    config = configparser.ConfigParser()

    if not os.path.exists(config_file):
        print(f"错误：配置文件 {config_file} 不存在")
        exit()

    config.read(config_file, encoding="utf-8")
    

    if "credentials" not in config:
        logging.error("错误：配置文件中缺少 [credentials] 部分")
        exit()

    cred = config["credentials"]
    if "username" not in cred or "password" not in cred:
        logging.error("错误：配置文件中缺少用户名或密码")
        exit()
        
    if "course" not in config:
        logging.error("错误：配置文件中缺少 [course] 部分")
        exit()

    course = config["course"]
    if "name" not in course or "target_time" not in course or "type" not in course:
        logging.error("错误：配置文件中缺少课程名称或抢课开始时间或学期")
        exit()
        
    notice_enable = False
    notice_url = None
    if "notice" not in config:
        logging.warning("未找到通知配置，将不会发送通知")
    else:    
        notice_config = config["notice"]
        if "enable" not in notice_config:
            logging.warning("未找到通知配置，将不会发送通知")
            notice_enable = False
        else:
            notice_enable = notice_config["enable"].strip() == "True"
            notice_url = notice_config["url"].strip() if notice_enable else None

    # 课程时间应该是类似 2025-03-01-15:00:00 这种格式
    try:
        target_time = datetime.strptime(course["target_time"], "%Y-%m-%d-%H:%M:%S").time()
    except ValueError:
        logging.error(f"错误：配置文件中抢课开始时间格式错误, 实际的格式为: {course['target_time']}, 期望的格式为: 2025-03-01-15:00:00")
        exit()

    return cred["username"], cred["password"], course["name"], course["type"], target_time, notice_enable, notice_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

parser = argparse.ArgumentParser(description="双流中学抢课脚本")

parser.add_argument("-c", "--config", type=str, help="配置文件路径")
parser.add_argument("-d", "--dry-run", action="store_true", help="Dry run，跳过选课")

args = parser.parse_args()

if args.config is None:
    print("错误：未提供配置文件路径")
    exit()


# 配置课程信息
username, password, course_name, course_type, target_time, notice_enable, notice_url = read_config(args.config)  # 从配置文件读取用户名和密码


# URL 定义
login_url = "http://xuanke.shuangzhong.com/elective/student/login.php"
course_list_url = "http://xuanke.shuangzhong.com/elective/student/s_course.php"

# 请求头
headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "content-type": "application/x-www-form-urlencoded",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
}

# 登录 payload
login_payload = {"username": username, "password": password, "submit": " 确定 "}

# 课程列表 payload
course_list_payload = {
    # 都转换为 gb2312
    "select": course_type.encode("gb2312"),  # 根据需要调整学期
    "key": course_name.encode("gb2312"),  # 可选，搜索关键词
    "Submit": " 查询 ".encode("gb2312"),
}

# 创建会话
session = requests.Session()

def post_message(message, enable, url):
    print(f"post_message: {message}, {enable}, {url}")
    if not enable:
        return
    if url is None:
        return
    url = url.strip('"').strip("'")
    resp = requests.post(url, json={"msg": message})
    if resp.status_code != 200:
        logging.error("发送消息失败")
        exit()
    logging.info(f"发送消息成功: {resp.text}")

# 登录函数
def login():
    response = session.post(login_url, data=login_payload, headers=headers)
    if response.status_code == 200:
        # 当前输出的格式是 gb2312, 需要转换为 utf-8
        response.encoding = "gb2312"
        if "注销" in response.text:
            post_message("登录成功", notice_enable, notice_url)
            logging.info(f"登录成功, 当前 cookie: {session.cookies}")
        else:
            logging.error("登录失败")
            post_message("登录失败", notice_enable, notice_url)
            exit()
    else:
        logging.error("登录失败")
        post_message("登录失败", notice_enable, notice_url)
        exit()

# 获取课程 URL
def get_course_url():
    # response = session.get(course_list_url, headers=headers)
    response = session.post(course_list_url, data=course_list_payload, headers=headers)
    if response.status_code != 200:
        post_message("获取课程列表失败", notice_enable, notice_url)
        logging.error("获取课程列表失败")
        exit()

    # 当前输出的格式是 gb2312, 需要转换为 utf-8
    response.encoding = "gb2312"
    text = response.text.encode("utf-8").decode("utf-8")
    # print(text)
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table")
    if not table:
        post_message("error: 未找到课程表格", notice_enable, notice_url)
        logging.error("未找到课程表格")
        exit()

    try:
        # 使用类型断言告诉类型检查器这是一个 Tag 对象
        table_tag = cast(Tag, table)
        rows = table_tag.find_all("tr")[1:]  # 跳过表头
        for row in rows:
            try:
                row_tag = cast(Tag, row)
                cols = row_tag.find_all("td")
                if len(cols) > 1:
                    # logging.info(f"课程行: {cols}")
                    logging.info(f"课程名称: {cols[1].text.strip()}")
                    if cols[1].text.strip() == course_name:
                        # 找到第12列的 a 标签
                        # post_message(f"找到课程: {course_name}, 第12列: {cols[12]}", notice_enable, notice_url)
                        logging.info(f"找到课程: {course_name}, 第12列: {cols[12]}")
                        try:
                            course_link = cast(Tag, cols[12]).find("a")
                            if course_link and isinstance(course_link, Tag) and "href" in course_link.attrs:
                                if course_link.text.strip() == "选择":
                                    full_url = f"http://xuanke.shuangzhong.com/elective/student/{course_link['href']}"
                                    # post_message(f"找到课程 {course_name}，选课 URL: {full_url}", notice_enable, notice_url)
                                    logging.info(f"找到课程 {course_name}，选课 URL: {full_url}")
                                    return full_url
                                elif course_link.text.strip() == "取消":
                                    # post_message(f"课程 {course_name} 已选，直接退出", notice_enable, notice_url)
                                    logging.info(f"课程 {course_name} 已选，直接退出")
                                    exit()
                        except Exception as e:
                            logging.warning(f"操作行的: {cols[12]}")
                            logging.warning(f"还没到抢课时间, {e}")
                            post_message(f"还没到抢课时间, {e}", notice_enable, notice_url)
                            continue
            except Exception as e:
                post_message(f"处理课程行时出错: {e}", notice_enable, notice_url)
                logging.warning(f"处理课程行时出错: {e}")
                continue
    except Exception as e:
        post_message(f"解析表格时出错: {e}", notice_enable, notice_url)
        logging.error(f"解析表格时出错: {e}")
    
    post_message(f"未找到课程 {course_name}", notice_enable, notice_url)
    logging.error(f"未找到课程 {course_name}")
    return None

# 抢课函数
def select_course(course_url):
    response = session.get(course_url, headers=headers)
    if response.status_code == 200:
        response.encoding = "gb2312"
        if "选择课程成功" in response.text:
            post_message(f"抢课成功！{course_name} @ {time.strftime('%H:%M:%S')}", notice_enable, notice_url)
            print(f"[{time.strftime('%H:%M:%S')}] 抢课成功！")
            exit()
        else:
            post_message(f"抢课失败，状态码: {response.text} @ {time.strftime('%H:%M:%S')}", notice_enable, notice_url)
            print(f"[{time.strftime('%H:%M:%S')}] 抢课失败，状态码: {response.text}")
            return response.text
    else:
        post_message(f"抢课失败，状态码: {response.status_code} @ {time.strftime('%H:%M:%S')}", notice_enable, notice_url)
        print(f"[{time.strftime('%H:%M:%S')}] 抢课失败，状态码: {response.status_code}")
        return f"HTTP错误: {response.status_code}"


# 精确定时触发函数
def precise_timer(target_tim, dry_run=False):
    post_message(f"等待到 {target_time} 触发抢课...", notice_enable, notice_url)
    print(f"等待到 {target_time} 触发抢课...")
    count = 0
    while True:
        now = datetime.now().time()
        if now >= target_time:
            # 添加重试机制获取课程 URL
            max_url_retries = 5
            for url_attempt in range(1, max_url_retries + 1):
                try:
                    course_url = get_course_url()
                    if course_url != None and course_url != "":
                        break
                except Exception as e:
                    post_message(f"第 {url_attempt} 次获取课程 URL 失败: {e}", notice_enable, notice_url)
                    logging.warning(f"第 {url_attempt} 次获取课程 URL 失败: {e}")
                    if url_attempt < max_url_retries:
                        retry_wait = 0.5 * url_attempt
                        #post_message(f"等待 {retry_wait} 秒后重试...", notice_enable, notice_url)
                        logging.info(f"等待 {retry_wait} 秒后重试...")
                        time.sleep(retry_wait)
                    else:
                        post_message("获取课程 URL 达到最大重试次数，抢课失败", notice_enable, notice_url)
                        logging.error("获取课程 URL 达到最大重试次数，抢课失败")
                        return
            
            # 添加重试机制进行选课
            max_select_retries = 10
            for select_attempt in range(1, max_select_retries + 1):
                try:
                    if dry_run:
                        post_message("Dry run，跳过选课", notice_enable, notice_url)
                        logging.info("Dry run，跳过选课")
                        return
                    #post_message(f"第 {select_attempt} 次尝试选课", notice_enable, notice_url)
                    logging.info(f"第 {select_attempt} 次尝试选课")
                    select_result = select_course(course_url)
                    if "成功" in select_result:
                        logging.info("抢课成功！")
                        return
                    else:
                        logging.warning(f"选课返回: {select_result}")
                except Exception as e:
                    logging.warning(f"第 {select_attempt} 次选课出错: {e}")
                
                if select_attempt < max_select_retries:
                    retry_wait = 0.3 * select_attempt
                    post_message(f"等待 {retry_wait} 秒后重试选课...", notice_enable, notice_url)
                    logging.info(f"等待 {retry_wait} 秒后重试选课...")
                    time.sleep(retry_wait)
                else:
                    post_message("选课达到最大重试次数，抢课失败", notice_enable, notice_url)
                    logging.error("选课达到最大重试次数，抢课失败")
            
            break
        time.sleep(0.1)  # 每0.1秒检查一次时间，确保精确触发
        count += 1
        if count % 10 == 0:
            print(f"[{time.strftime('%H:%M:%S')}] 等待到 {target_time} 触发抢课...")


# 主流程
def main():
    login()  # 提前登录
    precise_timer(target_time, args.dry_run)  # 等待目标时间并触发抢课


if __name__ == "__main__":
    main()
