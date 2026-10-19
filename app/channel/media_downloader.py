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
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import requests


# ═══════════════════════════════════════════════════════════
# CLI 定位（与三个 channel client + bridge.py 保持一致的查找顺序）
# ═══════════════════════════════════════════════════════════

def _locate_cli(*, meipass_rel: str, which_names: list[str], candidates: list[str], fallback: str = "") -> str:
    """统一的 CLI 定位函数（与三个 channel client + bridge.py 保持一致的查找顺序）。

    优先级：PyInstaller _MEIPASS 内置 → PATH (shutil.which) → 常见安装路径 → fallback 命令名。
    解决了之前 media_downloader 独立写 shutil.which 漏掉 sys._MEIPASS 的 bug。
    """
    import shutil as _shutil

    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, meipass_rel)
        if os.path.exists(bundled):
            return bundled
    for name in which_names:
        p = _shutil.which(name)
        if p:
            return p
    for c in candidates:
        if not c:
            continue
        if os.path.isfile(c):
            return c
    return fallback


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
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=HTTP_TIMEOUT)
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
# 钉钉：dws chat +messages-resource-download → 本地文件（首选）
# ========================================================================

def _download_dingtalk_dws_cli(resource_id: str, open_message_id: str,
                               open_conversation_id: str,
                               filename: str = "") -> Optional[str]:
    """用 dws CLI 下载钉钉消息里的图片/语音/视频/文件。

    dws CLI 命令：
      dws chat +messages-resource-download         --resource-id <mediaId>         --message-id <openMessageId>         --open-conversation-id <openConversationId>         --output ./downloads/         -y

    Args:
        resource_id:       dws 返回的 mediaId（@xxx 开头）或 fileId
        open_message_id:   dws 返回的 openMessageId（下载必需）
        open_conversation_id: dws 返回的 openConversationId（cid... 下载必需）
        filename:          可选，原始文件名（dws 自动生成一个）

    Returns:
        本地文件路径（str），失败返回 None
    """
    import tempfile as _tf

    dws_bin = "dws"
    for p in (
        os.path.expandvars(r"%USERPROFILE%\.local\bin\dws.exe"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Microsoft\WindowsApps\dws.exe"),
    ):
        if os.path.isfile(p):
            dws_bin = p
            break

    out_dir = Path(_tf.gettempdir()) / "dingtalk_downloads"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_relative = f"./{out_dir.name}/"

    cmd = [dws_bin, "chat", "+messages-resource-download"]

    is_file_id = not resource_id.startswith("@")
    cmd += ["--resource-id", resource_id]
    cmd += ["--type", "fileId" if is_file_id else "mediaId"]
    if not is_file_id:
        cmd += ["--message-id", open_message_id, "--open-conversation-id", open_conversation_id]
    cmd += ["--output", out_relative, "-y"]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            cwd=str(out_dir.parent),
        )
        if result.returncode != 0:
            print(f"[MediaDownloader] dws download 失败 rc={result.returncode}: {result.stderr[:300]}", flush=True)
            return None

        try:
            data = json.loads(result.stdout.strip())
        except Exception:
            stdout = result.stdout.strip()
            if stdout and os.path.isfile(stdout):
                return stdout
            print(f"[MediaDownloader] dws download 返回非 JSON: {stdout[:200]}", flush=True)
            return None

        local_path = data.get("localPath", "")
        # dws 返回相对路径时，相对 cwd（out_dir 的父目录）解析
        if local_path and not os.path.isabs(local_path):
            local_path = str(out_dir.parent / local_path).resolve()
        if local_path and os.path.isfile(local_path):
            size = data.get("sizeBytes", os.path.getsize(local_path))
            print(f"[MediaDownloader] dws download 成功: {local_path} ({size} bytes)", flush=True)
            return local_path
        print(f"[MediaDownloader] dws download 返回路径不存在: {local_path}", flush=True)
        return None
    except subprocess.TimeoutExpired:
        print("[MediaDownloader] dws download 超时", flush=True)
        return None
    except Exception as e:
        print(f"[MediaDownloader] dws download 异常: {type(e).__name__}: {e}", flush=True)
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
    """飞书 file/image/video/audio 下载（通过 lark-cli +messages-resources-download）。

    lark-cli 命令:
      lark-cli im +messages-resources-download --message-id om_xxx --file-key img_v3_xxx --type image --output /tmp/xxx

    返回本地文件绝对路径，失败返回 None。
    """
    import subprocess
    import tempfile
    from pathlib import Path

    # 根据 file_key 前缀判类型
    if file_key.startswith("img_"):
        res_type = "image"
        ext = ".png"
    elif file_key.startswith("file_"):
        res_type = "file"
        # 尽量沿用原始文件名后缀
        ext = Path(filename).suffix or ".bin"
    else:
        res_type = "image"
        ext = ".bin"

    lark_cli = _locate_cli(
        meipass_rel="channels/feishu/lark-cli.exe",
        which_names=["lark-cli"],
        candidates=[os.path.expandvars(r"%USERPROFILE%\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe")],
    )

    out_dir = Path(tempfile.gettempdir()) / "feishu_resources"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{file_key}{ext}"

    try:
        proc = subprocess.run(
            [
                lark_cli, "im", "+messages-resources-download",
                "--message-id", message_id,
                "--file-key", file_key,
                "--type", res_type,
                "--output", str(out_path),
                "--as", "user",
            ],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:300]
            print(f"[MediaDownloader] 飞书下载失败: {err}", flush=True)
            return None

        raw = (proc.stdout or "").strip()
        if raw:
            try:
                import json
                data = json.loads(raw)
                if isinstance(data, dict):
                    p = data.get("data", {}).get("path") or data.get("path") or data.get("file_path")
                    if p and Path(p).is_file():
                        print(f"[MediaDownloader] 飞书下载成功(CLI返回路径): {p}", flush=True)
                        return p
            except Exception:
                pass

        if out_path.is_file() and out_path.stat().st_size > 0:
            print(f"[MediaDownloader] 飞书下载成功: {out_path} ({out_path.stat().st_size}B)", flush=True)
            return str(out_path)

        print(f"[MediaDownloader] 飞书下载: 文件未落地 out_path={out_path} exists={out_path.is_file()}", flush=True)
        return None
    except subprocess.TimeoutExpired:
        print(f"[MediaDownloader] 飞书下载超时: message_id={message_id}", flush=True)
        return None
    except Exception as e:
        print(f"[MediaDownloader] 飞书下载异常: {e}", flush=True)
        return None


# ========================================================================
# 企微：url + aes_key → 下载 + AES 解密
# ========================================================================

def download_wecom(media_id: str, aes_key: str = "", filename: str = "") -> Optional[str]:
    """企微 media_id → 本地文件。

    wecom-cli message files get 的返回不是二进制，是 JSON：
      {"media_item": {"file_path": "C:\\...temp\\wecom\\requests\\真实文件.jpeg", ...}}
    真实文件由 CLI 存到了它自己的 temp 目录。
    我们需要：1) 不带 -o 调 CLI 拿 JSON 输出  2) 从 JSON 里取 file_path  3) 拷贝到我们的 temp。
    """
    if not media_id:
        return None
    try:
        import shutil
        cli = _locate_cli(
            meipass_rel="channels/wecom/wecom-cli.exe",
            which_names=["wecom-cli", "wecom-cli.cmd"],
            candidates=[
                os.path.expandvars(r"%APPDATA%\npm\node_modules\@wecom\cli\node_modules\@wecom\cli-win32-x64\bin\wecom-cli.exe"),
                os.path.expandvars(r"%APPDATA%\npm\wecom-cli.cmd"),
            ],
            fallback="wecom-cli",
        )
        cmd = [cli, "message", "files", "get", "--media-id", media_id]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            print(f"[MediaDownloader] wecom-cli 下载失败: {result.stderr.decode(errors='ignore')[:200]}", flush=True)
            return None
        raw_out = result.stdout.decode(errors="ignore").strip()
        try:
            data = json.loads(raw_out)
        except json.JSONDecodeError:
            print(f"[MediaDownloader] wecom-cli 输出不是 JSON: {raw_out[:100]}", flush=True)
            return None
        media_item = data.get("media_item") or {}
        cli_file_path = media_item.get("file_path", "")
        if not cli_file_path:
            print(f"[MediaDownloader] wecom-cli 返回无 file_path: {list(data.keys())}", flush=True)
            return None
        src_path = Path(cli_file_path)
        if not src_path.exists():
            print(f"[MediaDownloader] CLI 文件不存在: {src_path}", flush=True)
            return None
        ext = src_path.suffix or ".jpg"
        tmp_dir = Path(tempfile.gettempdir())
        dest_path = tmp_dir / f"wecom_{uuid.uuid4().hex[:12]}{ext}"
        shutil.copy2(str(src_path), str(dest_path))
        size = dest_path.stat().st_size
        print(f"[MediaDownloader] wecom 下载成功: {dest_path.name} ({size} bytes, from CLI)", flush=True)
        return str(dest_path)
    except subprocess.TimeoutExpired:
        print("[MediaDownloader] wecom-cli 下载超时", flush=True)
        return None
    except Exception as e:
        print(f"[MediaDownloader] wecom 下载异常: {e}", flush=True)
        return None


# ========================================================================
# 微信公众号（临时素材）：media_id + access_token → GET 二进制
# ========================================================================

def download_oa(media_id: str) -> Optional[str]:
    """微信公众号临时素材下载（图片/语音/视频/缩略图）。

    微信公众号用户发的图片/语音/视频消息里会带 media_id，
    用 access_token 调官方 API 直接 GET 二进制。
    """
    if not media_id:
        return None
    try:
        from channel.oa_client import default_client
        wx_client = getattr(default_client, "_wx_client", None) if default_client else None
        if not wx_client:
            print(f"[MediaDownloader] OA: default_client 未初始化，media_id={media_id[:20]}...", flush=True)
            return None
        token = wx_client.access_token or wx_client.fetch_access_token()
        if not token:
            print("[MediaDownloader] OA: access_token 获取失败", flush=True)
            return None
        url = f"https://api.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={media_id}"
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()

        # 出错时微信返回 JSON（errcode/errmsg），正常返回二进制
        ct = resp.headers.get("Content-Type", "")
        if "json" in ct.lower() or "text" in ct.lower():
            try:
                err = resp.json()
                print(f"[MediaDownloader] OA: 微信返回错误 {err}", flush=True)
            except Exception:
                print(f"[MediaDownloader] OA: 返回非文件 content-type={ct}", flush=True)
            return None

        ext = ".bin"
        content_disposition = resp.headers.get("Content-Disposition", "")
        if "filename=" in content_disposition:
            fn = content_disposition.split("filename=")[-1].strip('"')
            _, e = os.path.splitext(fn)
            if e:
                ext = e
        return cache_bytes(resp.content, filename=f"oa_{media_id}{ext}")
    except Exception as e:
        print(f"[MediaDownloader] OA 下载异常: {e}", flush=True)
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
            "id": getattr(msg, "id", ""),
            "channel": getattr(msg, "channel", ""),
            "file_path": getattr(msg, "file_path", ""),
            "file_name": getattr(msg, "file_name", ""),
            "media_id": getattr(msg, "media_id", ""),
            "content": getattr(msg, "content", ""),
            "open_message_id": getattr(msg, "open_message_id", ""),
            "open_conversation_id": getattr(msg, "open_conversation_id", ""),
        }
    else:
        msg_dict = dict(msg)

    # wcf 天然有本地路径
    if channel == "wcf":
        return msg_dict.get("file_path") or None

    # 钉钉：优先 dws CLI（需要 open_message_id + open_conversation_id），否则回退 downloadCode
    if channel == "dingtalk":
        resource_id = msg_dict.get("media_id") or ""
        open_msg_id = msg_dict.get("open_message_id") or msg_dict.get("id") or ""
        open_conv_id = msg_dict.get("open_conversation_id") or ""
        if resource_id and open_msg_id and open_conv_id:
            return _download_dingtalk_dws_cli(resource_id, open_msg_id, open_conv_id,
                                              msg_dict.get("file_name", ""))
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

    # 企微：需要 media_id
    if channel == "wecom":
        mid = msg_dict.get("media_id") or ""
        if mid:
            return download_wecom(mid, "", msg_dict.get("file_name", ""))
        return None

    # 微信公众号临时素材
    if channel == "oa":
        mid = msg_dict.get("media_id") or ""
        if mid:
            return download_oa(mid)
        return None

    return None
