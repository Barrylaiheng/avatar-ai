# -*- coding: utf-8 -*-
"""
管理者（主人）标签 E2E 测试
方案：channel_binding.is_manager 打标 → 命中主人模式时用全局预设替换 persona

用例：
  TEST 1 表结构自检（新建库自动带 is_manager；老库 ALTER 升级后数据不丢）
  TEST 2 DAO 基本语义（set_manager / is_manager_peer / list_managers / clear_managers）
  TEST 3 save_agent_managers 全量覆盖（去重 + 字符串入参兼容 + 清空 + 缺参报错）
  TEST 4 排他冲突守卫（不被静默抢占 + conflicts 回报 + 对方绑定无损）
  TEST 5 抢占替换清幽灵标记（replace_binding 清 is_manager）
  TEST 6 渠道归一（wcf/wechat 必须隔离）+ MANAGER_PROMPT 常量
  TEST 7 主人模式接线守卫（替换只发生在 is_manager_peer 命中的分支，且只动 persona 槽）
  TEST 8 主人模式真的生效（审计 A：用假 LLM 真跑 _handle_send_message，比对 system 消息）

注意：TEST 2/2g 会走 set_binding，该函数里有一段遗留调试代码，enabled 变化时会打印
      一大片 "⚠️⚠️⚠️ 状态变化！" + 调用栈 —— 那是既有噪声，不是报错。
"""

import os, sys, tempfile, shutil, sqlite3, pathlib, io, contextlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "app/storage"))

# 隔离 DB：用 SCAI_APP_DIR 覆盖 app/storage/db.py 里的 get_app_dir()
_TMP = tempfile.mkdtemp(prefix="tmp_agent_mgr_tag_")
os.environ["SCAI_APP_DIR"] = _TMP
print(f"[DB] 隔离 SCAI_APP_DIR = {_TMP}")

import py_compile
py_compile.compile(str(ROOT / "app/bridge.py"), doraise=True)
print("[BASELINE 0] bridge.py 编译通过")

# 在导入 storage 之前重置连接（任何之前的全局 _CONN 清掉）
from storage.db import reset_db_for_tests, get_conn
reset_db_for_tests()

from storage import agents_dao, channels_dao, llm_dao   # noqa: E402
from storage.retriever import MANAGER_PROMPT    # noqa: E402
from bridge import BridgeServer                 # noqa: E402

CH = "dingtalk"   # 用一个非 wcf 渠道，顺便覆盖「非默认渠道」路径


def create_bare_bridge():
    return BridgeServer.__new__(BridgeServer)


def _point_to(dirpath):
    """切换被测库（get_app_dir 每次读环境变量，重置连接即可生效）。"""
    os.environ["SCAI_APP_DIR"] = str(dirpath)
    reset_db_for_tests()


def new_agent(name):
    return agents_dao.create({"name": name})["id"]


def raw_binding(agent_id, channel, peer_id):
    row = get_conn().execute(
        "SELECT * FROM channel_binding WHERE agent_id=? AND channel=? AND peer_id=?",
        (agent_id, channel, peer_id),
    ).fetchone()
    return dict(row) if row else None


# =================================================================
# TEST 1：表结构自检 + 老库升级路径
# =================================================================
def test1_schema_migration():
    _point_to(_TMP)
    conn = get_conn()
    conn.execute("SELECT 1").fetchall()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(channel_binding)")]
    assert "is_manager" in cols, f"TEST1 FAIL：channel_binding 缺 is_manager 列，实得 {cols}"
    print("  [1a OK] 新建库自动带 is_manager 列")

    # 造一个「老库」：channel_binding 没有 is_manager 列
    legacy_dir = pathlib.Path(_TMP) / "legacy"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_db = legacy_dir / "scai_v1.db"
    lc = sqlite3.connect(str(legacy_db))
    lc.execute(
        """CREATE TABLE channel_binding (
               id TEXT PRIMARY KEY,
               agent_id TEXT NOT NULL,
               channel TEXT NOT NULL,
               peer_id TEXT NOT NULL,
               peer_name TEXT NOT NULL DEFAULT '',
               peer_type TEXT NOT NULL DEFAULT 'friend',
               enabled INTEGER NOT NULL DEFAULT 1,
               created_at INTEGER NOT NULL DEFAULT 0,
               updated_at INTEGER NOT NULL DEFAULT 0,
               UNIQUE (agent_id, channel, peer_id))"""
    )
    lc.execute(
        "INSERT INTO channel_binding "
        "(id, agent_id, channel, peer_id, peer_name, enabled, created_at, updated_at) "
        "VALUES (?,?,?,?,?,1,?,?)",
        ("cb-legacy-1", "agent-legacy", CH, "p-legacy", "老数据", 111, 222),
    )
    lc.commit()
    n_before = lc.execute("SELECT COUNT(*) FROM channel_binding").fetchone()[0]
    lc.close()

    # 切到老库，触发建表迁移
    _point_to(legacy_dir)
    lconn = get_conn()
    lconn.execute("SELECT 1").fetchall()
    lcols = [r[1] for r in lconn.execute("PRAGMA table_info(channel_binding)")]
    assert "is_manager" in lcols, f"TEST1 FAIL：老库没有自动补 is_manager 列，实得 {lcols}"
    n_after = lconn.execute("SELECT COUNT(*) FROM channel_binding").fetchone()[0]
    assert n_before == n_after == 1, f"TEST1 FAIL：升级丢数据 {n_before} -> {n_after}"
    keep = lconn.execute(
        "SELECT peer_name, enabled, is_manager FROM channel_binding WHERE id='cb-legacy-1'"
    ).fetchone()
    assert keep["peer_name"] == "老数据" and keep["enabled"] == 1 and keep["is_manager"] == 0, \
        f"TEST1 FAIL：老数据被污染 {dict(keep)}"
    print(f"  [1b OK] 老库 ALTER 升级：列已补上，{n_after} 条数据保留，旧行 is_manager 默认为 0")

    _point_to(_TMP)
    print("[TEST 1 PASS] 表结构自检 + 老库无损升级")


# =================================================================
# TEST 2：DAO 基本语义
# =================================================================
def test2_dao_semantics():
    _point_to(_TMP)
    a = new_agent("主人语义-A")

    # 2a 未标记
    assert channels_dao.is_manager_peer(a, CH, "p1") is False
    assert channels_dao.list_managers(a, CH) == []
    print("  [2a OK] 未标记时不认管理者")

    # 2b 标记：强制 enabled=1
    rec = channels_dao.set_manager(a, CH, "p1", peer_name="张三")
    assert rec and rec["is_manager"] == 1, f"TEST2b FAIL：标记失败 {rec}"
    assert rec["enabled"] == 1, "TEST2b FAIL：set_manager 未强制 enabled=1"
    assert channels_dao.is_manager_peer(a, CH, "p1") is True
    lm = channels_dao.list_managers(a, CH)
    assert len(lm) == 1 and lm[0]["peer_id"] == "p1" and lm[0]["peer_name"] == "张三"
    print("  [2b OK] 标记成功且自动 enabled=1")

    # 2c 重复标记不产生第二条
    channels_dao.set_manager(a, CH, "p1", peer_name="")
    assert len(channels_dao.list_managers(a, CH)) == 1, "TEST2c FAIL：重复标记产生了多条绑定"
    # 2d 空 peer_name 不覆盖已有姓名（COALESCE(NULLIF(...))）
    assert raw_binding(a, CH, "p1")["peer_name"] == "张三", "TEST2d FAIL：空名覆盖了已有 peer_name"
    print("  [2c/2d OK] 幂等标记，空名不覆盖已有姓名")

    # 2e 取消标记
    off = channels_dao.set_manager(a, CH, "p1", is_manager=False)
    assert off and off["is_manager"] == 0, f"TEST2e FAIL：取消失败 {off}"
    assert channels_dao.is_manager_peer(a, CH, "p1") is False
    print("  [2e OK] 取消标记生效")

    # 2f 不存在的记录取消标记 → 无操作返回 {}，不凭空建行
    assert channels_dao.set_manager(a, CH, "nope", is_manager=False) == {}, \
        "TEST2f FAIL：不存在的 peer 取消标记应返回 {}"
    assert raw_binding(a, CH, "nope") is None, "TEST2f FAIL：取消标记凭空建了行"
    print("  [2f OK] 不存在时取消标记为无操作")

    # 2g enabled=0 时不算管理者（is_manager=1 但 enabled=0）
    channels_dao.set_manager(a, CH, "p1", is_manager=True)
    channels_dao.set_binding(a, CH, "p1", "张三", enabled=False)
    rb = raw_binding(a, CH, "p1")
    assert rb["is_manager"] == 1 and rb["enabled"] == 0, \
        f"TEST2g FAIL：前置条件不成立 {rb}（旧写入不该动 is_manager）"
    assert channels_dao.is_manager_peer(a, CH, "p1") is False, \
        "TEST2g FAIL：enabled=0 仍被当作管理者"
    assert channels_dao.list_managers(a, CH) == []
    print("  [2g OK] enabled=0 时不算管理者；旧绑定写入不会清掉 is_manager 标记")

    # 2h clear_managers 只清标记不删绑定
    channels_dao.set_manager(a, CH, "p1", is_manager=True)
    channels_dao.set_manager(a, CH, "p2", peer_name="李四")
    n = channels_dao.clear_managers(a, CH)
    assert n == 2, f"TEST2h FAIL：clear_managers 应清 2 条，实得 {n}"
    assert channels_dao.list_managers(a, CH) == []
    assert raw_binding(a, CH, "p1") is not None and raw_binding(a, CH, "p2") is not None, \
        "TEST2h FAIL：clear_managers 把绑定一起删了"
    print("  [2h OK] clear_managers 只清标记，绑定行保留")

    print("[TEST 2 PASS] DAO 基本语义")


# =================================================================
# TEST 3：save_agent_managers 全量覆盖
# =================================================================
def test3_save_full_overwrite():
    _point_to(_TMP)
    br = create_bare_bridge()
    a = new_agent("全量覆盖-A")

    # 3a 首批写入
    r = br._handle_save_agent_managers({
        "agent_id": a, "channel": CH,
        "managers": [{"peer_id": "m3a", "peer_name": "甲"}, {"peer_id": "m3b", "peer_name": "乙"}],
    })
    assert r["saved"] is True and r["conflicts"] == [], f"TEST3a FAIL：{r}"
    ids = sorted(m["peer_id"] for m in channels_dao.list_managers(a, CH))
    assert ids == ["m3a", "m3b"], f"TEST3a FAIL：实得 {ids}"
    print("  [3a OK] 写入 2 名管理者")

    # 3b 全量覆盖 + 字符串入参兼容 + 去重
    r = br._handle_save_agent_managers({"agent_id": a, "channel": CH, "managers": ["m3b", "m3b", "m3c"]})
    assert r["saved"] is True
    ids = sorted(m["peer_id"] for m in channels_dao.list_managers(a, CH))
    assert ids == ["m3b", "m3c"], f"TEST3b FAIL：全量覆盖/去重不对，实得 {ids}"
    assert channels_dao.is_manager_peer(a, CH, "m3a") is False, "TEST3b FAIL：未覆盖掉旧名单 m3a"
    print("  [3b OK] 全量覆盖 + 字符串入参 + 去重")

    # 3c 清空
    r = br._handle_save_agent_managers({"agent_id": a, "channel": CH, "managers": []})
    assert r["cleared"] == 2, f"TEST3c FAIL：cleared 应为 2，实得 {r['cleared']}"
    assert channels_dao.list_managers(a, CH) == []
    print("  [3c OK] 空名单清空全部标记")

    # 3d 缺 agent_id 必须报错（不能默默写到一个空 id 上）
    caught = None
    try:
        br._handle_save_agent_managers({"channel": CH, "managers": ["m3a"]})
    except ValueError as e:
        caught = e
    assert caught is not None, "TEST3d FAIL：缺 agent_id 没有报错"
    print("  [3d OK] 缺 agent_id 抛 ValueError")

    print("[TEST 3 PASS] save_agent_managers 全量覆盖语义")


# =================================================================
# TEST 4：管理者可同时绑多个 agent（不排他）
# =================================================================
def test4_conflict_guard():
    _point_to(_TMP)
    br = create_bare_bridge()
    a = new_agent("守卫-A")
    b = new_agent("守卫-B")

    # ★ 新设计：管理者不排他——同一个 peer 可以同时绑在 A 和 B 下
    channels_dao.set_binding(b, CH, "px", "被占用者")
    r = br._handle_save_agent_managers({"agent_id": a, "channel": CH, "managers": [{"peer_id": "px"}]})
    assert r["conflicts"] == [], f"TEST4 FAIL：管理者不应有排他冲突 {r['conflicts']}"
    assert channels_dao.is_manager_peer(a, CH, "px") is True, \
        "TEST4 FAIL：管理者应能同时绑多个 agent"
    # 对方绑定也要无损
    bb = raw_binding(b, CH, "px")
    assert bb["enabled"] == 1 and bb["is_manager"] == 0, f"TEST4 FAIL：对方绑定被改动 {bb}"
    print("  [4a OK] 管理者可同时绑多个 agent（不排他），对方绑定无损")

    # 自己已 enabled 的 peer 也能绑定为管理者（自己覆盖自己）
    channels_dao.set_binding(a, CH, "px2", "自己的")
    r2 = br._handle_save_agent_managers({"agent_id": a, "channel": CH, "managers": [{"peer_id": "px2"}]})
    assert r2["conflicts"] == [], f"TEST4 FAIL：自己占用被误判为冲突 {r2['conflicts']}"
    assert channels_dao.is_manager_peer(a, CH, "px2") is True
    print("  [4b OK] 自己占用自己的 peer 不误报冲突")

    # 管理者同时绑多个 agent 验证（聚合路由的前提）
    channels_dao.set_binding(b, CH, "py", "被占用者2")
    r3 = br._handle_save_agent_managers({
        "agent_id": a, "channel": CH, "managers": [{"peer_id": "ok1"}, {"peer_id": "py"}],
    })
    assert r3["conflicts"] == [], f"TEST4 FAIL：管理者不应有排他冲突 {r3['conflicts']}"
    assert channels_dao.is_manager_peer(a, CH, "ok1") is True
    assert channels_dao.is_manager_peer(a, CH, "py") is True  # 同时绑成功
    print("  [4c OK] 管理者同时绑多个 agent 全部成功（聚合路由前提）")

    print("[TEST 4 PASS] 管理者不排他，可同时绑多个 agent")


# =================================================================
# TEST 5：抢占替换清幽灵标记
# =================================================================
def test5_replace_clears_ghost():
    _point_to(_TMP)
    a = new_agent("抢占新主-A")
    b = new_agent("抢占旧主-B")

    channels_dao.set_manager(b, CH, "py", peer_name="旧主人")
    assert channels_dao.is_manager_peer(b, CH, "py") is True

    channels_dao.replace_binding(a, CH, "py", "旧主人")
    assert channels_dao.is_manager_peer(b, CH, "py") is False, \
        "TEST5 FAIL：抢占后旧主人仍是管理者（幽灵标记）"
    ob = raw_binding(b, CH, "py")
    assert ob["is_manager"] == 0 and ob["enabled"] == 0, f"TEST5 FAIL：旧主人绑定未清干净 {ob}"
    nb = raw_binding(a, CH, "py")
    assert nb["enabled"] == 1, f"TEST5 FAIL：新主人绑定未启用 {nb}"
    print("  [5 OK] 抢占替换后旧主人的 is_manager 被清掉")

    print("[TEST 5 PASS] 抢占替换无幽灵标记")


# =================================================================
# TEST 6：渠道归一 + 主人模式预设常量
# =================================================================
def test6_channel_and_prompt_const():
    _point_to(_TMP)
    br = create_bare_bridge()
    a = new_agent("渠道归一-A")

    # 面板内部键是 wechat，后端是 wcf：两者必须隔离，才能证明前端 _apiChan 归一不是多余的
    br._handle_save_agent_managers({"agent_id": a, "channel": "wcf", "managers": ["pw"]})
    assert channels_dao.is_manager_peer(a, "wcf", "pw") is True
    assert channels_dao.is_manager_peer(a, "wechat", "pw") is False, \
        "TEST6 FAIL：wechat/wcf 未隔离"
    print("  [6a OK] wcf 与 wechat 是两条独立渠道（前端必须做 _apiChan 归一）")

    # 缺 channel 时默认走 wcf（与 message_pipeline / binding_router 的默认值一致）
    br._handle_save_agent_managers({"agent_id": a, "managers": ["pdef"]})
    assert channels_dao.is_manager_peer(a, "wcf", "pdef") is True, \
        "TEST6 FAIL：缺 channel 时默认渠道不是 wcf"
    print("  [6b OK] 缺 channel 默认 wcf")

    assert isinstance(MANAGER_PROMPT, str) and len(MANAGER_PROMPT) > 60, \
        f"TEST6 FAIL：MANAGER_PROMPT 异常 {type(MANAGER_PROMPT)}"
    assert "主人" in MANAGER_PROMPT, "TEST6 FAIL：MANAGER_PROMPT 不含『主人』"
    print(f"  [6c OK] MANAGER_PROMPT 就位（{len(MANAGER_PROMPT)} 字）")

    print("[TEST 6 PASS] 渠道归一 + 主人模式预设")


# =================================================================
# TEST 7：主人模式接线守卫
# =================================================================
def test7_persona_slot_wiring():
    """_handle_send_message 依赖 LLM / 记忆 / KB 等外部资源，不适合在这里整体跑通；
    本用例只守住接线：替换必须发生在 is_manager_peer 命中的分支里，且只动 persona 槽。"""
    src = (ROOT / "app" / "bridge.py").read_text(encoding="utf-8")

    assert "MANAGER_PROMPT" in src, "TEST7 FAIL：bridge.py 里没有引用 MANAGER_PROMPT"
    assert "from storage.retriever import" in src, "TEST7 FAIL：没有从 retriever 导入"
    assert "MANAGER_PROMPT" in src.split("def _handle_send_message")[0], \
        "TEST7 FAIL：MANAGER_PROMPT 不是在模块顶部导入的"

    n_use = src.count("system_parts[0] = MANAGER_PROMPT")
    assert n_use == 1, f"TEST7 FAIL：persona 槽替换点应恰好 1 处，实得 {n_use}"

    i_gate = src.find("_is_manager_peer = channels_dao.is_manager_peer")
    i_use = src.find("system_parts[0] = MANAGER_PROMPT")
    assert i_gate != -1, "TEST7 FAIL：找不到 is_manager_peer 判定"
    assert i_gate < i_use, "TEST7 FAIL：替换发生在管理者判定之前（会误伤普通用户）"
    assert "if _is_manager_peer:" in src, "TEST7 FAIL：缺少 if _is_manager_peer: 分支"
    print("  [7a OK] 替换点唯一，且位于 is_manager_peer 判定之后")

    # 只替换 persona（system_parts[0]），记忆 / 通用规则 / KB 继续照常注入
    assert "system_parts[1]" not in src.split("system_parts[0] = MANAGER_PROMPT")[0][-400:], \
        "TEST7 FAIL：主人模式分支动了 persona 以外的槽"
    print("  [7b OK] 只动 system_parts[0]，其余注入链不变")

    print("[TEST 7 PASS] 主人模式接线守卫")


# =================================================================
# TEST 8（审计 A）：主人模式真的生效
# 不动用真 LLM：把 bridge.LLMProvider 换成假的，截获真实发出去的消息列表，
# 直接比对 system 槽里到底装的是「智能体自定义 persona」还是「MANAGER_PROMPT」。
# =================================================================
def test8_manager_mode_actually_applies():
    _point_to(_TMP)
    import bridge as bridge_mod

    # 必须有一份 LLM 配置，否则 _handle_send_message 会在第 1 步就 return「未配置 LLM」
    llm_dao.upsert({"name": "测试模型", "base_url": "http://127.0.0.1:1/v1",
                    "api_key": "sk-test", "model": "test-model", "is_default": 1})

    a = new_agent("主人模式-A")
    agents_dao.update(a, {"system_prompt": "你是【小美的专属角色】。", "style": "", "aigc_enabled": 0})

    captured = {}

    class _FakeProvider:
        def __init__(self, *args, **kwargs):
            pass

        @classmethod
        def from_config(cls, cfg):
            captured["cfg"] = cfg
            return cls()

        def chat(self, messages, temperature=0.7):
            captured["messages"] = messages
            captured["temperature"] = temperature
            return {"text": "收到，主人。", "usage": {"total_tokens": 3}}

    orig_provider = bridge_mod.LLMProvider
    bridge_mod.LLMProvider = _FakeProvider
    try:
        br = create_bare_bridge()

        def _send(peer_id, channel=CH, text="你好"):
            captured.clear()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                out = br._handle_send_message({
                    "agent_id": a, "content": text, "channel": channel,
                    "peer_id": peer_id, "peer_type": "friend", "use_kb": False,
                })
            return out, buf.getvalue()

        # --- 8a 普通成员：走智能体自己的 persona，绝不能出现主人预设 ---
        out1, log1 = _send("stranger")
        assert not out1.get("error"), f"TEST8 FAIL：普通成员这条就报错了 {out1.get('error')}"
        sys1 = captured["messages"][0]
        assert sys1["role"] == "system", f"TEST8 FAIL：首条不是 system {sys1['role']}"
        assert "小美的专属角色" in sys1["content"], "TEST8 FAIL：普通成员没拿到自定义 persona"
        assert MANAGER_PROMPT not in sys1["content"], "TEST8 FAIL：普通成员被误判成主人"
        assert "主人模式生效" not in log1, "TEST8 FAIL：普通成员也打了主人模式日志"
        print("  [8a OK] 普通成员 → 用智能体自己的 persona，未触发主人模式")

        # --- 8b 管理者：persona 槽必须被 MANAGER_PROMPT 顶掉 ---
        channels_dao.set_manager(a, CH, "boss", peer_name="主人")
        out2, log2 = _send("boss")
        assert not out2.get("error"), f"TEST8 FAIL：管理者这条报错了 {out2.get('error')}"
        sys2 = captured["messages"][0]["content"]
        assert sys2.startswith(MANAGER_PROMPT), \
            f"TEST8 FAIL：管理者收到的不以 MANAGER_PROMPT 开头，实得前 60 字：{sys2[:60]!r}"
        assert "小美的专属角色" not in sys2, "TEST8 FAIL：主人模式下仍带着智能体自定义角色（没屏蔽干净）"
        assert f"主人模式生效: agent_id={a} channel={CH} peer_id=boss" in log2, \
            "TEST8 FAIL：没有打印主人模式生效日志"
        print("  [8b OK] 管理者 → system_parts[0] 被替换为 MANAGER_PROMPT，且不再带自定义角色")

        # --- 8c 只替换 persona 槽：通用回复要求 / 底部规则仍在 ---
        assert "请用中文回复" in sys2, "TEST8 FAIL：主人模式把通用回复要求也顶掉了（动多了）"
        print("  [8c OK] 仅 persona 槽被替换，后续注入链（通用要求/锚点规则）原样保留")

        # --- 8d 渠道隔离：同一 peer_id 换个渠道就不该是主人 ---
        out3, log3 = _send("boss", channel="wcf")
        sys3 = captured["messages"][0]["content"]
        assert MANAGER_PROMPT not in sys3, "TEST8 FAIL：换了渠道仍命中主人模式（渠道维度没隔离）"
        assert "小美的专属角色" in sys3, "TEST8 FAIL：换渠道后没回到智能体自己的 persona"
        print("  [8d OK] 管理者标记只对 (agent, channel, peer) 三元组生效，换渠道不误命中")

        # --- 8e 记忆为空时不会往 system 里塞垃圾 ---
        assert "\n\n\n" not in sys2, "TEST8 FAIL：主人模式下 system prompt 出现连续空行（空记忆被拼进去了）"
        print("  [8e OK] 免费版无记忆注入，system prompt 无空段")
    finally:
        bridge_mod.LLMProvider = orig_provider

    print("[TEST 8 PASS] 主人模式真的生效（假 LLM 实测 system 消息）")


if __name__ == "__main__":
    import traceback
    tests = [
        ("TEST 1", test1_schema_migration),
        ("TEST 2", test2_dao_semantics),
        ("TEST 3", test3_save_full_overwrite),
        ("TEST 4", test4_conflict_guard),
        ("TEST 5", test5_replace_clears_ghost),
        ("TEST 6", test6_channel_and_prompt_const),
        ("TEST 7", test7_persona_slot_wiring),
        ("TEST 8", test8_manager_mode_actually_applies),
    ]
    failed = 0
    for name, fn in tests:
        print(f"\n===== RUN {name} =====")
        try:
            fn()
            print(f"✅ {name} PASS")
        except Exception as e:
            failed += 1
            traceback.print_exc()
            print(f"❌ {name} FAIL: {e}")
    print(f"\n===== SUMMARY: {len(tests)-failed}/{len(tests)} PASS =====")
    try:
        os.environ["SCAI_APP_DIR"] = _TMP
        reset_db_for_tests()
    except Exception:
        pass
    try:
        shutil.rmtree(_TMP, ignore_errors=True)
    except Exception:
        pass
    sys.exit(0 if failed == 0 else 1)
