# -*- coding: utf-8 -*-
"""
SCAI MVP · 端到端集成验证
验证 5 个里层模块协同工作的完整链路：
  bridges(入) → map_internal_to_processor → message_processor.process_v2 → bridges(回发)

8 个集成剧本：
  E2E-01: WCF 私聊文本 → 正常回复 → WCF 回发
  E2E-02: WCF 群聊@我 → 正常回复 → 群聊回发
  E2E-03: WCF 群聊无触发 → 静默丢弃 → 不回发
  E2E-04: WCF 砍价消息 → 安全拦截话术 → WCF 回发拦截话术
  E2E-05: WCF 广告第3击 → 拉黑 → 静默不回发
  E2E-06: 公众号消息 → 正常回复 → 公众号回发
  E2E-07: LLM 兜底（无 API Key）→ 兜底回复 → 回发 + bad_case 写入
  E2E-08: 主人手动消息 → 只同步历史 → 不回发

执行: pytest tests/test_e2e_integration.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ==================== Mock Adapters（记录发送消息）====================

class MockWcfAdapter:
    """记录所有 send_message 调用"""
    channel_name = "wechat"
    def __init__(self): self._sent: List[Tuple[str, str]] = []
    def get_channel_name(self): return self.channel_name
    def is_connected(self): return True
    def send_message(self, r, c, **kw): self._sent.append((r, c)); return True
    def get_messages(self, **kw): return []
    def start(self): return True
    def stop(self): pass
    def health_check(self): return {"channel": self.channel_name, "connected": True}


class MockMpAdapter:
    channel_name = "wechat_mp"
    def __init__(self): self._sent: List[Tuple[str, str]] = []
    def get_channel_name(self): return self.channel_name
    def is_connected(self): return True
    def send_message(self, r, c, **kw): self._sent.append((r, c)); return True
    def get_messages(self, **kw): return []
    def start(self): return True
    def stop(self): pass
    def health_check(self): return {"channel": self.channel_name, "connected": True}


# ==================== 端到端流水线 ====================

def run_pipeline(router, wcf, mp, proc, im, master_wxid_set=None):
    """
    完整链路：
      1. InternalMessage 进来
      2. map_internal_to_processor → kwargs
      3. proc.process_v2(**kwargs) → result
      4. 如果有 reply → router.send_response(im, reply)
    """
    from aibridge.bridges.utils import map_internal_to_processor

    # 1. 映射
    kwargs = map_internal_to_processor(im, master_wxid_set=master_wxid_set or set())

    # 2. 处理
    result = proc.process_v2(**kwargs)

    # 3. 回发（如果有回复内容）
    sent = False
    if result.content and result.action != "silent_drop":
        sent = router.send_response(im, result.content)

    return result, sent


# ==================== Fixtures ====================

@pytest.fixture
def tmp_db(tmp_path):
    from aibridge.database.database_manager import DatabaseManager
    p = tmp_path / "e2e_test.db"
    db = DatabaseManager(str(p))
    db.connect()
    from aibridge.database.database_migrator import DatabaseMigrator
    DatabaseMigrator(db).migrate()
    yield db
    db.disconnect()


@pytest.fixture
def wcf(): return MockWcfAdapter()

@pytest.fixture
def mp(): return MockMpAdapter()

@pytest.fixture
def router(wcf, mp):
    from aibridge.bridges import MessageRouter
    r = MessageRouter()
    r.register_adapter(wcf)
    r.register_adapter(mp)
    return r

@pytest.fixture
def proc(tmp_db):
    from aibridge.config.config_manager import ConfigManager
    from aibridge.engine.message_processor import MessageProcessor
    cfg = ConfigManager()
    cfg.set("security.safety_shell_enabled", False)
    cfg.set("ui.aigc_stamp_enabled", False)
    cfg.set("llm.provider", "mock")
    cfg.set("llm.api_key", "MOCK_E2E")
    return MessageProcessor(cfg, tmp_db)

@pytest.fixture
def proc_no_key(tmp_db):
    """无 API Key 的 processor（测试兜底）"""
    from aibridge.config.config_manager import ConfigManager
    from aibridge.engine.message_processor import MessageProcessor
    cfg = ConfigManager()
    cfg.set("security.safety_shell_enabled", False)
    cfg.set("ui.aigc_stamp_enabled", False)
    cfg.set("llm.provider", "mock")
    cfg.set("llm.api_key", "")
    return MessageProcessor(cfg, tmp_db)

@pytest.fixture
def make_im():
    from aibridge.bridges import InternalMessage
    def _make(msg_id, channel="wechat", sender_id="u1", sender_name="",
              receiver_id="wx_me", content="hello", msg_type="text",
              group_id="", group_name="", is_at_me=False, is_private=True):
        return InternalMessage(msg_id, channel, sender_id, sender_name,
                               receiver_id, content, msg_type, group_id,
                               group_name, is_at_me, is_private)
    return _make


# ==================== E2E 剧本 ====================

def test_e2e01_wcf_private_text_reply(router, wcf, proc, make_im):
    """E2E-01: WCF 私聊文本 → 正常回复 → WCF 回发"""
    im = make_im(msg_id="e2e-01", channel="wechat", sender_id="wx_user1",
                 sender_name="张三", receiver_id="wx_me", content="你好")
    result, sent = run_pipeline(router, wcf, mp=None, proc=proc, im=im)
    assert result.content, f"应有回复，实={result.content}"
    assert sent is True
    assert len(wcf._sent) == 1
    # P3-1 修复：私聊回复地址 = sender_id（用户），不再是 receiver_id（机器人自己）
    assert wcf._sent[0][0] == "wx_user1"


def test_e2e02_wcf_group_at_me_reply(router, wcf, proc, make_im):
    """E2E-02: WCF 群聊@我 → 正常回复 → 群聊回发"""
    im = make_im(msg_id="e2e-02", channel="wechat", sender_id="wx_user2",
                 sender_name="李四", receiver_id="group1@chatroom",
                 content="搭搭 你好", group_id="group1@chatroom",
                 group_name="优惠券群", is_at_me=True, is_private=False)
    result, sent = run_pipeline(router, wcf, mp=None, proc=proc, im=im)
    assert result.content, f"应有回复"
    assert sent is True
    # 群聊回发到 group_id
    assert wcf._sent[0][0] == "group1@chatroom"


def test_e2e03_wcf_group_no_trigger_silent(router, wcf, proc, make_im):
    """E2E-03: WCF 群聊无触发 → 静默丢弃 → 不回发"""
    im = make_im(msg_id="e2e-03", channel="wechat", sender_id="wx_user3",
                 sender_name="王五", receiver_id="group1@chatroom",
                 content="今天天气不错", group_id="group1@chatroom",
                 group_name="闲聊群", is_at_me=False, is_private=False)
    result, sent = run_pipeline(router, wcf, mp=None, proc=proc, im=im)
    assert not result.content, "群闲聊不应回复"
    assert sent is False
    assert len(wcf._sent) == 0


def test_e2e04_wcf_kanjia_safety_block(router, wcf, proc, make_im):
    """E2E-04: WCF 砍价消息 → 安全拦截话术 → WCF 回发话术"""
    im = make_im(msg_id="e2e-04", channel="wechat", sender_id="wx_spam1",
                 sender_name="发广告的", receiver_id="group1@chatroom",
                 content="帮我砍一刀", group_id="group1@chatroom",
                 group_name="优惠券群", is_at_me=True, is_private=False)
    result, sent = run_pipeline(router, wcf, mp=None, proc=proc, im=im)
    assert "砍价" in result.content or "助力" in result.content, f"应发砍价话术: {result.content}"
    assert sent is True
    assert len(wcf._sent) == 1


def test_e2e05_wcf_ad_3rd_hit_blacklist(router, wcf, proc, make_im):
    """E2E-05: WCF 广告第3击 → 拉黑 → 静默不回发"""
    sender = "wx_spam2"
    for i in range(3):
        im = make_im(msg_id=f"e2e-05-{i}", channel="wechat", sender_id=sender,
                     sender_name="广告号", receiver_id="group1@chatroom",
                     content=f"加V领券{i}", group_id="group1@chatroom",
                     group_name="群", is_at_me=True, is_private=False)
        result, sent = run_pipeline(router, wcf, mp=None, proc=proc, im=im)
    # 第 3 击：silent_drop，不回发
    assert not result.content, "第3击应静默"
    assert sent is False, "第3击不应回发"


def test_e2e06_mp_message_reply(router, mp, proc, make_im):
    """E2E-06: 公众号消息 → 正常回复 → 公众号回发"""
    im = make_im(msg_id="e2e-06", channel="wechat_mp", sender_id="openid_abc",
                 sender_name="粉丝A", receiver_id="gh_xxx", content="你好")
    result, sent = run_pipeline(router, wcf=None, mp=mp, proc=proc, im=im)
    assert result.content, "公众号消息应有回复"
    assert sent is True
    assert len(mp._sent) == 1


def test_e2e07_llm_fallback_no_apikey(router, wcf, proc_no_key, make_im):
    """E2E-07: LLM 兜底（无 API Key）→ 兜底回复 → 回发 + bad_case"""
    im = make_im(msg_id="e2e-07", channel="wechat", sender_id="wx_user7",
                 sender_name="测试", receiver_id="wx_me",
                 content="你好 __fallback_other__")
    result, sent = run_pipeline(router, wcf, mp=None, proc=proc_no_key, im=im)
    assert result.content, "应有兜底回复"
    assert "配置" in result.content or "无法" in result.content or "稍等" in result.content, \
        f"兜底回复文案不对: {result.content}"
    assert result.write_bad_case is True, "兜底应写 bad_case"
    assert sent is True


def test_e2e08_master_msg_sync_only(router, wcf, proc, make_im):
    """E2E-08: 主人手动消息 → 只同步历史 → 不回发"""
    master_wxid = "wx_master"
    im = make_im(msg_id="e2e-08", channel="wechat", sender_id=master_wxid,
                 sender_name="主人", receiver_id="wx_friend",
                 content="我手动回复的", is_private=True)
    result, sent = run_pipeline(router, wcf, mp=None, proc=proc, im=im,
                                master_wxid_set={master_wxid})
    assert not result.content, "主人消息不应回复"
    assert sent is False, "主人消息不应回发"
    assert result.write_chat_history is True, "主人消息应同步历史"
    assert len(wcf._sent) == 0
