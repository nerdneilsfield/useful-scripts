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

import requests

import aiohttp
from aiohttp import FormData
import tqdm

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".bmp")


def load_config(config_path):
    """加载INI配置文件"""
    config = configparser.ConfigParser()
    config.read(config_path)

    api_url = config.get("Telegram", "api_url", fallback=None)
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
    logging.info(f"加载的 api_url: {api_url}")
    return api_url, [token["token"] for token in tokens]


class TokenPool:
    def __init__(self, api_url, tokens):
        self.api_url = api_url
        self.tokens = [token.strip() for token in tokens]
        self.working_tokens = []  # 现在存储字典格式 [{"token": str, "count": int}, ...]
        self.current_index = 0
        logging.info(f"初始化 token 池: {len(self.tokens)} 个 token")
        self.test_tokens()
        logging.info(f"测试 token 池完成: {len(self.working_tokens)} 个有效 token")

    def test_tokens(self):
        for token in tqdm.tqdm(self.tokens):
            if test_token(self.api_url, token):
                logging.info(f"token {token} 测试成功")
                self.working_tokens.append({"token": token, "count": 0})  # 初始化计数为0
            else:
                logging.error(f"token {token} 测试失败")

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
        self.working_tokens = [t for t in self.working_tokens if t["token"] != token_str]
        logging.info(f"移除 token {token_str}，剩余 token 数量: {len(self.working_tokens)}")


async def wait_for_seconds(seconds):
    await asyncio.sleep(seconds)


def test_token(api_url, bot_token):
    url = f"{api_url}/bot{bot_token}/getMe"
    try:
        response = requests.get(url)
        json_data = response.json()
        logging.info(f"测试 token 返回: {json_data}")
        if json_data.get("ok"):
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"测试 token 失败: {e}")
        return False
    
async def send_message(api_url, token_pool, channel_id, message):
    bot_token = token_pool.get_token()
    url = f"{api_url}/bot{bot_token}/sendMessage"
    form_data = FormData()
    form_data.add_field("chat_id", str(channel_id))
    form_data.add_field("text", message)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=form_data) as response:
            json_data = await response.json()
            if json_data.get("ok"):
                logging.info(f"发送消息成功")
                token_pool.increment_token(bot_token)
            else:
                logging.error(f"发送消息失败: {json_data.get('description')}")
                token_pool.remove_token(bot_token)


async def send_media_group(api_url, token_pool, channel_id, media_files, group_index):
    """
    发送一个媒体组
    :param media_files: [(filename, image_data), ...] 的列表，最多 9 个
    :param group_index: 当前媒体组的序号（用于调试输出）
    """
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

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=form_data) as response:
            json_data = await response.json()
            if json_data.get("ok"):
                logging.info(f"发送媒体组 {group_index} 成功")
                token_pool.increment_token(bot_token)
            else:
                logging.error(
                    f"发送媒体组 {group_index} 失败: {json_data.get('description')}"
                )
                token_pool.remove_token(bot_token)


async def send_images_from_dir(
    api_url, token_pool, channel_id, image_dir, group_size=4, start_index=1, end_index=0
):
    media_files = []
    group_index = 1
    idx = 1
    for _, _, files in os.walk(image_dir):
        await send_message(api_url, token_pool, channel_id, f"开始上传图片，共 {len(files)} 张")
        for file_name in tqdm.tqdm(files):
            if os.path.isfile(os.path.join(image_dir, file_name)) and file_name.lower().endswith(IMAGE_EXTENSIONS):
                if idx >= start_index * group_size and (
                    end_index == 0 or idx <= end_index * group_size
                ):
                    with open(os.path.join(image_dir, file_name), "rb") as image_file:
                        media_files.append((file_name, image_file.read()))
                        if len(media_files) >= group_size:
                            await send_media_group(
                                api_url, token_pool, channel_id, media_files, group_index
                            )
                            media_files = []
                            group_index += 1
                            logging.info(f"发送媒体组 {group_index} 完成")
                            await wait_for_seconds(3)
                idx += 1
    if media_files:
        await send_media_group(
            api_url, token_pool, channel_id, media_files, group_index
        )
        await send_message(api_url, token_pool, channel_id, f"从目录 {image_dir} 上传图片完成")

async def send_images_from_zip(
    api_url, token_pool, channel_id, zip_file, group_size=4, start_index=1, end_index=0
):
    media_files = []
    group_index = 1
    idx = 1
    with zipfile.ZipFile(zip_file, "r") as zip_ref:
        await send_message(api_url, token_pool, channel_id, f"开始上传图片，共 {len(zip_ref.namelist())} 张")
        for file_name in tqdm.tqdm(zip_ref.namelist()):
            if file_name.lower().endswith(IMAGE_EXTENSIONS):
                if idx >= start_index * group_size and (
                    end_index == 0 or idx <= end_index * group_size
                ):
                    with zip_ref.open(file_name) as image_file:
                        media_files.append((file_name, image_file.read()))
                        if len(media_files) >= group_size:
                            await send_media_group(
                                api_url,
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
    if media_files:
        await send_media_group(
            api_url, token_pool, channel_id, media_files, group_index
        )
    await send_message(api_url, token_pool, channel_id, f"从压缩包 {os.path.basename(zip_file)} 上传图片完成")


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
    parser.add_argument("--start_index", default=1, type=int, help="开始序号")
    parser.add_argument("--end_index", default=0, type=int, help="结束序号")
    parser.add_argument(
        "--config", type=str, help="Path to config file"
    )
    args = parser.parse_args()

    if not (args.bot_token or args.config) or not args.channel_id:
        parser.error("请提供 -t（bot_token） 和 -c（channel_id） 参数")

    if not args.zip_file and not args.image_dir:
        parser.error("请提供 -z（zip_file） 或 -d（image_dir） 参数")

    #     if not await test_token(args.api_url, args.bot_token):
    #         parser.error("token 测试失败，请检查 token 是否正确")

    api_url = ""
    tokens = []

    # 加载配置文件
    if Path(args.config).exists():
        config_api_url, config_tokens = load_config(args.config)
        api_url = config_api_url
        tokens = (
            config_tokens
            if not args.bot_token
            else [{"name": "CLI Token", "id": "cli", "token": args.bot_token}]
        )
    else:
        api_url = args.api_url
        tokens = args.bot_token.split(",") if args.bot_token else []

    if len(tokens) == 0:
        parser.error("没有找到有效的 token")
        
    logging.info(f"加载的 api_url: {api_url}")
    token_pool = TokenPool(api_url, tokens)

    if args.zip_file:
        await asyncio.gather(
            send_images_from_zip(
                api_url,
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
                api_url,
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
