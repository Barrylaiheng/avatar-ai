"""
模块 M12（UI Data Sync · 人设回显数据流）PDD Test Seams 固化
13 条 pytest 对应 Grill H1~H13。

策略：Engine 层 Grill（H1/H2/H6/H7/H10/H11/H12）直接用 AppEngine 实例；
      UI 逻辑 Grill（H3/H4/H5/H8/H9/H13）复用原型的 Fake QWidget Mock 避免 Qt 事件循环依赖。

运行：
  pytest tests/test_inner_ui_data_sync_persona_pdd.py -v
"""
import os
import sys
import shutil
import tempfile
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


# ---------- 辅助（与原型同构，直接复用不 import 原型） ----------
class _MockLabel:
    def __init__(self, initial: str = ""):
        self._t = initial

    def setText(self, t: str):
        self._t = str(t)

    def text(self) -> str:
        return self._t


class _FakeChatPageHeader:
    # P1-3 首启注入后默认人设为 EXAMPLE_PERSONA（鲜果小助手）
    DEFAULT_TITLE = "鲜果小助手 · 水果商家数字分身"
    DEFAULT_SUB = "默认人设，点击左侧 Persona 编辑器调整"

    def __init__(self, app_engine=None):
        self.title_label = _MockLabel(self.DEFAULT_TITLE)
        self.sub_label = _MockLabel(self.DEFAULT_SUB)
        self._engine = app_engine
        # 与真实 ChatPage.__init__ 行为一致：末尾立刻 refresh（读 Engine 真实值）
        self.refresh_persona_header()

    def refresh_persona_header(self, persona_dict=None):
        if persona_dict is None and self._engine is not None:
            persona_dict = self._engine.get_current_persona_dict()
        if persona_dict is None:
            name, ptype, desc = "鲜果小助手", "水果商家数字分身", ""
        else:
            name = str(persona_dict.get("name", "") or "鲜果小助手").strip()
            ptype = str(persona_dict.get("type", "") or "水果商家数字分身").strip()
            desc = str(persona_dict.get("description", "") or "").strip()
        self.title_label.setText(f"{name} · {ptype}")
        if len(desc) > 3:
            self.sub_label.setText(f"{desc[:40]}…" if len(desc) > 40 else desc)
        else:
            self.sub_label.setText(self.DEFAULT_SUB)


class _FakeWorkspaceCard:
    DEFAULT_NAME = "鲜果小助手"
    DEFAULT_TYPE = "水果商家数字分身"
    DEFAULT_TONE = "热情、专业、耐心，像邻居家的水果达人"

    def __init__(self, app_engine=None):
        self.name_lbl = _MockLabel(self.DEFAULT_NAME)
        self.type_lbl = _MockLabel(self.DEFAULT_TYPE)
        self.tone_lbl = _MockLabel(f"语气：{self.DEFAULT_TONE}")
        self.avatar_lbl = _MockLabel("🎭")
        self._engine = app_engine
        # 与真实 WorkspacePage.__init__ 行为一致：末尾立刻 refresh
        self.refresh_persona_card()

    def refresh_persona_card(self, persona_dict=None):
        if persona_dict is None and self._engine is not None:
            persona_dict = self._engine.get_current_persona_dict()
        if persona_dict is None:
            n, pt, to, av = self.DEFAULT_NAME, self.DEFAULT_TYPE, self.DEFAULT_TONE, "🎭"
        else:
            n = str(persona_dict.get("name", "") or self.DEFAULT_NAME).strip()
            pt = str(persona_dict.get("type", "") or self.DEFAULT_TYPE).strip()
            to = str(persona_dict.get("tone", "") or self.DEFAULT_TONE).strip()
            av_raw = str(persona_dict.get("avatar", "") or "🎭").strip()
            av = av_raw or "🎭"
        self.name_lbl.setText(n)
        self.type_lbl.setText(pt)
        self.tone_lbl.setText(f"语气：{to[:40]}…" if len(to) > 40 else f"语气：{to}")
        self.avatar_lbl.setText(av[0] if av else "🎭")


class _FakePersonaEditorInputs:
    def __init__(self, app_engine=None, has_selection: bool = False):
        self.name_edit = _MockLabel("")
        self.desc_edit = _MockLabel("")
        self.tone_edit = _MockLabel("")
        self.type_edit = _MockLabel("")
        self._engine = app_engine
        if not has_selection:
            self.fill_from_engine_if_no_selection()

    def fill_from_engine_if_no_selection(self):
        if self._engine is None:
            return
        pd = self._engine.get_current_persona_dict()
        self.name_edit.setText(str(pd.get("name", "") or "鲜果小助手"))
        self.desc_edit.setText(str(pd.get("description", "") or ""))
        self.tone_edit.setText(str(pd.get("tone", "") or "热情、专业、耐心，像邻居家的水果达人"))
        self.type_edit.setText(str(pd.get("type", "") or "水果商家数字分身"))


@pytest.fixture
def scai_tmp(monkeypatch, tmp_path):
    """每个用例独立数据目录，严格隔离"""
    target = tmp_path / f"scai_m12_{uuid.uuid4().hex[:8]}"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SCAI_DATA_DIR", str(target))
    yield target
    # 清理 chromadb / sqlite 残留
    shutil.rmtree(str(target), ignore_errors=True)


@pytest.fixture
def eng(scai_tmp):
    from aibridge.app_engine import AppEngine

    e = AppEngine()
    assert e.initialize() is True
    yield e
    # shutdown 释放锁/线程
    try:
        if hasattr(e, "shutdown"):
            e.shutdown()
    except Exception:
        pass


# ========================================= Grill H1~H13 =========================================
class TestH1H2CurrentPersonaDict:
    def test_H1_8_fields_present(self, eng):
        d = eng.get_current_persona_dict()
        assert set(d.keys()) == {
            "name", "description", "tone", "type",
            "avatar", "background_story", "language_style", "keywords",
        }

    def test_H2_default_name(self, eng):
        assert eng.get_current_persona_dict()["name"] == "鲜果小助手"

    def test_H2_default_type(self, eng):
        assert eng.get_current_persona_dict()["type"] == "水果商家数字分身"

    def test_H2_default_tone(self, eng):
        assert eng.get_current_persona_dict()["tone"] == "热情、专业、耐心，像邻居家的水果达人"

    def test_H2_uninitialized_engine_still_returns_defaults(self, scai_tmp):
        from aibridge.app_engine import AppEngine

        bad = AppEngine()  # 不 initialize
        d = bad.get_current_persona_dict()
        # 未 initialize 时返回代码内置硬编码默认值（非首启注入值）
        assert d["name"] == "影分身 AI"
        assert d["type"] == "AI 数字分身"
        assert d["avatar"] == "🎭"
        assert set(d.keys()) == {
            "name", "description", "tone", "type",
            "avatar", "background_story", "language_style", "keywords",
        }


class TestH3H4ChatPageHeaderInitial:
    def test_H3_title_initial_format(self, eng):
        h = _FakeChatPageHeader(eng)
        assert h.title_label.text() == "鲜果小助手 · 水果商家数字分身"

    def test_H4_sub_initial_when_empty_description(self, eng):
        h = _FakeChatPageHeader(eng)
        # P1-3 首启注入 description 非空，sub 应显示 description 截断
        assert h.sub_label.text() != _FakeChatPageHeader.DEFAULT_SUB


class TestH5H6PersonaChangedCallbackAndHotRefresh:
    def test_H6_callback_fires_once_on_save(self, eng):
        calls = []
        eng.register_persona_changed_callback(lambda pd: calls.append(pd))
        eng.save_persona({"name": "销售 AI 小崔", "type": "T"})
        assert len(calls) == 1, f"回调触发次数={len(calls)}"
        # 回调入参就是最新的 persona_dict
        assert calls[0]["name"] == "销售 AI 小崔"
        assert calls[0]["type"] == "T"

    def test_H5_chatpage_refreshes_immediately_via_callback(self, eng):
        h = _FakeChatPageHeader(eng)
        eng.register_persona_changed_callback(h.refresh_persona_header)
        eng.save_persona({
            "name": "小崔",
            "type": "销售助理",
            "description": "B2B SaaS 销售老兵",
        })
        assert h.title_label.text() == "小崔 · 销售助理"
        # description 只有 12 字 ≤40 → 不省略号
        assert h.sub_label.text() == "B2B SaaS 销售老兵"

    def test_H6_callback_does_not_fire_when_no_fields_changed(self, eng):
        eng.save_persona({"name": "固定名字", "type": "固定类型"})
        current = eng.get_current_persona_dict()
        exact_same_input = {
            "name": current["name"],
            "type": current["type"],
            "tone": current["tone"],
            "description": current["description"],
            "avatar": current["avatar"],
            "background_story": current["background_story"],
            "language_style": current["language_style"],
            "keywords": current["keywords"],
        }
        # 关键：先把所有字段完整写入 Config 一次（此时 persona.tone 等 key 还是空的，会被写入兜底默认值 → 触发 1 次回调）
        calls_first = []
        eng.register_persona_changed_callback(lambda pd: calls_first.append(1))
        eng.save_persona(exact_same_input)
        assert len(calls_first) == 1, f"首次全量同步应该触发 1 次回调，实际 {len(calls_first)}"

        # 现在 exact_same_input 里每个字段都和 Config 内完全一致
        calls_second = []
        eng.register_persona_changed_callback(lambda pd: calls_second.append(1))
        eng.save_persona(exact_same_input)
        assert len(calls_second) == 0, (
            f"第二次完全相同的输入不应触发回调，但触发了 {len(calls_second)} 次。"
            f" 可能 diff 逻辑有漏洞：检查 exact_same_input == Config 当前值。"
        )


class TestH7SequentialSaveKeepsLastValue:
    def test_H7_final_value_after_saves(self, eng):
        h = _FakeChatPageHeader(eng)
        eng.register_persona_changed_callback(h.refresh_persona_header)
        eng.save_persona({"name": "迭代1", "type": "T1", "tone": "语气1", "description": "D1"})
        eng.save_persona({"name": "迭代2", "type": "T2", "tone": "语气2", "description": "D2"})
        eng.save_persona({"name": "最终-final", "type": "T-final", "tone": "语气-final", "description": "D-final"})
        assert h.title_label.text() == "最终-final · T-final"
        eng_dict = eng.get_current_persona_dict()
        assert eng_dict["name"] == "最终-final"
        assert eng_dict["tone"] == "语气-final"


class TestH8H9PersonaEditorEchoOnOpen:
    def test_H8_4_fields_filled_without_selection(self, eng):
        eng.save_persona({"name": "成交顾问", "type": "B2B SaaS", "tone": "沉稳专业",
                          "description": "帮助销售成交的人设"})
        pe = _FakePersonaEditorInputs(eng, has_selection=False)
        assert pe.name_edit.text() == "成交顾问"
        assert pe.type_edit.text() == "B2B SaaS"
        assert pe.tone_edit.text() == "沉稳专业"
        assert pe.desc_edit.text() == "帮助销售成交的人设"

    def test_H9_echo_exactly_matches_engine_current(self, eng):
        eng.save_persona({"name": "Barry", "type": "AI 导师", "tone": "严肃",
                          "description": "带小白上手 AI 工程实践"})
        pe = _FakePersonaEditorInputs(eng, has_selection=False)
        engine_dict = eng.get_current_persona_dict()
        assert pe.name_edit.text() == engine_dict["name"]
        assert pe.tone_edit.text() == engine_dict["tone"]
        assert pe.type_edit.text() == engine_dict["type"]
        assert pe.desc_edit.text() == engine_dict["description"]


class TestH10SaveFailureAtomicity:
    def test_H10_save_returns_false_when_uninitialized(self, scai_tmp):
        from aibridge.app_engine import AppEngine

        bad = AppEngine()
        before = bad.get_current_persona_dict()
        ok = bad.save_persona({"name": "不应保存", "type": "XX", "tone": "YY", "description": "Z"})
        after = bad.get_current_persona_dict()
        assert ok is False
        # 所有字段不变（完全回滚/从未被写入）
        assert before == after
        # 未 initialize 的 AppEngine 返回代码硬编码默认值
        assert after["name"] == "影分身 AI"


class TestH11CrossRestartPersistence:
    def test_H11_new_engine_reads_old_values(self, scai_tmp):
        from aibridge.app_engine import AppEngine

        e1 = AppEngine()
        assert e1.initialize() is True
        e1.save_persona({
            "name": "持久化名",
            "type": "持久化类型",
            "tone": "持久化语气",
            "description": "持久化描述",
        })
        if hasattr(e1, "shutdown"):
            e1.shutdown()
        del e1

        e2 = AppEngine()
        assert e2.initialize() is True
        d2 = e2.get_current_persona_dict()
        assert d2["name"] == "持久化名"
        assert d2["type"] == "持久化类型"
        assert d2["tone"] == "持久化语气"
        assert d2["description"] == "持久化描述"
        if hasattr(e2, "shutdown"):
            e2.shutdown()


class TestH12EmptyAndLongDescriptionDisplay:
    def test_H12_empty_description_shows_default_guide_text(self, eng):
        eng.save_persona({"name": "N", "type": "T", "description": ""})
        # 先构造 header 再强制 refresh（构造时会读一次 engine；save_persona 之后构造也 OK，直接读到最新）
        h = _FakeChatPageHeader(eng)
        assert h.sub_label.text() == _FakeChatPageHeader.DEFAULT_SUB

    def test_H12_whitespace_only_description_shows_default_guide_text(self, eng):
        eng.save_persona({"name": "N", "type": "T", "description": "   "})
        h = _FakeChatPageHeader(eng)
        # 3 个空格 strip 后 len(desc)==0 → 走默认引导文案
        assert h.sub_label.text() == _FakeChatPageHeader.DEFAULT_SUB

    def test_H12_long_description_ellipsis(self, eng):
        eng.save_persona({"description": "X" * 45})
        h = _FakeChatPageHeader(eng)
        assert h.sub_label.text() == "X" * 40 + "…"

    def test_H12_long_tone_ellipsis_in_workspace_card(self, eng):
        eng.save_persona({"tone": "幽默 " * 50})
        ws = _FakeWorkspaceCard(eng)
        # "语气：" 前缀 + 40 字 + "…"
        assert ws.tone_lbl.text().endswith("…")
        assert len(ws.tone_lbl.text()) <= 40 + len("语气：…") + 5  # 宽松边界


class TestH13WorkspacePersonaCard:
    def test_H13_initial_values_from_engine(self, eng):
        eng.save_persona({
            "name": "成交侠",
            "type": "B2B SaaS 销售机器人",
            "tone": "轻松、专业、会讲段子",
            "avatar": "🦸",
        })
        ws = _FakeWorkspaceCard(eng)
        assert ws.name_lbl.text() == "成交侠"
        assert ws.type_lbl.text() == "B2B SaaS 销售机器人"
        assert ws.tone_lbl.text() == "语气：轻松、专业、会讲段子"
        assert ws.avatar_lbl.text() == "🦸"

    def test_H13_card_hot_refresh_via_callback_after_save(self, eng):
        ws = _FakeWorkspaceCard(eng)
        eng.register_persona_changed_callback(ws.refresh_persona_card)
        eng.save_persona({"name": "新名字", "type": "新类型", "tone": "新语气", "avatar": "🤖"})
        assert ws.name_lbl.text() == "新名字"
        assert ws.type_lbl.text() == "新类型"
        assert ws.tone_lbl.text() == "语气：新语气"
        assert ws.avatar_lbl.text() == "🤖"

    def test_H13_avatar_only_first_glyph_prevents_long_text(self, eng):
        eng.save_persona({"avatar": "长文本不是头像"})
        ws = _FakeWorkspaceCard(eng)
        # 只取第一个字符
        assert ws.avatar_lbl.text() == "长"
