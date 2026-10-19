"""端到端验证：模拟 WCF 收到 1 条好友消息 → 完整链路跑通。

完全不碰真实微信 / 真实 WCF。做法：
1. 建一个智能体 + 绑定 Skip LLM（占位：allow_no_llm 模式）
2. 给这个智能体绑定 peer wxid_testfriend
3. Bridge 单例启动 channel_modules（WCF 线程只探活，不注入）
4. 手动调 wcf_client.inject_message() 注入一条"你好"消息
5. 等 pipeline 处理完 → 查 conversation + chat_message
6. 调 get_all_history + get_history_session 看结构是否符合前端预期

注意：LLM 调用如果用户没配真实 API 会失败，但 send_message 会把错误写进 assistant_message，
保证链路不中断。这里用户说"可以配合"，所以用 Skip LLM + send_message 错误回退路径来测。
"""

import sys
import os
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "app"))

from storage import (
    agents_dao, channels_dao, conv_dao, msg_dao, llm_dao,
)
from storage.db import get_conn, reset_db_for_tests
from bridge import BridgeServer
from channel.wcf_client import WcfMessage


def main():
    # 首次 get_conn() 会自动建表/迁移，不需要额外 init
    get_conn()

    # 1. 清理旧测试数据（只清测试 peer 的会话和绑定）
    TEST_PEER = "wxid_testfriend_e2e"
    TEST_AGENT_NAME = "E2E 测试智能体 WCF"

    # 先找有没有旧测试智能体，有就复用
    existing_agents = [a for a in agents_dao.list_all()
                       if a.get("name") == TEST_AGENT_NAME]
    if existing_agents:
        agent = existing_agents[0]
    else:
        agent = agents_dao.create({
            "name": TEST_AGENT_NAME,
            "avatar_emoji": "🤖",
            "system_prompt": "你是一个 E2E 测试助手，回复要简短。",
            "style": "简洁",
            "aigc_enabled": 1,
            "kb_ids": "[]",
        })
    agent_id = agent["id"]
    print(f"[E2E] 测试智能体: {agent_id}  name={agent['name']}", flush=True)

    # 2. 建绑定
    b = channels_dao.set_binding(
        agent_id=agent_id,
        channel="wcf",
        peer_id=TEST_PEER,
        peer_name="测试好友-小凡",
        peer_type="friend",
        enabled=True,
    )
    print(f"[E2E] 绑定: cb_id={b['id']} enabled={b['enabled']}", flush=True)

    # 3. 启动 Bridge + channel_modules（WCF 线程只探活，不注入）
    bridge = BridgeServer()
    bridge.start_channel_modules()
    print(f"[E2E] Bridge 启动，WCF 连接态={bridge.wcf_client.connected}", flush=True)

    # 4. 注入一条 WCF 消息（纯内存，不碰真实微信）
    msg = WcfMessage(
        id="test_e2e_001",
        channel="wcf",
        peer_id=TEST_PEER,
        peer_name="测试好友-小凡",
        peer_type="friend",
        sender_id=TEST_PEER,
        sender_name="测试好友-小凡",
        content="你好，我是小凡，今天天气怎么样？",
        is_self=False,
        is_at=False,
        ts_ms=int(time.time() * 1000),
    )
    print(f"[E2E] 注入 WCF 消息: {msg.content}", flush=True)
    result = bridge.pipeline.handle_wcf_message(msg)
    print(f"[E2E] Pipeline 结果: handled={result.handled} reason={result.reason} "
          f"conv_id={result.conversation_id} sent_to_wcf={result.sent_to_wcf}",
          flush=True)
    if result.assistant_text:
        snippet = result.assistant_text.replace("\n", " ")[:80]
        print(f"[E2E] 回复内容: {snippet}", flush=True)

    # 5. 查 DB：conversation + 两条消息
    time.sleep(0.3)  # 等异步落库（send_message 是同步的，其实不用，但保险）
    rows = conv_dao.list_all(agent_id=agent_id, channel="wcf")
    mine = [r for r in rows if r.get("peer_id") == TEST_PEER]
    if not mine:
        print("[E2E] ❌ 未找到对应 conversation", flush=True)
        return 1
    conv = mine[0]
    print(f"[E2E] conversation: {conv['id']} title={conv['title']} "
          f"msg_count={conv.get('message_count')} channel={conv.get('channel')} "
          f"peer_name={conv.get('peer_name')}", flush=True)

    msgs = msg_dao.list_by_conversation(conv["id"])
    print(f"[E2E] 消息数: {len(msgs)}", flush=True)
    for m in msgs:
        mark = " [AIGC]" if m.get("aigc_marked") else ""
        channel_ok = m.get("channel") == "wcf"
        print(f"  - role={m['role']:9} aigc={m.get('aigc_marked')} channel_ok={channel_ok} "
              f"model={m.get('model','') or 'None'} content={m['content'][:60]}{mark}",
              flush=True)

    # 6. 用 Bridge handler 拉历史页需要的结构
    hist = bridge._handle_get_all_history({
        "agent_id": agent_id, "channel": "wcf", "with_messages": False,
    })
    print(f"[E2E] get_all_history 返回会话数: {len(hist['sessions'])}", flush=True)
    for s in hist["sessions"]:
        print(f"  - id={s['id']} agent_name={s['agent_name']} "
              f"channel={s['channel']} user_name={s['user_name']} "
              f"msg_count={s['message_count']}", flush=True)
        break

    if result.conversation_id:
        sess = bridge._handle_get_history_session({"session_id": result.conversation_id})
        print(f"[E2E] get_history_session: session id={sess['session']['id']} "
              f"messages={len(sess['messages'])}", flush=True)

    print("[E2E] ✅ 全链路验证完成", flush=True)
    bridge.stop_channel_modules()
    return 0


if __name__ == "__main__":
    sys.exit(main())
