"""WCF 客户端：连接 WCF 服务、接收消息、发送回复。

设计原则：
1. 用户明确：WCF / 微信是用户自己负责启动的，阿维达底座绝不主动打开微信、绝不调用 Wcf()
   导致自动拉起微信。所以这里的 "connect" 只做 TCP 探活 + 如果 wcferry 提供了只读 API
   才调用（绝不 new Wcf()）。
2. WCF 当前没跑也没关系：
   - receive 线程跑在后台，每 2 秒 poll 一次；连上就正常收，断开就继续 poll 不退出。
   - inject_message() 给测试/单调用，纯内存注入一条消息，完全不碰真实微信。
3. get_contacts()：WCF 跑着就用真的，没跑就返回 []（由上层决定是否显示 Mock 候选）。
"""

from __future__ import annotations

import os
import queue
import socket
import subprocess
import sys
import threading
import time
from dataclasses import field
from typing import Callable, Optional

from .base import ChannelMessage

# 向后兼容：WcfMessage 就是 ChannelMessage，channel 默认 "wcf"
WcfMessage = ChannelMessage


class WcfClient:
    """WCF 客户端：后台线程接收消息，对外暴露回调 + send_reply 接口。

    实现 ChannelClient 协议，可被多渠道 Pipeline 统一调度。
    """

    channel_name = "wcf"
    POLL_INTERVAL_SEC = 2.0

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self._on_message: Optional[Callable[[WcfMessage], None]] = None
        self._queue: "queue.Queue[WcfMessage]" = queue.Queue()  # 测试/模拟注入用
        # 真实 wcferry 连接对象（只有连上了才会有，绝不主动 new Wcf()）
        self._wcf_real = None
        self._last_connect_attempt = 0.0
        # 消息接收异常计数：连续异常超过阈值才判定连接断开
        self._recv_error_streak = 0
        self._RECV_ERROR_THRESHOLD = 5  # 连续 5 轮异常才断开
        # 连接进行中标志：start_wcf 在跑时，禁止 health_check 创建临时 Wcf() 抢通道
        self._start_connecting = False

    # -------- 对外属性 --------
    @property
    def connected(self) -> bool:
        return self._connected

    def set_message_handler(self, cb: Callable[[WcfMessage], None]):
        self._on_message = cb

    # -------- 生命周期 --------
    def start(self):
        """启动后台接收线程。"""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="WcfClient", daemon=True,
            )
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._disconnect_real()

    # -------- 一键启动/停止 --------
    def start_wcf(self, progress_cb=None) -> dict:
        """一键接入 WCF。

        与 dada-wcf（旧电脑成功运行版本）保持完全一致的调用策略：
          - 默认只用本地注入模式：wcferry.Wcf(block=False)，不传 host/port
          - 创建 Wcf() 之后，轮询 is_login() 最多等待 30s（dada-wcf 是 4 分钟）
          - 绝不再把远端模式（Wcf(host="127.0.0.1")）作为首选，否则极易触发 is_login 超时

        只有当本地注入模式明确抛出"端口已占用/已被注入"类异常，并且 10086 在监听时，
        才 fallback 到远端模式连接已有底座。

        progress_cb: 进度回调函数 (step: str, detail: str) -> None
        返回 {"ok": bool, "error": str, "wxid": str, "contacts": int, "mode": "local"|"remote"|"none"}
        """
        def _progress(step, detail=""):
            if progress_cb:
                try:
                    progress_cb(step, detail)
                except Exception:
                    pass

        if self._wcf_real is not None and self._connected:
            return {"ok": True, "error": "", "wxid": getattr(self, "_self_wxid", ""),
                    "contacts": 0, "mode": "reuse"}

        self._start_connecting = True  # ← 禁止 health_check 创建临时 Wcf() 抢通道
        try:
            return self._start_wcf_inner(_progress)
        finally:
            self._start_connecting = False  # ← 连接结束（无论成功失败）都恢复标志

    def _start_wcf_inner(self, _progress):
        _progress("checking", "检查微信进程...")
        # 先检查微信是否在跑
        import subprocess as _sp
        try:
            out = _sp.run(
                ["tasklist", "/fi", "imagename eq WeChat.exe", "/fo", "csv"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            ).stdout or ""
            if "WeChat.exe" not in out:
                _progress("failed", "微信未运行，请先打开微信并登录")
                return {"ok": False, "error": "微信未运行，请先打开微信并登录",
                        "wxid": "", "contacts": 0, "mode": "none"}
        except Exception:
            pass

        _progress("probing", "探测底座端口...")
        import wcferry
        errors = []
        last_err = ""
        chosen_mode = "none"

        port_listening = self._probe_port(10086)
        modes_to_try = []  # (mode_name, wcf_kwargs, poll_seconds, init_delay_seconds)
        #
        # ═══════════════════════════════════════════════════════
        #  动态模式选择（彻底修复 DLL 注入状态错乱 Bug）
        #
        #  dada-wcf 场景（首次启动微信后MVP是第一个调用者）：
        #    10086 未监听 → DLL还没注入 → 只能走 local 模式 Wcf(block=False)
        #    同时给 local 模式 5 秒 init 延迟，等 wcferry 把 DLL 注入并启动RPC服务，
        #    不然第一次 is_login 就 Timed out，后面全乱。
        #
        #  重启MVP场景（微信底座已经在跑）：
        #    10086 已监听 → DLL已注入，绝对不能再 local 重复注入！
        #    必须走 remote 模式连那个已经存在的底座，否则所有 FUNC_* 全部 Timed out！
        #
        # ═══════════════════════════════════════════════════════
        if not port_listening:
            # DLL还没注入：只能 local 注入
            modes_to_try.append(("local", dict(block=False), 30, 5.0))
        else:
            # DLL已经注入：先 remote 连已存在的；remote 明确失败再 local 兜底
            modes_to_try.append(("remote", dict(host="127.0.0.1", port=10086, block=False), 30, 2.0))
            modes_to_try.append(("local", dict(block=False), 30, 5.0))

        for mode_name, wcf_kwargs, poll_sec, init_delay in modes_to_try:
            _progress("connecting", f"尝试 {mode_name} 模式连接底座...")
            try:
                print(f"[WcfClient] ▶ 尝试 {mode_name} 模式: Wcf({wcf_kwargs})   init_delay={init_delay}s", flush=True)
                w = wcferry.Wcf(**wcf_kwargs)
            except Exception as e:
                last_err = f"{mode_name}模式 Wcf() 创建失败: {type(e).__name__}: {e}"
                print(f"[WcfClient] ✗ {last_err}", flush=True)
                errors.append(last_err)
                continue

            #
            # ═══ 关键时序修复 ═══
            # Wcf(...) 只是把 DLL 注入 / 创建连接，RPC 通道还需要几秒才能 ready。
            # wcferry 39.5.2.0 下，立即调 is_login / enable_receiving_msg 必然 Timed out！
            # 这里等 init_delay 秒，再开始轮询。
            #
            _progress("initializing", f"等待 RPC 通道就绪 ({init_delay}s)...")
            print(f"[WcfClient]   等待{init_delay}秒让RPC通道就绪...", flush=True)
            time.sleep(init_delay)

            # 指标1：轮询 is_login() 必须有一次 True
            _progress("checking_login", "检测微信登录状态...")
            logged_in = False
            is_login_tries = max(1, poll_sec)  # 1秒1次，poll_sec秒
            for i in range(is_login_tries):
                try:
                    logged_in = bool(w.is_login())
                except Exception as e:
                    if i % 10 == 9:  # 每10次打一次，避免刷屏
                        print(f"[WcfClient]   is_login 第{i+1}次异常: {type(e).__name__}: {e}", flush=True)
                    logged_in = False
                if logged_in:
                    print(f"[WcfClient]   ✓ is_login OK (轮询{i+1}次 × 1秒)", flush=True)
                    break
                time.sleep(1)

            if not logged_in:
                _progress("failed", f"登录检测失败（{is_login_tries}秒超时）")
                last_err = f"{mode_name}模式: 等待{is_login_tries}秒后is_login仍为False（未登录 / RPC通道未就绪）"
                errors.append(last_err)
                print(f"[WcfClient] ✗ {last_err}", flush=True)
                try:
                    if hasattr(w, "cleanup"): w.cleanup()
                except Exception:
                    pass
                continue

            # 指标2：开启消息接收（enable_receiving_msg）必须成功！
            #         这一步失败 = 收不到任何消息！必须直接判当前mode失败！
            _progress("enabling", "开启消息接收...")
            recv_enabled = False
            recv_err_info = ""
            for method_name in ("enable_receiving_msg", "enable_recv_msg"):
                fn = getattr(w, method_name, None)
                if not callable(fn):
                    continue
                try:
                    fn()
                    recv_enabled = True
                    print(f"[WcfClient]   ✓ 消息接收已启用: {method_name}()", flush=True)
                    break
                except Exception as e:
                    recv_err_info = f"{method_name}(): {type(e).__name__}: {e}"
                    print(f"[WcfClient]   ✗ 开启消息接收失败 {recv_err_info}", flush=True)
                    # 再试 3 次（有些RPC通道需要时间）
                    for retry in range(3):
                        time.sleep(1.5)
                        try:
                            fn()
                            recv_enabled = True
                            print(f"[WcfClient]   ✓ 消息接收重试成功 (第{retry+2}次): {method_name}()", flush=True)
                            break
                        except Exception as e2:
                            recv_err_info = f"{method_name()} 第{retry+2}次: {type(e2).__name__}: {e2}"
                    if recv_enabled:
                        break

            if not recv_enabled:
                _progress("failed", "开启消息接收失败")
                last_err = f"{mode_name}模式: 开启消息接收失败! {recv_err_info or '无可用方法'}"
                errors.append(last_err)
                print(f"[WcfClient] ✗ {last_err}", flush=True)
                try:
                    if hasattr(w, "cleanup"): w.cleanup()
                except Exception:
                    pass
                continue

            # 指标3：get_contacts 函数调用必须能成功（不抛异常）——空列表也没关系，只要通就行
            _progress("fetching", "获取联系人列表...")
            raw_contacts = []
            contacts_ok = False
            try:
                raw_contacts = list(w.get_contacts())
                contacts_ok = True
                print(f"[WcfClient]   ✓ get_contacts OK: {len(raw_contacts)} 条原始记录", flush=True)
            except Exception as e:
                # 再重试2次
                for retry in range(2):
                    time.sleep(1.5)
                    try:
                        raw_contacts = list(w.get_contacts())
                        contacts_ok = True
                        print(f"[WcfClient]   ✓ get_contacts OK (第{retry+2}次): {len(raw_contacts)} 条", flush=True)
                        break
                    except Exception as e2:
                        last_err = f"{mode_name}模式 get_contacts 全部超时: {type(e).__name__}: {e}"
                if not contacts_ok:
                    last_err = last_err or f"{mode_name}模式 get_contacts 失败: {type(e).__name__}: {e}"

            if not contacts_ok:
                errors.append(last_err)
                print(f"[WcfClient] ✗ {last_err}", flush=True)
                try:
                    if hasattr(w, "cleanup"): w.cleanup()
                except Exception:
                    pass
                continue

            # ════════════════════════════════════════
            #  三大指标全通过 → 真正成功！这次不造假！
            # ════════════════════════════════════════
            chosen_mode = mode_name
            self._wcf_real = w
            self._connected = True
            self._recv_error_streak = 0

            # 自身 wxid：与 dada-wcf 完全对齐（先 get_self_info → get_user_info → get_self_wxid 兜底）
            self._self_wxid = ""
            for method_name, getter in [
                ("get_self_info", lambda: (w.get_self_info() or {}).get("wxid", "") if isinstance(w.get_self_info(), dict) else ""),
                ("get_user_info", lambda: (w.get_user_info() or {}).get("wxid", "") if isinstance(w.get_user_info(), dict) else ""),
                ("get_self_wxid", lambda: (w.get_self_wxid() or "") if callable(getattr(w, "get_self_wxid", None)) else ""),
            ]:
                if not hasattr(w, method_name):
                    continue
                try:
                    val = getter()
                    if isinstance(val, str) and val:
                        self._self_wxid = val
                        print(f"[WcfClient]   ✓ self_wxid={val!r} (via {method_name})", flush=True)
                        break
                except Exception:
                    pass
            if not self._self_wxid:
                print(f"[WcfClient]   ⚠ 自身wxid获取失败，但三大硬指标已过，继续", flush=True)

            contact_count = len(raw_contacts)
            _progress("success", f"连接成功！已接入 {contact_count} 个联系人")
            print(f"[WcfClient] ✓ {mode_name}模式 接入成功！三大硬指标全过: "
                  f"wxid={self._self_wxid!r}  contacts={contact_count} mode={mode_name}",
                  flush=True)

            return {"ok": True, "error": "", "wxid": self._self_wxid,
                    "contacts": contact_count, "mode": chosen_mode}

        # 所有模式都失败
        combined_err = last_err or ("；".join(errors) if errors else "未知错误")
        _progress("failed", f"连接失败: {combined_err[:80]}")
        print(f"[WcfClient] ✗✗✗ start_wcf 所有模式均失败 → {combined_err}", flush=True)
        return {"ok": False, "error": combined_err, "wxid": "", "contacts": 0, "mode": "none"}

    def stop_wcf(self) -> dict:
        """停止 WCF 底座连接。"""
        self._disconnect_real()
        print("[WcfClient] WCF 已停止", flush=True)
        return {"ok": True, "error": ""}

    # -------- 探活 --------
    def health_check(self) -> dict:
        """只读探活：检查端口 + 微信进程状态。

        两个关键状态分离：
        - wechat_logged_in : 微信进程本身是否已登录（窗口标题判断）
        - is_login         : MVP 是否真正通过 wcferry 连上了 WCF（只看 self._connected）
        绝不创建 Wcf() 实例，避免与用户已运行的底座冲突。

        性能优化：结果缓存 3 秒，频繁切换 Tab 时不重复探测端口。
        """
        import time as _time
        now = _time.time()
        cached = getattr(self, "_health_cache", None)
        cache_ts = getattr(self, "_health_cache_ts", 0.0)
        if cached is not None and (now - cache_ts) < 3.0:
            return cached
        port_10086 = self._probe_port(10086)

        info = {
            "port_10086": port_10086,
            "port_10087": self._probe_port(10087),
            "connected": self._connected,
            # is_login 严格等价于 MVP 是否已作为客户端接入 WCF
            "is_login": self._connected and self._wcf_real is not None,
            "self_wxid": "",
            "another_client_pid": 0,
            "hint": "",
            "wechat_version": "",
            "friend_count": 0,
            "group_count": 0,
            # wechat_logged_in：独立判断的"微信窗口本身是否已登录"，用于步骤 1
            "wechat_logged_in": False,
            "wechat_nickname": "",
        }

        # 检查微信进程：有主窗口 = 已登录（只更新 wechat_logged_in，绝不改 is_login）
        try:
            import subprocess as _sp
            out = _sp.run(
                ["tasklist", "/fi", "imagename eq WeChat.exe", "/fo", "csv", "/v"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            ).stdout or ""
            if "WeChat.exe" in out:
                lines = [l for l in out.splitlines() if "WeChat.exe" in l]
                for line in lines:
                    parts = line.split('","')
                    if len(parts) >= 9:
                        title = parts[-1].strip('"').strip()
                        if title and title not in ("N/A", "暂无", "") and len(title) > 1:
                            info["wechat_logged_in"] = True
                            info["wechat_nickname"] = title
                            break
        except Exception:
            pass

        # 额外检查：用 win32 方式确认微信主窗口（同样只更新 wechat_logged_in）
        if not info["wechat_logged_in"]:
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.WinDLL('user32', use_last_error=True)

                EnumWindowsProc = ctypes.WINFUNCTYPE(
                    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
                )

                def check_wechat_window(hwnd, lparam):
                    if user32.IsWindowVisible(hwnd):
                        title = ctypes.create_unicode_buffer(256)
                        user32.GetWindowTextW(hwnd, title, 256)
                        t = title.value
                        class_name = ctypes.create_unicode_buffer(256)
                        user32.GetClassNameW(hwnd, class_name, 256)
                        if class_name.value == "WeChatMainWndForPC":
                            info["wechat_logged_in"] = True
                            info["wechat_nickname"] = t or "微信用户"
                            return False
                    return True

                user32.EnumWindows(EnumWindowsProc(check_wechat_window), 0)
            except Exception:
                pass

        # 好友/群数量：只要 Wcf 实例存在就算（与 get_contacts 的条件保持一致）
        # 联系人是只读 API，即使消息接收状态异常也能读到数量
        if self._wcf_real is not None:
            try:
                info["self_wxid"] = getattr(self, "_self_wxid", "") or ""
                normalized = self.get_contacts()
                info["friend_count"] = sum(1 for c in normalized if c.get("peer_type") == "friend")
                info["group_count"]  = sum(1 for c in normalized if c.get("peer_type") == "group")
                info["wechat_version"] = info.get("wechat_version") or getattr(self, "_wechat_version", "")
            except Exception:
                pass
        elif port_10086 and info["wechat_logged_in"] and not self._start_connecting:
            # 通道就绪（10086在监听+微信已登录）但 MVP 自己还没作为客户端接入
            # start_wcf 正在跑时跳过，避免双重 Wcf() 抢通道导致 FUNC_IS_LOGIN 超时
            # → 临时用 remote 模式连一次，只读获取联系人/版本信息（不注入 DLL，不拉起微信）
            # → 获取完立即 cleanup，避免霸占端口；最多 5 秒完成，避免卡住前端刷新
            try:
                try:
                    from wcferry import Wcf as _Wcf
                except Exception:
                    _Wcf = None
                if _Wcf is not None:
                    import time as _t
                    _tmp = None
                    _tmp_start = _t.time()
                    try:
                        _tmp = _Wcf(host="127.0.0.1", port=10086)
                    except Exception as _e:
                        _tmp = None
                    if _tmp is not None:
                        # 轮询 is_login 最多 3 秒（remote 模式下 is_login 很快）
                        _login_ok = False
                        for _ in range(6):
                            try:
                                if _tmp.is_login():
                                    _login_ok = True
                                    break
                            except Exception:
                                pass
                            _t.sleep(0.5)
                            if _t.time() - _tmp_start > 4.5:
                                break
                        if _login_ok:
                            try:
                                self_wxid = ""
                                for m_name in ("get_self_wxid", "get_self_wxid"):
                                    fn = getattr(_tmp, m_name, None)
                                    if callable(fn):
                                        try:
                                            self_wxid = str(fn() or "")
                                            break
                                        except Exception:
                                            continue
                                if not self_wxid:
                                    try:
                                        _s = getattr(_tmp, "get_self_info", lambda: None)()
                                        if isinstance(_s, dict):
                                            self_wxid = str(_s.get("wxid") or _s.get("userName") or "")
                                    except Exception:
                                        pass
                                info["self_wxid"] = self_wxid
                                try:
                                    _raw = _tmp.get_contacts()
                                except Exception:
                                    _raw = []
                                _friends = 0
                                _groups = 0
                                for c in (_raw or []):
                                    _wxid = ""
                                    if isinstance(c, dict):
                                        _wxid = c.get("wxid") or c.get("userName") or ""
                                    elif hasattr(c, "wxid"):
                                        try:
                                            _wxid = getattr(c, "wxid", "")
                                        except Exception:
                                            pass
                                    if isinstance(_wxid, str) and _wxid.endswith("@chatroom"):
                                        _groups += 1
                                    elif _wxid and not _wxid.startswith("gh_"):
                                        _friends += 1
                                # 好友通常几百人、群聊几十；wcferry 默认过滤了系统号，
                                # 但这里仍然做一次"移除明显系统号"兜底（filehelper 等）
                                info["friend_count"] = _friends
                                info["group_count"]  = _groups
                                # 微信版本号
                                for m_name in ("get_version", "wechat_version", "version"):
                                    fn = getattr(_tmp, m_name, None)
                                    if callable(fn):
                                        try:
                                            v = str(fn() or "")
                                            if v:
                                                info["wechat_version"] = v
                                                break
                                        except Exception:
                                            continue
                            except Exception as _e2:
                                pass
                        # 收尾：temp client 必须 cleanup，避免留下不释放的连接
                        try:
                            _cleanup = getattr(_tmp, "cleanup", None)
                            if callable(_cleanup):
                                _cleanup()
                        except Exception:
                            pass
            except Exception:
                pass

        if not port_10086 and not info["wechat_logged_in"]:
            info["hint"] = "请先打开微信并扫码登录"
        elif not port_10086 and info["wechat_logged_in"]:
            info["hint"] = "微信已登录，点击上方开关开启连接"
        elif port_10086 and not info["is_login"]:
            info["hint"] = "微信通道已就绪，可开启连接"
        self._health_cache = info
        self._health_cache_ts = now
        return info

    @staticmethod
    def _probe_port(port: int, host: str = "127.0.0.1", timeout_ms: int = 200) -> bool:
        s = socket.socket()
        s.settimeout(timeout_ms / 1000.0)
        try:
            return s.connect_ex((host, port)) == 0
        finally:
            s.close()

    @staticmethod
    def _another_wcf_client_pid() -> Optional[int]:
        """单例保护：检查端口 10086 是否已经被别的进程 ESTABLISHED（即已连有 wcferry 客户端）。
        返回占用 ESTABLISHED 的对端 PID（非微信自身），没有就返回 None。
        netstat 格式：协议  本地地址:本地端口        外部地址:外部端口      状态        PID
        LISTENING 的 PID 是微信（被注入端），ESTABLISHED 的本地是 127.0.0.1:10086，
        远端是某个 127.0.0.1:xxx，远端那个对应的 PID 如果不是我们（os.getpid），就是别人占了。
        """
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            ).stdout or ""
        except Exception:
            return None
        my_pid = 0
        try:
            my_pid = __import__("os").getpid()
        except Exception:
            pass
        for line in out.splitlines():
            cols = line.split()
            if len(cols) < 5:
                continue
            state = cols[-2]
            pid = cols[-1]
            if state != "ESTABLISHED":
                continue
            # 找到 10086 参与的 ESTABLISHED，看另一端是否是别人
            if ":10086" not in cols[1] and ":10086" not in cols[2]:
                continue
            try:
                p = int(pid)
            except Exception:
                continue
            # 微信进程是 LISTENING 的 Owner，ESTABLISHED 的 Owner 是客户端
            # 用端口判断：本地端口=10086 的话，远端是客户端（另一个 socket），pid 就是客户端进程
            if cols[1].endswith(":10086"):
                # 我们要看的是远端那个 socket 的进程，但 netstat 每条只记录这条 socket 的 Owner
                # 所以需要反向查：找同一条 ESTABLISHED 的反向 netstat（cols[2].endswith(":10086") 的那条）的 Owner
                continue
            # cols[2].endswith(":10086") → 本地连向远端 10086，Owner 就是客户端
            if cols[2].endswith(":10086") and p != my_pid:
                return p
        return None

    @staticmethod
    def env_diagnose() -> dict:
        """环境预检：逐项检查微信 + wcferry 环境是否就绪。
        返回 {"ok": bool, "summary": str, "checks": [{"key","label","status","detail","suggestion"}]}
        status: "pass" | "warn" | "fail"
        """
        import subprocess as _sp
        import ctypes as _ct
        from ctypes import wintypes as _wt
        import time as _t

        checks = []

        # ── 1. 微信进程 ──
        wechat_running = False
        try:
            out = _sp.run(
                ["tasklist", "/fi", "imagename eq WeChat.exe", "/fo", "csv"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            ).stdout or ""
            wechat_running = "WeChat.exe" in out
        except Exception:
            pass
        if wechat_running:
            checks.append({"key": "wechat_proc", "label": "微信进程", "status": "pass",
                           "detail": "WeChat.exe 正在运行", "suggestion": ""})
        else:
            checks.append({"key": "wechat_proc", "label": "微信进程", "status": "fail",
                           "detail": "未检测到 WeChat.exe", "suggestion": "请打开微信并登录"})

        # ── 2. 微信登录状态（主窗口存在） ──
        wechat_logged = False
        if wechat_running:
            try:
                WNDENUMPROC = _ct.WINFUNCTYPE(_wt.BOOL, _wt.HWND, _wt.LPARAM)
                found = [False]
                def _cb(hwnd, lparam):
                    cls = _ct.create_unicode_buffer(256)
                    _ct.windll.user32.GetClassNameW(hwnd, cls, 256)
                    if cls.value == "WeChatMainWndForPC":
                        found[0] = True
                    return True
                _ct.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
                wechat_logged = found[0]
            except Exception:
                wechat_logged = False

        if wechat_logged:
            checks.append({"key": "wechat_login", "label": "微信登录", "status": "pass",
                           "detail": "微信主窗口已检测到", "suggestion": ""})
        elif wechat_running:
            checks.append({"key": "wechat_login", "label": "微信登录", "status": "warn",
                           "detail": "微信进程在跑但主窗口未检测到", "suggestion": "请切换到微信确认已登录"})
        else:
            checks.append({"key": "wechat_login", "label": "微信登录", "status": "fail",
                           "detail": "微信未运行", "suggestion": "请打开微信并登录"})

        # ── 3. wcferry DLL 注入 / 10086 端口（仅 start_wcf 之后才就绪，预检只做提示） ──
        port_listening = WcfClient._probe_port(10086, timeout_ms=300)
        if port_listening:
            checks.append({"key": "wcf_port", "label": "wcferry 通道", "status": "pass",
                           "detail": "10086 端口已监听（DLL 已注入）", "suggestion": ""})
        else:
            # 预检阶段没开连接 → 端口本来就不会监听 → 不报告失败，只提示
            checks.append({"key": "wcf_port", "label": "wcferry 通道", "status": "pass",
                           "detail": "尚未注入（点『开启连接』后自动完成）", "suggestion": ""})

        # ── 4. 残留 wcferry 客户端抢通道 ──
        residual_pid = WcfClient._another_wcf_client_pid()
        if residual_pid:
            checks.append({"key": "residual", "label": "通道残留", "status": "fail",
                           "detail": f"发现残留客户端 PID={residual_pid} 霸占通道",
                           "suggestion": "关闭所有 MVP 窗口 → 打开任务管理器结束 PID 进程 → 重新打开 MVP"})
        else:
            checks.append({"key": "residual", "label": "通道残留", "status": "pass",
                           "detail": "通道干净，无残留客户端", "suggestion": ""})

        # ── 5. wcferry SDK 版本 ──
        try:
            import wcferry as _wc
            ver = getattr(_wc, "__version__", getattr(_wc, "VERSION", "未知"))
            checks.append({"key": "wcf_sdk", "label": "wcferry SDK", "status": "pass",
                           "detail": f"版本 {ver}", "suggestion": ""})
        except ImportError:
            checks.append({"key": "wcf_sdk", "label": "wcferry SDK", "status": "fail",
                           "detail": "wcferry 未安装", "suggestion": "pip install wcferry"})

        # ── 汇总 ──
        fails = sum(1 for c in checks if c["status"] == "fail")
        warns = sum(1 for c in checks if c["status"] == "warn")
        if fails == 0 and warns == 0:
            summary = "环境全部就绪，可以开启连接"
            ok = True
        elif fails == 0:
            summary = f"有 {warns} 项警告（不影响连接，但建议关注）"
            ok = True
        else:
            summary = f"有 {fails} 项必须修复，请按建议操作"
            ok = False

        return {"ok": ok, "summary": summary, "checks": checks}

    # -------- 真实连接（仅当 WCF 已经在跑时才会成功，绝不 new Wcf()） --------
    def _try_connect_real(self) -> bool:
        """真正建立 wcferry 连接。
        直接调 Wcf() —— Wcf() 自己会做 DLL 注入、开端口、建连接。
        不需要预先检查端口，因为 Wcf() 就是开端口的那个调用。
        """
        if self._wcf_real is not None:
            return True
        # 单例保护：别人先连上了就绝不抢占
        other = self._another_wcf_client_pid()
        if other:
            return False
        try:
            import wcferry
        except Exception:
            return False
        try:
            w = wcferry.Wcf(block=False)
            ok = w.is_login()
            if ok:
                self._wcf_real = w
                return True
            else:
                try:
                    w.cleanup()
                except Exception:
                    pass
                return False
        except Exception:
            return False

    def _disconnect_real(self):
        w, self._wcf_real = self._wcf_real, None
        self._connected = False
        self._recv_error_streak = 0
        if w is None:
            return
        try:
            # 尽量清理，但不抛异常
            try:
                w.disable_recv_msg()
            except Exception:
                pass
            try:
                w.cleanup()
            except Exception:
                pass
        except Exception:
            pass

    # -------- 主循环 --------
    def _run_loop(self):
        """后台循环：处理注入队列 + 连接时 poll 真实消息。"""
        while not self._stop.is_set():
            # 1) 处理注入队列（测试/模拟）
            self._drain_injected()
            # 2) 连上了就 poll 真实消息
            if self._connected and self._wcf_real is not None:
                self._drain_real_messages()
            else:
                time.sleep(self.POLL_INTERVAL_SEC)

    def _drain_injected(self):
        while True:
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                return
            self._dispatch(msg)

    def _drain_real_messages(self, max_per_round: int = 50):
        """从真实 WCF 拉一批消息（wcferry 标准 API：get_msg(block=False)）。
        容错：一次异常不计为断开，连续多轮异常才判定连接失效（避免瞬时抖动误判）。
        """
        had_any_msg = False
        for _ in range(max_per_round):
            try:
                raw = self._wcf_real.get_msg(block=False)
            except queue.Empty:
                # wcferry 39.5.2.0: get_msg 无消息时抛 queue.Empty，这是正常的"没有消息"信号
                # 绝对不能当作连接异常！
                if had_any_msg:
                    self._recv_error_streak = 0
                return
            except Exception as e:
                # 真正的异常（非 Empty）才累计
                err_name = type(e).__name__
                # Empty 也可能以其他形式出现
                if "Empty" in err_name or "empty" in str(e).lower():
                    if had_any_msg:
                        self._recv_error_streak = 0
                    return
                # 单次 get_msg 异常不直接断开，累计计数
                self._recv_error_streak += 1
                if self._recv_error_streak >= self._RECV_ERROR_THRESHOLD:
                    print(f"[WcfClient] 消息接收连续异常{self._recv_error_streak}次({err_name})，判定连接断开", flush=True)
                    self._connected = False
                return
            if raw is None:
                # 正常空队列：清零异常计数，继续sleep等待下一轮
                if had_any_msg:
                    self._recv_error_streak = 0
                return
            had_any_msg = True
            self._recv_error_streak = 0  # 成功拿到消息：清零异常计数
            raw_type = int(getattr(raw, "type", 0) or 0)
            raw_content = str(getattr(raw, "content", "") or "")[:60]
            print(f"[WcfClient] 📨 raw get_msg → type={raw_type} content={raw_content!r}", flush=True)
            # DEBUG: type=49(文件) 额外 dump 所有字段
            if raw_type == 49:
                _xml = str(getattr(raw, "xml", "") or "")
                _full_content = str(getattr(raw, "content", "") or "")
                _extra = str(getattr(raw, "extra", "") or "")
                _thumb = str(getattr(raw, "thumb", "") or "")
                _mid = getattr(raw, "id", "")
                print(f"[WcfClient] 🔍 type=49 DUMP: id={_mid} extra={_extra!r} thumb={_thumb!r}", flush=True)
                print(f"[WcfClient] 🔍 type=49 DUMP content(full): {_full_content[:800]!r}", flush=True)
                print(f"[WcfClient] 🔍 type=49 DUMP xml: {_xml[:800]!r}", flush=True)
            msg = self._normalize_raw(raw, wcf_client=self._wcf_real)
            if msg is None:
                print(f"[WcfClient]   → normalize_raw 返回 None", flush=True)
            elif msg.is_self:
                print(f"[WcfClient]   → 自己发的，跳过", flush=True)
            else:
                print(f"[WcfClient]   → 归一化 OK msg_type={msg.msg_type} file_path={msg.file_path!r} → dispatch", flush=True)
                self._dispatch(msg)

    # -------- 真实消息归一化 --------
    @staticmethod
    def _normalize_raw(raw, wcf_client=None) -> Optional[WcfMessage]:
        try:
            ts_ms = int(getattr(raw, "ts", 0) or 0) * 1000
            content = str(getattr(raw, "content", "") or "")
            # 原始：roomid 非空 = 群消息；sender 是发消息的 wxid
            roomid = str(getattr(raw, "roomid", "") or "")
            sender = str(getattr(raw, "sender", "") or "")
            is_group = bool(roomid)
            peer_id = roomid if is_group else sender
            peer_type = "group" if is_group else "friend"
            if not peer_id:
                return None
            is_self = bool(getattr(raw, "is_self", False))
            # wcferry WxMsg.type：1=文本 3=图片 34=语音 43=视频 47=表情 49=文件/链接 10000=系统
            raw_type = int(getattr(raw, "type", 1) or 1)
            wcf_type_map = {
                1: "text", 3: "image", 34: "voice", 43: "video",
                47: "emoji", 49: "file", 10000: "other",
            }
            msg_type = wcf_type_map.get(raw_type, "other")

            file_path = ""
            file_name = ""
            file_size = 0        # 🆕
            is_ready = False     # 🆕

            # --- 图片（type=3）：WCF 不自动下载解密，必须手动调 download_image ---
            if raw_type == 3 and wcf_client is not None:
                mid = int(getattr(raw, "id", 0) or 0)
                extra = str(getattr(raw, "extra", "") or "")
                if mid and extra:
                    tmp_dir = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "scai_media")
                    os.makedirs(tmp_dir, exist_ok=True)
                    try:
                        downloaded = wcf_client.download_image(mid, extra, tmp_dir, timeout=30)
                        if downloaded and os.path.isfile(downloaded):
                            file_path = downloaded
                            file_name = os.path.basename(downloaded)
                            print(f"[WcfClient]   → 🖼️ download_image 成功: {file_name}", flush=True)
                        else:
                            print(f"[WcfClient]   → 🖼️ download_image 返回空或文件不存在", flush=True)
                    except Exception as dl_e:
                        print(f"[WcfClient]   → 🖼️ download_image 异常: {type(dl_e).__name__}: {dl_e}", flush=True)

            # --- 视频（type=43）：也手动调 download_video ---
            elif raw_type == 43 and wcf_client is not None:
                mid = int(getattr(raw, "id", 0) or 0)
                thumb = str(getattr(raw, "thumb", "") or "")
                extra = str(getattr(raw, "extra", "") or "")
                if mid:
                    tmp_dir = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "scai_media")
                    os.makedirs(tmp_dir, exist_ok=True)
                    try:
                        downloaded = wcf_client.download_video(mid, thumb, tmp_dir, timeout=30)
                        if downloaded and os.path.isfile(downloaded):
                            file_path = downloaded
                            file_name = os.path.basename(downloaded)
                            print(f"[WcfClient]   → 🎬 download_video 成功: {file_name}", flush=True)
                        else:
                            print(f"[WcfClient]   → 🎬 download_video 返回空或文件不存在", flush=True)
                    except Exception as dl_e:
                        print(f"[WcfClient]   → 🎬 download_video 异常: {type(dl_e).__name__}: {dl_e}", flush=True)

            # --- 语音/文件：WCF 自动下载，extra 就是路径 ---
            if not file_path and msg_type in ("file", "voice", "image", "video"):
                for attr in ("content", "extra"):
                    candidate = str(getattr(raw, attr, "") or "")
                    if not candidate:
                        continue
                    # WCF 经常给正斜杠路径，Windows os.path.isfile 不认，需要标准化
                    candidate = os.path.normpath(candidate)
                    if os.path.isfile(candidate):
                        file_path = candidate
                        file_name = os.path.basename(candidate)
                        break
                # 兜底：type=49 文件的 extra 大概率是对的，就算 isfile 暂时 False（文件还在落盘）也先记下路径
                if not file_path and raw_type == 49:
                    _extra = os.path.normpath(str(getattr(raw, "extra", "") or ""))
                    if _extra:
                        file_path = _extra
                        file_name = os.path.basename(_extra)
                        # 等文件落盘：最多等 3 秒，每 0.3 秒检查一次
                        import time
                        for _retry in range(10):
                            if os.path.isfile(file_path):
                                print(f"[WcfClient]   → 📎 file 兜底用 extra，落盘成功: {file_path}", flush=True)
                                break
                            time.sleep(0.3)
                        else:
                            print(f"[WcfClient]   → 📎 file 兜底用 extra（可能还在落盘，isfile=False）: {file_path}", flush=True)

            # 🆕 统一补 file_size / is_ready（所有成功分支最终都会汇聚到这里）
            if file_path:
                _is_file = os.path.isfile(file_path)
                is_ready = _is_file
                # 🆕 type=49 文件的 size 藏在 content 的 XML <totallen> 里
                try:
                    import re as _re
                    _ta = _re.search(r'<totallen[^>]*>(\d+)</totallen>', content)
                    if _ta:
                        file_size = int(_ta.group(1))
                        if file_size > 0:
                            print(f"[WcfClient]   → file_size 从 XML totallen 解析: {file_size} ({file_size/1024/1024:.1f}MB)", flush=True)
                except Exception:
                    pass
                # 兜底：还是 0 就用本地文件大小
                if file_size == 0 and _is_file:
                    try:
                        file_size = os.path.getsize(file_path)
                    except OSError:
                        file_size = 0
                print(f"[WcfClient]   → file_size={file_size} is_ready={is_ready}", flush=True)

            return WcfMessage(**{
                "id": str(getattr(raw, "id", "") or f"m_{ts_ms}_{peer_id}"),
                "channel": "wcf",
                "peer_id": peer_id,
                "peer_name": "",  # 上层 binding_router 会补
                "peer_type": peer_type,
                "sender_id": sender,
                "sender_name": "",
                "content": content,
                "msg_type": msg_type,
                "is_self": is_self,
                "is_at": False,  # TODO: 解析 content 是否包含 @me
                "ts_ms": ts_ms or int(time.time() * 1000),
                "file_path": file_path,
                "file_name": file_name,
                "file_size": file_size,    # 🆕
                "is_ready": is_ready,      # 🆕
            })
        except Exception as _e:
            import traceback as _tb
            print(f"[WcfClient] ❌ normalize_raw 异常: {type(_e).__name__}: {_e}", flush=True)
            _tb.print_exc()
            return None

    # -------- 注入 & 发送 --------
    def inject_message(self, msg: WcfMessage):
        """纯内存注入，给测试/单调用。完全不碰真实微信。"""
        self._queue.put(msg)

    def send_reply(self, peer_id: str, content: str, peer_type: str = "friend",
                   at_sender_id: str = "") -> bool:
        """发送回复。WCF 跑着就真发；没跑就只返回 False，不抛异常。

        peer_type='group' 时会用 send_text(..., roomid=peer_id)；
        私聊就是 send_text(..., receiver=peer_id)。
        at_sender_id 仅群聊有值时才 @该用户。
        """
        content = (content or "").strip()
        if not content:
            return False
        if self._wcf_real is None or not self._connected:
            return False
        try:
            if peer_type == "group":
                # wcferry: send_text 可支持 roomid
                if at_sender_id and at_sender_id != peer_id:
                    self._wcf_real.send_text(content, receiver=peer_id, aters=at_sender_id)
                else:
                    self._wcf_real.send_text(content, receiver=peer_id)
            else:
                self._wcf_real.send_text(content, receiver=peer_id)
            return True
        except Exception as e:
            print(f"[WcfClient] send_reply 失败: {e}", flush=True)
            return False

    # -------- 候选联系人读取（WCF 跑着就真读，否则空） --------
    def get_contacts(self) -> list:
        """只读获取联系人列表（好友 + 群聊）。

        关键区分（wcferry 两个 API 不要搞混）：
          - get_friends()  → 真正的微信好友（加过的）✅ 好友列表应该用这个
          - get_contacts() → 完整通讯录（好友 + 群成员见过的陌生人 + 系统号）❌ 坑！

        所以这里分别取：好友走 get_friends()，群聊走 get_contacts() 过滤 @chatroom。
        """
        if self._wcf_real is not None:
            try:
                self_wxid = getattr(self, "_self_wxid", "")

                # --- 0) ★ SQL 查 MicroMsg.db.Contact 表拿真实好友白名单 ---
                # wcferry 源码 get_chatroom_members() L977 就是这么干的
                sql_friend_wxids = set()
                try:
                    # Contact 表存了所有通讯录条目（好友+群聊+公众号+企微外部联系人）
                    all_contact_rows = self._wcf_real.query_sql(
                        "MicroMsg.db", "SELECT UserName, NickName, Remark FROM Contact;"
                    ) or []
                    # 过滤：排除群聊@chatroom、公众号gh_、企微外部联系人@openim（让它们进好友列表）
                    # 这里只拿 UserName 做白名单
                    for row in all_contact_rows:
                        wxid = row.get("UserName", "") or ""
                        if not wxid:
                            continue
                        sql_friend_wxids.add(wxid)
                    print(f"[SQL] Contact 表总条目={len(all_contact_rows)}, 去重后 wxid={len(sql_friend_wxids)}", flush=True)
                except Exception as sql_err:
                    print(f"[SQL] MicroMsg.db.Contact 查询失败（可能未注入）: {sql_err}", flush=True)

                # --- 1) get_friends() 拿候选好友 ---
                friends_raw = []
                try:
                    friends_raw = list(self._wcf_real.get_friends())
                except Exception:
                    pass

                # --- 2) 群聊：get_contacts() 里过滤 @chatroom ---
                chatrooms_raw = []
                try:
                    all_raw = list(self._wcf_real.get_contacts())
                    chatrooms_raw = [
                        r for r in all_raw
                        if (r.get("wxid", "") if isinstance(r, dict) else getattr(r, "wxid", "")).endswith("@chatroom")
                    ]
                except Exception:
                    pass

                # --- 3) ★ 用 SQL 白名单再次过滤好友 ---
                # 如果 SQL 拿到了白名单，用它过滤 get_friends() 的结果
                if sql_friend_wxids:
                    before = len(friends_raw)
                    friends_raw = [
                        f for f in friends_raw
                        if (f.get("wxid", "") if isinstance(f, dict) else getattr(f, "wxid", "")) in sql_friend_wxids
                    ]
                    print(f"[SQL] 白名单过滤后好友: {before} → {len(friends_raw)}", flush=True)
                    for f in friends_raw:
                        wxid = f.get("wxid", "") if isinstance(f, dict) else getattr(f, "wxid", "")
                        name = f.get("name", "") if isinstance(f, dict) else getattr(f, "name", "")
                        print(f"  ✅ {wxid} / {name}", flush=True)
                else:
                    print("[SQL] 无白名单（注入模式未生效？），跳过过滤", flush=True)

                # --- 4) 合并好友 + 群聊 ---
                merged = friends_raw + chatrooms_raw
                normalized = self._normalize_contacts(merged, self._wcf_real, self_wxid)
                return normalized
            except Exception as e:
                import traceback
                traceback.print_exc()
                return []
        return []

    # -------- 联系人详情 & 头像 --------
    def get_contact_detail(self, wxid: str) -> dict:
        """通过 wxid 获取联系人详情（wcferry 提供的 get_info_by_wxid 接口）。
        返回 dict（结构由 wcferry 决定，一般包含昵称、大/小头像URL等字段），
        失败返回空 dict。该接口只读，绝不创建新 Wcf 实例。
        """
        if not wxid or self._wcf_real is None:
            return {}
        try:
            if not hasattr(self._wcf_real, "get_info_by_wxid"):
                return {}
            info = self._wcf_real.get_info_by_wxid(wxid)
            # wcferry 一般返回 dict；若不是，转为字符串说明兜底
            if isinstance(info, dict):
                return info
            return {"_raw": str(info) if info is not None else ""}
        except Exception as e:
            print(f"[WcfClient] get_contact_detail({wxid!r}) 异常: {type(e).__name__}: {e}", flush=True)
            return {}

    def get_avatar_base64(self, wxid: str) -> str:
        """尝试获取联系人头像并返回 base64（不含 data:image/xxx;base64, 前缀）。

        优先级：
        1) 本地 Wcf 实例若有下载接口（download_image / get_head_img 等），直接返回 bytes base64；
        2) get_info_by_wxid 返回结果里取头像 URL，由 **Python 端** 发起 HTTP 请求下载图片字节，
           再编码为 base64 返回；避免前端 file:// 页面加载 http(s) 头像时被 QWebEngine
           安全策略 / 混合内容拦截（这是前端头像不显示的最大根因）；
        3) 失败返回空字符串。
        """
        if not wxid or self._wcf_real is None:
            return ""
        w = self._wcf_real
        # 方式 1：下载接口拿 bytes（少数 wcferry 版本支持，优先级最高）
        for method_name in ("download_image", "get_head_img", "get_avatar", "get_head_image"):
            fn = getattr(w, method_name, None)
            if not callable(fn):
                continue
            try:
                r = fn(wxid)
                if isinstance(r, (bytes, bytearray)) and len(r) > 0:
                    import base64 as _b64
                    b64 = _b64.b64encode(bytes(r)).decode("ascii")
                    print(f"[WcfClient] get_avatar_base64({wxid!r}) → {method_name}() 直接返回 bytes 长度 {len(b64)}", flush=True)
                    return b64
            except Exception as _e1:
                print(f"[WcfClient] get_avatar_base64 {method_name} 失败: {type(_e1).__name__}: {_e1}", flush=True)
                continue
        # 方式 2：从详情接口取头像 URL → 由 Python 侧自行下载再 base64 返回
        detail = self.get_contact_detail(wxid)
        url = ""
        url_key = ""
        if isinstance(detail, dict) and detail:
            for key in ("big_head_img_url", "small_head_img_url", "avatar", "avatar_url", "headImgUrl", "headimgurl"):
                u = detail.get(key) or ""
                if isinstance(u, str) and u.startswith("http"):
                    url = u
                    url_key = key
                    break
        if url:
            import base64 as _b64
            try:
                import urllib.request as _ur
                import ssl as _ssl
                # 头像域名证书不完整时允许跳过（只用于只读下载，不涉及隐私数据）
                try:
                    _ctx = _ssl._create_unverified_context()
                except Exception:
                    _ctx = None
                req = _ur.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AvatarAI/1.0",
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                })
                kwargs = {"timeout": 6}
                if _ctx is not None:
                    kwargs["context"] = _ctx
                with _ur.urlopen(req, **kwargs) as resp:
                    data = resp.read()
                if data and len(data) > 64:
                    b64 = _b64.b64encode(data).decode("ascii")
                    print(f"[WcfClient] get_avatar_base64({wxid!r}) → Python 下载 detail.{url_key} OK ({len(data)} bytes → base64 {len(b64)})", flush=True)
                    return b64
                print(f"[WcfClient] get_avatar_base64({wxid!r}) → 下载到的图片数据过短: {len(data or b'')}", flush=True)
            except Exception as e:
                print(f"[WcfClient] get_avatar_base64({wxid!r}) → 下载 URL 失败: {type(e).__name__}: {e}", flush=True)
            # 若 Python 侧下载失败（无网络、证书问题等），退回 URL 模式给前端尝试最后一次
            print(f"[WcfClient] get_avatar_base64({wxid!r}) → 退回 URL 模式给前端兜底", flush=True)
            return f"__URL__:{url}"
        # 方式 3：没有任何头像来源
        print(f"[WcfClient] get_avatar_base64({wxid!r}) → 未找到任何头像来源", flush=True)
        return ""

    # 常见系统内置账号 wxid 前缀（公众号/服务号 gh_、以及若干系统号）
    _SYSTEM_WXIDS = {
        "filehelper",      # 文件传输助手
        "weixin",          # 微信团队
        "newsapp",         # 腾讯新闻
        "fmessage",        # 朋友推荐消息
        "qqmail",          # QQ邮箱提醒
        "medianote",       # 语音记事本
        "floatbottle",     # 漂流瓶
        "tmessage",        # 群发助手
        "recomend_helper", # 推荐助手
        "blogapp",         # 博客邮件
        "brand_",          # 品牌号（前缀）
    }

    @classmethod
    def _filter_system_contact(cls, wxid: str) -> bool:
        """返回 True 表示该 wxid 是系统/公众号等不应作为绑定目标的账号。"""
        if not wxid:
            return True
        # 公众号/服务号 gh_ 开头
        if wxid.startswith("gh_"):
            return True
        # 完全匹配的系统号
        if wxid in cls._SYSTEM_WXIDS:
            return True
        # 前缀匹配的系统号
        for prefix in ("brand_", "qqsync", "mphelper"):
            if wxid.startswith(prefix):
                return True
        return False

    @staticmethod
    def _normalize_contacts(rows: list, wcf_real=None, self_wxid: str = "") -> list:
        """联系人归一化：
        关键修复（对齐 wcferry 39.5.2.0 + dada-wcf 成功经验）：
          - wcferry 返回的每条联系人是 **dict** 类型，不是 object attribute！
            所以必须优先用 r.get("wxid") / r.get("name") 读取，getattr 仅作兼容兜底。
          - 群聊 wxid 以 "@chatroom" 结尾（不是 code.startswith("@@")）。
        """
        total = len(rows) if rows else 0
        stats = {"total": total, "skip_empty_wxid": 0, "skip_self": 0, "skip_system": 0, "ok": 0, "exceptions": 0}
        samples = []
        raw_keys_seen = set()  # ★ 收集 raw dict 所有出现过的 key
        friend_like_seen = []  # ★ 非群聊条目的 type / isFriend / remark 样本
        out = []

        def _f(r, key: str, default: str = "") -> str:
            """兼容 dict / object 两种结构的字段读取"""
            if isinstance(r, dict):
                v = r.get(key, default)
                return default if v is None else str(v)
            # 不是 dict，按 getattr 兜底
            try:
                v = getattr(r, key, default)
                return default if v is None else str(v)
            except Exception:
                return default

        for idx, r in enumerate(rows or []):
            try:
                # ★ 收集 raw dict keys + 非群聊样本（不管后面 skip 还是 include 都收集）
                if isinstance(r, dict):
                    raw_keys_seen.update(r.keys())
                wxid = _f(r, "wxid", "")
                if not wxid:
                    stats["skip_empty_wxid"] += 1
                    continue
                # 排除自己和系统号
                if self_wxid and wxid == self_wxid:
                    stats["skip_self"] += 1
                    continue
                if WcfClient._filter_system_contact(wxid):
                    stats["skip_system"] += 1
                    continue
                name = _f(r, "name", wxid) or wxid
                remark = _f(r, "remark", "")
                code = _f(r, "code", "")
                # 群聊判断：优先 wxid 结尾 @chatroom（与 dada-wcf 对齐），兜底 @@ 前缀
                is_group = wxid.endswith("@chatroom") or (code.startswith("@@") if code else False)
                peer_type = "group" if is_group else "friend"

                # ★ 非群聊条目：记录 raw dict 里可能区分好友/陌生人的字段
                if not is_group and isinstance(r, dict) and len(friend_like_seen) < 20:
                    friend_like_seen.append({
                        "wxid": wxid,
                        "name": name,
                        "remark": remark or "(空)",
                        "type": r.get("type", "(无)"),
                        "isFriend": r.get("isFriend", "(无)"),
                        "labelIdList": r.get("labelIdList", "(无)"),
                        "verifyFlag": r.get("verifyFlag", "(无)"),
                        "extra": r.get("extra", "(无)"),
                        "code": r.get("code", "(无)"),
                    })

                # 群成员数：WCF 已连接的话调用 get_chatroom_members 拿一下
                member_count = 0
                if is_group and wcf_real is not None:
                    try:
                        members = wcf_real.get_chatroom_members(wxid)
                        if members is not None:
                            member_count = len(list(members))
                    except Exception:
                        member_count = 0

                display_name = remark or name or wxid
                item = {
                    "peer_id": wxid,
                    "peer_name": display_name,
                    "peer_type": peer_type,
                    "member_count": member_count,
                    "nickname": name,
                    "remark": remark,
                }
                out.append(item)
                stats["ok"] += 1
                if len(samples) < 12:
                    samples.append(f"[{idx}] wxid={wxid!r} name={name!r} remark={remark!r} type={peer_type} display={display_name!r}")
            except Exception as e:
                stats["exceptions"] += 1
                if len(samples) < 12:
                    samples.append(f"[{idx}] 异常: {type(e).__name__}: {e}")
                continue
        # 好友在前，群聊在后；各组按名称排
        out.sort(key=lambda x: (0 if x["peer_type"] == "friend" else 1, (x["peer_name"] or "").lower()))
        friend_n = sum(1 for x in out if x["peer_type"] == "friend")
        group_n  = sum(1 for x in out if x["peer_type"] == "group")
        for s in samples:
            print(f"  → {s}", flush=True)
        # ★ 打印非群聊样本的 type/isFriend/remark，找区分规律
        if friend_like_seen:
            for item in friend_like_seen:
                print(f"    {item['wxid'][:25]:25s} {item['name'][:15]:15s} remark={item['remark'][:12]:12s} type={item['type']!r} isFriend={item['isFriend']!r} labelId={item['labelIdList']!r} verify={item['verifyFlag']!r} extra={str(item['extra'])[:25]!r}")
        return out

    # -------- 内部 --------
    def _dispatch(self, msg: WcfMessage):
        cb = self._on_message
        if cb is None:
            return
        try:
            cb(msg)
        except Exception as e:
            print(f"[WcfClient] 消息回调异常: {e}", flush=True)
