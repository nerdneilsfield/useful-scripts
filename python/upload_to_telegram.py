import argparse
import asyncio
import json
import random
import zipfile
from io import BytesIO
import os
import logging
import configparser
from pathlib import Path
from functools import wraps
import time

import requests

import aiohttp
from aiohttp import FormData
import tqdm

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".bmp")


def load_config(config_path):
    """加载INI配置文件"""
    config = configparser.ConfigParser()
    config.read(config_path)

    api_urls = config.get(
        "Telegram", "api_url", fallback="https://api.telegram.org"
    ).split(",")
    tokens = []
    for section in config.sections():
        if section.startswith("Token"):
            tokens.append(
                {
                    "name": config.get(section, "name"),
                    "id": config.get(section, "id"),
                    "token": config.get(section, "token"),
                }
            )

    logging.info(f"加载配置文件完成: {len(tokens)} 个 token")
    logging.info(f"加载配置文件完成: {len(api_urls)} 个 url")
    for api_url in api_urls:
        logging.info(f"\tapi_url: {api_url}")
    return api_urls, [token["token"] for token in tokens]


class UrlPool:
    def __init__(self, urls):
        """
        初始化URL池
        :param urls: API URL列表
        """
        self.urls = []
        urls = [url.strip() for url in urls]
        for url in urls:
            if not url.startswith("https://"):
                url = f"https://{url}"
            if url.endswith("/"):
                url = url.rstrip("/")
            self.urls.append(url)
        self.working_urls = [{"url": url, "count": 0} for url in self.urls]
        logging.info(f"初始化 API URL 池: {len(self.urls)} 个 URL")

    def get_url(self):
        """获取使用次数最少的URL"""
        if not self.working_urls:
            return None

        # 找到最低使用次数
        min_count = min(u["count"] for u in self.working_urls)
        # 收集所有最低使用次数的URL
        candidates = [u for u in self.working_urls if u["count"] == min_count]
        # 随机选择一个
        selected = random.choice(candidates)
        return selected["url"]

    def increment_url(self, url_str):
        """增加指定URL的使用计数"""
        for url in self.working_urls:
            if url["url"] == url_str:
                url["count"] += 1
                break

    def remove_url(self, url_str):
        """移除指定URL"""
        self.working_urls = [u for u in self.working_urls if u["url"] != url_str]
        logging.info(f"移除 URL {url_str}，剩余 URL 数量: {len(self.working_urls)}")


class TokenPool:
    def __init__(self, url_pool, tokens):
        self.url_pool = url_pool
        self.tokens = [token.strip() for token in tokens]
        self.working_tokens = []  # 现在存储字典格式 [{"token": str, "count": int}, ...]
        self.current_index = 0
        logging.info(f"初始化 token 池: {len(self.tokens)} 个 token")
        self.test_tokens()
        logging.info(f"测试 token 池完成: {len(self.working_tokens)} 个有效 token")

    def test_tokens(self):
        for token in tqdm.tqdm(self.tokens):
            url = self.url_pool.get_url()
            if test_token(url, token):
                logging.info(f"token {token} 测试成功")
                self.working_tokens.append(
                    {"token": token, "count": 0}
                )  # 初始化计数为0
            else:
                logging.error(f"token {token} 测试失败")
            self.url_pool.increment_url(url)

    def get_token(self):
        if not self.working_tokens:
            return None

        # 找到最低使用次数
        min_count = min(t["count"] for t in self.working_tokens)
        # 收集所有最低使用次数的token
        candidates = [t for t in self.working_tokens if t["count"] == min_count]
        # 随机选择一个
        selected = random.choice(candidates)
        return selected["token"]

    def increment_token(self, token_str):
        """增加指定token的使用计数"""
        for token in self.working_tokens:
            if token["token"] == token_str:
                token["count"] += 1
                break

    def remove_token(self, token_str):
        """移除指定token"""
        self.working_tokens = [
            t for t in self.working_tokens if t["token"] != token_str
        ]
        logging.info(
            f"移除 token {token_str}，剩余 token 数量: {len(self.working_tokens)}"
        )


async def wait_for_seconds(seconds):
    await asyncio.sleep(seconds)


def get_proxy_from_env():
    """从环境变量获取代理设置"""
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if https_proxy:
        logging.info(f"使用系统代理: {https_proxy}")
        return https_proxy
    return None


def test_token(url, bot_token):
    url = f"{url}/bot{bot_token}/getMe"
    proxy = get_proxy_from_env()
    try:
        response = requests.get(url, proxies={"https": proxy} if proxy else None)
        json_data = response.json()
        logging.info(f"使用 {url} 测试 token 返回: {json_data}")
        if json_data.get("ok"):
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"使用 {url} 测试 token 失败: {e}")
        return False


def retry_async(max_retries=3, delay=3):
    """异步重试装饰器"""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries == max_retries:
                        logging.error(f"重试{max_retries}次后仍然失败: {str(e)}")
                        raise
                    logging.warning(
                        f"操作失败，{delay}秒后进行第{retries}次重试: {str(e)}"
                    )
                    await asyncio.sleep(delay)
            return None

        return wrapper

    return decorator


@retry_async(max_retries=3, delay=3)
async def send_message(url_pool, token_pool, channel_id, message):
    """发送消息（带重试）"""
    api_url = url_pool.get_url()
    bot_token = token_pool.get_token()
    url = f"{api_url}/bot{bot_token}/sendMessage"
    form_data = FormData()
    form_data.add_field("chat_id", str(channel_id))
    form_data.add_field("text", message)

    proxy = get_proxy_from_env()
    async with aiohttp.ClientSession() as session:
        if proxy:
            connector = aiohttp.TCPConnector(ssl=False)
            session._connector = connector
            async with session.post(url, data=form_data, proxy=proxy) as response:
                json_data = await response.json()
                if json_data.get("ok"):
                    logging.info(f"发送消息成功")
                    token_pool.increment_token(bot_token)
                    url_pool.increment_url(api_url)
                    return True
                else:
                    error_msg = json_data.get("description", "未知错误")
                    logging.error(f"发送消息失败: {error_msg}")
                    if "Too Many Requests" in error_msg:
                        await asyncio.sleep(5)  # 特殊处理请求限制错误
                    token_pool.remove_token(bot_token)
                    raise Exception(f"发送失败: {error_msg}")
        else:
            async with session.post(url, data=form_data) as response:
                json_data = await response.json()
                if json_data.get("ok"):
                    logging.info(f"发送消息成功")
                    token_pool.increment_token(bot_token)
                    url_pool.increment_url(api_url)
                    return True
                else:
                    error_msg = json_data.get("description", "未知错误")
                    logging.error(f"发送消息失败: {error_msg}")
                    token_pool.remove_token(bot_token)
                    raise Exception(f"发送失败: {error_msg}")


@retry_async(max_retries=3, delay=3)
async def send_media_group(url_pool, token_pool, channel_id, media_files, group_index):
    """发送媒体组（带重试）"""
    api_url = url_pool.get_url()
    bot_token = token_pool.get_token()
    url = f"{api_url}/bot{bot_token}/sendMediaGroup"
    media_list = []

    # 创建FormData对象
    form_data = aiohttp.FormData()
    form_data.add_field("chat_id", str(channel_id))

    # 构造媒体组数据
    for i, (filename, image_data) in enumerate(media_files):
        file_key = f"file{i}"
        media_item = {"type": "photo", "media": f"attach://{file_key}"}
        media_list.append(media_item)
        # 添加文件到表单数据
        form_data.add_field(
            file_key, image_data, filename=filename, content_type="image/jpeg"
        )

    form_data.add_field("media", json.dumps(media_list))

    proxy = get_proxy_from_env()
    async with aiohttp.ClientSession() as session:
        if proxy:
            connector = aiohttp.TCPConnector(ssl=False)
            session._connector = connector
            async with session.post(url, data=form_data, proxy=proxy) as response:
                json_data = await response.json()
                if json_data.get("ok"):
                    # logging.info(f"发送媒体组 {group_index} 成功")
                    token_pool.increment_token(bot_token)
                    url_pool.increment_url(api_url)
                    return True
                else:
                    error_msg = json_data.get("description", "未知错误")
                    logging.error(f"发送媒体组 {group_index} 失败: {error_msg}")
                    if "Too Many Requests" in error_msg:
                        await asyncio.sleep(5)
                    token_pool.remove_token(bot_token)
                    raise Exception(f"发送失败: {error_msg}")
        else:
            async with session.post(url, data=form_data) as response:
                json_data = await response.json()
                if json_data.get("ok"):
                    # logging.info(f"发送媒体组 {group_index} 成功")
                    token_pool.increment_token(bot_token)
                    url_pool.increment_url(api_url)
                    return True
                else:
                    error_msg = json_data.get("description", "未知错误")
                    logging.error(f"发送媒体组 {group_index} 失败: {error_msg}")
                    token_pool.remove_token(bot_token)
                    raise Exception(f"发送失败: {error_msg}")


async def send_images_from_dir(
    url_pool,
    token_pool,
    channel_id,
    image_dir,
    group_size=4,
    start_index=0,
    end_index=0,
):
    media_files = []
    group_index = 0
    idx = 0

    # 递归获取所有子目录中的图片文件
    all_files = []
    for root, _, files in os.walk(image_dir):
        for file in files:
            if file.lower().endswith(IMAGE_EXTENSIONS):
                full_path = os.path.join(root, file)
                if os.path.isfile(full_path):
                    all_files.append((full_path, file))
    
    await send_message(
        url_pool, token_pool, channel_id, f"开始上传图片，共 {len(all_files)} 张"
    )

    for full_path, file_name in tqdm.tqdm(all_files):
        if idx >= start_index * group_size and (
            end_index == 0 or idx <= end_index * group_size
        ):
        #     logging.info(f"处理文件: {full_path}")
            with open(full_path, "rb") as image_file:
                media_files.append((file_name, image_file.read()))
                if len(media_files) >= group_size:
                    await send_media_group(
                        url_pool,
                        token_pool,
                        channel_id,
                        media_files,
                        group_index,
                    )
                    media_files = []
                    group_index += 1
                    logging.info(f"发送媒体组 {group_index} 完成")
                    await wait_for_seconds(3)
                if group_index % 10 == 0:
                        await send_message(
                        url_pool,
                        token_pool,
                        channel_id,
                        f"发送媒体组 {group_index}/{len(all_files) // group_size} 完成",
                        )
        idx += 1

    if media_files:
        await send_media_group(
            url_pool, token_pool, channel_id, media_files, group_index
        )
        await send_message(
            url_pool, token_pool, channel_id, f"从目录 {image_dir} 上传图片完成"
        )


async def send_images_from_zip(
    url_pool, token_pool, channel_id, zip_file, group_size=4, start_index=1, end_index=0
):
    media_files = []
    group_index = 0
    idx = 0
    with zipfile.ZipFile(zip_file, "r") as zip_ref:
        await send_message(
            url_pool,
            token_pool,
            channel_id,
            f"开始上传图片，共 {len(zip_ref.namelist())} 张",
        )
        fitting_files = [
            file_name
            for file_name in zip_ref.namelist()
            if file_name.lower().endswith(IMAGE_EXTENSIONS)
        ]
        for file_name in tqdm.tqdm(fitting_files):
            if idx >= start_index * group_size and (
                end_index == 0 or idx <= end_index * group_size
            ):
                with zip_ref.open(file_name) as image_file:
                    media_files.append((file_name, image_file.read()))
                    if len(media_files) >= group_size:
                        await send_media_group(
                            url_pool,
                            token_pool,
                            channel_id,
                            media_files,
                            group_index,
                        )
                        media_files = []
                        group_index += 1
                        logging.info(f"发送媒体组 {group_index} 完成")
                        await wait_for_seconds(3)
                idx += 1
                if group_index % 10 == 0:
                    await send_message(
                        url_pool,
                        token_pool,
                        channel_id,
                        f"发送媒体组 {group_index}/{len(fitting_files) % group_size} 完成",
                    )
    if media_files:
        await send_media_group(
            url_pool, token_pool, channel_id, media_files, group_index
        )
    await send_message(
        url_pool,
        token_pool,
        channel_id,
        f"从压缩包 {os.path.basename(zip_file)} 上传图片完成",
    )


async def main():
    parser = argparse.ArgumentParser(description="上传图片到 Telegram 频道")
    parser.add_argument("-t", "--bot_token", type=str, help="Telegram 机器人 token")
    parser.add_argument("-c", "--channel_id", type=str, help="Telegram 频道 ID")
    parser.add_argument("-z", "--zip_file", type=str, help="压缩包文件路径")
    parser.add_argument("-d", "--image_dir", type=str, help="图片目录")
    parser.add_argument(
        "--api_url",
        default="https://api.telegram.org",
        type=str,
        help="Telegram API URL",
    )
    parser.add_argument("--group_size", default=4, type=int, help="媒体组大小")
    parser.add_argument("--start_index", default=0, type=int, help="开始序号")
    parser.add_argument("--end_index", default=0, type=int, help="结束序号")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument(
        "--max_retries", type=int, default=3, help="发送失败时的最大重试次数"
    )
    parser.add_argument(
        "--retry_delay", type=int, default=3, help="重试之间的延迟时间（秒）"
    )
    args = parser.parse_args()

    if not (args.bot_token or args.config) or not args.channel_id:
        parser.error("请提供 -t（bot_token） 和 -c（channel_id） 参数")

    if not args.zip_file and not args.image_dir:
        parser.error("请提供 -z（zip_file） 或 -d（image_dir） 参数")

    #     if not await test_token(args.api_url, args.bot_token):
    #         parser.error("token 测试失败，请检查 token 是否正确")

    api_urls = None
    tokens = None

    # 加载配置文件
    if Path(args.config).exists():
        config_api_urls, config_tokens = load_config(args.config)
        api_urls = config_api_urls
        tokens = (
            config_tokens
            if not args.bot_token
            else [{"name": "CLI Token", "id": "cli", "token": args.bot_token}]
        )
    else:
        api_urls = args.api_url.split(",")
        tokens = args.bot_token.split(",") if args.bot_token else []

    if len(tokens) == 0:
        parser.error("没有找到有效的 token")

    if len(api_urls) == 0:
        parser.error("没有找到有效的 api_url")

    logging.info(f"加载的 api_url: {api_urls}")
    url_pool = UrlPool(api_urls)
    token_pool = TokenPool(url_pool, tokens)

    # 设置重试装饰器的参数
    send_message.__wrapped__.__defaults__ = (args.max_retries, args.retry_delay)
    send_media_group.__wrapped__.__defaults__ = (args.max_retries, args.retry_delay)

    if args.zip_file:
        await asyncio.gather(
            send_images_from_zip(
                url_pool,
                token_pool,
                args.channel_id,
                args.zip_file,
                args.group_size,
                args.start_index,
                args.end_index,
            )
        )

    if args.image_dir:
        await asyncio.gather(
            send_images_from_dir(
                url_pool,
                token_pool,
                args.channel_id,
                args.image_dir,
                args.group_size,
                args.start_index,
                args.end_index,
            )
        )

    logging.info("所有图片上传完成")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    asyncio.run(main())
