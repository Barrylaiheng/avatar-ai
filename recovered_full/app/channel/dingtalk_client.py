"""钉钉智能机器人客户端：dws user 身份轮询模式。

与企微/飞书对齐的通信模型：
- 收消息：user 身份 + chat message list 定时轮询已绑定会话
- 发消息：user 身份 + chat message send
- 通讯录：chat +conversation-list + +my-groups（区分单聊/群聊）
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .base import ChannelMessage

# ═══════════════════════════════════════════════════════════
# 钉钉特化常量
# ═══════════════════════════════════════════════════════════

# 凭证目录：dws 配置存在 ~/.dws/
_CONFIG_DIR = Path.home() / ".dws"
_IDENTITY_FILE = _CONFIG_DIR / "identity.json"

# 去重集合上限
_SEEN_MAX = 5000

# 轮询游标持久化文件
_STATE_FILE = Path.home() / ".config" / "dingtalk" / ".last_processed"

# 去重集合持久化文件
_SEEN_FILE = Path.home() / ".config" / "dingtalk" / ".seen_msgs"

# 首次运行回看窗口（秒）：第一次启动时往前拉 10 分钟
_FIRST_RUN_LOOKBACK_SEC = 600

# 每次轮询回看重叠（从上一次处理时间往前再拉 60 秒防漏）
_POLL_OVERLAP_SEC = 60

# API 最大回看
_MAX_LOOKBACK_SEC = 7 * 24 * 3600

# AI 生成内容标记：仅用于发送时给回复打上可读声明，不再作为 self-filter 依据
_AI_MARKER = "（AI 生成内容）"

# dws CLI 发送的消息会带 messageAiSendFlag（实测值 "DWS"），
# 与文本是否含 _AI_MARKER 无关，是 self-filter 的主判据

# 鉴权状态缓存时长（秒），避免 connected 每次探测都起子进程
_AUTH_CACHE_TTL_SEC = 30.0


def _dws_cli_path() -> str:
    """定位 dws 可执行文件。"""
    import shutil
    import os
    p = shutil.which("dws") or shutil.which("dws.exe")
    if p:
        return p
    candidates = [
        os.path.expandvars(r"%USERPROFILE%\.local\bin\dws.exe"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Microsoft\WindowsApps\dws.exe"),
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return "dws"


class DingtalkClient:
    """钉钉 CLI 客户端：user 身份轮询 + 统一 ChannelClient 接口。"""

    channel_name = "dingtalk"
    POLL_INTERVAL_ACTIVE = 5.0    # 活跃时 5s 一轮
    POLL_INTERVAL_IDLE = 20.0     # 空闲时 20s 一轮
    ACTIVITY_WINDOW = 300.0       # 5 分钟内有新消息算活跃

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self._on_message: Optional[Callable[[ChannelMessage], None]] = None
        self._seen_msgs: set[str] = self._load_seen_msgs()
        self._last_msg_ts = 0.0
        self._cli = _dws_cli_path()
        # 轮询游标：上次处理到的时间戳
        self._last_processed_ts = self._load_last_ts()
        # 已绑定的 peer 列表（从 channels_dao 加载）
        self._bound_peers: list[dict] = []
        # 鉴权状态缓存（auth status 结果 + 上次探测时间）
        self._auth_info: Optional[dict] = None
        self._auth_checked_at = 0.0
        # 本账号 openDingTalkId（self-filter 兜底，懒解析 + 缓存）
        self._self_open_id = ""
        self._self_open_id_resolved = False

    # --------- 连接状态 ---------

    def auth_status(self, refresh: bool = False) -> dict:
        """返回 dws 实时鉴权信息（含 authenticated / user_name / corp_name）。

        带 TTL 缓存，refresh=True 时强制重新探测。
        未绑定（无 identity.json）时返回空 dict。
        """
        if not _IDENTITY_FILE.exists():
            return {}
        now = time.time()
        with self._lock:
            fresh = self._auth_info is not None and (now - self._auth_checked_at) < _AUTH_CACHE_TTL_SEC
        if refresh or not fresh:
            self._refresh_auth()
        with self._lock:
            return dict(self._auth_info or {})

    def _refresh_auth(self) -> None:
        """探测一次 dws auth status 并写入缓存。"""
        ok, data, _ = self._cli_run("auth", "status", timeout=10)
        with self._lock:
            if ok and isinstance(data, dict) and "authenticated" in data:
                self._auth_info = data
            elif self._auth_info is None:
                # 探测失败且无历史结果：置空，交由 connected 回退判断
                self._auth_info = {}
            self._auth_checked_at = time.time()

    @property
    def connected(self) -> bool:
        """检查钉钉是否可用：已绑定（identity.json）且鉴权有效。

        以 dws auth status 的 authenticated 为准，不再只凭 identity.json 存在；
        若 CLI 探测不出结论（网络/超时），回退为“已绑定即连接”，避免误判离线。
        """
        if not _IDENTITY_FILE.exists():
            return False
        info = self.auth_status()
        if "authenticated" not in info:
            return True
        return bool(info.get("authenticated"))

    # --------- start / stop ---------

    def set_message_handler(self, cb: Callable[[ChannelMessage], None]) -> None:
        self._on_message = cb

    def start(self) -> None:
        """启动后台轮询线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="DingtalkPoll", daemon=True)
        self._thread.start()
        print(f"[Dingtalk] 轮询线程已启动，CLI={self._cli}，绑定={len(self._bound_peers)} 个 peer", flush=True)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[Dingtalk] 轮询线程已停止", flush=True)

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
            # 与 _load_seen_msgs 的上限保持一致（同为 _SEEN_MAX）
            data = list(self._seen_msgs)[-_SEEN_MAX:]
            _SEEN_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def _trim_seen_msgs(self) -> None:
        """超上限时滑窗裁剪，避免长时间运行内存无界增长。"""
        if len(self._seen_msgs) > _SEEN_MAX * 2:
            self._seen_msgs = set(list(self._seen_msgs)[-_SEEN_MAX:])

    # --------- CLI 调用 ---------

    def _cli_run(self, *args, timeout: int = 30) -> tuple[bool, dict | None, str]:
        """调用 dws CLI，返回 (ok, data_dict, error_msg)。"""
        cmd = [self._cli] + list(args) + ["--format", "json"]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8"
            )
            out = (proc.stdout or "").strip()
            if not out:
                out = (proc.stderr or "").strip()
            if not out:
                return False, None, "CLI 无输出"
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                return False, None, f"非 JSON 输出: {out[:200]}"
            # dws 错误格式：{"error": {...}}
            if isinstance(data, dict) and "error" in data:
                err = data["error"]
                msg = err.get("message") or err.get("reason") or str(err)
                return False, data, msg
            return True, data, ""
        except subprocess.TimeoutExpired:
            return False, None, f"CLI 超时 ({timeout}s)"
        except Exception as e:
            return False, None, str(e)

    # --------- 联系人 ---------

    def get_contacts(self) -> list[dict]:
        """获取钉钉会话列表（单聊 + 群聊）。"""
        if not self.connected:
            return []
        # 1. 拉群聊（有 memberCount）
        group_ids: dict[str, int] = {}
        ok_g, data_g, _ = self._cli_run(
            "chat", "+my-groups", "--page-all", "--limit", "100", timeout=30
        )
        if ok_g and isinstance(data_g, dict):
            for g in data_g.get("groups", []):
                cid = g.get("conversationId", "")
                if cid:
                    group_ids[cid] = g.get("memberCount", 0)

        # 2. 拉全量会话
        ok, data, _ = self._cli_run(
            "chat", "+conversation-list", "--page-all", "--limit", "100", timeout=30
        )
        if not ok or not isinstance(data, dict):
            return []

        contacts = []
        for c in data.get("conversations", []):
            cid = c.get("openConversationId", "")
            cname = c.get("conversationName", "")
            if not cid:
                continue
            # 跳过系统通知类会话
            if cname.startswith("工作通知") or cname.startswith("主页通知"):
                continue
            if cid in group_ids:
                contacts.append({
                    "peer_type": "group",
                    "peer_id": cid,
                    "peer_name": cname or cid[:20],
                    "member_count": group_ids.get(cid, 0),
                })
            else:
                contacts.append({
                    "peer_type": "friend",
                    "peer_id": cid,
                    "peer_name": cname or cid[:20],
                })
        return contacts

    # --------- 发消息 ---------

    def send_reply(self, peer_id: str, content: str,
                   peer_type: str = "friend", at_sender_id: str = "") -> bool:
        """发送回复。peer_id: openConversationId。"""
        if not self.connected:
            return False
        # 给回复打上可读的 AI 声明（self-filter 已改为结构化判定，不依赖该标记）
        text = content
        if _AI_MARKER not in text:
            text = content + "\n" + _AI_MARKER
        try:
            ok, data, err = self._cli_run(
                "chat", "message", "send",
                "--conversation-id", peer_id,
                "--content", text,
                timeout=30,
            )
            if ok:
                print(f"[Dingtalk] 发送成功 peer={peer_id[:20]}", flush=True)
                return True
            print(f"[Dingtalk] 发送失败: {err}", flush=True)
            return False
        except Exception as e:
            print(f"[Dingtalk] 发送异常: {e}", flush=True)
            return False

    # --------- self 身份判定 ---------

    def _get_self_open_id(self) -> str:
        """解析本账号 openDingTalkId（懒解析 + 缓存）。"""
        if not self._self_open_id_resolved:
            self._self_open_id = self._resolve_self_open_id()
            self._self_open_id_resolved = True
        return self._self_open_id

    def _resolve_self_open_id(self) -> str:
        """通过 auth status 拿姓名，再 search-user 解析 openDingTalkId。"""
        info = self.auth_status()
        user_id = str(info.get("user_id") or "")
        name = info.get("user_name") or ""
        if not name:
            return ""
        ok, data, _ = self._cli_run(
            "contact", "+search-user", "--query", name, timeout=15
        )
        if not ok or not isinstance(data, dict):
            return ""
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        users = payload.get("users") or []
        if not isinstance(users, list):
            return ""
        for u in users:
            if user_id and str(u.get("userId") or "") == user_id:
                return u.get("openDingTalkId") or ""
        # 无 userId 可比对、且结果唯一时才退取第一个
        if len(users) == 1:
            return users[0].get("openDingTalkId") or ""
        return ""

    def _is_self_message(self, m: dict) -> bool:
        """判断消息是否由本端（AI / dws CLI）发出。

        主判据：messageAiSendFlag 非空——dws CLI 发送的消息必带该结构化标记，
        与文本是否含 _AI_MARKER 无关（历史版本存在漏打标记的回复）。
        兜底：senderId 等于本账号 openDingTalkId。
        """
        if m.get("messageAiSendFlag"):
            return True
        sender_id = m.get("senderId") or m.get("senderOpenDingTalkId") or ""
        if sender_id:
            self_id = self._get_self_open_id()
            if self_id and sender_id == self_id:
                return True
        return False

    # --------- 轮询 ---------

    def _poll_loop(self) -> None:
        """后台轮询循环。"""
        # 启动时加载已绑定的 peer
        self._reload_bound_peers()
        consecutive_errors = 0
        # 连接状态边沿检测：仅在翻转时打日志，便于事后追溯断连
        prev_connected: Optional[bool] = None
        while not self._stop.is_set():
            try:
                is_connected = self.connected
                if prev_connected is None:
                    print(f"[Dingtalk] 轮询启动，连接状态={is_connected}", flush=True)
                elif is_connected != prev_connected:
                    print(
                        f"[Dingtalk] 连接状态变化: {prev_connected} → {is_connected}",
                        flush=True,
                    )
                prev_connected = is_connected
                if not is_connected:
                    self._stop.wait(30)
                    continue
                # 每次轮询前重新加载绑定列表（支持运行时变更）
                self._reload_bound_peers()
                if not self._bound_peers:
                    self._stop.wait(self.POLL_INTERVAL_IDLE)
                    continue
                new_count = self._poll_once()
                if new_count > 0:
                    consecutive_errors = 0
                    self._last_msg_ts = time.time()
                    self._stop.wait(self.POLL_INTERVAL_ACTIVE)
                else:
                    # 空闲判断
                    if time.time() - self._last_msg_ts < self.ACTIVITY_WINDOW:
                        self._stop.wait(self.POLL_INTERVAL_ACTIVE)
                    else:
                        self._stop.wait(self.POLL_INTERVAL_IDLE)
            except Exception as e:
                consecutive_errors += 1
                print(f"[Dingtalk] 轮询异常 (连续{consecutive_errors}次): {e}", flush=True)
                self._stop.wait(min(30, 5 * consecutive_errors))

    def _reload_bound_peers(self) -> None:
        """从数据库加载所有已启用的钉钉绑定。"""
        try:
            from storage import channels_dao
            self._bound_peers = channels_dao.list_all_enabled_peer_occupants("dingtalk")
        except Exception as e:
            print(f"[Dingtalk] 加载绑定列表失败: {e}", flush=True)
            self._bound_peers = []

    def _poll_once(self) -> int:
        """轮询一次所有已绑定 peer，返回新消息数。"""
        if not self._bound_peers:
            return 0

        # 计算拉取起始时间（上次处理时间 - 重叠窗口，且不早于 API 最大回看）
        now_ts = time.time()
        start_ts = max(self._last_processed_ts - _POLL_OVERLAP_SEC,
                       now_ts - _MAX_LOOKBACK_SEC)
        start_time_str = datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S")

        new_count = 0
        pull_error = False
        for peer in self._bound_peers:
            peer_id = peer.get("peer_id", "")
            peer_type = peer.get("peer_type", "friend")
            peer_name = peer.get("peer_name", "")
            if not peer_id:
                continue
            try:
                msgs = self._pull_messages(peer_id, start_time_str)
                if msgs is None:
                    # 拉取失败：本轮不推进游标，让该时间窗在下一轮被重新覆盖
                    pull_error = True
                    continue
                for m in msgs:
                    msg_id = m.get("messageId") or m.get("openMessageId", "")
                    if not msg_id or msg_id in self._seen_msgs:
                        continue
                    text = m.get("text") or m.get("content", "")
                    # self-filter：跳过本端（AI / dws CLI）发出的消息，避免回声
                    if self._is_self_message(m):
                        self._seen_msgs.add(msg_id)
                        continue
                    sender_name = m.get("sender", "")
                    sender_id = m.get("senderId") or m.get("senderOpenDingTalkId", "")
                    create_time_str = m.get("createTime", "")
                    ts_ms = self._parse_time_to_ms(create_time_str)

                    # 钉钉消息类型识别（原生 CLI 返回的字段）
                    raw_msgtype = (
                        m.get("msgType")
                        or m.get("msgtype")
                        or m.get("messageType")
                        or "text"
                    ).strip().lower()
                    type_map = {
                        "text": "text",
                        "textmessage": "text",
                        "voice": "voice",
                        "audiomessage": "voice",
                        "image": "image",
                        "imagemessage": "image",
                        "video": "video",
                        "videomessage": "video",
                        "file": "file",
                        "filemessage": "file",
                    }
                    msg_type = type_map.get(raw_msgtype, raw_msgtype or "other")
                    # -------- 统一提取所有非文本消息的元数据 --------
                    # 钉钉 payload 里 content 是嵌套 dict，包含 recognition / downloadCode 等
                    file_name = ""
                    media_id = ""
                    # 钉钉 payload 里 content 可能是 dict（非文本）或 str（文本）
                    raw_content_obj = m.get("content")
                    if isinstance(raw_content_obj, str):
                        # 字符串：可能是文件名（file）或空
                        content_text = raw_content_obj
                    elif isinstance(raw_content_obj, dict):
                        content_text = raw_content_obj.get("text", "") or ""
                    else:
                        content_text = ""

                    # voice：转写字段 recognition（钉钉自带 ASR）
                    if msg_type == "voice" and isinstance(raw_content_obj, dict):
                        recognition = raw_content_obj.get("recognition") or ""
                        if recognition:
                            text = recognition  # 替换成转写文本，Pipeline _preprocess_voice 会直接用

                    # voice/image/video/file 都有 downloadCode（统一提取）
                    if msg_type in ("voice", "image", "video", "file"):
                        # downloadCode 可能在 content 子对象，也可能在顶层
                        media_id = (
                            (raw_content_obj.get("downloadCode") if isinstance(raw_content_obj, dict) else None)
                            or m.get("downloadCode")
                            or m.get("mediaId")
                            or m.get("media_id")
                            or m.get("fileId")
                            or ""
                        )
                        # 文件名：file 有 fileName，image/video 可能没有
                        if msg_type == "file":
                            file_name = (
                                m.get("fileName")
                                or m.get("filename")
                                or (raw_content_obj.get("fileName") if isinstance(raw_content_obj, dict) else None)
                                or ""
                            )
                            if not file_name and content_text and "." in content_text:
                                file_name = content_text

                    cm = ChannelMessage(
                        id=msg_id,
                        channel="dingtalk",
                        peer_id=peer_id,
                        peer_name=peer_name,
                        peer_type=peer_type,
                        sender_id=sender_id,
                        sender_name=sender_name,
                        content=text,
                        msg_type=msg_type,
                        is_self=False,
                        is_at=False,
                        ts_ms=ts_ms,
                        file_name=file_name,
                        media_id=media_id,
                        file_size=0,              # 🆕 media_downloader 下载后补
                        is_ready=False,           # 🆕
                    )
                    self._seen_msgs.add(msg_id)
                    if self._on_message:
                        self._on_message(cm)
                    new_count += 1
            except Exception as e:
                pull_error = True
                print(f"[Dingtalk] 拉取 peer={peer_id[:20]} 失败: {e}", flush=True)

        # 更新游标：仅当本轮所有 peer 拉取成功时才推进到当前时间。
        # 若有 peer 拉取失败，保留上次游标，避免失败窗口内的消息被静默跳过。
        if pull_error:
            kept = datetime.fromtimestamp(self._last_processed_ts).strftime("%Y-%m-%d %H:%M:%S")
            print(f"[Dingtalk] 本轮存在拉取失败，游标保持 {kept}，下轮重试该窗口", flush=True)
        else:
            self._last_processed_ts = time.time()
            self._save_last_ts(self._last_processed_ts)
        if new_count > 0:
            self._trim_seen_msgs()
            self._save_seen_msgs()
        return new_count

    def _pull_messages(self, peer_id: str, start_time_str: str) -> list[dict] | None:
        """拉取某个会话的新消息。

        返回 None 表示拉取失败（区别于「拉取成功但没有新消息」的空列表），
        以便调用方在失败时不推进游标。
        """
        ok, data, err = self._cli_run(
            "chat", "message", "list",
            "--conversation-id", peer_id,
            "--time", start_time_str,
            "--direction", "newer",
            "--limit", "50",
            timeout=30,
        )
        if not ok or not isinstance(data, dict):
            if err:
                print(f"[Dingtalk] 拉消息失败 peer={peer_id[:20]}: {err}", flush=True)
            return None
        return data.get("messages", [])

    @staticmethod
    def _parse_time_to_ms(time_str: str) -> int:
        """将 'yyyy-MM-dd HH:mm:ss' 转为毫秒时间戳。"""
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp() * 1000)
        except Exception:
            return int(time.time() * 1000)

    # --------- 健康检查 ---------

    def health_check(self) -> dict:
        """健康检查：复用实时鉴权缓存（TTL 内不重复探测 CLI）。

        刻意不传 refresh=True 强制探测：状态接口会被 UI 低频轮询，
        强制探测等于每次轮询都起一个 dws 子进程；鉴权缓存 30s 过期已足够。
        """
        if not _IDENTITY_FILE.exists():
            return {"channel": self.channel_name, "ok": False, "error": "钉钉未绑定"}
        info = self.auth_status()
        if "authenticated" in info:
            authed = bool(info.get("authenticated"))
            return {
                "channel": self.channel_name,
                "ok": authed,
                "corp_name": info.get("corp_name", ""),
                "user_name": info.get("user_name", ""),
                "error": "" if authed else "认证失效",
            }
        return {"channel": self.channel_name, "ok": False, "error": "认证检查失败"}
