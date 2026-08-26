#!/usr/bin/env python3
"""Reset selected NewAPI users' quotas once. Scheduling belongs outside."""

import json
import logging
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOG = logging.getLogger(__name__)

# Configuration method 1 (default): environment variables.
CONFIG = {
    "base_url": os.getenv("NEWAPI_URL", ""),
    "key": os.getenv("NEWAPI_MANAGEMENT_KEY", ""),
    "users": os.getenv("NEWAPI_USERS", ""),
    "groups": os.getenv("NEWAPI_GROUPS", ""),
    "quota": os.getenv("NEWAPI_QUOTA", ""),
    "mode": os.getenv("NEWAPI_QUOTA_MODE", ""),
    "notify": os.getenv("NEWAPI_NOTIFY", "true"),
    "notice": os.getenv("NEWAPI_NOTICE", "本月额度已重置。"),
}

# Configuration method 2: write values here. To use it, comment out the
# CONFIG block above and uncomment this block.
# CONFIG = {
#     "base_url": "https://newapi.example.com",
#     "key": "your-management-key",
#     "users": "alice,bob",
#     "groups": "vip",
#     "quota": "1000000",
#     "mode": "set",  # set, top_up, or add
#     "notify": "true",  # false disables the NewAPI Notice update
#     "notice": "本月额度已重置。",
# }


def new_quota(current: int, target: int, mode: str) -> int:
    if mode == "set":
        return target
    if mode == "top_up":
        return max(current, target)
    if mode == "add":
        return current + target
    raise ValueError("NEWAPI_QUOTA_MODE must be set, top_up, or add")


def csv_items(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


class NewAPI:
    def __init__(self, base_url: str, key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, payload: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.base_url + path, body, self.headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                result = json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"HTTP {error.code}: {error.read().decode(errors='replace')}") from error
        except URLError as error:
            raise RuntimeError(f"request failed: {error.reason}") from error

        if not result.get("success", True):
            raise RuntimeError(result.get("message") or "NewAPI rejected request")
        return result.get("data", result)

    def users(self) -> list[dict]:
        users: list[dict] = []
        page = 1
        while True:
            data = self.request("GET", "/api/user/?" + urlencode({"p": page, "page_size": 100}))
            items = data.get("items", [])
            if not isinstance(items, list):
                raise RuntimeError("unexpected user-list response")
            users.extend(items)
            if len(users) >= data.get("total", 0) or not items:
                return users
            page += 1

    def user(self, user_id: int) -> dict:
        data = self.request("GET", f"/api/user/{user_id}")
        if not isinstance(data, dict):
            raise RuntimeError("unexpected user-detail response")
        return data

    def update_user(self, user: dict) -> None:
        self.request("PUT", "/api/user/", user)

    def update_notice(self, notice: str) -> None:
        self.request("PUT", "/api/option/", {"key": "Notice", "value": notice})


def main() -> int:
    base_url = CONFIG["base_url"].strip()
    key = CONFIG["key"].strip()
    usernames = csv_items(CONFIG["users"])
    groups = csv_items(CONFIG["groups"])
    mode = CONFIG["mode"].strip()
    quota_text = CONFIG["quota"].strip()
    notify_text = CONFIG["notify"].strip().lower()
    notice = CONFIG["notice"].strip()

    if not base_url or not key or not quota_text or not (usernames or groups):
        LOG.error("missing required NEWAPI_* configuration")
        return 2
    try:
        quota = int(quota_text)
        if quota < 0:
            raise ValueError
        new_quota(0, quota, mode)
    except ValueError as error:
        LOG.error(error or "NEWAPI_QUOTA must be a non-negative integer")
        return 2
    if notify_text not in {"true", "false"}:
        LOG.error("NEWAPI_NOTIFY must be true or false")
        return 2

    api = NewAPI(base_url, key)
    try:
        all_users = api.users()
    except RuntimeError as error:
        LOG.error(error)
        return 1

    selected: dict[int, dict] = {}
    found_users: set[str] = set()
    found_groups: set[str] = set()
    for user in all_users:
        username = user.get("username", "")
        user_groups = {item.strip() for item in user.get("group", "").split(",") if item.strip()}
        if username in usernames or user_groups & groups:
            selected[user["id"]] = user
            found_users.add(username)
            found_groups.update(user_groups & groups)

    for username in sorted(usernames - found_users):
        LOG.warning("user not found: %s", username)
    for group in sorted(groups - found_groups):
        LOG.warning("group has no users: %s", group)

    failed = False
    for user in selected.values():
        username = user.get("username", str(user["id"]))
        try:
            detail = api.user(user["id"])
            current = int(detail["quota"])
            updated = new_quota(current, quota, mode)
            if updated != current:
                detail["quota"] = updated
                api.update_user(detail)
            LOG.info("%s: %s -> %s", username, current, updated)
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            failed = True
            LOG.error("%s: %s", username, error)
    if failed or notify_text == "false":
        return 1 if failed else 0
    try:
        api.update_notice(notice)
        LOG.info("NewAPI Notice updated")
    except RuntimeError as error:
        LOG.error("NewAPI Notice: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
