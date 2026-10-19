"""渠道抽象层：统一消息模型 + 统一客户端接口。

所有渠道（微信 WCF、企微、飞书、钉钉、公众号）都实现 ChannelClient 协议，
消息统一用 ChannelMessage，Pipeline 只认这两个抽象，不关心具体渠道。

设计原则：
1. 渠道无关的放在抽象层（消息模型、发送/接收/联系人/健康检查）
2. 渠道特有的留在各自 Client 里（如微信的 start_wcf/stop_wcf、公众号的 5s 超时）
3. 风控是微信特有，不进抽象层，由 Pipeline 按 channel 判断是否走
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable


@dataclass
class ChannelMessage:
    """统一消息模型，所有渠道的原生消息都转换成这个结构。"""
    id: str                           # 唯一消息 id
    channel: str = ""                 # 渠道标识：wcf / wecom / feishu / dingtalk / oa
    peer_id: str = ""                 # 对方 id（wxid / roomid / openid / user_id）
    peer_name: str = ""               # 对方名称（展示用）
    peer_type: str = "friend"         # friend / group
    sender_id: str = ""               # 群里发消息的人 id，私聊 = peer_id
    sender_name: str = ""             # 群里发消息的人昵称，私聊 = peer_name
    content: str = ""                 # 文本内容
    msg_type: str = "text"            # 消息类型：text / voice / image / video / file / emoji / location / other
    is_self: bool = False             # 是否自己发的（过滤掉）
    is_at: bool = False               # 群里是否 @我
    ts_ms: int = 0                    # 毫秒时间戳
    # ===== 非文本消息扩展字段 =====
    file_path: str = ""               # 本地文件路径（file / voice / image / video 落地后填）
    file_name: str = ""               # 原始文件名（用户发的那个）
    media_id: str = ""                # 渠道侧 media_id（企微/飞书/钉钉用）
    media_url: str = ""               # base64 data URL（image/video 预处理后填，格式 data:mime;base64,xxx）
    file_size: int = 0                # 🆕 字节数，0=未知（各渠道归一化填）
    is_ready: bool = False            # 🆕 文件是否已下载就绪


@runtime_checkable
class ChannelClient(Protocol):
    """统一渠道客户端接口。所有渠道 Client 都实现这个协议。"""

    # 渠道名称（如 "wcf" / "wecom" / "feishu"）
    channel_name: str

    @property
    def connected(self) -> bool:
        """是否已连接。"""
        ...

    def start(self) -> None:
        """启动后台接收线程（不阻塞）。"""
        ...

    def stop(self) -> None:
        """停止后台线程，释放资源。"""
        ...

    def set_message_handler(self, cb: Callable[[ChannelMessage], None]) -> None:
        """注册消息回调。收到消息时调用 cb(msg)。"""
        ...

    def send_reply(self, peer_id: str, content: str,
                   peer_type: str = "friend", at_sender_id: str = "") -> bool:
        """发送回复。成功返回 True，失败/未连接返回 False（不抛异常）。"""
        ...

    def get_contacts(self) -> list[dict]:
        """获取联系人/群列表。未连接返回 []。"""
        ...

    def health_check(self) -> dict:
        """健康检查。返回 {"ok": bool, "error": str, ...}。"""
        ...
