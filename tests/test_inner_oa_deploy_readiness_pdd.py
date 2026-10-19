# -*- coding: utf-8 -*-
"""
SCAI PDD 模块 18 · OA Cloud Deploy Readiness pytest 用例

覆盖 10 条 Grill（G1-G10）。
验证 config_loader 新字段、start.sh / deploy.sh 内容、requirements 补全。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

DEPLOY_DIR = PROJECT_ROOT / "deploy" / "oa_service"


# ============== G1-G3 · config_loader 新字段 ==============

class TestG1ConfigLoaderNewFields:
    def test_optional_defaults_has_4_new_fields(self):
        """G1: OPTIONAL_DEFAULTS 包含 persona_file / llm_base_url / llm_model / kb_enabled"""
        from aibridge.oa_service.config_loader import OPTIONAL_DEFAULTS
        for field in ("persona_file", "llm_base_url", "llm_model", "kb_enabled"):
            assert field in OPTIONAL_DEFAULTS, f"OPTIONAL_DEFAULTS 缺少新字段: {field}"

    def test_load_config_fills_new_fields_defaults(self, tmp_path):
        """G2: load_config 后 config 字典包含所有新字段（即使 config.json 里没写）"""
        from aibridge.oa_service.config_loader import load_config
        cfg_file = tmp_path / "config.json"
        # 只写 4 个必填字段，不写任何新字段
        cfg_file.write_text(json.dumps({
            "app_id": "wx_test",
            "app_secret": "secret",
            "token": "token",
            "encoding_aes_key": "0123456789abcdef0123456789abcdef0123456789a",
        }), encoding="utf-8")
        config = load_config(str(cfg_file))
        for field in ("persona_file", "llm_base_url", "llm_model", "kb_enabled"):
            assert field in config, f"load_config 后 config 缺少: {field}（应从 OPTIONAL_DEFAULTS 补全）"

    def test_validate_config_accepts_minimal_config(self):
        """G3: validate_config 对只有 4 个必填字段的 config 仍返回 True"""
        from aibridge.oa_service.config_loader import validate_config
        minimal = {
            "app_id": "wx_test",
            "app_secret": "secret",
            "token": "token",
            "encoding_aes_key": "0123456789abcdef0123456789abcdef0123456789a",
        }
        assert validate_config(minimal) is True


# ============== G4-G6 · start.sh 接入 auto_bootstrap ==============

class TestG4StartShAutoBootstrap:
    def test_start_sh_uses_auto_bootstrap(self):
        """G4: start.sh 调用 auto_bootstrap 而非 create_app(mp=None)"""
        start_sh = DEPLOY_DIR / "start.sh"
        content = start_sh.read_text(encoding="utf-8")
        assert "auto_bootstrap" in content, "start.sh 必须调用 OACloudService.auto_bootstrap"
        # 旧方式 create_app(config, mp=None) 不应再出现
        assert "mp=None" not in content or "create_app(config=config, mp=None)" not in content, \
            "start.sh 不应再用 create_app(config, mp=None) 旧方式"

    def test_start_sh_imports_build_flask_app(self):
        """G5: start.sh 导入 build_flask_app（auto_bootstrap 的配套工厂）"""
        content = (DEPLOY_DIR / "start.sh").read_text(encoding="utf-8")
        assert "build_flask_app" in content, "start.sh 必须导入 build_flask_app"
        assert "OACloudService" in content

    def test_start_sh_prints_degraded_status(self):
        """G6: start.sh 打印 degraded 状态"""
        content = (DEPLOY_DIR / "start.sh").read_text(encoding="utf-8")
        assert "degraded" in content.lower(), "start.sh 必须打印 degraded 状态"


# ============== G7-G9 · deploy.sh 复制完整依赖 ==============

class TestG7DeployShFullPackage:
    def test_deploy_sh_copies_full_aibridge(self):
        """G7: deploy.sh 复制 src/aibridge/ 完整目录（含 rag/ engine/）"""
        content = (DEPLOY_DIR / "deploy.sh").read_text(encoding="utf-8")
        assert "rag" in content, "deploy.sh 必须复制 rag/ 子目录"
        assert "engine" in content, "deploy.sh 必须复制 engine/ 子目录"
        assert "config" in content, "deploy.sh 必须复制 config/ 子目录"
        # 不应只复制 oa_service
        assert "for subdir in" in content, "deploy.sh 应循环复制所有子目录"

    def test_deploy_sh_checks_bootstrap_import(self):
        """G8: deploy.sh 自检步骤包含 bootstrap_oa_components 导入测试"""
        content = (DEPLOY_DIR / "deploy.sh").read_text(encoding="utf-8")
        assert "bootstrap_oa_components" in content, \
            "deploy.sh 自检必须包含 bootstrap_oa_components 导入测试"

    def test_deploy_sh_checks_auto_bootstrap_attr(self):
        """G9: deploy.sh 自检验证 OACloudService.auto_bootstrap 存在"""
        content = (DEPLOY_DIR / "deploy.sh").read_text(encoding="utf-8")
        assert "auto_bootstrap" in content, \
            "deploy.sh 自检必须验证 hasattr(OACloudService, 'auto_bootstrap')"
        assert "hasattr" in content


# ============== G10 · requirements 补充 ==============

class TestG10Requirements:
    def test_requirements_has_openai_and_chromadb(self):
        """G10: requirements_oa.txt 新增 openai + chromadb"""
        content = (DEPLOY_DIR / "requirements_oa.txt").read_text(encoding="utf-8")
        assert "openai" in content.lower(), "requirements 必须包含 openai"
        assert "chromadb" in content.lower(), "requirements 必须包含 chromadb（可选标记）"
