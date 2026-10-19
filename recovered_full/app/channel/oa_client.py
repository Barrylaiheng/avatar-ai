"""公众号（OA）客户端：接收微信回调、通过客服消息 API 回复。

实现 ChannelClient 协议，可被多渠道 Pipeline 统一调度。

架构：
  微信服务器 → 回调 URL（Flask 内嵌服务）
                 ↓ 验签 + 解析 XML（wechatpy）
                 ↓ 立即返回 "success"（满足5秒限制）
                 ↓ 异步转 ChannelMessage → Pipeline
                 ↓ AI 处理完 → 客服消息 API 回复用户

依赖：wechatpy（验签、加解密、客服消息、粉丝列表、token 管理）
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable, Optional

from .base import ChannelMessage


class OaClient:
    """公众号客户端：Flask 内嵌服务接收回调 + wechatpy 调 API。"""

    channel_name = "oa"

    def __init__(self,
                 app_id: str = "",
                 app_secret: str = "",
                 token: str = "",
                 encoding_aes_key: str = "",
                 callback_port: int = 80,
                 callback_path: str = "/wechat"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.token = token
        self.encoding_aes_key = encoding_aes_key
        self.callback_port = callback_port
        self.callback_path = callback_path

        self._connected = False
        self._flask_running = False
        self._api_verified = False
        self._last_verify_time: float = 0.0  # 最近一次微信回调验签成功时间
        self._last_error: str = ""
        self._on_message: Optional[Callable[[ChannelMessage], None]] = None
        self._on_subscribe: Optional[Callable[[str], None]] = None  # 新关注用户回调(openid)
        self._flask_app = None
        self._flask_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # wechatpy 客户端（懒加载，配置填好后才创建）
        self._wx_client = None

        # 消息排重：msgid 去重，防止微信重试导致重复处理
        self._processed_msgs: dict[str, float] = {}
        self._msgid_expire = 300  # 5 分钟过期

        # 关注者列表缓存（500 次/日限制，手动刷新）
        self._followers_cache: list[dict] = []
        self._followers_cache_time: float = 0
        self._last_followers_error: str = ""

    # -------- ChannelClient 接口 --------

    @property
    def connected(self) -> bool:
        """是否真正「已连接」——只有收到过微信服务端的回调验签才算。

        这是诚实状态分层的核心：
          - configured（配置就绪）= Flask 跑起来 + API 凭据过 + 有 URL
          - connected（已连接）  = configured + 真微信回调验签过（_last_verify_time > 0）
        """
        return self._last_verify_time > 0

    @property
    def configured(self) -> bool:
        """是否「配置就绪」——Flask 跑起来了 + API 凭据有效（不依赖真微信回调）。"""
        return self._flask_running and self._api_verified and bool(self.app_id and self.token)

    def start(self) -> dict:
        """启动 Flask 内嵌服务，接收微信回调。

        返回真实连接状态：
          {flask_running, api_verified, last_verify_time, error}
        """
        if self._flask_thread and self._flask_thread.is_alive():
            self._flask_running = True
            return self._status()

        if not self.app_id or not self.app_secret:
            self._last_error = "缺少 AppID 或 AppSecret，无法启动"
            self._connected = False
            return self._status()

        # 重置验签记录——每次新会话都要等微信重新验签才算"已连接"
        self._last_verify_time = 0.0

        self._init_wx_client()
        self._init_flask()

        self._stop_event.clear()
        self._flask_thread = threading.Thread(
            target=self._run_flask, name="OaClient", daemon=True,
        )
        self._flask_thread.start()

        # 等 Flask 启动并确认端口监听
        self._flask_running = self._wait_flask_ready(timeout=5)
        if not self._flask_running:
            self._last_error = "Flask 服务启动失败或端口被占用"
            return self._status()

        # 验证微信 API 凭据（获取 access_token，检查 AppID/AppSecret + IP 白名单）
        self._api_verified = self._verify_api()
        if not self._api_verified:
            return self._status()

        # 注意：这里不设 _connected = True——要等真微信回调验签才算"已连接"
        # 启动成功只代表 configured=True（配置就绪）
        self._last_error = ""
        print(f"[OaClient] 启动完成，端口={self.callback_port} 路径={self.callback_path} API验证={'通过' if self._api_verified else '失败'}", flush=True)
        return self._status()

    def probe_callback_url(self, url: str, timeout: float = 5.0) -> tuple:
        """主动探测穿透 URL 是否通到本地 Flask。

        发一个伪造签名的 GET 请求到 url，期望返回 403 Invalid
        （Flask 验签失败但确实收到了请求 = 链路通了）。
        返回 (ok: bool, msg: str)。
        """
        import urllib.request
        import urllib.error
        from urllib.parse import urlparse
        if not url:
            return False, "未配置回调 URL"
        try:
            # 兼容用户保存的 URL 是否已带 callback_path（如 .../wechat），避免拼成 /wechat/wechat
            parsed = urlparse(url)
            if parsed.path.rstrip("/").endswith(self.callback_path.lstrip("/")):
                full = url
            else:
                full = url.rstrip("/") + self.callback_path
            req = urllib.request.Request(full + "?signature=probe&timestamp=0&nonce=0&echostr=probe")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = resp.getcode()
                body = resp.read(200).decode(errors="ignore")
                # 200 也是可能的（如果 Flask 那边签名恰好对了，虽然极不可能）
                return code < 500, f"HTTP {code} ({body[:50]})"
        except urllib.error.HTTPError as e:
            # 403 Invalid = Flask 收到了请求但验签失败 = 链路通了
            if e.code == 403:
                return True, "链路通（Flask 返回 403 Invalid，说明穿透→Flask 可达）"
            body = e.read(200).decode(errors="ignore")
            return False, f"HTTP {e.code}: {body[:80]}"
        except Exception as e:
            return False, f"连接失败: {e}"

    def _status(self) -> dict:
        return {
            "flask_running": self._flask_running,
            "api_verified": self._api_verified,
            "last_verify_time": self._last_verify_time,
            "error": self._last_error,
        }

    def _wait_flask_ready(self, timeout: float = 5.0) -> bool:
        """等待 Flask 端口真正开始监听。"""
        import socket
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not (self._flask_thread and self._flask_thread.is_alive()):
                return False
            try:
                with socket.create_connection(("127.0.0.1", self.callback_port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.2)
        return False

    def _verify_api(self) -> bool:
        """调用微信 API 获取 access_token，验证凭据和 IP 白名单。"""
        if not self._wx_client:
            self._last_error = "wechatpy 客户端未初始化"
            return False
        try:
            # fetch_access_token 会真正请求微信服务器，验证 AppID/AppSecret/IP白名单
            token = self._wx_client.fetch_access_token()
            if token:
                return True
            self._last_error = "access_token 返回为空"
            return False
        except Exception as e:
            msg = str(e)
            # wechatpy 异常通常包含 errcode，提炼给用户
            self._last_error = f"微信 API 验证失败: {msg}"
            print(f"[OaClient] API 验证失败: {msg}", flush=True)
            return False

    def stop(self) -> None:
        """停止 Flask 服务。"""
        self._stop_event.set()
        self._connected = False
        if self._flask_thread:
            self._flask_thread.join(timeout=3)
        print("[OaClient] 已停止", flush=True)

    def set_message_handler(self, cb: Callable[[ChannelMessage], None]) -> None:
        self._on_message = cb

    def set_subscribe_handler(self, cb: Callable[[str], None]) -> None:
        """注册新关注用户回调，参数为 openid。"""
        self._on_subscribe = cb

    def send_reply(self, peer_id: str, content: str,
                   peer_type: str = "friend", at_sender_id: str = "") -> bool:
        """通过客服消息 API 发送回复。

        peer_id 是用户的 openid。公众号无群聊，peer_type 固定 friend。
        """
        if not content or not content.strip():
            return False
        if not self._wx_client:
            return False

        try:
            # wechatpy 客服消息：48小时窗口限制，2048字节限制
            self._wx_client.message.send_text(
                user_id=peer_id,
                content=content[:2048],
            )
            return True
        except Exception as e:
            print(f"[OaClient] 客服消息发送失败: {e}", flush=True)
            return False

    def get_contacts(self) -> list[dict]:
        """获取关注者列表（openid 列表）。

        受 500 次/日限制，默认返回缓存，手动调用 refresh_followers() 刷新。
        """
        if not self._wx_client:
            return []
        # 返回缓存（如果有）
        if self._followers_cache:
            return self._followers_cache
        # 首次拉取
        return self.refresh_followers()

    def health_check(self) -> dict:
        """健康检查：token 是否有效、Flask 是否在跑。

        直接检查 access_token 是否有效，不调 get_followers 等业务 API，
        避免消耗 500 次/天的业务配额。
        wechatpy 内部已缓存 access_token（2小时），未过期时零 API 调用。
        """
        if not self._wx_client:
            return {"ok": False, "error": "未配置公众号"}
        try:
            token = self._wx_client.access_token
            return {"ok": bool(token), "error": "" if token else "access_token 获取失败"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -------- 公众号特有方法 --------

    def refresh_followers(self) -> list[dict]:
        """强制刷新关注者列表（消耗 API 配额）。

        只调 get_followers() 拿 openid 列表，不调 user.get() 拉单个用户信息
        （服务号拉不到昵称等有效数据，没必要多消耗配额）。
        """
        if not self._wx_client:
            return []
        try:
            result = self._wx_client.user.get_followers()
            openids = result.get("data", {}).get("openid", [])
            contacts = []
            for oid in openids:
                contacts.append({
                    "peer_id": oid,
                    "peer_name": oid[:12],
                    "peer_type": "official",
                    "nickname": "",
                    "remark": "",
                    "gender": "",
                    "subscribe_at": 0,
                    "follow_at": "",
                })
            self._followers_cache = contacts
            self._followers_cache_time = time.time()
            self._last_followers_error = ""
            print(f"[OaClient] 关注者列表已刷新，共 {len(contacts)} 人", flush=True)
            return self._followers_cache
        except Exception as e:
            self._last_followers_error = str(e)
            print(f"[OaClient] 拉取关注者失败: {e}", flush=True)
            return []

    def configure(self, app_id: str, app_secret: str, token: str,
                  encoding_aes_key: str = "") -> None:
        """（重新）配置公众号参数。"""
        self.app_id = app_id
        self.app_secret = app_secret
        self.token = token
        self.encoding_aes_key = encoding_aes_key
        self._init_wx_client()

    # -------- 内部实现 --------

    def _init_wx_client(self) -> None:
        """初始化 wechatpy 客户端。"""
        if not self.app_id or not self.app_secret:
            return
        try:
            from wechatpy import WeChatClient
            self._wx_client = WeChatClient(self.app_id, self.app_secret)
        except Exception as e:
            print(f"[OaClient] wechatpy 客户端初始化失败: {e}", flush=True)
            self._wx_client = None

    def _init_flask(self) -> None:
        """初始化 Flask 应用和路由。"""
        from flask import Flask, request, make_response

        app = Flask(__name__)

        @app.route(self.callback_path, methods=["GET", "POST"])
        def wechat_callback():
            if request.method == "GET":
                return self._handle_verify(request)
            return self._handle_message(request)

        self._flask_app = app

    def _run_flask(self) -> None:
        """Flask 服务运行线程。"""
        if not self._flask_app:
            return
        # 用 werkzeug 直接跑，不输出访问日志
        from werkzeug.serving import make_server
        server = make_server("0.0.0.0", self.callback_port, self._flask_app)
        self._flask_running = True
        try:
            server.serve_forever()
        except Exception as e:
            print(f"[OaClient] Flask 服务异常: {e}", flush=True)
            self._last_error = f"Flask 服务异常: {e}"
        finally:
            self._flask_running = False
            self._connected = False

    def _handle_verify(self, request) -> str:
        """处理微信服务器验证（GET）。"""
        from wechatpy.utils import check_signature

        signature = request.args.get("signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        echostr = request.args.get("echostr", "")

        # 识别请求来源：MVP 自验还是真微信
        # 注意：不能用 remote_addr 判断，因为隧道（cloudflared/natapp/cpolar）转发后 remote_addr 也是 127.0.0.1
        # MVP 自验用固定 UA "MVP-SelfTest"，真微信服务器 UA 不含此关键字
        ua = request.headers.get("User-Agent", "")
        remote = request.remote_addr or ""
        is_self_test = "MVP-SelfTest" in ua

        try:
            check_signature(self.token, signature, timestamp, nonce)
            # 只有真微信请求才记录验签时间——MVP 自验不算
            if not is_self_test:
                self._last_verify_time = time.time()
                print(f"[OaClient] 微信回调验签成功: {self._last_verify_time}, ua={ua}, remote={remote}", flush=True)
            else:
                print(f"[OaClient] MVP 自验请求（不记录 last_verify_time）, remote={remote}", flush=True)
            return echostr
        except Exception as e:
            print(f"[OaClient] 微信回调验签失败: {e}", flush=True)
            return "Invalid", 403

    def _handle_message(self, request) -> str:
        """处理微信消息推送（POST）。"""
        from wechatpy import parse_message

        try:
            # 验签
            from wechatpy.utils import check_signature
            signature = request.args.get("signature", "")
            timestamp = request.args.get("timestamp", "")
            nonce = request.args.get("nonce", "")
            check_signature(self.token, signature, timestamp, nonce)
            # POST 消息只有真微信会发，MVP 自验不发 POST，能验签成功就是真微信
            ua = request.headers.get("User-Agent", "")
            remote = request.remote_addr or ""
            self._last_verify_time = time.time()
            print(f"[OaClient] 微信消息验签成功: {self._last_verify_time}, ua={ua}, remote={remote}", flush=True)
        except Exception:
            return "Invalid", 403

        # 解析消息
        xml = request.data
        try:
            msg = parse_message(xml)
        except Exception as e:
            print(f"[OaClient] 消息解析失败: {e}", flush=True)
            return "success"

        msg_id = getattr(msg, "id", "") or str(uuid.uuid4())

        # 消息排重
        if self._is_duplicate_msg(msg_id):
            return "success"

        # 事件消息（关注/取关/菜单）
        if msg.type == "event":
            event = getattr(msg, "event", "")
            if event == "subscribe" and self._on_subscribe:
                openid = getattr(msg, "source", "")
                if openid:
                    threading.Thread(
                        target=self._on_subscribe,
                        args=(openid,),
                        daemon=True,
                    ).start()
            return "success"

        # 文本消息：正常走 LLM
        if msg.type == "text":
            content = (msg.content or "").strip()
            if content:
                threading.Thread(
                    target=self._dispatch_message,
                    args=(msg,),
                    daemon=True,
                ).start()
            return "success"

        # 非文本消息（语音/图片/视频等）：交给 pipeline 判断是否回复提示语
        threading.Thread(
            target=self._dispatch_message,
            args=(msg,),
            daemon=True,
        ).start()
        return "success"

    def _dispatch_message(self, msg) -> None:
        """把微信消息转成 ChannelMessage，回调给 Pipeline。"""
        if not self._on_message:
            return

        # 微信公众号消息类型 → 统一 msg_type
        raw_type = getattr(msg, "type", "text")
        type_map = {
            "text": "text",
            "image": "image",
            "voice": "voice",
            "video": "video",
            "shortvideo": "video",
            "location": "location",
            "link": "text",
            "file": "file",
        }
        msg_type = type_map.get(raw_type, "other")

        channel_msg = ChannelMessage(
            id=str(getattr(msg, "id", uuid.uuid4())),
            channel=self.channel_name,
            peer_id=getattr(msg, "source", ""),  # openid
            peer_name=getattr(msg, "source", ""),
            peer_type="friend",  # 公众号无群聊
            sender_id=getattr(msg, "source", ""),
            sender_name="",
            content=getattr(msg, "content", ""),
            msg_type=msg_type,
            is_self=False,
            is_at=False,
            ts_ms=int(time.time() * 1000),
            file_size=0,              # 🆕 OA 公众号无原生文件 size
            is_ready=False,           # 🆕
        )
        try:
            self._on_message(channel_msg)
        except Exception as e:
            print(f"[OaClient] 消息分发异常: {e}", flush=True)

    def _is_duplicate_msg(self, msg_id: str) -> bool:
        """检查消息是否已处理过（防微信重试）。"""
        if not msg_id:
            return False
        now = time.time()
        # 清理过期记录
        expired = [k for k, v in self._processed_msgs.items() if now - v > self._msgid_expire]
        for k in expired:
            del self._processed_msgs[k]
        if msg_id in self._processed_msgs:
            return True
        self._processed_msgs[msg_id] = now
        return False
