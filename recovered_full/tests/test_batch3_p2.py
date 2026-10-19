"""
批次3 (P2) 验证：
  P2a: ScheduleManager CRUD + 调度表达式计算（不依赖 Qt，纯 Python 测试）
  P2b: AppEngine.schedule_* / update_knowledge_entry / export_knowledge_base 接口存在性
       + 未初始化时的防御式返回
  P2c: KnowledgeBaseManager.update_entry / export_knowledge_base 结构验证
       （用临时目录 + Mock ChromaDB，不依赖真实向量库）
  P2d: MainWindow 信号桥接层验证（槽函数存在 + 信号连接到 AppEngine）

运行：
    set QT_QPA_PLATFORM=offscreen
    set PYTHONPATH=src
    python tests/test_batch3_p2.py
"""
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_p2a_schedule_manager():
    """P2a: ScheduleManager CRUD + 调度表达式计算"""
    print("=" * 60)
    print("[P2a] ScheduleManager CRUD + 调度表达式计算")
    print("=" * 60)

    from aibridge.engine.schedule_manager import ScheduleManager, ScheduleTask

    # Mock ConfigManager（用内存 dict 模拟配置存储）
    config = MagicMock()
    _store = {}
    config.get = lambda key, default=None: _store.get(key, default if default is not None else [])
    config.set = lambda key, value: _store.__setitem__(key, value)

    mgr = ScheduleManager(config)
    assert not mgr.is_running(), "新建的 ScheduleManager 不应正在运行"

    # 1. 新增任务
    task_id = mgr.add_task(
        name="每日早安",
        channel="wechat",
        target="all",
        content="早安！",
        schedule_expr="daily:08:00",
        icon="☀️",
    )
    assert task_id, "add_task 应返回非空 task_id"
    print(f"[OK] 新增任务 task_id={task_id}")

    # 2. 查询任务
    tasks = mgr.get_tasks()
    assert len(tasks) == 1, f"应有 1 个任务，实际 {len(tasks)}"
    assert tasks[0].name == "每日早安"
    assert tasks[0].schedule_desc() == "每天 08:00"
    assert tasks[0].next_run is not None, "启用任务应有 next_run"
    print(f"[OK] 查询任务: {tasks[0].name} | {tasks[0].schedule_desc()} | next_run={tasks[0].next_run}")

    # 3. 更新任务
    ok = mgr.update_task(task_id, {"name": "每日早安问候", "content": "早安，今天加油！"})
    assert ok, "update_task 应返回 True"
    task = mgr.get_task(task_id)
    assert task.name == "每日早安问候"
    assert task.content == "早安，今天加油！"
    print(f"[OK] 更新任务: name={task.name} content={task.content}")

    # 4. 切换任务状态
    ok = mgr.toggle_task(task_id, False)
    assert ok, "toggle_task 应返回 True"
    task = mgr.get_task(task_id)
    assert not task.enabled, "禁用后 enabled 应为 False"
    assert task.next_run is None, "禁用后 next_run 应为 None"
    print(f"[OK] 禁用任务: enabled={task.enabled} next_run={task.next_run}")

    ok = mgr.toggle_task(task_id, True)
    task = mgr.get_task(task_id)
    assert task.enabled, "重新启用后 enabled 应为 True"
    assert task.next_run is not None, "重新启用后 next_run 应非空"
    print(f"[OK] 重新启用任务: enabled={task.enabled} next_run={task.next_run}")

    # 5. 调度表达式计算
    now = datetime.now()
    next_daily = mgr._calc_next_run("daily:08:00")
    assert isinstance(next_daily, datetime)
    # daily:08:00 若现在已过 08:00，下次应是明天 08:00
    if now.hour >= 8 or (now.hour == 8 and now.minute > 0):
        assert next_daily > now, "daily 表达式下次执行应在未来"
    print(f"[OK] daily:08:00 → next_run={next_daily.isoformat()}")

    next_weekly = mgr._calc_next_run("weekly:4:10:00")  # 每周五 10:00
    assert isinstance(next_weekly, datetime)
    assert next_weekly > now, "weekly 表达式下次执行应在未来"
    print(f"[OK] weekly:4:10:00 → next_run={next_weekly.isoformat()}")

    next_interval = mgr._calc_next_run("interval:30")
    expected = now + timedelta(minutes=30)
    delta = abs((next_interval - expected).total_seconds())
    assert delta < 5, f"interval:30 应为 30 分钟后，偏差 {delta}s"
    print(f"[OK] interval:30 → next_run={next_interval.isoformat()}")

    # 非法表达式应回退到 1 小时后
    next_invalid = mgr._calc_next_run("invalid_expr")
    expected_invalid = now + timedelta(hours=1)
    delta_invalid = abs((next_invalid - expected_invalid).total_seconds())
    assert delta_invalid < 5, f"非法表达式应回退到 1 小时后，偏差 {delta_invalid}s"
    print(f"[OK] invalid_expr → 回退到 1 小时后: {next_invalid.isoformat()}")

    # 6. 删除任务
    ok = mgr.delete_task(task_id)
    assert ok, "delete_task 应返回 True"
    assert len(mgr.get_tasks()) == 0, "删除后任务列表应为空"
    print(f"[OK] 删除任务: 剩余 {len(mgr.get_tasks())} 个")

    # 7. 持久化验证（配置已被写入）
    assert "schedule.tasks" in _store or len(_store) > 0, "配置应已持久化"
    print(f"[OK] 持久化: 配置存储中有 {len(_store)} 个键")

    print("[P2a] PASS\n")
    return 0


def test_p2b_appengine_interfaces():
    """P2b: AppEngine 接口存在性 + 未初始化防御"""
    print("=" * 60)
    print("[P2b] AppEngine.schedule_* / update_knowledge_entry / export_knowledge_base 接口")
    print("=" * 60)

    from aibridge.app_engine import AppEngine

    engine = AppEngine()
    assert not engine.is_initialized(), "新建 AppEngine 不应已初始化"

    # 验证接口存在
    for method in [
        "update_knowledge_entry",
        "export_knowledge_base",
        "get_schedule_tasks",
        "add_schedule_task",
        "update_schedule_task",
        "delete_schedule_task",
        "toggle_schedule_task",
        "_schedule_send_callback",
    ]:
        assert hasattr(engine, method), f"AppEngine 应有方法 {method}"
        assert callable(getattr(engine, method)), f"{method} 应可调用"
    print("[OK] 8 个新接口全部存在且可调用")

    # 未初始化时的防御式返回
    assert engine.update_knowledge_entry("e1", {"title": "x"}) is False, "未初始化 update_knowledge_entry 应返回 False"
    assert engine.export_knowledge_base() is None, "未初始化 export_knowledge_base 应返回 None"
    assert engine.get_schedule_tasks() == [], "未初始化 get_schedule_tasks 应返回 []"
    assert engine.add_schedule_task("n", "wechat", "all", "c", "daily:08:00") is None, "未初始化 add_schedule_task 应返回 None"
    assert engine.update_schedule_task("t1", {}) is False, "未初始化 update_schedule_task 应返回 False"
    assert engine.delete_schedule_task("t1") is False, "未初始化 delete_schedule_task 应返回 False"
    assert engine.toggle_schedule_task("t1", True) is False, "未初始化 toggle_schedule_task 应返回 False"
    print("[OK] 未初始化时所有接口返回安全的空值/False/None")

    # 验证 initialize() 中会创建 ScheduleManager（通过 inspect 源码）
    import inspect
    source = inspect.getsource(AppEngine.initialize)
    assert "ScheduleManager" in source, "initialize() 应创建 ScheduleManager"
    assert "set_send_callback" in source, "initialize() 应注入 send_callback"
    assert "_schedule_manager.start" in source, "initialize() 应启动调度线程"
    print("[OK] initialize() 源码包含 ScheduleManager 创建 + callback 注入 + start")

    # 验证 shutdown 会停止调度
    shutdown_source = inspect.getsource(AppEngine.shutdown)
    assert "_schedule_manager" in shutdown_source and "stop" in shutdown_source, "shutdown() 应停止 ScheduleManager"
    print("[OK] shutdown() 源码包含 ScheduleManager.stop()")

    print("[P2b] PASS\n")
    return 0


def test_p2c_knowledge_manager():
    """P2c: KnowledgeBaseManager.update_entry / export_knowledge_base 结构验证"""
    print("=" * 60)
    print("[P2c] KnowledgeBaseManager.update_entry / export_knowledge_base")
    print("=" * 60)

    from aibridge.rag.knowledge_base_manager import (
        KnowledgeBaseManager, KnowledgeEntry, PageType
    )

    # Mock db_manager / config_manager
    db = MagicMock()
    config = MagicMock()
    config.get = lambda key, default=None: default

    # 用临时目录测试，避免污染真实知识库
    tmp_dir = tempfile.mkdtemp(prefix="p2c_test_")
    try:
        with patch.object(KnowledgeBaseManager, "_get_kb_path", return_value=tmp_dir), \
             patch.object(KnowledgeBaseManager, "__init__", lambda self, db, cfg: None):
            mgr = KnowledgeBaseManager.__new__(KnowledgeBaseManager)
            mgr._db = db
            mgr._config = config
            mgr._chromadb = MagicMock()  # Mock ChromaDB
            mgr._parser = MagicMock()
            mgr._kb_path = tmp_dir

            # 1. 手动构造一个知识库目录结构
            kb_id = "kb_test_001"
            kb_dir = os.path.join(tmp_dir, kb_id)
            entries_dir = os.path.join(kb_dir, "entries")
            os.makedirs(entries_dir, exist_ok=True)

            # 写 index.md
            index_path = os.path.join(kb_dir, "index.md")
            with open(index_path, "w", encoding="utf-8") as f:
                f.write("""---
name: 测试知识库
description: P2c 测试用
created_at: 2026-08-07
entries: []
---

# 测试知识库

## 知识条目
""")

            # 写一个 entry.md
            entry_id = "entry_test_001"
            entry_path = os.path.join(entries_dir, f"{entry_id}.md")
            entry = KnowledgeEntry(
                entry_id=entry_id,
                kb_id=kb_id,
                title="原标题",
                content="原内容",
                page_type=PageType.QUESTION,
                category="default",
                tags=["原标签"],
            )
            with open(entry_path, "w", encoding="utf-8") as f:
                f.write(entry.to_markdown())
            print(f"[OK] 构造测试知识库: kb_id={kb_id} entry_id={entry_id}")

            # Mock get_knowledge_base（export 用到）：存在的 kb_id 返回信息，不存在的返回 None
            def mock_get_kb(k):
                if k == kb_id:
                    return {
                        "kb_id": kb_id,
                        "kb_name": "测试知识库",
                        "description": "P2c 测试用",
                        "created_at": "2026-08-07",
                    }
                return None
            mgr.get_knowledge_base = MagicMock(side_effect=mock_get_kb)
            mgr.get_knowledge_bases = MagicMock(return_value=[{
                "kb_id": kb_id,
                "kb_name": "测试知识库",
                "description": "P2c 测试用",
                "created_at": "2026-08-07",
            }])

            # 2. 测试 update_entry
            ok = mgr.update_entry(entry_id, {
                "title": "新标题",
                "content": "新内容",
                "tags": ["新标签1", "新标签2"],
            })
            assert ok, "update_entry 应返回 True"
            print(f"[OK] update_entry 成功")

            # 验证文件已更新
            with open(entry_path, "r", encoding="utf-8") as f:
                updated_md = f.read()
            assert "新标题" in updated_md, "更新后文件应含新标题"
            assert "新内容" in updated_md, "更新后文件应含新内容"
            assert "新标签1" in updated_md, "更新后文件应含新标签"
            print(f"[OK] 文件已更新: 含新标题/新内容/新标签")

            # 验证 ChromaDB update_chunks 被调用
            assert mgr._chromadb.update_chunks.called, "update_entry 应调用 chromadb.update_chunks"
            call_args = mgr._chromadb.update_chunks.call_args
            assert call_args[0][0] == kb_id, "update_chunks 应传入正确的 kb_id"
            print(f"[OK] ChromaDB.update_chunks 已被调用 (kb_id={kb_id})")

            # 3. 测试 update_entry 不存在的 entry
            ok = mgr.update_entry("nonexistent_id", {"title": "x"})
            assert not ok, "更新不存在的 entry 应返回 False"
            print(f"[OK] 更新不存在的 entry 返回 False")

            # 4. 测试 export_knowledge_base（指定 kb_id）
            export_path = os.path.join(tmp_dir, "export_test.md")
            result = mgr.export_knowledge_base(kb_id=kb_id, output_path=export_path)
            assert result == export_path, "export 应返回输出路径"
            assert os.path.exists(export_path), "导出文件应存在"
            with open(export_path, "r", encoding="utf-8") as f:
                export_content = f.read()
            assert "知识库导出" in export_content, "导出内容应含标题"
            assert "测试知识库" in export_content, "导出内容应含知识库名"
            assert "新标题" in export_content, "导出内容应含条目标题（更新后的）"
            print(f"[OK] export_knowledge_base(kb_id) 成功: {export_path}")

            # 5. 测试 export_knowledge_base（导出所有，不指定 kb_id）
            export_path_all = os.path.join(tmp_dir, "export_all.md")
            result = mgr.export_knowledge_base(output_path=export_path_all)
            assert result == export_path_all
            with open(export_path_all, "r", encoding="utf-8") as f:
                export_all_content = f.read()
            assert "知识库数量: 1" in export_all_content, "导出所有应含知识库数量"
            print(f"[OK] export_knowledge_base(所有) 成功: {export_path_all}")

            # 6. 测试 export 不存在的 kb_id
            result = mgr.export_knowledge_base(kb_id="nonexistent_kb")
            assert result is None, "导出不存在的 kb_id 应返回 None"
            print(f"[OK] 导出不存在的 kb_id 返回 None")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[P2c] PASS\n")
    return 0


def test_p2d_main_window_bridges():
    """P2d: MainWindow 信号桥接层验证"""
    print("=" * 60)
    print("[P2d] MainWindow 信号桥接层验证")
    print("=" * 60)

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from aibridge.ui.main_window import MainWindow

    # Mock AppEngine
    mock_engine = MagicMock()
    mock_engine.is_initialized.return_value = True
    mock_engine.update_knowledge_entry.return_value = True
    mock_engine.export_knowledge_base.return_value = "/tmp/fake_export.md"
    mock_engine.toggle_schedule_task.return_value = True
    mock_engine.add_schedule_task.return_value = "sched_new_001"
    mock_engine.get_schedule_tasks.return_value = []  # 空列表，不触发 UI 注入
    # SettingsPage 初始化时会调 get_current_settings_dict，MagicMock 自动属性会返回 MagicMock 导致 setText 崩溃
    mock_engine.get_current_settings_dict.return_value = {}
    # ChatPage/WorkspacePage 初始化时可能调 get_current_persona_dict / get_channel_messages
    mock_engine.get_current_persona_dict.return_value = {}
    mock_engine.get_channel_messages.return_value = []
    mock_engine.get_workspace_stats.return_value = {}
    mock_engine.get_bad_cases.return_value = []
    mock_engine.get_messages.return_value = []
    mock_engine.get_degraded_details.return_value = []
    mock_engine.register_persona_changed_callback.return_value = None

    # 验证槽函数存在
    for slot in [
        "_on_knowledge_entry_saved",
        "_on_knowledge_export",
        "_on_knowledge_export_done",
        "_on_workspace_schedule_toggled",
        "_on_workspace_new_schedule",
        "_refresh_workspace_schedules",
        "_expr_to_desc",
    ]:
        assert hasattr(MainWindow, slot), f"MainWindow 应有槽函数 {slot}"
        assert callable(getattr(MainWindow, slot)), f"{slot} 应可调用"
    print("[OK] 7 个新槽函数全部存在")

    # 验证 _build_page 中信号连接（通过 inspect 源码）
    import inspect
    build_source = inspect.getsource(MainWindow._build_page)
    assert "entry_saved.connect(self._on_knowledge_entry_saved)" in build_source, \
        "_build_page 应连接 entry_saved → _on_knowledge_entry_saved"
    assert "export_requested.connect(self._on_knowledge_export)" in build_source, \
        "_build_page 应连接 export_requested → _on_knowledge_export"
    assert "schedule_toggled.connect(self._on_workspace_schedule_toggled)" in build_source, \
        "_build_page 应连接 schedule_toggled → _on_workspace_schedule_toggled"
    assert "new_schedule_requested.connect(self._on_workspace_new_schedule)" in build_source, \
        "_build_page 应连接 new_schedule_requested → _on_workspace_new_schedule"
    print("[OK] _build_page 源码包含 4 个新信号连接")

    # 实例化 MainWindow 并触发 entry_saved 信号
    mw = MainWindow(mock_engine)

    # 触发 entry_saved
    mw._on_knowledge_entry_saved("entry_001", {"title": "测试标题"})
    assert mock_engine.update_knowledge_entry.called, "entry_saved 应调用 update_knowledge_entry"
    call_args = mock_engine.update_knowledge_entry.call_args
    assert call_args[0][0] == "entry_001", "应传入正确的 entry_id"
    assert call_args[0][1] == {"title": "测试标题"}, "应传入正确的 fields"
    print(f"[OK] entry_saved → update_knowledge_entry(entry_001, {{title:...}})")

    # 触发 schedule_toggled
    mock_engine.toggle_schedule_task.reset_mock()
    mw._on_workspace_schedule_toggled("task_001", False)
    assert mock_engine.toggle_schedule_task.called, "schedule_toggled 应调用 toggle_schedule_task"
    call_args = mock_engine.toggle_schedule_task.call_args
    assert call_args[0][0] == "task_001"
    assert call_args[0][1] is False
    print(f"[OK] schedule_toggled → toggle_schedule_task(task_001, False)")

    # 验证 _expr_to_desc 静态方法
    assert mw._expr_to_desc("daily:08:00") == "每天 08:00"
    assert mw._expr_to_desc("weekly:4:10:00") == "每周五 10:00"
    assert mw._expr_to_desc("interval:30") == "每 30 分钟"
    assert mw._expr_to_desc("invalid") == "invalid"
    print(f"[OK] _expr_to_desc: daily/weekly/interval/invalid 全部正确")

    # 验证 ExportKbWorker 存在
    from aibridge.ui.worker_threads import ExportKbWorker
    assert hasattr(ExportKbWorker, "finished") and hasattr(ExportKbWorker, "failed"), \
        "ExportKbWorker 应有 finished/failed 信号"
    print(f"[OK] ExportKbWorker 已定义，含 finished/failed 信号")

    print("[P2d] PASS\n")
    return 0


def main() -> int:
    results = []
    results.append(test_p2a_schedule_manager())
    results.append(test_p2b_appengine_interfaces())
    results.append(test_p2c_knowledge_manager())
    results.append(test_p2d_main_window_bridges())

    print("=" * 60)
    print(f"批次3-P2 验证结果: {'全部 PASS' if all(r == 0 for r in results) else '有失败项'}")
    print(f"  P2a ScheduleManager: {'PASS' if results[0] == 0 else 'FAIL'}")
    print(f"  P2b AppEngine 接口:  {'PASS' if results[1] == 0 else 'FAIL'}")
    print(f"  P2c KB update/export: {'PASS' if results[2] == 0 else 'FAIL'}")
    print(f"  P2d MainWindow 桥接:  {'PASS' if results[3] == 0 else 'FAIL'}")
    print("=" * 60)

    return 0 if all(r == 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
