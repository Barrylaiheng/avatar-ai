"""
P3-1 模块 pytest：WCF 私聊回复地址修复 + 回复链路验证（6 Seams）
对应 docs/PDD_INNER_wcf_reply_fix.md §3 的 6 条 Grill。

运行：
  python -m pytest tests/test_inner_wcf_reply_fix_pdd.py -v --tb=short
"""
import inspect
from typing import List, Tuple

import pytest

from aibridge.bridges.internal_message import InternalMessage
from aibridge.bridges.message_router import MessageRouter


# -------------------- MockAdapter --------------------
class MockAdapter:
    """Mock 渠道适配器，捕获 send_message 调用实参"""
    def __init__(self):
        self.sent: List[Tuple[str, str]] = []  # [(receiver_id, content), ...]

    def get_channel_name(self):
        return "wechat"

    def send_message(self, receiver_id: str, content: str, **kwargs) -> bool:
        self.sent.append((receiver_id, content))
        return True


# -------------------- fixtures --------------------
@pytest.fixture
def router_with_adapter():
    """带 mock adapter 的 MessageRouter"""
    router = MessageRouter()
    adapter = MockAdapter()
    router.register_adapter(adapter)
    return router, adapter


BOT_WXID = "bot_001"
USER_WXID = "user_alice"
GROUP_ID = "group_123"


def _make_private_msg(sender_id=USER_WXID, sender_name="Alice", content="你好"):
    """构造私聊 InternalMessage（模拟 wcf_adapter 产出）"""
    return InternalMessage(
        msg_id="msg_private",
        channel="wechat",
        sender_id=sender_id,
        sender_name=sender_name,
        receiver_id=BOT_WXID,  # wcf_adapter 私聊时 receiver_id = 机器人自己
        content=content,
        msg_type="text",
        group_id="",
        group_name="",
        is_at_me=False,
        is_private=True,
        timestamp=1700000000,
    )


def _make_group_msg(sender_id=USER_WXID, group_id=GROUP_ID, content="@bot 问题"):
    """构造群聊 InternalMessage"""
    return InternalMessage(
        msg_id="msg_group",
        channel="wechat",
        sender_id=sender_id,
        sender_name="",
        receiver_id=group_id,
        content=content,
        msg_type="text",
        group_id=group_id,
        group_name="测试群",
        is_at_me=True,
        is_private=False,
        timestamp=1700000001,
    )


# =========================================================================
# G1：私聊回复地址 = sender_id
# =========================================================================
def test_p31_g1_private_reply_to_sender(router_with_adapter):
    router, adapter = router_with_adapter
    msg = _make_private_msg()
    router.send_response(msg, "有的，阿克苏苹果很甜！")

    assert len(adapter.sent) == 1, f"期望 1 次发送，实际 {len(adapter.sent)}"
    receiver = adapter.sent[0][0]
    assert receiver == USER_WXID, f"私聊回复地址应=sender_id({USER_WXID})，实际={receiver}"
    assert receiver != BOT_WXID, f"私聊回复地址不应=机器人自己({BOT_WXID})"


# =========================================================================
# G2：群聊回复地址 = group_id
# =========================================================================
def test_p31_g2_group_reply_to_group(router_with_adapter):
    router, adapter = router_with_adapter
    msg = _make_group_msg()
    router.send_response(msg, "拍一拍，声音清脆的就是好西瓜！")

    assert len(adapter.sent) == 1
    receiver = adapter.sent[0][0]
    assert receiver == GROUP_ID, f"群聊回复地址应=group_id({GROUP_ID})，实际={receiver}"


# =========================================================================
# G3：send_response 源码正确
# =========================================================================
def test_p31_g3_source_code_correct():
    src = inspect.getsource(MessageRouter.send_response)
    assert "sender_id" in src and "is_private" in src, (
        "send_response 源码应包含 sender_id + is_private"
    )
    assert "msg.receiver_id if msg.is_private" not in src, (
        "send_response 源码不应再出现 'msg.receiver_id if msg.is_private' 模式"
    )


# =========================================================================
# G4：多用户私聊各自收到回复
# =========================================================================
def test_p31_g4_multi_user_private(router_with_adapter):
    router, adapter = router_with_adapter
    users = [
        ("user_bob", "Bob", "有葡萄吗？"),
        ("user_carol", "Carol", "西瓜怎么选？"),
        ("user_dave", "Dave", "草莓多少钱？"),
    ]
    for uid, uname, text in users:
        msg = _make_private_msg(sender_id=uid, sender_name=uname, content=text)
        router.send_response(msg, f"回复给{uname}")

    assert len(adapter.sent) == 3, f"期望 3 次发送，实际 {len(adapter.sent)}"
    for i, (uid, uname, _) in enumerate(users):
        receiver = adapter.sent[i][0]
        assert receiver == uid, f"用户{i+1}({uname}) 回复地址应={uid}，实际={receiver}"


# =========================================================================
# G5：多群聊各自收到回复
# =========================================================================
def test_p31_g5_multi_group(router_with_adapter):
    router, adapter = router_with_adapter
    groups = [
        ("group_a", "水果群", "user_bob"),
        ("group_b", "团购群", "user_carol"),
    ]
    for gid, gname, uid in groups:
        msg = _make_group_msg(sender_id=uid, group_id=gid, content=f"@bot {gname}问题")
        router.send_response(msg, f"回复到{gname}")

    assert len(adapter.sent) == 2
    for i, (gid, gname, _) in enumerate(groups):
        receiver = adapter.sent[i][0]
        assert receiver == gid, f"群{i+1}({gname}) 回复地址应={gid}，实际={receiver}"


# =========================================================================
# G6：修复前后对比
# =========================================================================
def test_p31_g6_before_after_comparison(router_with_adapter):
    router, adapter = router_with_adapter
    msg = _make_private_msg()

    # 模拟修复前的 buggy 逻辑
    buggy_receiver = msg.receiver_id if msg.is_private else msg.group_id
    assert buggy_receiver == BOT_WXID, (
        f"修复前私聊回复地址应=机器人自己({BOT_WXID})，实际={buggy_receiver}"
    )

    # 修复后的正确逻辑
    router.send_response(msg, "fixed reply")
    fixed_receiver = adapter.sent[0][0] if adapter.sent else None
    assert fixed_receiver == USER_WXID, (
        f"修复后私聊回复地址应=用户({USER_WXID})，实际={fixed_receiver}"
    )
    assert buggy_receiver != fixed_receiver, "修复前后地址应不同"
