"""各渠道媒体文件下载：media_id/downloadCode/file_key → 本地文件路径。

外部项目范式（AstrBot / LangBot / dingtalk-hermes-connector）一致：
  渠道原始消息 → 提取 media_id/downloadCode/file_key
               → 调官方 API 换临时下载 URL（带 headers 鉴权）
               → httpx/requests GET 二进制
               → cache_bytes() 存到本地 tmp 目录
               → 返回文件路径给 pipeline.parse_document()

MVP 实现策略：
  - 钉钉：dws api POST /robot/message/download 拿临时 URL + headers → requests.get
  - 飞书：requests 直接调 OpenAPI（tenant_access_token 飞书 CLI 能拿到）
  - 企微：requests 调 OpenAPI（注意 AES 解密，如果 CLI 没直接给 url）
  - wcf：天然有本地路径，不进 downloader
  - 下载失败 → 返回 None，pipeline 走占位提示
"""

from __future__ import annotations
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import requests

# 临时下载目录：%APPDATA%/SCAI/media_cache/
_APP_DATA = os.environ.get("APPDATA", str(Path.home() / ".config"))
CACHE_DIR = Path(_APP_DATA) / "SCAI" / "media_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 默认请求超时（秒）
HTTP_TIMEOUT = 30


def cache_bytes(data: bytes, filename: str = "", ext: str = "") -> str:
    """bytes → 存到 CACHE_DIR → 返回完整文件路径。

    filename 给了就用它（取后缀当 ext）；ext 单独给则覆盖。
    没给 filename/ext 就用 uuid 做文件名。
    """
    if not ext and filename:
        ext = Path(filename).suffix or ""
    if not ext:
        ext = ""
    safe_ext = re.sub(r"[^a-zA-Z0-9._-]", "", ext)
    fname = f"{uuid.uuid4().hex}{safe_ext}"
    path = CACHE_DIR / fname
    path.write_bytes(data)
    return str(path)


def _run_dws_api(method: str, path: str, data: dict | None = None) -> Optional[dict]:
    """调 dws api 子命令。返回解析后的 JSON dict，失败返回 None。

    dws 自带 token 管理——用户 auth login 过了就能直接用。
    """
    cmd = ["dws", "api", method.upper(), path]
    if data is not None:
        cmd += ["--data", json.dumps(data, ensure_ascii=False)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=HTTP_TIMEOUT)
        if r.returncode != 0:
            print(f"[MediaDownloader] dws api 失败: {r.stderr[:300]}", flush=True)
            return None
        out = r.stdout.strip()
        if not out:
            return None
        return json.loads(out)
    except subprocess.TimeoutExpired:
        print(f"[MediaDownloader] dws api 超时: {method} {path}", flush=True)
        return None
    except Exception as e:
        print(f"[MediaDownloader] dws api 异常: {e}", flush=True)
        return None


# ========================================================================
# 钉钉：downloadCode → dws api → 临时下载 URL + headers → requests.get
# ========================================================================

def download_dingtalk(download_code: str, robot_code: str = "") -> Optional[str]:
    """钉钉 file/image/video/audio 下载。

    钉钉机器人接收消息时，非文本消息 msg 里会有 downloadCode 字段，
    通过官方 API 换临时下载链接。

    参考文档：
      https://open.dingtalk.com/document/orgapp/download-the-file-content-of-the-robot-receiving-message

    Args:
        download_code: 钉钉消息里的 downloadCode
        robot_code:   可选，机器人 code（dws api 可能自动注入）

    Returns:
        本地文件路径（str），失败返回 None
    """
    # 1) 调 API 换临时下载链接
    body = {"downloadCode": download_code}
    if robot_code:
        body["robotCode"] = robot_code

    result = _run_dws_api(
        "POST",
        "/robot/message/download",
        data=body,
    )
    if not result:
        return None

    # 钉钉返回格式：{ "downloadUrl": "https://...", "headers": {...}, "expireSeconds": 900 }
    temp_url = result.get("downloadUrl") or result.get("internalResourceUrls", [None])[0]
    headers = result.get("headers", {}) or {}
    if not temp_url:
        print(f"[MediaDownloader] 钉钉 downloadCode 换不到下载 URL: {result}", flush=True)
        return None

    # 2) GET 下载
    try:
        resp = requests.get(temp_url, headers=headers, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        # 3) 推断文件名（从 URL 里猜）
        name_from_url = ""
        if "/" in temp_url.split("?")[0]:
            name_from_url = temp_url.split("?")[0].rsplit("/", 1)[-1]
        return cache_bytes(resp.content, filename=name_from_url)
    except Exception as e:
        print(f"[MediaDownloader] 钉钉下载失败: {e}", flush=True)
        return None


# ========================================================================
# 飞书：tenant_access_token → GET /im/v1/messages/:id/resources/:file_key
# ========================================================================

def download_feishu(message_id: str, file_key: str, filename: str = "") -> Optional[str]:
    """飞书 file/image/video/audio 下载。

    飞书消息 payload 里 msg_type=file 时会有 file_key 字段，
    配合 message_id + tenant_access_token 就能下载。

    参考文档：
      https://open.feishu.cn/document/server-docs/im-v1/message/get-2

    鉴权：
      tenant_access_token 需要通过 app_id + app_secret 换。
      MVP 先用飞书 CLI 跑 auth 看 token 缓存位置——如果拿不到，
      退化为 requests 手动换 token（需要用户填 app_id/app_secret）。
    """
    # TODO: 先不写具体实现，等用户实际跑起来拿到飞书 file 消息 payload 再补
    #  skeleton 占位
    print(
        f"[MediaDownloader] 飞书下载暂未实现: message_id={message_id}, file_key={file_key}",
        flush=True,
    )
    return None


# ========================================================================
# 企微：url + aes_key → 下载 + AES 解密
# ========================================================================

def download_wecom(url: str, aes_key: str = "", filename: str = "") -> Optional[str]:
    """企微 file/image/video/audio 下载。

    企微智能机器人（WebSocket 模式）消息里 file 字段会有 url（有时加密），
    以及可选的 aes_key（AES-256-CBC 解密）。

    参考：
      wecom-aibot-sdk-python 的 download_file(url, aes_key)
      纯 requests 就能搞定下载，AES 解密需要 pycryptodome
    """
    # TODO: 同上，先 skeleton
    print(
        f"[MediaDownloader] 企微下载暂未实现: url={url[:80]}..., aes_key={'yes' if aes_key else 'no'}",
        flush=True,
    )
    return None


# ========================================================================
# 统一入口
# ========================================================================

def download_file(channel: str, msg: dict) -> Optional[str]:
    """统一下载入口。

    Args:
        channel: 渠道标识 dingtalk / feishu / wecom / wcf
        msg:     ChannelMessage dataclass（传对象也行，会自动取属性）

    Returns:
        本地文件路径 str，失败或不需要下载返回 None
    """
    import dataclasses

    if dataclasses.is_dataclass(msg):
        msg_dict = {
            "channel": getattr(msg, "channel", ""),
            "file_path": getattr(msg, "file_path", ""),
            "file_name": getattr(msg, "file_name", ""),
            "media_id": getattr(msg, "media_id", ""),
            "content": getattr(msg, "content", ""),
        }
    else:
        msg_dict = dict(msg)

    # wcf 天然有本地路径
    if channel == "wcf":
        return msg_dict.get("file_path") or None

    # 钉钉：用 downloadCode（存进了 media_id）
    if channel == "dingtalk":
        dc = msg_dict.get("media_id") or msg_dict.get("content")
        if dc:
            return download_dingtalk(dc)
        return None

    # 飞书：需要 message_id + file_key
    if channel == "feishu":
        mid = msg_dict.get("id") or ""
        fk = msg_dict.get("media_id") or ""
        if mid and fk:
            return download_feishu(mid, fk, msg_dict.get("file_name", ""))
        return None

    # 企微：需要 url + aes_key（先在 payload 里找）
    if channel == "wecom":
        url = msg_dict.get("content") or msg_dict.get("media_id") or ""
        # aes_key 可能在 extra 字段里，暂时空
        if url:
            return download_wecom(url, "", msg_dict.get("file_name", ""))
        return None

    return None
