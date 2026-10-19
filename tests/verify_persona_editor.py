"""
七段结构人设编辑器验证脚本

验证内容：
1. SevenSectionPersona 数据模型
2. 七段结构 Prompt 组装
3. 硬规则配置器
4. 数据库持久化（可选）
5. UI 组件导入
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 设置环境变量避免 COM 输入法崩溃
os.environ['QT_IM_MODULE'] = ''


def test_persona_data_model():
    """测试 1: SevenSectionPersona 数据模型"""
    print("\n--- 测试 1: SevenSectionPersona 数据模型 ---")
    from aibridge.ui.persona_editor import SevenSectionPersona

    persona = SevenSectionPersona(
        name="测试人设",
        role="你是测试助手",
        task="帮助用户测试",
        rules="保持友好",
    )

    assert persona.persona_id.startswith("persona_"), "应自动生成 ID"
    assert persona.created_at, "应有创建时间"
    assert persona.updated_at, "应有更新时间"
    assert not persona.is_active, "默认不激活"

    print(f"  ✓ 自动生成 ID: {persona.persona_id}")
    print(f"  ✓ 时间戳: {persona.created_at}")
    print(f"  ✓ 七段结构: role/task/rules 已设置")

    # 测试序列化
    d = persona.to_dict()
    assert d["name"] == "测试人设"
    assert d["role"] == "你是测试助手"
    print(f"  ✓ 序列化为 dict: {len(d)} 个字段")

    # 测试反序列化
    restored = SevenSectionPersona.from_dict(d)
    assert restored.name == persona.name
    assert restored.role == persona.role
    print(f"  ✓ 反序列化恢复: {restored.name}")


def test_to_prompt_conversion():
    """测试 2: 转换为 MessageProcessor 的 role_config 格式"""
    print("\n--- 测试 2: 转换为 role_config ---")
    from aibridge.ui.persona_editor import SevenSectionPersona

    persona = SevenSectionPersona(
        name="AI 实战导师",
        role="你是 AI 实战导师",
        task="每次只讲一个知识点",
        rules="70-80%来自实践",
        examples="用户：怎么做\nAI：我们先从...",
        style="耐心专业",
        constraints="不超过 250 字",
        output_format="直接回答",
    )

    role_config = persona.to_prompt()

    assert role_config["identity"] == "你是 AI 实战导师"
    assert role_config["task"] == "每次只讲一个知识点"
    assert role_config["rules"] == "70-80%来自实践"
    assert role_config["examples"] == "用户：怎么做\nAI：我们先从..."
    assert role_config["tone"] == "耐心专业"
    assert role_config["constraints"] == "不超过 250 字"
    assert role_config["output_format"] == "直接回答"
    print(f"  ✓ role_config 包含 7 个字段")
    print(f"  ✓ identity: {role_config['identity']}")


def test_default_template():
    """测试 3: 默认模板"""
    print("\n--- 测试 3: 默认模板 ---")
    from aibridge.ui.persona_editor import DEFAULT_PERSONA_TEMPLATE

    assert DEFAULT_PERSONA_TEMPLATE.name == "AI 实战导师"
    assert "AI 实战导师" in DEFAULT_PERSONA_TEMPLATE.role
    assert "70-80%" in DEFAULT_PERSONA_TEMPLATE.rules
    assert "250" in DEFAULT_PERSONA_TEMPLATE.constraints
    print(f"  ✓ 模板名称: {DEFAULT_PERSONA_TEMPLATE.name}")
    print(f"  ✓ 角色设定: {DEFAULT_PERSONA_TEMPLATE.role[:30]}...")
    print(f"  ✓ 行为规则: {DEFAULT_PERSONA_TEMPLATE.rules[:30]}...")


def test_hard_rules_config():
    """测试 4: 硬规则配置器"""
    print("\n--- 测试 4: 硬规则配置器 ---")
    from aibridge.ui.persona_editor import HardRulesConfigWidget
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    widget = HardRulesConfigWidget()
    config = widget.get_config()

    assert config["max_chars"] == 250, "默认 250 字"
    assert config["force_question_ending"] is True, "默认启用"
    assert config["max_steps"] == 1, "默认 1 步"
    assert config["require_term_explanation"] is True, "默认启用"
    print(f"  ✓ 默认配置: max_chars={config['max_chars']}, steps={config['max_steps']}")

    # 修改配置
    widget.set_config({
        "max_chars": 500,
        "force_question_ending": False,
        "max_steps": 3,
        "require_term_explanation": False,
    })
    config = widget.get_config()
    assert config["max_chars"] == 500
    assert config["force_question_ending"] is False
    assert config["max_steps"] == 3
    print(f"  ✓ 修改配置: max_chars={config['max_chars']}, steps={config['max_steps']}")


def test_section_editor():
    """测试 5: 单段编辑器"""
    print("\n--- 测试 5: 单段编辑器 ---")
    from aibridge.ui.persona_editor import SectionEditor
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    received_signals = []
    editor = SectionEditor("role", "1.角色设定", "输入角色设定")
    editor.content_changed.connect(
        lambda name, content: received_signals.append((name, content))
    )

    editor.set_content("你是 AI 实战导师")
    assert editor.get_content() == "你是 AI 实战导师"
    print(f"  ✓ 设置内容: {editor.get_content()}")

    # 测试信号触发
    editor.set_content("新内容")
    # set_content 使用 blockSignals，不应触发
    assert len(received_signals) == 0, "set_content 不应触发信号"
    print(f"  ✓ set_content 不触发信号（使用 blockSignals）")


def test_ui_import():
    """测试 6: UI 组件完整导入"""
    print("\n--- 测试 6: UI 组件导入 ---")
    from aibridge.ui.persona_editor import (
        PersonaEditorPanel,
        SevenSectionPersona,
        DEFAULT_PERSONA_TEMPLATE,
        SectionEditor,
        HardRulesConfigWidget,
    )
    print(f"  ✓ PersonaEditorPanel 导入成功")
    print(f"  ✓ SevenSectionPersona 导入成功")
    print(f"  ✓ DEFAULT_PERSONA_TEMPLATE 导入成功")
    print(f"  ✓ SectionEditor 导入成功")
    print(f"  ✓ HardRulesConfigWidget 导入成功")


def test_db_persistence():
    """测试 7: 数据库持久化（可选）"""
    print("\n--- 测试 7: 数据库持久化 ---")
    from aibridge.database.database_manager import DatabaseManager
    from aibridge.ui.persona_editor import SevenSectionPersona

    db = DatabaseManager()
    db.connect()

    # 初始化 personas 表
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS personas (
                persona_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                role TEXT,
                task TEXT,
                rules TEXT,
                examples TEXT,
                style TEXT,
                constraints TEXT,
                output_format TEXT,
                created_at TEXT,
                updated_at TEXT,
                is_active INTEGER DEFAULT 0
            )
        """)
        print(f"  ✓ personas 表初始化")
    except Exception as e:
        print(f"  - personas 表初始化失败（跳过）: {e}")
        return

    # 保存
    persona = SevenSectionPersona(
        name="测试持久化人设",
        role="测试角色",
        task="测试任务",
    )

    db.execute(
        """
        INSERT OR REPLACE INTO personas
        (persona_id, name, description, role, task, rules, examples,
         style, constraints, output_format, created_at, updated_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            persona.persona_id, persona.name, persona.description,
            persona.role, persona.task, persona.rules, persona.examples,
            persona.style, persona.constraints, persona.output_format,
            persona.created_at, persona.updated_at, int(persona.is_active),
        )
    )
    print(f"  ✓ 保存人设: {persona.persona_id}")

    # 读取
    db.execute(
        "SELECT * FROM personas WHERE persona_id = ?",
        (persona.persona_id,)
    )
    result = db.fetchone()
    assert result is not None, "应能读取到"
    assert result["name"] == "测试持久化人设"
    assert result["role"] == "测试角色"
    print(f"  ✓ 读取人设: {result['name']}")

    # 清理
    db.execute("DELETE FROM personas WHERE persona_id = ?", (persona.persona_id,))
    print(f"  ✓ 清理测试数据")


if __name__ == "__main__":
    print("=" * 60)
    print("AI Bridge - 七段结构人设编辑器 验证")
    print("=" * 60)

    tests = [
        test_persona_data_model,
        test_to_prompt_conversion,
        test_default_template,
        test_hard_rules_config,
        test_section_editor,
        test_ui_import,
        test_db_persistence,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"  ✗ 失败: {e}")
        except Exception as e:
            failed += 1
            print(f"  ✗ 异常: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    if failed == 0:
        print("✓ 全部验证通过")
        sys.exit(0)
    else:
        print("✗ 存在验证失败")
        sys.exit(1)
