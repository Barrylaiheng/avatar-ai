"""飞书智能机器人客户端：lark-cli user 身份轮询模式。

与企微对齐的通信模型：
- 收消息：user 身份 +chat-messages-list 定时轮询内部会话
- 发消息：user 身份 +messages-send（user 不可用 fallback bot）
- 通讯录：user 身份 +chat-list + contact search-user

飞书平台限制：event consume（实时推送）只支持 bot 身份，
为统一"以用户身份通信"的产品定位，采用与企微一致的轮询模式。
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .base import ChannelMessage, ChannelClient

# ═══════════════════════════════════════════════════════════
# 飞书特化常量
# ═══════════════════════════════════════════════════════════

# 凭证目录：lark-cli 配置存在 ~/.lark-cli/
_CONFIG_DIR = Path.home() / ".lark-cli"

# 去重集合上限
_SEEN_MAX = 5000

# 轮询游标持久化文件
_STATE_FILE = Path.home() / ".config" / "feishu" / ".last_processed"

# 去重集合持久化文件（重启后恢复，避免 overlap 窗口内消息重复处理）
_SEEN_FILE = Path.home() / ".config" / "feishu" / ".seen_msgs"

# 首次运行回看窗口（秒）：第一次启动时往前拉 10 分钟
_FIRST_RUN_LOOKBACK_SEC = 600

# 每次轮询回看重叠（从上一次处理时间往前再拉 60 秒防漏）
_POLL_OVERLAP_SEC = 60

# API 最大回看（飞书消息历史可回看较长时间）
_MAX_LOOKBACK_SEC = 7 * 24 * 3600

# MVP 直连消息收发/群读必需 scope，用于授权完整性自检
FEISHU_REQUIRED_SCOPES = [
    "im:message.send_as_user",
    "im:message.p2p_msg:get_as_user",
    "im:message.group_msg:get_as_user",
    "im:chat:read",
]


def _lark_cli_path() -> str:
    """定位 lark-cli 可执行文件。

    lark-cli.exe 是单文件 (~48MB)，spec 里已硬打进 EXE 到
    sys._MEIPASS/channels/feishu/lark-cli.exe，这里优先查找。
    """
    import shutil
    import sys
    import os
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "channels", "feishu", "lark-cli.exe")
        if os.path.exists(bundled):
            return bundled
    p = shutil.which("lark-cli")
    if p:
        return p
    # TRAE 插件自带的 lark-cli
    candidates = [
        os.path.expandvars(r"%USERPROFILE%\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\lark-cli\lark-cli.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return "lark-cli"


class FeishuClient:
    """飞书 CLI 客户端：user 身份轮询 + 统一 ChannelClient 接口。"""

    channel_name = "feishu"
    POLL_INTERVAL_ACTIVE = 3.0    # 活跃时 3s 一轮
    POLL_INTERVAL_IDLE = 15.0     # 空闲时 15s 一轮
    ACTIVITY_WINDOW = 300.0       # 5 分钟内有新消息算活跃

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self._on_message: Optional[Callable[[ChannelMessage], None]] = None
        self._seen_msgs: set[str] = self._load_seen_msgs()
        self._last_msg_ts = 0.0
        self._cli = _lark_cli_path()
        # bot 自己的 open_id，用于自消息过滤
        self._bot_open_id: str = ""
        # user 身份自己的 open_id（用 --as user 发消息时 sender.id 就是这个）
        self._self_open_id: str = ""
        # 轮询游标：上次处理到的时间戳
        self._last_processed_ts = self._load_last_ts()
        # p2p 会话映射：chat_id (oc_...) → 对方 user open_id (ou_...)
        self._p2p_map: dict = {}

    @property
    def connected(self) -> bool:
        """检查 lark-cli 是否已配置（有凭证）。"""
        # 方式1：检查配置目录是否有 profile
        if _CONFIG_DIR.exists():
            # 有 profile 文件或 cache 就算已配置
            if any(_CONFIG_DIR.iterdir()):
                # 进一步用 auth status 确认
                return self._check_auth()
        return False

    def _check_auth(self) -> bool:
        """调用 lark-cli auth status --json 检查是否已认证。"""
        try:
            proc = subprocess.run(
                [self._cli, "auth", "status", "--json"],
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout.strip())
                # 缓存 user 身份的 open_id，用于自消息过滤
                user = data.get("identities", {}).get("user", {}) or {}
                if user.get("openId"):
                    self._self_open_id = user["openId"]
                # lark-cli auth status 输出格式：
                # identities.bot.status == "ready" 表示 bot 凭证已就绪
                bot = data.get("identities", {}).get("bot", {})
                if bot.get("status") == "ready" or bot.get("available"):
                    return True
                # 兼容旧格式
                if data.get("ok"):
                    return True
        except Exception:
            pass
        return False

    # --------- start / stop ---------

    def set_message_handler(self, cb: Callable[[ChannelMessage], None]) -> None:
        self._on_message = cb

    def start(self) -> None:
        """启动后台轮询线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="FeishuPoll", daemon=True)
        self._thread.start()
        print(f"[Feishu] 轮询线程已启动，CLI={self._cli}", flush=True)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[Feishu] 轮询线程已停止", flush=True)

    # --------- 游标持久化 ---------

    def _load_last_ts(self) -> float:
        try:
            if _STATE_FILE.exists():
                ts = float(_STATE_FILE.read_text().strip())
                now = time.time()
                if ts > now:
                    return now - _FIRST_RUN_LOOKBACK_SEC
                if now - ts > _MAX_LOOKBACK_SEC:
                    return now - _FIRST_RUN_LOOKBACK_SEC
                return ts
        except Exception:
            pass
        return time.time() - _FIRST_RUN_LOOKBACK_SEC

    def _save_last_ts(self, ts: float) -> None:
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(str(ts))
        except Exception:
            pass

    def _load_seen_msgs(self) -> set[str]:
        try:
            if _SEEN_FILE.exists():
                data = json.loads(_SEEN_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return set(data[-_SEEN_MAX:])
        except Exception:
            pass
        return set()

    def _save_seen_msgs(self) -> None:
        try:
            _SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            # 只保存最近 2500 条，控制文件大小
            data = list(self._seen_msgs)[-2500:]
            _SEEN_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    # --------- send_reply ---------

    def send_reply(self, peer_id: str, content: str,
                   peer_type: str = "friend", at_sender_id: str = "") -> bool:
        """发送回复。

        friend: peer_id 可以是 chat_id (oc_xxx) 或 open_id (ou_xxx)，
                自动转换为 open_id → --user-id
        group:  peer_id=chat_id (oc_xxx) → --chat-id
        """
        try:
            text = content
            # 群里 @ 指定成员（飞书 <at user_id="ou_xxx"></at>）
            if at_sender_id and peer_type == "group":
                text = f'<at user_id="{at_sender_id}"></at> {content}'
            # 优先 user 身份发送；失败则 fallback bot 身份
            auth_mode = self._best_auth_mode()
            # friend: 用 --user-id；group: 用 --chat-id
            # p2p 会话（oc_xxx）需要先转换成对方 user open_id
            if peer_type == "friend":
                id_flag = "--user-id"
                if peer_id.startswith("oc_") and peer_id in self._p2p_map:
                    send_id = self._p2p_map[peer_id]
                else:
                    send_id = peer_id
            else:
                id_flag = "--chat-id"
                send_id = peer_id
            cmd = [
                self._cli, "im", "+messages-send",
                id_flag, send_id,
                "--text", text,
                "--as", auth_mode,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=30)
            if proc.returncode != 0 and auth_mode == "user":
                # user 身份失败，fallback bot 身份
                cmd[-1] = "bot"
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=30)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[:200]
                print(f"[Feishu] send_reply 失败: {err}", flush=True)
                return False
            return True
        except Exception as e:
            print(f"[Feishu] send_reply 异常: {e}", flush=True)
            return False

    def get_contacts(self) -> list[dict]:
        """获取飞书通讯录 + 群聊列表（纯 lark-cli，不绕 OpenAPI）。

        五步流程：
        1. im +chat-list --types=group → 拉所有群聊
        2. 遍历每个群 → im +chat-members-list → 取群成员
        3. im +chat-list --types=p2p → 拉所有单聊对象
        4. tenant_key 过滤 → 排除组织外的人
        5. 合并去重 → 返回统一 contacts 列表
        """
        result: list[dict] = []
        seen_ids: set = set()
        seen_names: set = set()

        auth_mode = self._best_auth_mode()
        identity_label = "user" if auth_mode == "user" else "bot"
        print(f"[Feishu] get_contacts 使用身份: {identity_label}", flush=True)

        def _run(args):
            proc = subprocess.run(
                [self._cli] + args,
                capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                return None
            try:
                return json.loads(proc.stdout.strip())
            except Exception:
                return None

        def _add_peer(peer_type, peer_id, peer_name, dedup_name=False, extra=None):
            """添加 peer。dedup_name=True 时额外用 peer_name 去重（用于 friend 避免 open_id/chat_id 重复）。
            extra: 额外字段字典（如 open_id/chat_id，用于 send_reply 转换）。"""
            if not peer_id:
                return
            key = (peer_type, peer_id)
            if key in seen_ids:
                return
            clean_name = (peer_name or "").strip()
            if dedup_name and clean_name and clean_name in seen_names:
                return
            seen_ids.add(key)
            if dedup_name and clean_name:
                seen_names.add(clean_name)
            entry = {
                "peer_id": peer_id,
                "peer_name": peer_name or peer_id,
                "peer_type": peer_type,
            }
            if extra:
                entry.update(extra)
            result.append(entry)

        try:
            self_tenant = None
            if auth_mode == "user":
                me = _run(["contact", "+get-user", "--as", "user"])
                if me:
                    user_obj = me.get("data", {}).get("user", {})
                    self_tenant = user_obj.get("tenant_key") or user_obj.get("tenant_key_str")
                    print(f"[Feishu] 自己 tenant_key={self_tenant}", flush=True)

            chats_data = _run([
                "im", "+chat-list", "--types=group", "--page-all", "--as", auth_mode,
            ])
            group_chats = []
            if chats_data:
                chats = chats_data.get("data", {}).get("chats") or chats_data.get("data", {}).get("items", [])
                for chat in chats:
                    chat_id = chat.get("chat_id", "")
                    chat_name = chat.get("name", "") or "未命名群聊"
                    if not chat_id:
                        continue
                    _add_peer("group", chat_id, chat_name)
                    group_chats.append(chat_id)

            if auth_mode == "user":
                p2p_data = _run([
                    "im", "+chat-list", "--types=p2p", "--page-all", "--as", "user",
                ])
                if p2p_data:
                    p2p_chats = p2p_data.get("data", {}).get("chats") or p2p_data.get("data", {}).get("items", [])
                    for chat in p2p_chats:
                        chat_id = chat.get("chat_id", "")
                        chat_name = chat.get("name", "") or ""
                        p2p_open_id = chat.get("p2p_target_id", "")
                        p2p_type = chat.get("p2p_target_type", "")
                        tenant = chat.get("tenant_key", "")
                        if p2p_type == "bot":
                            continue
                        if self_tenant and tenant and tenant != self_tenant:
                            continue
                        friend_id = chat_id or p2p_open_id
                        if friend_id:
                            extra = {"open_id": p2p_open_id, "chat_id": chat_id}
                            _add_peer("friend", friend_id, chat_name, dedup_name=True, extra=extra)
                        if chat_id and p2p_open_id:
                            self._p2p_map[chat_id] = p2p_open_id

            if auth_mode == "user":
                for chat_id in group_chats:
                    members_data = _run([
                        "im", "+chat-members-list",
                        "--chat-id", chat_id,
                        "--page-all", "--as", "user",
                    ])
                    if not members_data:
                        continue
                    bucket = members_data.get("data", {})
                    for u in (bucket.get("users") or []):
                        member_id = u.get("member_id", "") or u.get("open_id", "")
                        name = u.get("name", "") or u.get("localized_name", "")
                        member_tenant = u.get("tenant_key", "")
                        if self_tenant and member_tenant and member_tenant != self_tenant:
                            continue
                        if not member_id:
                            continue
                        _add_peer("friend", member_id, name, dedup_name=True)

        except Exception as e:
            print(f"[Feishu] get_contacts 异常: {e}", flush=True)

        friend_n = sum(1 for c in result if c["peer_type"] == "friend")
        group_n = sum(1 for c in result if c["peer_type"] == "group")
        print(f"[Feishu] get_contacts: {friend_n} 成员 / {group_n} 群聊 (tenant_filter={bool(self_tenant)})", flush=True)
        return result

    def _best_auth_mode(self) -> str:
        """选择最佳可用身份: user > bot。"""
        try:
            proc = subprocess.run(
                [self._cli, "auth", "status", "--json"],
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout.strip())
                identities = data.get("identities", {}) or {}
                user_ident = identities.get("user", {}) or {}
                bot_ident = identities.get("bot", {}) or {}
                if user_ident.get("status") == "ready" or user_ident.get("available"):
                    return "user"
                if bot_ident.get("status") == "ready" or bot_ident.get("available"):
                    return "bot"
        except Exception:
            pass
        return "bot"

    def health_check(self) -> dict:
        """健康检查：lark-cli 已配置凭证即视为已连接。

        返回结构对齐 ChannelClient 协议（含 ok 字段），供 bridge 状态接口统一消费。
        """
        connected = self.connected
        return {
            "channel": self.channel_name,
            "ok": connected,
            "connected": connected,
            "cli_path": self._cli,
            "error": "" if connected else "未绑定飞书机器人",
        }

    def check_required_scopes(self) -> dict:
        """检查 user token 是否包含 MVP 必需的 scope。

        Returns:
            {
                "ok": True/False,
                "scope_ok": True/False,  # 是否完整
                "missing": [...],        # 缺的 scope 列表
                "granted": [...],        # 已有的 scope 列表
                "hint": "...",           # 中文提示
            }
        """
        import json as _json
        cli = self._cli
        if not cli:
            return {"ok": False, "scope_ok": False,
                    "missing": FEISHU_REQUIRED_SCOPES, "granted": [],
                    "hint": "未找到 lark-cli"}
        try:
            r = subprocess.run(
                [cli, "auth", "check", "--scope", " ".join(FEISHU_REQUIRED_SCOPES)],
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
            )
            data = _json.loads(r.stdout)
            missing = data.get("missing") or []
            granted = data.get("granted") or []
            scope_ok = len(missing) == 0
            hint = ""
            if scope_ok:
                hint = "权限完整"
            else:
                hint = f"缺少 {len(missing)} 个必要权限: {', '.join(missing)}。可能是管理员尚未在飞书开放平台完成权限审批，请联系组织管理员后点击「补授权」重新走授权流程。"
            print(f"[Feishu] scope 检查: ok={scope_ok} granted={len(granted)} missing={missing}", flush=True)
            return {
                "ok": True,
                "scope_ok": scope_ok,
                "missing": missing,
                "granted": granted,
                "hint": hint,
            }
        except Exception as e:
            return {"ok": False, "scope_ok": False,
                    "missing": FEISHU_REQUIRED_SCOPES, "granted": [],
                    "hint": f"检查 scope 异常: {e}"}

    # ═══════════════════════════════════════════════════════════
    # 轮询主循环（与企微对齐）
    # ═══════════════════════════════════════════════════════════

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self._connected = self.connected
                if not self._connected:
                    print("[Feishu] connected=False, sleep 30s", flush=True)
                    time.sleep(30)
                    continue
                self._poll_once()
            except Exception as e:
                print(f"[Feishu] 轮询异常: {e}", flush=True)

            interval = (self.POLL_INTERVAL_ACTIVE
                        if time.time() - self._last_msg_ts < self.ACTIVITY_WINDOW
                        else self.POLL_INTERVAL_IDLE)
            self._stop.wait(interval)

    def _poll_once(self):
        now = datetime.now()
        now_ts = time.time()
        begin_ts = max(self._last_processed_ts - _POLL_OVERLAP_SEC,
                       now_ts - _MAX_LOOKBACK_SEC)
        begin = datetime.fromtimestamp(begin_ts)

        import datetime as _dt
        _utc = _dt.timezone.utc
        time_fmt = lambda dt: dt.astimezone(_utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        any_new = False

        try:
            from storage import channels_dao
            bindings = channels_dao.list_all_enabled_peer_occupants("feishu")
            if len(bindings) == 0:
                print("[Feishu] _poll_once: bindings=0, skip", flush=True)
        except Exception as e:
            print(f"[Feishu] 拉绑定列表异常: {e}", flush=True)
            bindings = []

        for b in bindings:
            peer_id = b.get("peer_id", "")
            peer_type = b.get("peer_type", "friend")
            peer_name = b.get("peer_name", "")
            if not peer_id:
                continue
            cnt = self._pull_and_dispatch(peer_id, peer_name, peer_type,
                                          begin, now, time_fmt)
            if cnt:
                any_new = True

        self._last_processed_ts = now_ts
        # 每轮都保存游标，确保重启后从最新位置继续
        self._save_last_ts(self._last_processed_ts)

    def _pull_and_dispatch(self, peer_id: str, peer_name: str, peer_type: str,
                           begin: datetime, end: datetime, time_fmt) -> int:
        """拉取某个会话的新消息并分发。返回实际处理的人类消息数。"""
        auth_mode = self._best_auth_mode()
        try:
            proc = subprocess.run(
                [self._cli, "im", "+chat-messages-list",
                 "--chat-id", peer_id,
                 "--start", time_fmt(begin),
                 "--end", time_fmt(end),
                 "--order", "asc",
                 "--page-size", "50",
                 "--as", auth_mode],
                capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[:200]
                print(f"[Feishu] 拉消息失败 peer_id={peer_id}: {err}", flush=True)
                return 0
            data = json.loads(proc.stdout.strip())
            messages = data.get("data", {}).get("messages", []) if isinstance(data, dict) else []
        except Exception as e:
            print(f"[Feishu] 拉消息异常 peer_id={peer_id}: {e}", flush=True)
            return 0

        dispatched = 0
        for msg in messages:
            message_id = msg.get("message_id", "")
            sender = msg.get("sender", {}) or {}
            sender_id = sender.get("id", "")
            sender_type = sender.get("sender_type", "")  # user / app

            # 自消息过滤：
            # 1. sender_type == "app" 是 bot 身份发的
            # 2. sender.id == self._self_open_id 是 user 身份自己发的（用 --as user 发消息）
            if sender_type == "app":
                continue
            if self._self_open_id and sender_id == self._self_open_id:
                continue

            # 去重
            if message_id and message_id in self._seen_msgs:
                continue
            if message_id:
                self._seen_msgs.add(message_id)
                if len(self._seen_msgs) > _SEEN_MAX:
                    self._seen_msgs = set(list(self._seen_msgs)[-2500:])
                # 持久化去重集合，重启后避免 overlap 窗口内消息重复处理
                self._save_seen_msgs()

            # 解析内容
            msg_type = msg.get("msg_type", "")
            content = ""
            file_name = ""
            media_id = ""  # 飞书叫 file_key

            # 飞书 payload 里非文本消息的 content 是 JSON 字符串
            raw_content_str = msg.get("content", "") or ""
            try:
                content_obj = json.loads(raw_content_str) if raw_content_str.startswith("{") else {}
            except Exception:
                content_obj = {}

            if msg_type == "text":
                content = raw_content_str
            elif msg_type == "audio":
                # voice：飞书 payload 有 Transcript 转写字段（飞书自带 ASR）
                content = content_obj.get("Transcript") or content_obj.get("transcript") or ""
                # 兜底：从文本里截取 [Audio: file_key]
                media_id = content_obj.get("file_key") or ""
                if not media_id:
                    m = re.search(r"\[Audio:\s*(\S+)\]", raw_content_str)
                    if m:
                        media_id = m.group(1)
            elif msg_type in ("image", "file", "video", "media"):
                content = content_obj.get("text") or ""
                # 非文本消息：从 content JSON / 文本标签里解析 file_key（兼容多种 tag 形态）
                media_id = ""
                _patterns = [
                    r"\[" + msg_type.capitalize() + r":\s*(\S+)\]",   # [File: file_xxx]
                    "<" + msg_type + '\\s+key=\\"([^\\"]+)\\"',        # <file key="file_xxx">
                    '<video\\s+key=\\"([^\\"]+)\\"',                   # <video key="file_xxx">
                ]
                for _pat in _patterns:
                    m = re.search(_pat, raw_content_str, re.IGNORECASE)
                    if not m:
                        continue
                    media_id = m.group(1)
                    break
                if not media_id:
                    media_id = content_obj.get("file_key") or content_obj.get("image_key") or ""
                # 文件名
                file_name = ""
                m_name = re.search(r'name="([^"]+)"', raw_content_str)
                if m_name:
                    file_name = m_name.group(1)
                if not file_name:
                    file_name = content_obj.get("file_name") or ""
                if msg_type == "media":
                    msg_type = "video"
            elif msg_type == "audio":
                msg_type = "voice"
            elif msg_type == "interactive":
                # 卡片消息：飞书日程/位置/名片等交互卡片，结构化解析复杂，给用户提示
                content = "[飞书卡片消息: 日程/位置/名片/任务等，请文字描述]"
                msg_type = "card"
            else:
                content = f"[非文本消息: {msg_type}]"

            ts_ms = self._parse_create_time(msg.get("create_time", ""))
            sender_name = sender.get("name", "") or sender_id
            channel_msg = ChannelMessage(
                id=message_id or f"feishu_{peer_id}_{ts_ms}",
                channel="feishu",
                peer_id=peer_id,
                peer_name=peer_name or peer_id,
                peer_type=peer_type,
                sender_id=sender_id,
                sender_name=sender_name,
                content=content,
                msg_type="text" if msg_type == "text" else msg_type,
                is_self=False,
                is_at=False,
                ts_ms=ts_ms,
                file_name=file_name,
                media_id=media_id,
                file_size=0,
                is_ready=False,
            )

            self._last_msg_ts = time.time()
            if not self._on_message:
                continue
            try:
                self._on_message(channel_msg)
                dispatched += 1
            except Exception as e:
                print(f"[Feishu] 消息回调异常: {e}", flush=True)

        return dispatched

    @staticmethod
    def _parse_create_time(s: str) -> int:
        """解析飞书 create_time 字符串为毫秒时间戳。"""
        if not s:
            return int(time.time() * 1000)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return int(datetime.strptime(s, fmt).timestamp() * 1000)
            except Exception:
                continue
        return int(time.time() * 1000)
