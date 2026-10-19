"""企微智能机器人客户端：CLI 轮询模式。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  【CLI 渠道模板 - 飞书/Lark 复制指南】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  复制此文件 → 改名 feishu_client.py → 创建 FeishuClient

  需要改的地方（共 7 处，全部标了 ✏️）：

  ① 常量区（文件顶部）
     - _STATE_FILE                  → ~/.config/lark/.last_processed
     - _MAX_LOOKBACK_SEC            → 飞书 API 回看限制（企微是 7 天，飞书可能不同）
     - _FIRST_RUN_LOOKBACK_SEC      → 保持 600（10 分钟，通用）
     - _POLL_OVERLAP_SEC            → 保持 60（通用）
     - POLL_INTERVAL_ACTIVE / IDLE  → 保持（15s / 60s，通用）

  ② _feishu_cli_path()              → 换 CLI 命令名 + fallback 路径

  ③ connected property             → 改凭证文件路径（飞书 credential 文件位置）

  ④ _cli_run 里的 JSON-RPC 解析     → 企微返回 result.content[0].text，飞书 CLI 结构可能相同也可能不同

  ⑤ _is_self_message                → 企微用 userid 带 @ 判断，飞书用 bot_open_id 或 chat_type

  ⑥ _poll_once 里的 CLI 子命令      → 企微：msg get_message / contact get_userlist / msg get_msg_chat_list
                                        飞书 CLI 命令名可能完全不同，需要查文档

  ⑦ send_reply 的 JSON 结构         → 企微：{chat_type, chatid, msgtype, text:{content}}
                                        飞书消息发送 API 的 JSON 结构需要查

  不需要改的（模板骨架）：
  - _poll_loop（分级间隔 + try/except 自愈 + 游标持久化）
  - _load_last_ts / _save_last_ts（游标持久化）
  - _seen_msgs 去重集合（含 10000 条上限 + 滑动窗口降级）
  - set_message_handler / start / stop（线程管理）
  - health_check（通用结构）
  - ChannelMessage 构造逻辑（chat_type → peer_type 映射）
  - Pipeline 接入方式（在 bridge.__init__ 创建、bridge.start 启动、bridge.shutdown 停）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .base import ChannelMessage, ChannelClient

# ═══════════════════════════════════════════════════════════
# 【模板骨架 - 常量】飞书复制时只改 ✏️ 处
# ═══════════════════════════════════════════════════════════

# ✏️ 凭证/游标文件所在目录（企微 ~/.config/wecom/，飞书改成 ~/.config/lark/）
_STATE_FILE = Path.home() / ".config" / "wecom" / ".last_processed"

# 首次启动回看窗口（只拉最近 10 分钟，避免重放历史造成循环）
_FIRST_RUN_LOOKBACK_SEC = 600

# 每次轮询回看重叠（从上一次处理时间往前再拉 60 秒防漏）
_POLL_OVERLAP_SEC = 60

# ✏️ API 最大回看（企微 7 天，飞书可能不同）
_MAX_LOOKBACK_SEC = 7 * 24 * 3600


# ═══════════════════════════════════════════════════════════
# 【企微特化 - CLI 定位】飞书复制时改成 _feishu_cli_path()
# ═══════════════════════════════════════════════════════════

def _wecom_cli_path() -> str:
    """定位 wecom-cli 可执行文件。

    优先级：PyInstaller 内置 → PATH → 常见 npm 路径。
    wecom-cli.exe 是 @wecom/cli platform-specific 包预编译的 9.6MB 自包含 PE32，
    spec 里已硬打进 EXE 到 sys._MEIPASS/channels/wecom/wecom-cli.exe。
    """
    import shutil
    import sys
    import os
    # ① PyInstaller 内置（exe 解包目录）
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "channels", "wecom", "wecom-cli.exe")
        if os.path.exists(bundled):
            return bundled
    # ② PATH 里的命令
    p = shutil.which("wecom-cli") or shutil.which("wecom-cli.cmd")
    if p:
        return p
    # ③ 常见 npm 安装路径
    candidates = [
        os.path.expandvars(r"%APPDATA%\npm\node_modules\@wecom\cli\node_modules\@wecom\cli-win32-x64\bin\wecom-cli.exe"),
        os.path.expandvars(r"%APPDATA%\npm\wecom-cli.cmd"),
        os.path.expandvars(r"%ProgramFiles%\nodejs\wecom-cli.cmd"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Roaming\npm\wecom-cli.cmd"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return "wecom-cli"


# ═══════════════════════════════════════════════════════════
# 【模板骨架 - ChannelClient 实现】
# ═══════════════════════════════════════════════════════════

class WecomClient:
    """企微 CLI 客户端：后台轮询线程 + 统一 ChannelClient 接口。"""

    channel_name = "wecom"           # ✏️ 飞书改成 "feishu"
    POLL_INTERVAL_ACTIVE = 5.0       # 活跃时 5s 一轮（企微 v1.2+ 单次 CLI ~1s，可调密）
    POLL_INTERVAL_IDLE = 20.0        # 空闲时 20s 一轮
    ACTIVITY_WINDOW = 300.0          # 5 分钟内有新消息算活跃（通用）

    def __init__(self):
        # 以下全部是模板骨架，飞书复制不动
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self._on_message: Optional[Callable[[ChannelMessage], None]] = None
        self._seen_msgs: set[str] = set()
        self._recently_sent = set()
        self._last_msg_ts = 0.0
        # ✏️ 飞书改成 _feishu_cli_path()
        self._cli = _wecom_cli_path()
        self._last_processed_ts = self._load_last_ts()

        # 健康状态追踪（health_check 三态判定用）
        self._start_ts = time.time()
        self._last_success_ts = 0.0
        self._last_error = ""
        self._consecutive_failures = 0

    @property
    def connected(self) -> bool:
        """检查凭证文件是否存在 → 飞书改成检查飞书的 credential 文件路径。"""
        # ✏️ 飞书：Path.home().joinpath(".config/lark/xxx.credential").exists()
        return Path.home().joinpath(".config/wecom/credentials.enc").exists()

    # --------- 持久化游标（模板骨架） ---------

    def _load_last_ts(self) -> float:
        """加载上次处理到的时间戳。首次启动返回 'now - 10min'。"""
        if _STATE_FILE.exists():
            try:
                ts = float(_STATE_FILE.read_text(encoding="utf-8").strip())
                # 安全边界：不能超过 API 回看上限，不能在未来
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
            _STATE_FILE.write_text(str(ts), encoding="utf-8")
        except Exception:
            pass

    # --------- start / stop（模板骨架） ---------

    def set_message_handler(self, cb: Callable[[ChannelMessage], None]) -> None:
        self._on_message = cb

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="WecomPoll", daemon=True)
        self._thread.start()
        print(f"[Wecom] 轮询线程已启动，CLI={self._cli}，绑定={'是' if self._connected else '否'}，"
              f"回看={int((time.time() - self._last_processed_ts) / 60)}min", flush=True)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._save_last_ts(self._last_processed_ts)
        self.reset_state()
        print("[Wecom] 轮询线程已停止，游标已保存", flush=True)

    def reset_state(self) -> None:
        """解绑/重绑时调用，清空状态追踪残留（避免 health_check 读到上一轮的 failure 计数）。"""
        self._last_success_ts = 0.0
        self._last_error = ""
        self._consecutive_failures = 0

    # --------- send_reply（企微特化，飞书改 JSON 结构） ---------

    def send_reply(self, peer_id: str, content: str,
                   peer_type: str = "friend", at_sender_id: str = "") -> bool:
        """发送回复。peer_id: userid（单聊）或 chat_id（群聊）。

        wecom-cli v1.2+ 新命令：message send
          参数: chat_id + msg_type + text.content
        （旧命令 msg send_message 已废弃）
        """
        try:
            ok, raw, err = self._cli_run("message", "send", json_params={
                "chat_id": peer_id,
                "msg_type": "text",
                "text": {"content": content},
            })
            if not ok:
                print(f"[Wecom] send_reply 失败: {err or raw}", flush=True)
                return False
            # 记录最近发过的文本：轮询会把这条再拉回来，靠它去重防二次回复
            self._recently_sent.add(content.strip())
            if len(self._recently_sent) > 200:
                self._recently_sent = set(list(self._recently_sent)[-100:])
            return True
        except Exception as e:
            print(f"[Wecom] send_reply 异常: {e}", flush=True)
            return False

    def health_check(self) -> dict:
        """健康检查：三态判定。

        状态逻辑：
          1. enc 文件不存在 → state="unbound"（未绑定）
          2. enc 文件存在 AND (从未成功 OR 连续失败 >=3) → state="auth_expired"（需重新授权）
          3. enc 文件存在 AND 最近成功过 → state="connected"（已连接）

        轮询循环负责维护 _last_success_ts / _last_error / _consecutive_failures 三个字段，
        health_check 只读，不新起 CLI 子进程（前端 15s 轮询一次，省资源）。
        """
        enc_exists = Path.home().joinpath(".config/wecom/credentials.enc").exists()
        now = time.time()

        if not enc_exists:
            return {
                "channel": self.channel_name,
                "state": "unbound",
                "ok": False,
                "connected": False,
                "cli_path": self._cli,
                "error": "未绑定企微机器人",
                "last_success_ts": 0,
                "consecutive_failures": 0,
            }

        never_succeeded = (self._last_success_ts == 0)
        stable_failure = (self._consecutive_failures >= 3)
        boot_grace_passed = (now - self._start_ts > 90)
        if (never_succeeded and boot_grace_passed) or stable_failure:
            state = "auth_expired"
        else:
            state = "connected"

        ok = (state == "connected")
        error = "" if ok else (self._last_error or "授权可能已过期，请重新扫码绑定")
        return {
            "channel": self.channel_name,
            "state": state,
            "ok": ok,
            "connected": ok,
            "cli_path": self._cli,
            "error": error,
            "last_success_ts": self._last_success_ts,
            "consecutive_failures": self._consecutive_failures,
        }

    # ═══════════════════════════════════════════════════════════
    # 【模板骨架 - CLI 调用 + 轮询框架】
    # ═══════════════════════════════════════════════════════════

    def _cli_run(self, *args, json_params: dict | None = None,
                 timeout: int = 30) -> tuple[bool, dict, str]:
        """统一封装：调 CLI 子命令并解析 JSON 输出 → (ok, data_dict_or_empty, err_msg).

        企微 CLI v1.2+ 两种返回格式都要兼容：
          ① 新格式（直接业务 JSON）：{messages: [...], chats: [...], extra_identity_context: "..."}
          ② 老格式（JSON-RPC 外壳）：{result: {content: [{text: "{...json...}"}]}}
        """
        cli_path = self._cli
        cmd = [cli_path] + list(args)
        if json_params is not None:
            cmd += ["--json", json.dumps(json_params, ensure_ascii=False)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, None, f"wecom-cli 超时（{timeout}s）"
        except Exception as e:
            return False, None, f"wecom-cli 调用失败: {e}"

        raw = (proc.stdout or proc.stderr or "").strip()
        if proc.returncode != 0:
            return False, None, (proc.stderr or raw or "wecom-cli 返回非零状态").strip()[:200]

        try:
            parsed = json.loads(raw)
        except Exception:
            return False, None, f"wecom-cli 输出解析失败: {raw[:100]}"

        # 判断是新格式还是老格式
        if isinstance(parsed, dict) and "result" in parsed:
            # 老格式：JSON-RPC 外壳
            content = parsed.get("result", {}).get("content", [])
            if content and isinstance(content[0], dict):
                text = content[0].get("text", "")
                try:
                    return True, json.loads(text), ""
                except Exception:
                    return True, {}, ""
            return True, {}, ""
        else:
            # 新格式：直接业务 JSON
            return True, parsed, ""

    # --------- 轮询主循环（模板骨架） ---------

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self._connected = self.connected
                if not self._connected:
                    time.sleep(30)
                    continue

                self._poll_once()
            except Exception as e:
                # 线程自愈：异常只跳过这一轮，不退出
                print(f"[Wecom] 轮询异常: {e}", flush=True)

            interval = (self.POLL_INTERVAL_ACTIVE
                        if time.time() - self._last_msg_ts < self.ACTIVITY_WINDOW
                        else self.POLL_INTERVAL_IDLE)
            self._stop.wait(interval)

    # ═══════════════════════════════════════════════════════════
    # 【企微特化 - 单次轮询逻辑】飞书复制时改 CLI 子命令名
    # ═══════════════════════════════════════════════════════════

    def _poll_once(self):
        now = datetime.now()
        now_ts = time.time()
        begin_ts = max(self._last_processed_ts - _POLL_OVERLAP_SEC,
                       now_ts - _MAX_LOOKBACK_SEC)
        begin = datetime.fromtimestamp(begin_ts)
        time_fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")
        any_new_human_msg = False
        poll_ok = False
        poll_error = ""

        # 1. 拉单聊（绑定的联系人）
        try:
            from storage import channels_dao
            bindings = channels_dao.list_all_enabled_peer_occupants("wecom")
            for b in bindings:
                userid = b.get("peer_id", "")
                if not userid:
                    continue
                new_count, cli_ok, cli_err = self._pull_and_dispatch(1, userid, userid, begin, now, time_fmt)
                if new_count:
                    any_new_human_msg = True
                if cli_ok:
                    poll_ok = True
                    continue
                if poll_error:
                    continue
                if cli_err:
                    poll_error = cli_err
        except Exception as e:
            print(f"[Wecom] 拉单聊绑定异常: {e}", flush=True)
            if not poll_error:
                poll_error = str(e)

        # 2. 拉群聊会话列表
        # wecom-cli v1.2+：chat groups list（旧命令 msg get_msg_chat_list 已废弃）
        # 注意：chat groups list 本来就只返回群聊，不需要 chat_type 字段
        ok_chats, chats_raw, err_chats = self._cli_run("chat", "groups", "list", json_params={
            "begin_time": time_fmt(begin),
            "end_time": time_fmt(now),
        })
        if ok_chats and isinstance(chats_raw, dict):
            poll_ok = True
        else:
            if not poll_error:
                poll_error = err_chats
            print(f"[Wecom] 拉群聊列表失败: {err_chats}", flush=True)
            chats_raw = {}
        for chat in chats_raw.get("chats", []):
            chat_id = chat.get("chat_id", "")
            chat_name = chat.get("chat_name", "")
            if not chat_id:
                continue
            # chat groups list 只返回群聊，固定 chat_type=2
            new_count, cli_ok, cli_err = self._pull_and_dispatch(2, chat_id, chat_name, begin, now, time_fmt)
            if new_count:
                any_new_human_msg = True
            if cli_ok:
                poll_ok = True
                continue
            if poll_error:
                continue
            if cli_err:
                poll_error = cli_err

        # 更新健康状态追踪
        if poll_ok:
            self._last_success_ts = now_ts
            self._consecutive_failures = 0
            self._last_error = ""
        elif poll_error:
            self._consecutive_failures += 1
            self._last_error = poll_error[:200]

        # 更新持久化游标
        self._last_processed_ts = now_ts
        if any_new_human_msg or (int(now_ts) % 30 == 0):
            self._save_last_ts(self._last_processed_ts)

    def _pull_and_dispatch(self, chat_type: int, chatid: str, chat_name: str,
                           begin: datetime, end: datetime, time_fmt) -> tuple[int, bool, str]:
        """拉取某个会话的新消息并分发。返回 (实际处理数, CLI是否成功, 错误信息)。"""
        try:
            ok_msg, raw, err_msg = self._cli_run("chat", "messages", "list", json_params={
                "chat_id": chatid,
                "begin_time": time_fmt(begin),
                "end_time": time_fmt(end),
            })
            if not ok_msg or not isinstance(raw, dict):
                print(f"[Wecom] 拉消息失败 chatid={chatid}: {err_msg}", flush=True)
                return 0, False, (err_msg or "拉消息返回异常")
            # 从 extra_identity_context 解析机器人 ID（新 CLI 每次都带）
            self._extract_bot_userid(raw)
            messages = raw.get("messages", [])
        except Exception as e:
            print(f"[Wecom] 拉消息失败 chatid={chatid}: {e}", flush=True)
            return 0, False, str(e)

        # 按时间升序排序（新 CLI 已正序，保留兜底）
        messages.sort(key=lambda m: m.get("send_time", ""))

        dispatched = 0
        for msg in messages:
            userid = msg.get("userid", "")
            msg_text = msg.get("text", {}).get("content", "")

            # self-filter：AI 生成标记 + 机器人 ID + 旧 CLI 兼容
            if self._is_self_message(userid, msg_text):
                continue

            # 去重
            msg_id = f"{chatid}_{userid}_{msg.get('send_time', '')}_{msg_text}"
            if msg_id in self._seen_msgs:
                continue
            self._seen_msgs.add(msg_id)
            if len(self._seen_msgs) > 10000:
                self._seen_msgs = set(list(self._seen_msgs)[-5000:])

            # 只处理文本（新 CLI 字段 msg_type 替代旧 msgtype）
            msgtype = msg.get("msg_type", "")
            content = ""
            file_name = ""
            media_id = ""

            # 企微 payload 里 media 类消息可能有 media_id 或 url 字段
            # 企微 voice.content 就是转写文本（企微自带 ASR）
            if msgtype == "text":
                content = msg_text
            elif msgtype == "voice":
                # 企微 voice.content 已经是 ASR 转写结果
                voice_obj = msg.get("voice") or {}
                content = msg.get("content") or ""
                media_id = voice_obj.get("media_id") or msg.get("media_id") or msg.get("mediaId") or msg.get("url") or ""
            elif msgtype in ("image", "video", "file"):
                type_obj = msg.get(msgtype) or {}
                content = msg.get("content") or ""
                media_id = type_obj.get("media_id") or msg.get("media_id") or msg.get("mediaId") or msg.get("url") or ""
                file_name = type_obj.get("file_name") or msg.get("file_name") or msg.get("filename") or msg.get("name") or ""
            else:
                # 未知类型：尽量把 payload 里有信息量的字段抠出来，拼成可读文本
                _parts = [f"[非文本消息: {msgtype}]"]
                _type_obj = msg.get(msgtype) if isinstance(msg.get(msgtype), dict) else {}
                _interesting_keys = {
                    "title", "content", "description", "url", "href", "link", "text",
                    "name", "desc", "nickname", "remark", "label", "reason", "address",
                    "location", "latitude", "longitude", "amount", "meeting",
                    "start_time", "end_time", "wxid", "userid",
                }
                for _k in _interesting_keys:
                    _v = _type_obj.get(_k) or msg.get(_k)
                    if not _v:
                        continue
                    if not isinstance(_v, (str, int, float)):
                        continue
                    _parts.append(f"{_k}={_v}")
                for _k, _v in msg.items():
                    if _k in ("msg_type", "userid", "send_time", "chatid", "sender", msgtype,
                              "text", "media_id", "mediaId", "file_name"):
                        continue
                    if not isinstance(_v, (str, int, float)):
                        continue
                    if not _v:
                        continue
                    _parts.append(f"{_k}={_v}")
                content = " | ".join(_parts)

            # 时间戳解析
            send_time_str = msg.get("send_time", "")
            try:
                ts_ms = int(datetime.strptime(send_time_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
            except Exception:
                ts_ms = int(time.time() * 1000)

            # sender_name：新 CLI 直接返回 user_name 字段，旧 CLI 从 userid 解析
            sender_name = msg.get("user_name") or (
                userid.split("@")[0] if "@" in userid else userid
            )

            channel_msg = ChannelMessage(
                id=msg_id,
                channel="wecom",
                peer_id=chatid,
                peer_name=chat_name or chatid,
                peer_type="group" if chat_type == 2 else "friend",
                sender_id=userid,
                sender_name=sender_name,
                content=content,
                msg_type="text" if msgtype == "text" else msgtype,
                is_self=False,
                ts_ms=ts_ms,
                file_name=file_name,
                media_id=media_id,
                file_size=0,              # 🆕 media_downloader 下载后补
                is_ready=False,           # 🆕
            )

            self._last_msg_ts = time.time()
            dispatched += 1
            if self._on_message:
                try:
                    self._on_message(channel_msg)
                except Exception as e:
                    print(f"[Wecom] 消息回调异常: {e}", flush=True)

        return dispatched, True, ""

    # --------- self-filter（企微特化，飞书改判断逻辑） ---------

    # 缓存从 extra_identity_context 解析的机器人 userid（新 CLI 每次都返回）
    _bot_userid: str | None = None

    def _is_self_message(self, userid: str, msg_text: str = "") -> bool:
        """判断是否为机器人自己发的消息。

        wecom-cli v1.2+ 规则：
        1. 最近自己发过这条文本 → 跳过（防拦截语/错误提示被二次拉取）
        2. 消息内容包含 "(AI 生成" → MVP 正常 LLM 回复（带标记）
        3. userid 等于机器人 ID → 自己发的
        4. 旧 CLI 兼容：userid 带 @ 也是 bot
        """
        # 最近自己发过这条文本 → 跳过（防拦截语/错误提示被二次拉取）
        if msg_text and msg_text.strip() in self._recently_sent:
            return True
        # 再查 AI 生成标记（MVP 正常回复带此标记）
        if msg_text and ("(AI 生成" in msg_text or "（AI 生成" in msg_text):
            return True
        # 机器人 ID 匹配
        if self._bot_userid and userid == self._bot_userid:
            return True
        # 旧 CLI 兼容
        return "@" in userid

    def _extract_bot_userid(self, cli_output: dict | None) -> None:
        """从 CLI 输出里的 extra_identity_context 解析机器人 userid。

        每次 CLI 调用都会返回这段文本：
          机器人身份：
          名字：阿维达AI
          ID：aibWyANBUpMZYr116c8zlBm-YpiTEorHorC
        """
        if not cli_output or self._bot_userid:
            return
        import re
        ctx = str(cli_output)
        m = re.search(r'机器人身份[：:]\s*.*?ID[：:]\s*([A-Za-z0-9\-_]+)', ctx, re.DOTALL)
        if m:
            self._bot_userid = m.group(1)
            print(f"[Wecom] 解析到机器人 ID: {self._bot_userid}", flush=True)
