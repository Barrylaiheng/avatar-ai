"""
模块 M13（Settings Data Sync · 设置回显数据流）PDD Test Seams 固化
14 条 pytest 对应 Grill S1~S14，共 63 个测试点。

策略：
  - Engine 层 Grill（S1/S2/S7/S8/S10/S11/S13）直接用真实 AppEngine 实例
    （通过 SCAI_DATA_DIR 环境变量做测试隔离，复用 M-12 的 fixture 范式）
  - UI 逻辑 Grill（S3/S4/S5/S6/S9/S12/S14）用与原型同构的 _Fake* Mock 类
    （避免 PyQt6 事件循环依赖，聚焦"回显 / 热更新 / 双路径"逻辑契约）

运行：
  pytest tests/test_inner_settings_data_sync_pdd.py -v
"""
import os
import sys
import shutil
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


# ========================================= Fake UI Mock（与原型同构，不 import 原型） =========================================

class _FakeSettingsPage:
    """
    模拟 SettingsPage 的"回显 / 收集 / 热更新 / provider 联动"逻辑契约。
    控件用 dict 表示状态（current/text/checked/items/echo_mode），避免 PyQt6 依赖。
    逻辑与 settings_page_v2.py 的 _apply_settings_to_ui / refresh_settings / _on_save_llm 对齐。
    """
    PROVIDERS = ["deepseek", "doubao"]
    MODELS = {
        "deepseek": ["deepseek-v4-flash"],
        "doubao": ["doubao-seed-2.0-lite"],
    }
    URLS = {
        "deepseek": "https://api.deepseek.com/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    }

    def __init__(self, app_engine=None):
        self._engine = app_engine
        # 控件状态（对应真实 SettingsPage 的 self. 属性）
        self.provider_combo = {"items": list(self.PROVIDERS), "current": "deepseek"}
        self.baseurl_edit = {"text": "", "readonly": True}
        self._apikey_edit = {"text": "", "echo_mode": "password"}
        self.model_combo = {"items": self.MODELS["deepseek"], "current": "deepseek-v4-flash"}
        self.thinking_toggle = {"checked": False}
        self._aigc_check = {"checked": False}
        self._aigc_prefix_edit = {"text": "[AI]"}
        self._echo = {}
        # 与真实 SettingsPage.__init__ 行为一致：末尾立刻 _load_settings_from_engine
        self._load_settings_from_engine()

    def _load_settings_from_engine(self):
        if self._engine is not None:
            self._apply_settings_to_ui(self._engine.get_current_settings_dict())

    def _apply_settings_to_ui(self, sd):
        p = str(sd.get("active_provider", "deepseek"))
        if p not in self.PROVIDERS:
            p = "deepseek"
        self.provider_combo["current"] = p
        self.baseurl_edit["text"] = str(sd.get("base_url", self.URLS.get(p, "")))
        self._apikey_edit["text"] = str(sd.get("api_key", ""))
        self.model_combo["items"] = list(self.MODELS.get(p, []))
        self.model_combo["current"] = str(sd.get("model", self.model_combo["items"][0] if self.model_combo["items"] else ""))
        self._aigc_check["checked"] = bool(sd.get("aigc_explicit", False))
        self._aigc_prefix_edit["text"] = str(sd.get("aigc_prefix", "[AI]"))
        self._echo = dict(sd)

    def refresh_settings(self, settings_dict=None):
        """双路径：有参数直接用（回调场景），无参数主动拉 Engine（init 场景）"""
        if settings_dict is None and self._engine is not None:
            settings_dict = self._engine.get_current_settings_dict()
        if settings_dict:
            self._apply_settings_to_ui(settings_dict)

    def _on_provider_changed(self):
        """provider 切换时联动更新 base_url 和 model 列表（D10 决策）"""
        p = self.provider_combo["current"]
        self.baseurl_edit["text"] = self.URLS.get(p, "")
        self.model_combo["items"] = list(self.MODELS.get(p, []))
        self.model_combo["current"] = self.model_combo["items"][0] if self.model_combo["items"] else ""

    def _collect_save_fields(self):
        """收集所有字段（provider 从 combo 读，不写死 deepseek）"""
        return {
            "active_provider": self.provider_combo["current"],
            "api_key": self._apikey_edit["text"].strip(),
            "base_url": self.baseurl_edit["text"],
            "model": self.model_combo["current"],
            "aigc_explicit": self._aigc_check["checked"],
            "aigc_prefix": self._aigc_prefix_edit["text"],
        }

    def save(self):
        if self._engine is None:
            return False
        return self._engine.save_settings(self._collect_save_fields())


class _FakeWorkspacePage:
    """
    模拟 WorkspacePage 的"当前 LLM 卡片"逻辑契约。
    对齐 workspace_page.py 的 refresh_llm_card：provider + model + 红/绿连通状态点。
    """
    _LLM_PROVIDER_LABELS = {"deepseek": "DeepSeek", "doubao": "豆包"}

    def __init__(self, app_engine=None):
        self._engine = app_engine
        self._llm_provider_label_text = "DeepSeek"
        self._llm_model_label_text = ""
        self._llm_dot_color = "#ef4444"  # 默认红
        self._echo = {}
        self.refresh_llm_card()
        if self._engine is not None:
            self._engine.register_settings_changed_callback(self.refresh_llm_card)

    def refresh_llm_card(self, settings_dict=None):
        """双路径：有参数直接用，无参数主动拉 Engine"""
        if settings_dict is None and self._engine is not None:
            settings_dict = self._engine.get_current_settings_dict()
        if not settings_dict:
            return
        provider = str(settings_dict.get("active_provider", "deepseek"))
        model = str(settings_dict.get("model", ""))
        has_key = bool(settings_dict.get("api_key", ""))
        self._llm_provider_label_text = self._LLM_PROVIDER_LABELS.get(provider, provider)
        self._llm_model_label_text = model
        # D12 决策：有 api_key → green，无 → red
        self._llm_dot_color = "#22c55e" if has_key else "#ef4444"
        self._echo = dict(settings_dict)


# ========================================= Fixtures（复用 M-12 TD-7 隔离范式） =========================================

@pytest.fixture
def scai_tmp(monkeypatch, tmp_path):
    """每个用例独立数据目录，严格隔离"""
    target = tmp_path / f"scai_m13_{uuid.uuid4().hex[:8]}"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SCAI_DATA_DIR", str(target))
    yield target
    shutil.rmtree(str(target), ignore_errors=True)


@pytest.fixture
def eng(scai_tmp):
    from aibridge.app_engine import AppEngine

    e = AppEngine()
    assert e.initialize() is True
    yield e
    try:
        if hasattr(e, "shutdown"):
            e.shutdown()
    except Exception:
        pass


# ========================================= Grill S1/S2: get_current_settings_dict 8 字段 + 未初始化兜底 =========================================

class TestS1S2CurrentSettingsDict:
    """S1: AppEngine 返回 8 字段标准接口；S2: 未初始化时返回合理默认值"""

    def test_S1a_returns_dict(self, eng):
        s = eng.get_current_settings_dict()
        assert isinstance(s, dict)

    def test_S1b_eight_fields_present(self, eng):
        s = eng.get_current_settings_dict()
        expected = {
            "active_provider", "api_key", "base_url", "model",
            "supports_image", "supports_audio", "aigc_explicit", "aigc_prefix",
        }
        assert expected.issubset(s.keys()), f"缺失字段: {expected - set(s.keys())}"

    def test_S1c_default_provider_deepseek(self, eng):
        assert eng.get_current_settings_dict()["active_provider"] == "deepseek"

    def test_S1d_default_model(self, eng):
        assert eng.get_current_settings_dict()["model"] == "deepseek-v4-flash"

    def test_S1e_default_base_url_nonempty(self, eng):
        assert len(eng.get_current_settings_dict()["base_url"]) > 0

    def test_S2a_uninitialized_returns_dict(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        bad = AppEngine()  # 不 initialize
        s = bad.get_current_settings_dict()
        assert isinstance(s, dict)

    def test_S2b_uninitialized_default_provider(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        bad = AppEngine()
        assert bad.get_current_settings_dict()["active_provider"] == "deepseek"

    def test_S2c_uninitialized_default_model(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        bad = AppEngine()
        assert bad.get_current_settings_dict()["model"] == "deepseek-v4-flash"

    def test_S2d_uninitialized_default_apikey_empty(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        bad = AppEngine()
        assert bad.get_current_settings_dict()["api_key"] == ""

    def test_S2e_uninitialized_default_baseurl_nonempty(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        bad = AppEngine()
        assert len(bad.get_current_settings_dict()["base_url"]) > 0


# ========================================= Grill S3: SettingsPage 控件全 self. 属性 =========================================

class TestS3SettingsPageControlsAreSelf:
    """S3: 7 个控件都是实例属性（不是局部变量），外部可访问回显"""

    def test_S3a_provider_combo_attr(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        assert hasattr(p, "provider_combo")

    def test_S3b_baseurl_edit_attr(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        assert hasattr(p, "baseurl_edit")

    def test_S3c_apikey_edit_attr(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        assert hasattr(p, "_apikey_edit")

    def test_S3d_model_combo_attr(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        assert hasattr(p, "model_combo")

    def test_S3e_thinking_toggle_attr(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        assert hasattr(p, "thinking_toggle")

    def test_S3f_aigc_check_attr(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        assert hasattr(p, "_aigc_check")

    def test_S3g_aigc_prefix_edit_attr(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        assert hasattr(p, "_aigc_prefix_edit")


# ========================================= Grill S4: 打开时控件从 Engine 回显 =========================================

class TestS4SettingsEchoOnOpen:
    """S4: SettingsPage 构造时立即从 Engine 读当前值回填控件"""

    def test_S4a_provider_echoed(self, eng):
        eng.save_settings({"api_key": "sk-test1234"})
        p = _FakeSettingsPage(app_engine=eng)
        assert p.provider_combo["current"] == "deepseek"

    def test_S4b_api_key_echoed(self, eng):
        eng.save_settings({"api_key": "sk-test1234"})
        p = _FakeSettingsPage(app_engine=eng)
        assert p._apikey_edit["text"] == "sk-test1234"

    def test_S4c_model_echoed(self, eng):
        eng.save_settings({"api_key": "sk-test1234"})
        p = _FakeSettingsPage(app_engine=eng)
        assert p.model_combo["current"] == "deepseek-v4-flash"

    def test_S4d_base_url_echoed_nonempty(self, eng):
        eng.save_settings({"api_key": "sk-test1234"})
        p = _FakeSettingsPage(app_engine=eng)
        assert len(p.baseurl_edit["text"]) > 0

    def test_S4e_aigc_prefix_echoed(self, eng):
        eng.save_settings({"api_key": "sk-test1234"})
        p = _FakeSettingsPage(app_engine=eng)
        assert p._aigc_prefix_edit["text"] == "[AI]"


# ========================================= Grill S5: API Key password 模式 =========================================

class TestS5ApiKeyPasswordMode:
    """S5: API Key 输入框默认 password 模式（显示 ●●●●），保护视觉"""

    def test_S5a_echo_mode_password(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        assert p._apikey_edit["echo_mode"] == "password"


# ========================================= Grill S6: Save 收集 ALL 字段 =========================================

class TestS6CollectAllFields:
    """S6: 保存时收集所有字段（provider 从 combo 读，不写死 deepseek），含 base_url/model/aigc_**"""

    def test_S6a_provider_read_from_combo(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        p.provider_combo["current"] = "doubao"
        p._on_provider_changed()
        p._apikey_edit["text"] = "dk-5678"
        c = p._collect_save_fields()
        assert c["active_provider"] == "doubao"

    def test_S6b_api_key_collected(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        p._apikey_edit["text"] = "dk-5678"
        c = p._collect_save_fields()
        assert c["api_key"] == "dk-5678"

    def test_S6c_base_url_collected_nonempty(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        p.provider_combo["current"] = "doubao"
        p._on_provider_changed()
        c = p._collect_save_fields()
        assert len(c["base_url"]) > 0

    def test_S6d_model_collected_after_provider_switch(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        p.provider_combo["current"] = "doubao"
        p._on_provider_changed()
        c = p._collect_save_fields()
        assert c["model"] == "doubao-seed-2.0-lite"

    def test_S6e_aigc_explicit_collected(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        c = p._collect_save_fields()
        assert "aigc_explicit" in c

    def test_S6f_aigc_prefix_collected(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        c = p._collect_save_fields()
        assert "aigc_prefix" in c


# ========================================= Grill S7: save_settings 增量 diff =========================================

class TestS7SaveDiff:
    """S7: 完全相同的值重复保存，不触发磁盘 IO 也不触发回调"""

    def test_S7a_first_save_triggers_callback(self, eng):
        cnt = []
        eng.register_settings_changed_callback(lambda sd: cnt.append(1))
        eng.save_settings({"api_key": "sk-first"})
        assert len(cnt) == 1

    def test_S7b_first_save_writes_disk(self, eng, monkeypatch):
        save_calls = []
        monkeypatch.setattr(eng._config, "save_config", lambda: save_calls.append(1))
        eng.save_settings({"api_key": "sk-first-disk"})
        assert len(save_calls) == 1

    def test_S7c_same_value_no_callback(self, eng):
        eng.save_settings({"api_key": "sk-same"})
        cnt = []
        eng.register_settings_changed_callback(lambda sd: cnt.append(1))
        eng.save_settings({"api_key": "sk-same"})
        assert len(cnt) == 0

    def test_S7d_same_value_no_disk_write(self, eng, monkeypatch):
        eng.save_settings({"api_key": "sk-same2"})
        save_calls = []
        monkeypatch.setattr(eng._config, "save_config", lambda: save_calls.append(1))
        eng.save_settings({"api_key": "sk-same2"})
        assert len(save_calls) == 0

    def test_S7e_different_value_triggers_callback(self, eng):
        eng.save_settings({"api_key": "sk-v1"})
        cnt = []
        eng.register_settings_changed_callback(lambda sd: cnt.append(1))
        eng.save_settings({"api_key": "sk-v2"})
        assert len(cnt) == 1

    def test_S7f_different_value_writes_disk(self, eng, monkeypatch):
        eng.save_settings({"api_key": "sk-v3"})
        save_calls = []
        monkeypatch.setattr(eng._config, "save_config", lambda: save_calls.append(1))
        eng.save_settings({"api_key": "sk-v4"})
        assert len(save_calls) == 1


# ========================================= Grill S8: register/unregister 回调机制 =========================================

class TestS8RegisterUnregister:
    """S8: 任何 UI 可订阅设置变化；注销后不再被调用"""

    def test_S8a_register_returns_true(self, eng):
        assert eng.register_settings_changed_callback(lambda sd: None) is True

    def test_S8b_two_callbacks_registered(self, eng):
        eng.register_settings_changed_callback(lambda sd: None)
        eng.register_settings_changed_callback(lambda sd: None)
        assert len(eng._settings_changed_callbacks) == 2

    def test_S8c_register_non_callable_returns_false(self, eng):
        assert eng.register_settings_changed_callback("not-callable") is False

    def test_S8d_first_callback_called_on_save(self, eng):
        calls = []
        eng.register_settings_changed_callback(lambda sd: calls.append(1))
        eng.save_settings({"api_key": "sk-t"})
        assert len(calls) == 1

    def test_S8e_second_callback_called_on_save(self, eng):
        c1, c2 = [], []
        eng.register_settings_changed_callback(lambda sd: c1.append(1))
        eng.register_settings_changed_callback(lambda sd: c2.append(1))
        eng.save_settings({"api_key": "sk-t"})
        assert len(c2) == 1

    def test_S8f_unregister_returns_removed_count(self, eng):
        cb = lambda sd: None
        eng.register_settings_changed_callback(cb)
        removed = eng.unregister_settings_changed_callback(cb)
        assert removed == 1

    def test_S8g_one_callback_remains_after_unregister(self, eng):
        cb1 = lambda sd: None
        cb2 = lambda sd: None
        eng.register_settings_changed_callback(cb1)
        eng.register_settings_changed_callback(cb2)
        eng.unregister_settings_changed_callback(cb1)
        assert len(eng._settings_changed_callbacks) == 1

    def test_S8h_unregistered_callback_not_called(self, eng):
        c1 = []
        cb1 = lambda sd: c1.append(1)
        eng.register_settings_changed_callback(cb1)
        eng.register_settings_changed_callback(lambda sd: None)
        eng.unregister_settings_changed_callback(cb1)
        eng.save_settings({"api_key": "sk-t2"})
        assert len(c1) == 0

    def test_S8i_remaining_callback_still_called(self, eng):
        c2 = []
        eng.register_settings_changed_callback(lambda sd: None)
        cb2 = lambda sd: c2.append(1)
        eng.register_settings_changed_callback(cb2)
        eng.unregister_settings_changed_callback(lambda sd: None)
        eng.save_settings({"api_key": "sk-t3"})
        assert len(c2) == 1


# ========================================= Grill S9: save 后热更新 =========================================

class TestS9HotRefresh:
    """S9: 保存设置成功后，SettingsPage 控件立即热更新（通过回调驱动）"""

    def test_S9a_initial_api_key_empty(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        eng.register_settings_changed_callback(p.refresh_settings)
        assert p._apikey_edit["text"] == ""

    def test_S9b_api_key_hot_updated_after_save(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        eng.register_settings_changed_callback(p.refresh_settings)
        eng.save_settings({"api_key": "sk-hot"})
        assert p._apikey_edit["text"] == "sk-hot"

    def test_S9c_provider_hot_updated_after_save(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        eng.register_settings_changed_callback(p.refresh_settings)
        eng.save_settings({
            "active_provider": "doubao",
            "api_key": "dh",
            "model": "doubao-seed-2.0-lite",
        })
        assert p.provider_combo["current"] == "doubao"

    def test_S9d_model_hot_updated_after_save(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        eng.register_settings_changed_callback(p.refresh_settings)
        eng.save_settings({
            "active_provider": "doubao",
            "api_key": "dh",
            "model": "doubao-seed-2.0-lite",
        })
        assert p.model_combo["current"] == "doubao-seed-2.0-lite"


# ========================================= Grill S10: 失败原子性 =========================================

class TestS10SaveFailureAtomicity:
    """S10: Engine 未初始化时 save 返回 False，已有配置不被污染"""

    def test_S10a_save_returns_false_when_uninitialized(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        bad = AppEngine()  # 不 initialize
        ok = bad.save_settings({"api_key": "sk-bad"})
        assert ok is False

    def test_S10b_old_value_preserved_after_failed_save(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        e = AppEngine()
        assert e.initialize() is True
        e.save_settings({"api_key": "sk-orig"})
        # 模拟未初始化状态下的保存尝试（构造新实例不 init）
        bad = AppEngine()
        bad.save_settings({"api_key": "sk-bad"})
        # 原实例的值应保持不变
        s = e.get_current_settings_dict()
        assert s["api_key"] == "sk-orig"
        try:
            e.shutdown()
        except Exception:
            pass


# ========================================= Grill S11: 跨重启持久化 =========================================

class TestS11CrossRestartPersistence:
    """S11: 关掉 App 再重新打开，上次 save 的 provider/api_key/model 读回来完全一致"""

    def test_S11a_provider_persisted(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        e1 = AppEngine()
        assert e1.initialize() is True
        e1.save_settings({
            "api_key": "sk-p",
            "active_provider": "doubao",
            "model": "doubao-seed-2.0-lite",
        })
        e1.shutdown()

        e2 = AppEngine()
        assert e2.initialize() is True
        s = e2.get_current_settings_dict()
        assert s["active_provider"] == "doubao"
        e2.shutdown()

    def test_S11b_api_key_persisted(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        e1 = AppEngine()
        assert e1.initialize() is True
        e1.save_settings({
            "api_key": "sk-p",
            "active_provider": "doubao",
            "model": "doubao-seed-2.0-lite",
        })
        e1.shutdown()

        e2 = AppEngine()
        assert e2.initialize() is True
        s = e2.get_current_settings_dict()
        assert s["api_key"] == "sk-p"
        e2.shutdown()

    def test_S11c_model_persisted(self, scai_tmp):
        from aibridge.app_engine import AppEngine
        e1 = AppEngine()
        assert e1.initialize() is True
        e1.save_settings({
            "api_key": "sk-p",
            "active_provider": "doubao",
            "model": "doubao-seed-2.0-lite",
        })
        e1.shutdown()

        e2 = AppEngine()
        assert e2.initialize() is True
        s = e2.get_current_settings_dict()
        assert s["model"] == "doubao-seed-2.0-lite"
        e2.shutdown()


# ========================================= Grill S12: WorkspacePage LLM 卡片 =========================================

class TestS12WorkspaceLLMCard:
    """S12: Workbench 新增"当前 LLM"卡片（provider + model + 红/绿点），保存后立刻刷新"""

    def test_S12a_initial_provider_deepseek(self, eng):
        ws = _FakeWorkspacePage(app_engine=eng)
        assert ws._llm_provider_label_text == "DeepSeek"

    def test_S12b_initial_model_echoed(self, eng):
        ws = _FakeWorkspacePage(app_engine=eng)
        assert ws._llm_model_label_text == "deepseek-v4-flash"

    def test_S12c_initial_dot_red_without_key(self, eng):
        ws = _FakeWorkspacePage(app_engine=eng)
        assert ws._llm_dot_color == "#ef4444"

    def test_S12d_dot_turns_green_after_save_key(self, eng):
        ws = _FakeWorkspacePage(app_engine=eng)
        eng.save_settings({"api_key": "sk-ws"})
        assert ws._llm_dot_color == "#22c55e"

    def test_S12e_provider_hot_updated_after_switch(self, eng):
        ws = _FakeWorkspacePage(app_engine=eng)
        eng.save_settings({
            "active_provider": "doubao",
            "api_key": "dw",
            "model": "doubao-seed-2.0-lite",
        })
        assert ws._llm_provider_label_text == "豆包"

    def test_S12f_model_hot_updated_after_switch(self, eng):
        ws = _FakeWorkspacePage(app_engine=eng)
        eng.save_settings({
            "active_provider": "doubao",
            "api_key": "dw",
            "model": "doubao-seed-2.0-lite",
        })
        assert ws._llm_model_label_text == "doubao-seed-2.0-lite"


# ========================================= Grill S13: 连续多次 save 最终显示最后一次 =========================================

class TestS13SequentialSave:
    """S13: 连续多次 save，最终 UI 显示最后一次的值，不会出现第一次把第二次覆盖"""

    def test_S13_final_value_after_multiple_saves(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        eng.register_settings_changed_callback(p.refresh_settings)
        eng.save_settings({"api_key": "i1"})
        eng.save_settings({"api_key": "i2"})
        eng.save_settings({"api_key": "i3-final"})
        assert p._apikey_edit["text"] == "i3-final"


# ========================================= Grill S14: refresh_settings 双路径 =========================================

class TestS14RefreshDualPath:
    """S14: refresh_settings 有参数直接用（回调场景），无参数主动拉 Engine（init 场景）"""

    def test_S14a_explicit_param_used_directly(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        p.refresh_settings({
            "active_provider": "doubao",
            "api_key": "sk-p",
            "base_url": "t",
            "model": "doubao-seed-2.0-lite",
        })
        assert p.provider_combo["current"] == "doubao"

    def test_S14b_explicit_param_api_key(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        p.refresh_settings({
            "active_provider": "doubao",
            "api_key": "sk-p",
            "base_url": "t",
            "model": "doubao-seed-2.0-lite",
        })
        assert p._apikey_edit["text"] == "sk-p"

    def test_S14c_none_param_pulls_from_engine(self, eng):
        p = _FakeSettingsPage(app_engine=eng)
        eng.save_settings({"api_key": "sk-e"})
        p.refresh_settings(None)
        assert p._apikey_edit["text"] == "sk-e"
