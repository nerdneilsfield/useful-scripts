#!/usr/bin/env python3
"""
双流中学抢课脚本
支持自动登录、精确定时抢课、重试机制和通知功能
"""

import argparse
import configparser
import logging
import os
import time
from datetime import datetime, time as time_obj
from typing import Optional, Dict, Any, Tuple

import requests
from bs4 import BeautifulSoup, Tag
from requests import Session


# 常量定义
BASE_URL = "http://xuanke.shuangzhong.com/elective/student"
LOGIN_URL = f"{BASE_URL}/login.php"
COURSE_LIST_URL = f"{BASE_URL}/s_course.php"

DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "content-type": "application/x-www-form-urlencoded",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
}

# 重试配置
MAX_URL_RETRIES = 5
MAX_SELECT_RETRIES = 10


class ConfigError(Exception):
    """配置错误异常"""
    pass


class CourseSelector:
    """选课器主类"""
    
    def __init__(self, config_file: str, dry_run: bool = False):
        """
        初始化选课器
        
        Args:
            config_file: 配置文件路径
            dry_run: 是否为测试模式（不实际选课）
        """
        self.config_file = config_file
        self.dry_run = dry_run
        self.session: Optional[Session] = None
        self.config: Dict[str, Any] = {}
        
        # 初始化日志
        self._setup_logging()
        
        # 加载配置
        self._load_config()
        
        # 初始化会话
        self.session = requests.Session()
    
    def _setup_logging(self) -> None:
        """配置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )
    
    def _load_config(self) -> None:
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            raise ConfigError(f"配置文件 {self.config_file} 不存在")
        
        config = configparser.ConfigParser()
        config.read(self.config_file, encoding="utf-8")
        
        # 验证并读取凭证配置
        if "credentials" not in config:
            raise ConfigError("配置文件中缺少 [credentials] 部分")
        
        cred = config["credentials"]
        required_creds = ["username", "password"]
        for field in required_creds:
            if field not in cred:
                raise ConfigError(f"配置文件中缺少 {field}")
        
        self.config["username"] = cred["username"]
        self.config["password"] = cred["password"]
        
        # 验证并读取课程配置
        if "course" not in config:
            raise ConfigError("配置文件中缺少 [course] 部分")
        
        course = config["course"]
        required_course = ["name", "target_time", "type"]
        for field in required_course:
            if field not in course:
                raise ConfigError(f"配置文件中缺少 {field}")
        
        self.config["course_name"] = course["name"]
        self.config["course_type"] = course["type"]
        
        # 解析目标时间
        try:
            target_time = datetime.strptime(course["target_time"], "%Y-%m-%d-%H:%M:%S").time()
            self.config["target_time"] = target_time
        except ValueError as e:
            raise ConfigError(
                f"配置文件中抢课开始时间格式错误, "
                f"实际格式: {course['target_time']}, "
                f"期望格式: 2025-03-01-15:00:00, "
                f"错误: {e}"
            )
        
        # 读取通知配置（可选）
        self.config["notice_enable"] = False
        self.config["notice_url"] = None
        
        if "notice" in config:
            notice_config = config["notice"]
            if "enable" in notice_config and "url" in notice_config:
                self.config["notice_enable"] = notice_config["enable"].strip() == "True"
                if self.config["notice_enable"]:
                    self.config["notice_url"] = notice_config["url"].strip()
            
            if not self.config["notice_enable"]:
                logging.warning("未启用通知配置")
    
    def _send_notification(self, message: str) -> None:
        """发送通知"""
        if not self.config["notice_enable"] or not self.config["notice_url"]:
            logging.info(f"[通知] {message}")
            return
        
        try:
            url = self.config["notice_url"].strip('"').strip("'")
            response = requests.post(url, json={"msg": message}, timeout=5)
            if response.status_code == 200:
                logging.info(f"发送通知成功: {response.text}")
            else:
                logging.warning(f"发送通知失败，状态码: {response.status_code}")
        except requests.RequestException as e:
            logging.error(f"发送通知时出错: {e}")
    
    def login(self) -> bool:
        """
        登录系统
        
        Returns:
            是否登录成功
        """
        if not self.session:
            logging.error("会话未初始化")
            return False
        
        payload = {
            "username": self.config["username"],
            "password": self.config["password"],
            "submit": " 确定 "
        }
        
        try:
            response = self.session.post(LOGIN_URL, data=payload, headers=DEFAULT_HEADERS)
            response.encoding = "gb2312"
            
            if response.status_code == 200 and "注销" in response.text:
                logging.info(f"登录成功, Cookie: {dict(self.session.cookies)}")
                self._send_notification("登录成功")
                return True
            else:
                logging.error("登录失败，响应中未找到登录标识")
                self._send_notification("登录失败")
                return False
        except requests.RequestException as e:
            logging.error(f"登录请求失败: {e}")
            self._send_notification("登录失败")
            return False
    
    def _get_course_url(self) -> Optional[str]:
        """
        获取课程选课 URL
        
        Returns:
            选课 URL，如果未找到则返回 None
        """
        if not self.session:
            return None
        
        payload = {
            "select": self.config["course_type"].encode("gb2312"),
            "key": self.config["course_name"].encode("gb2312"),
            "Submit": " 查询 ".encode("gb2312"),
        }
        
        try:
            response = self.session.post(COURSE_LIST_URL, data=payload, headers=DEFAULT_HEADERS)
            if response.status_code != 200:
                logging.error("获取课程列表失败")
                self._send_notification("获取课程列表失败")
                return None
            
            response.encoding = "gb2312"
            text = response.text.encode("utf-8").decode("utf-8")
            soup = BeautifulSoup(text, "html.parser")
            table = soup.find("table")
            
            if not table:
                logging.error("未找到课程表格")
                self._send_notification("未找到课程表格")
                return None
            
            # 解析表格
            table_tag = cast(Tag, table)
            rows = table_tag.find_all("tr")[1:]  # 跳过表头
            
            for row in rows:
                try:
                    row_tag = cast(Tag, row)
                    cols = row_tag.find_all("td")
                    
                    if len(cols) <= 12:
                        continue
                    
                    course_name = cols[1].text.strip()
                    logging.info(f"发现课程: {course_name}")
                    
                    if course_name == self.config["course_name"]:
                        action_col = cast(Tag, cols[12])
                        course_link = action_col.find("a")
                        
                        if course_link and isinstance(course_link, Tag) and "href" in course_link.attrs:
                            action = course_link.text.strip()
                            
                            if action == "取消":
                                logging.info(f"课程 {self.config['course_name']} 已选")
                                self._send_notification(f"课程 {self.config['course_name']} 已选")
                                exit()
                            elif action == "选择":
                                full_url = f"{BASE_URL}/{course_link['href']}"
                                logging.info(f"找到选课 URL: {full_url}")
                                self._send_notification(f"找到课程 {self.config['course_name']}")
                                return full_url
                except Exception as e:
                    logging.warning(f"处理课程行时出错: {e}")
                    continue
            
            logging.error(f"未找到课程 {self.config['course_name']}")
            self._send_notification(f"未找到课程 {self.config['course_name']}")
            return None
            
        except Exception as e:
            logging.error(f"获取课程 URL 时出错: {e}")
            self._send_notification(f"获取课程 URL 失败: {e}")
            return None
    
    def _select_course(self, course_url: str) -> bool:
        """
        执行选课操作
        
        Args:
            course_url: 选课 URL
            
        Returns:
            是否选课成功
        """
        if not self.session:
            return False
        
        try:
            response = self.session.get(course_url, headers=DEFAULT_HEADERS)
            response.encoding = "gb2312"
            
            if response.status_code == 200:
                if "选择课程成功" in response.text:
                    timestamp = time.strftime('%H:%M:%S')
                    message = f"抢课成功！{self.config['course_name']} @ {timestamp}"
                    logging.info(message)
                    self._send_notification(message)
                    return True
                else:
                    timestamp = time.strftime('%H:%M:%S')
                    logging.warning(f"抢课失败，响应: {response.text[:100]} @ {timestamp}")
                    return False
            else:
                timestamp = time.strftime('%H:%M:%S')
                logging.warning(f"抢课失败，状态码: {response.status_code} @ {timestamp}")
                return False
                
        except requests.RequestException as e:
            timestamp = time.strftime('%H:%M:%S')
            logging.error(f"选课请求失败: {e} @ {timestamp}")
            return False
    
    def _wait_and_select(self) -> bool:
        """
        等待目标时间并执行选课
        
        Returns:
            是否选课成功
        """
        target_time = self.config["target_time"]
        logging.info(f"等待到 {target_time} 触发抢课...")
        self._send_notification(f"等待到 {target_time} 触发抢课...")
        
        while True:
            now = datetime.now().time()
            
            if now >= target_time:
                # 获取课程 URL（带重试）
                course_url = None
                for attempt in range(1, MAX_URL_RETRIES + 1):
                    try:
                        logging.info(f"尝试获取课程 URL ({attempt}/{MAX_URL_RETRIES})")
                        course_url = self._get_course_url()
                        if course_url:
                            break
                    except Exception as e:
                        logging.warning(f"第 {attempt} 次获取课程 URL 失败: {e}")
                    
                    if attempt < MAX_URL_RETRIES:
                        retry_wait = 0.5 * attempt
                        logging.info(f"等待 {retry_wait} 秒后重试...")
                        time.sleep(retry_wait)
                
                if not course_url:
                    self._send_notification("获取课程 URL 失败，抢课终止")
                    logging.error("获取课程 URL 失败，抢课终止")
                    return False
                
                # 执行选课（带重试）
                if self.dry_run:
                    self._send_notification("Dry run 模式，跳过实际选课")
                    logging.info("Dry run 模式，跳过实际选课")
                    return True
                
                for attempt in range(1, MAX_SELECT_RETRIES + 1):
                    try:
                        logging.info(f"尝试选课 ({attempt}/{MAX_SELECT_RETRIES})")
                        if self._select_course(course_url):
                            return True
                    except Exception as e:
                        logging.warning(f"第 {attempt} 次选课出错: {e}")
                    
                    if attempt < MAX_SELECT_RETRIES:
                        retry_wait = 0.3 * attempt
                        logging.info(f"等待 {retry_wait} 秒后重试...")
                        time.sleep(retry_wait)
                
                self._send_notification("选课达到最大重试次数，抢课失败")
                logging.error("选课达到最大重试次数，抢课失败")
                return False
            
            time.sleep(0.1)  # 每 0.1 秒检查一次
    
    def run(self) -> bool:
        """
        运行选课流程
        
        Returns:
            是否成功完成选课
        """
        # 登录
        if not self.login():
            return False
        
        # 等待并选课
        return self._wait_and_select()


def parse_arguments() -> Tuple[str, bool]:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="双流中学抢课脚本 - 自动登录并精确定时抢课"
    )
    parser.add_argument(
        "-c", "--config",
        type=str,
        required=True,
        help="配置文件路径"
    )
    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        help="测试模式，跳过实际选课"
    )
    
    args = parser.parse_args()
    return args.config, args.dry_run


def main() -> None:
    """主函数"""
    try:
        config_file, dry_run = parse_arguments()
        
        # 创建选课器实例
        selector = CourseSelector(config_file, dry_run)
        
        # 运行选课流程
        success = selector.run()
        
        if not success:
            exit(1)
            
    except ConfigError as e:
        logging.error(f"配置错误: {e}")
        exit(1)
    except KeyboardInterrupt:
        logging.info("用户中断")
        exit(0)
    except Exception as e:
        logging.error(f"未知错误: {e}", exc_info=True)
        exit(1)


if __name__ == "__main__":
    main()
