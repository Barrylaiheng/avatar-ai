"""
ChatPage PDD 验证测试（Phase 5 /tdd）

原型契约 (ui_mockup.html L1615-1917):
  ┌─ ChatPage HBox: chat-area (flex:1) + right-panel (300px) ───────┐
  │  Left chat-area (VBox):                                          │
  │    [API Alert Bar, hidden] ⚠️ "AI 引擎未连接, 前往配置 →"  (L1617)  │
  │    Chat Header: ● dot + "AI 面试官 · 数字分身搭建引导" +        │
  │                  "当前阶段：知识萃取 → 人格塑造" + StageBars 6段  │
  │    Messages ScrollArea (gap 16px, padding 24) ⬇️                  │
  │      msg.ai: bot avatar + bubble (chips: 4 quick replies)        │
  │      msg.user: user avatar + bubble                              │
  │      msg.ai: upload-area (dashed border, "点击上传文档")          │
  │    TypingIndicator (hidden, bot side)                             │
  │    Chat Input Bar: input-wrap(border:1px solid radius-lg) +     │
  │      textarea placeholder="输入你的回复..." + send btn 30x30      │
  │      tool-btns: 📎 上传文档 / 💬 发送图片 / 🗂 导入聊天记录       │
  │  Right Panel:                                                     │
  │    Tabs: [搭建进度 active] / [运行看板]  (L1711-1713)             │
  │    Progress Steps 6: vertical layout, gap 4px,                   │
  │      [1目标确认✓ 2知识萃取✓ 3人格塑造● 4交互设计○ 5部署交付○ 6持续演化○]│
  │    Brand Badge: 影分身AI logo + "13 条已提炼知识"                 │
  │    Extracted Cards: 目标确认·3条 → 3 cards (角色定位/服务对象/边界)│
  │                      知识萃取·6条 → ...                            │
  │  Signals: goto_settings / goto_knowledge / goto_workspace /      │
  │           message_sent / llm_saved / kb_toggled(兼容)             │
  └──────────────────────────────────────────────────────────────────┘

执行: pytest tests/test_chat_page_pdd.py -v
"""
from __future__ import annotations

import os, sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.environ.setdefault("QT_OPENGL", "software")

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFrame, QScrollArea,
    QStackedWidget, QPlainTextEdit, QHBoxLayout, QVBoxLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def cp(qapp):
    from aibridge.ui.chat_page import ChatPage
    from aibridge.ui.theme import apply_theme
    apply_theme(None, "light")
    parent = QWidget()
    parent.resize(1100, 750)
    page = ChatPage(parent=parent)
    page.resize(1080, 730)
    parent.show()
    page.show()
    QTest.qWait(150)
    yield page
    try:
        page.close(); parent.close(); page.deleteLater(); parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ========== CP-1: 双栏布局（chat-area + right-panel） ==========
def test_cp1_two_columns(cp):
    """CP-1: chat-area exists + right-panel exists"""
    assert cp._chat_area is not None
    assert cp._right_panel is not None

# ========== CP-2: Chat Header 标题 ==========
def test_cp2_header_title(cp):
    """CP-2: chat-header title 含人设名（默认 '影分身 AI'）"""
    labels = [l for l in cp.findChildren(QLabel) if "影分身 AI" in l.text()]
    assert len(labels) >= 1, "未找到 '影分身 AI' 标题"

# ========== CP-3: Chat Header 子标题 ==========
def test_cp3_header_sub(cp):
    """CP-3: header sub-label 含默认人设引导文案"""
    labels = [l for l in cp.findChildren(QLabel) if "默认人设" in l.text() or "Persona 编辑器" in l.text()]
    assert len(labels) >= 1, "未找到默认人设引导文案 sub-label"

# ========== CP-4: 6 StageBars segments ==========
def test_cp4_six_stage_bars(cp):
    """CP-4: _StageBars contains 6 QFrame segments + 6 QLabel stages"""
    from aibridge.ui.chat_page import _StageBars
    bars = cp.findChildren(_StageBars)
    assert len(bars) >= 1, "未找到 StageBars"
    bar = bars[0]
    frames = bar.findChildren(QFrame)
    # 6 progress bar segments (排除嵌套 frame)
    assert len(frames) >= 6, f"StageBars 应有至少 6 段 bars，实际 {len(frames)}"
    labels = [l for l in bar.findChildren(QLabel)]
    assert len(labels) >= 6, f"StageBars 应有至少 6 个阶段名称 label，实际 {len(labels)}"

# ========== CP-5: STAGES 名称匹配原型 ==========
def test_cp5_stage_names(cp):
    """CP-5: 6 stage names == 目标确认/知识萃取/人格塑造/交互设计/部署交付/持续演化"""
    from aibridge.ui.chat_page import STAGES
    names = [n for _, n in STAGES]
    expected = ["目标确认", "知识萃取", "人格塑造", "交互设计", "部署交付", "持续演化"]
    assert names == expected, f"STAGES 不匹配: {names}"

# ========== CP-6: Messages ScrollArea ==========
def test_cp6_msg_scroll(cp):
    """CP-6: _msg_scroll 是 QScrollArea 且 widgetResizable"""
    assert isinstance(cp._msg_scroll, QScrollArea)
    assert cp._msg_scroll.widgetResizable() is True

# ========== CP-7: 有 QPlainTextEdit 输入框 ==========
def test_cp7_plaintext_edit(cp):
    """CP-7: _input_edit 是 QPlainTextEdit，有 placeholder"""
    assert isinstance(cp._input_edit, QPlainTextEdit)
    assert "输入你的回复" in cp._input_edit.placeholderText()

# ========== CP-8: 发送按钮 30x30 ==========
def test_cp8_send_btn_size(cp):
    """CP-8: send btn size 30x30, primary bg"""
    # 找到 send btn（30x30, 位于 input area）
    all_btns = cp.findChildren(QPushButton)
    send = [b for b in all_btns if b.width() == 30 and b.height() == 30]
    assert len(send) >= 1, "未找到 30x30 发送按钮"

# ========== CP-9: 至少 2 个工具按钮（上传文档/导入聊天记录） ==========
def test_cp9_tool_btns(cp):
    """CP-9: chat tool btns (QToolButton) 存在（📎上传文档 + 💬导入聊天记录）"""
    from PyQt6.QtWidgets import QToolButton
    all_tb = cp.findChildren(QToolButton)
    tool_texts = [b.text() for b in all_tb]
    assert any("上传文档" in t for t in tool_texts), f"缺少📎上传文档 btn，现有: {tool_texts}"
    assert any("导入聊天记录" in t for t in tool_texts), f"缺少💬导入聊天记录 btn，现有: {tool_texts}"
    assert len(all_tb) >= 2, f"应有至少 2 个 QToolButton，实际 {len(all_tb)}: {tool_texts}"

# ========== CP-10: API Alert Bar 默认隐藏 ==========
def test_cp10_api_alert_hidden(cp):
    """CP-10: _api_alert 默认 isVisible == False"""
    assert cp._api_alert.isVisible() is False

# ========== CP-11: TypingIndicator 默认隐藏 ==========
def test_cp11_typing_hidden(cp):
    """CP-11: _typing 默认 hidden, TypingIndicator 类"""
    from aibridge.ui.components.typing_indicator import TypingIndicator
    assert isinstance(cp._typing, TypingIndicator)
    assert cp._typing.isVisible() is False

# ========== CP-12: 默认会话创建 ==========
def test_cp12_default_session(cp):
    """CP-12: 默认创建 1 个 session，active_session_id 非 None"""
    assert len(cp._sessions) >= 1
    assert cp._active_session_id is not None

# ========== CP-13: append_reply API ==========
def test_cp13_append_reply(cp):
    """CP-13: append_reply → message count 增加 1"""
    from aibridge.ui.chat_page import _ChatMessage
    sid = cp._active_session_id
    orig_count = len(cp._sessions[sid].messages)
    cp.append_reply(sid, "测试回复 PDD")
    new_count = len(cp._sessions[sid].messages)
    assert new_count == orig_count + 1, f"消息数应增加 1，实际 {orig_count}→{new_count}"

# ========== CP-14: 右侧 2 个 Panel tab buttons ==========
def test_cp14_two_panel_tabs(cp):
    """CP-14: 右侧 2 个 tab: 搭建进度/运行看板"""
    rp = cp._right_panel
    all_labels = rp.findChildren(QLabel)
    all_btns = rp.findChildren(QPushButton)
    texts = [l.text() for l in all_labels] + [b.text() for b in all_btns]
    assert any("搭建进度" in t for t in texts), f"缺少 '搭建进度' tab，现有: {texts}"
    assert any("运行看板" in t for t in texts), f"缺少 '运行看板' tab，现有: {texts}"

# ========== CP-15: 右侧 6 垂直 progress steps ==========
def test_cp15_six_progress_steps_vertical(cp):
    """CP-15: right panel 有 6 个 progress steps（含 '目标确认' 文本）"""
    rp = cp._right_panel
    labels = [l.text() for l in rp.findChildren(QLabel)]
    # 目标确认 / 知识萃取 / 人格塑造 / 交互设计 / 部署交付 / 持续演化
    six = ["目标确认", "知识萃取", "人格塑造", "交互设计", "部署交付", "持续演化"]
    found = 0
    for s in six:
        if any(s == t for t in labels):
            found += 1
    assert found >= 6, f"6 progress steps 应有全部，实际 {found}/6: {[l for l in labels if l in six]}"

# ========== CP-16: 品牌徽章 "影分身AI" ==========
def test_cp16_brand_badge(cp):
    """CP-16: '影分身AI' 文本存在"""
    labels = [l for l in cp._right_panel.findChildren(QLabel)]
    texts = [l.text() for l in labels]
    assert any("影分身" in t for t in texts), f"缺少品牌徽章，现有品牌相关: {[t for t in texts if len(t) < 20]}"

# ========== CP-17: extracted cards ≥ 3（目标确认·3） ==========
def test_cp17_extracted_cards(cp):
    """CP-17: 清零版 — extracted 区域为空状态占位，不含任何示意数据"""
    labels = [l.text() for l in cp._right_panel.findChildren(QLabel)]
    # 清零后不应包含水果电商示意数据
    fruit_keywords = ["水果", "分身角色：水果", "水果电商", "当季水果", "水果小助手"]
    fruit_hits = [t for t in labels if any(kw in t for kw in fruit_keywords)]
    assert len(fruit_hits) == 0, f"清零后不应包含水果示意数据，发现: {fruit_hits}"
    # 应有空状态提示
    empty_hints = [t for t in labels if "萃取的知识将显示在此" in t or "搭建完成" in t]
    assert len(empty_hints) >= 1, f"应有空状态占位提示，现有: {labels[:30]}"

# ========== CP-18: 信号 goto_settings_requested ==========
def test_cp18_signal_goto_settings(cp):
    """CP-18: goto_settings_requested 信号存在"""
    from PyQt6.QtCore import pyqtBoundSignal
    assert isinstance(cp.goto_settings_requested, pyqtBoundSignal)

# ========== CP-19: 信号 goto_knowledge_requested ==========
def test_cp19_signal_goto_knowledge(cp):
    """CP-19: goto_knowledge_requested(str) 信号存在"""
    from PyQt6.QtCore import pyqtBoundSignal
    assert isinstance(cp.goto_knowledge_requested, pyqtBoundSignal)

# ========== CP-20: 信号 goto_workspace_requested ==========
def test_cp20_signal_goto_workspace(cp):
    """CP-20: goto_workspace_requested(str) 信号存在"""
    from PyQt6.QtCore import pyqtBoundSignal
    assert isinstance(cp.goto_workspace_requested, pyqtBoundSignal)

# ========== CP-21: 信号 message_sent ==========
def test_cp21_signal_message_sent(cp):
    """CP-21: message_sent(str, str) 信号存在"""
    from PyQt6.QtCore import pyqtBoundSignal
    assert isinstance(cp.message_sent, pyqtBoundSignal)

# ========== CP-22: active_session_id() API ==========
def test_cp22_active_session_api(cp):
    """CP-22: active_session_id() 返回非 None str"""
    sid = cp.active_session_id()
    assert isinstance(sid, str) and len(sid) > 0

# ========== CP-23: create_new_session API ==========
def test_cp23_create_new_session(cp):
    """CP-23: create_new_session → session 数 +1，且 active"""
    orig = len(cp._sessions)
    new_sid = cp.create_new_session("测试会话 PDD")
    assert new_sid in cp._sessions
    assert cp._sessions[new_sid].title == "测试会话 PDD"
    assert len(cp._sessions) == orig + 1

# ========== CP-24: 输入非空时 append_user_message + 消息可见 ==========
def test_cp24_user_message_appended(cp):
    """CP-24: append_reply(user role) → new message role=user"""
    sid = cp._active_session_id
    cp.append_reply(sid, "你好", role="user")
    last = cp._sessions[sid].messages[-1]
    assert last.role == "user"
    assert last.content == "你好"

# ========== CP-25: 根布局 VBox + 水平 QSplitter（容器化双栏孤岛布局） ==========
def test_cp25_root_hbox(cp):
    """CP-25: 容器化改造后：外层VBox（留白12px）+ 水平QSplitter，内含 chat-area / right-panel 两个孤岛容器"""
    from PyQt6.QtWidgets import QVBoxLayout, QSplitter, QFrame
    from PyQt6.QtCore import Qt

    outer = cp.layout()
    assert isinstance(outer, QVBoxLayout), \
        f"容器化外层应为 QVBoxLayout（留白层），实际 {type(outer)}"
    # 检查外边距：容器化改造要求四周留白 12px，形成悬浮孤岛感
    m = outer.contentsMargins()
    assert m.left() == 12 and m.top() == 12 and m.right() == 12 and m.bottom() == 12, \
        f"外层留白应为 12px/四边，实际 L={m.left()} T={m.top()} R={m.right()} B={m.bottom()}"

    # 外层下必须有一个水平 QSplitter（两容器左右排列 + 拖拽拉伸 + 16px孤岛间距）
    splitter = cp.findChild(QSplitter, "chat-splitter")
    assert splitter is not None, "未找到 chat-splitter（两容器间水平分割器）"
    assert splitter.orientation() == Qt.Orientation.Horizontal, \
        f"Splitter 方向应为水平(Horizontal)，实际 {splitter.orientation()}"
    assert splitter.handleWidth() == 16, \
        f"QSplitter handleWidth 应为 16px（孤岛间距），实际 {splitter.handleWidth()}"

    # Splitter 中必须包含 2 个 widget：左侧 chat-area（悬浮卡片） + 右侧 right-panel
    assert splitter.count() >= 2, \
        f"Splitter 至少含 2 个子容器（chat-area / right-panel），实际 {splitter.count()}"
    chat_area = splitter.widget(0)
    right_panel = splitter.widget(1)
    assert isinstance(chat_area, QFrame) and chat_area.objectName() == "chat-area", \
        f"Splitter[0] 应为 chat-area QFrame，实际 {type(chat_area)} objName={chat_area.objectName() if hasattr(chat_area,'objectName') else 'N/A'}"
    assert right_panel is not None, "Splitter[1] right-panel 不存在"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
