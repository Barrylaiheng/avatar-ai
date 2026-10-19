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


def _lark_cli_path() -> str:
    """定位 lark-cli 可执行文件。"""
    import shutil
    p = shutil.which("lark-cli")
    if p:
        return p
    # TRAE 插件自带的 lark-cli
    candidates = [
        r"C:\Users\Administrator\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return "lark-cli"


class FeishuClient:
    """飞书 CLI 客户端：user 身份轮询 + 统一 ChannelClient 接口。"""

    channel_name = "feishu"
    POLL_INTERVAL_ACTIVE = 15.0   # 活跃时 15s 一轮
    POLL_INTERVAL_IDLE = 60.0     # 空闲时 60s 一轮
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
                capture_output=True, text=True, timeout=10, encoding="utf-8"
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
        """发送回复。peer_id: chat_id (oc_xxx)

        优先 user 身份（AI 接管用户账号），user 不可用时 fallback bot 身份。
        """
        try:
            # 群聊需要 @发消息的人
            text = content
            if at_sender_id and peer_type == "group":
                text = f'<at user_id="{at_sender_id}"></at> {content}'

            # 优先 user 身份发送；失败则 fallback bot 身份
            auth_mode = self._best_auth_mode()
            cmd = [
                self._cli, "im", "+messages-send",
                "--chat-id", peer_id,
                "--text", text,
                "--as", auth_mode,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=30, encoding="utf-8")
            if proc.returncode != 0 and auth_mode == "user":
                # user 身份失败，fallback bot 身份
                cmd[-1] = "bot"
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=30, encoding="utf-8")
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[:200]
                print(f"[Feishu] send_reply 失败: {err}", flush=True)
                return False
            return True
        except Exception as e:
            print(f"[Feishu] send_reply 异常: {e}", flush=True)
            return False

    def get_contacts(self) -> list[dict]:
        """获取飞书通讯录 + 群聊列表。

        优先使用 user 身份（第二步 OAuth 授权后），可以拉到组织内所有可见群聊和私聊成员；
        仅当 bot 身份可用时 fallback 到 bot 模式（只能看到 bot 被加入的群）。
        """
        result = []
        auth_mode = self._best_auth_mode()
        identity_label = "user" if auth_mode == "user" else "bot"
        print(f"[Feishu] get_contacts 使用身份: {identity_label}", flush=True)

        try:
            # 1. 拉群聊列表
            proc = subprocess.run(
                [self._cli, "im", "+chat-list", "--page-all", "--as", auth_mode],
                capture_output=True, text=True, timeout=30, encoding="utf-8"
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout.strip())
                chats = data.get("data", {}).get("chats", []) if isinstance(data, dict) else []
                for chat in chats:
                    result.append({
                        "peer_id": chat.get("chat_id", ""),
                        "peer_name": chat.get("name", "") or "未命名群聊",
                        "peer_type": "group",
                        "member_count": chat.get("member_count", 0),
                    })
            else:
                print(f"[Feishu] get_contacts chat-list 失败: {proc.stderr[:200]}", flush=True)

            # 2. user 身份额外拉组织内成员（有过私聊的）
            if auth_mode == "user":
                proc2 = subprocess.run(
                    [self._cli, "contact", "+search-user", "--has-chatted",
                     "--exclude-external-users", "--as", "user"],
                    capture_output=True, text=True, timeout=30, encoding="utf-8"
                )
                if proc2.returncode == 0:
                    data2 = json.loads(proc2.stdout.strip())
                    users = data2.get("data", {}).get("users", []) if isinstance(data2, dict) else []
                    for u in users:
                        name = u.get("localized_name") or u.get("name") or u.get("en_name") or ""
                        p2p_id = u.get("p2p_chat_id", "") or u.get("open_id", "")
                        if not p2p_id:
                            continue
                        result.append({
                            "peer_id": p2p_id,
                            "peer_name": name or p2p_id,
                            "peer_type": "friend",
                        })
                else:
                    print(f"[Feishu] get_contacts search-user 失败: {proc2.stderr[:200]}", flush=True)

        except Exception as e:
            print(f"[Feishu] get_contacts 异常: {e}", flush=True)
        return result

    def _best_auth_mode(self) -> str:
        """选择最佳可用身份: user > bot。"""
        try:
            proc = subprocess.run(
                [self._cli, "auth", "status", "--json"],
                capture_output=True, text=True, timeout=10, encoding="utf-8"
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

    # ═══════════════════════════════════════════════════════════
    # 轮询主循环（与企微对齐）
    # ═══════════════════════════════════════════════════════════

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self._connected = self.connected
                if not self._connected:
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
        time_fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")
        any_new = False

        try:
            from storage import channels_dao
            bindings = channels_dao.list_all_enabled_peer_occupants("feishu")
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
                capture_output=True, text=True, timeout=30, encoding="utf-8"
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

            # 解析内容（+chat-messages-list 的 text 消息 content 是纯文本字符串）
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
                # 兜底：没有转写就留空，Pipeline _preprocess_voice 会占位
                media_id = content_obj.get("file_key") or ""
            elif msg_type in ("image", "file"):
                content = content_obj.get("text") or ""
                media_id = content_obj.get("file_key") or ""
                file_name = content_obj.get("file_name") or ""
            elif msg_type == "video":
                content = content_obj.get("text") or ""
                media_id = content_obj.get("file_key") or ""
            else:
                content = f"[非文本消息: {msg_type}]"

            # 时间戳解析（create_time 格式 "2026-09-12 14:53"）
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
                file_size=0,              # 🆕 media_downloader 下载后补
                is_ready=False,           # 🆕
            )

            self._last_msg_ts = time.time()
            if self._on_message:
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
