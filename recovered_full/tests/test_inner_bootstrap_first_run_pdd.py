"""
SCAI MVP · P1-3 首次启动引导 · PDD Test Seams

Grill 清单（10 条）：
- G1: ConfigManager.is_first_run() 首次返回 True
- G2: ConfigManager.mark_first_run_done() 后 is_first_run() 返回 False
- G3: mark_first_run_done() 持久化到 config.json
- G4: bootstrap_data.EXAMPLE_PERSONA 含必要字段（name/type/description/tone）
- G5: bootstrap_data.EXAMPLE_WIKI_PAGES 至少 5 条，覆盖 concepts/entities/architecture
- G6: inject_example_wiki 写入文件且内容含 frontmatter（type:）
- G7: inject_example_wiki 幂等（二次调用写入数为 0）
- G8: bootstrap_first_run 首次返回 persona_injected=True + wiki_written>=5
- G9: bootstrap_first_run 二次调用 wiki_written=0（已标记首启完成）
- G10: inject_example_persona 不覆盖已有非空字段
"""
import os
import json
import tempfile
from pathlib import Path

import pytest


# ============================================================
# G1-G3: ConfigManager 首次启动检测
# ============================================================

class TestG1G3ConfigManagerFirstRun:
    def test_G1_is_first_run_true_on_new_config(self, tmp_path, monkeypatch):
        """G1: 新 config.json → is_first_run() 返回 True"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager()
        assert cm.is_first_run() is True

    def test_G2_mark_first_run_done_flips_to_false(self, tmp_path, monkeypatch):
        """G2: mark_first_run_done() 后 is_first_run() 返回 False"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager()
        assert cm.is_first_run() is True
        cm.mark_first_run_done()
        assert cm.is_first_run() is False

    def test_G3_first_run_flag_persisted_to_disk(self, tmp_path, monkeypatch):
        """G3: mark_first_run_done() 持久化到 config.json"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager()
        cm.mark_first_run_done()

        # 重新加载 ConfigManager 模拟重启
        cm2 = ConfigManager()
        assert cm2.is_first_run() is False


# ============================================================
# G4-G5: 示例数据完整性
# ============================================================

class TestG4G5ExampleDataIntegrity:
    def test_G4_example_persona_has_required_fields(self):
        """G4: EXAMPLE_PERSONA 含 name/type/description/tone"""
        from aibridge.bootstrap_data import EXAMPLE_PERSONA
        assert "name" in EXAMPLE_PERSONA
        assert "type" in EXAMPLE_PERSONA
        assert "description" in EXAMPLE_PERSONA
        assert "tone" in EXAMPLE_PERSONA
        assert len(EXAMPLE_PERSONA["name"]) > 0
        assert len(EXAMPLE_PERSONA["type"]) > 0

    def test_G5_example_wiki_pages_count_and_types(self):
        """G5: EXAMPLE_WIKI_PAGES 至少 5 条，覆盖三层目录"""
        from aibridge.bootstrap_data import EXAMPLE_WIKI_PAGES
        assert len(EXAMPLE_WIKI_PAGES) >= 5

        paths = [p["path"] for p in EXAMPLE_WIKI_PAGES]
        assert any(p.startswith("concepts/") for p in paths)
        assert any(p.startswith("entities/") for p in paths)
        assert any(p.startswith("architecture/") for p in paths)


# ============================================================
# G6-G7: inject_example_wiki 写入 + 幂等
# ============================================================

class TestG6G7InjectWiki:
    def test_G6_inject_writes_files_with_frontmatter(self, tmp_path):
        """G6: inject_example_wiki 写入文件且含 frontmatter"""
        from aibridge.bootstrap_data import inject_example_wiki
        wiki_root = tmp_path / "wiki"
        written = inject_example_wiki(wiki_root)
        assert written >= 5

        # 验证文件存在且含 frontmatter
        for page in [
            "concepts/fruit-seasonality.md",
            "entities/grape-varieties.md",
            "architecture/customer-service-flow.md",
        ]:
            fpath = wiki_root / page
            assert fpath.exists(), f"文件不存在: {page}"
            content = fpath.read_text(encoding="utf-8")
            assert content.startswith("---"), f"缺 frontmatter: {page}"
            assert "type:" in content[:200], f"缺 type 字段: {page}"

    def test_G7_inject_idempotent_second_run_zero(self, tmp_path):
        """G7: 二次调用写入数为 0（幂等）"""
        from aibridge.bootstrap_data import inject_example_wiki
        wiki_root = tmp_path / "wiki"
        first = inject_example_wiki(wiki_root)
        second = inject_example_wiki(wiki_root)
        assert first >= 5
        assert second == 0


# ============================================================
# G8-G9: bootstrap_first_run 完整流程
# ============================================================

class TestG8G9BootstrapFirstRun:
    def test_G8_first_bootstrap_injects_persona_and_wiki(self, tmp_path, monkeypatch):
        """G8: 首次调用注入人设 + 知识

        P1-1 调整：bootstrap_first_run 不再标记 first_run_done（改由 FirstRunWizard 完成）
        所以 G8 不再断言 is_first_run()=False，改为断言 example_data_injected=True
        """
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.config.config_manager import ConfigManager
        from aibridge.bootstrap_data import bootstrap_first_run

        cm = ConfigManager()
        wiki_root = tmp_path / "wiki"
        result = bootstrap_first_run(cm, wiki_root)

        assert result["persona_injected"] is True
        assert result["wiki_written"] >= 5
        # P1-1: example_data_injected 标志已设置（独立于 first_run_done）
        assert cm.get("app.example_data_injected", False) is True
        # P1-1: first_run_done 仍为 False（等 FirstRunWizard 完成时标记）
        assert cm.is_first_run() is True
        # 人设字段已写入
        assert cm.get("persona.name") == "鲜果小助手"

    def test_G9_second_bootstrap_skips_injection(self, tmp_path, monkeypatch):
        """G9: 二次调用跳过注入（已标记 example_data_injected）"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.config.config_manager import ConfigManager
        from aibridge.bootstrap_data import bootstrap_first_run

        cm = ConfigManager()
        wiki_root = tmp_path / "wiki"
        first = bootstrap_first_run(cm, wiki_root)
        second = bootstrap_first_run(cm, wiki_root)

        assert first["wiki_written"] >= 5
        assert second["persona_injected"] is False
        assert second["wiki_written"] == 0


# ============================================================
# G10: 人设注入不覆盖已有值
# ============================================================

class TestG10PersonaNoOverwrite:
    def test_G10_existing_persona_not_overwritten(self, tmp_path, monkeypatch):
        """G10: 已有非空人设字段不被覆盖"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.config.config_manager import ConfigManager
        from aibridge.bootstrap_data import bootstrap_first_run, EXAMPLE_PERSONA

        cm = ConfigManager()
        # 预设用户已有的人设名
        cm.set("persona.name", "我的自定义人设")
        cm.save_config()

        wiki_root = tmp_path / "wiki"
        bootstrap_first_run(cm, wiki_root)

        # 用户已有的人设名应保留
        assert cm.get("persona.name") == "我的自定义人设"
        # 但其他未设置的字段（如 description）应被注入
        assert cm.get("persona.description") == EXAMPLE_PERSONA["description"]
