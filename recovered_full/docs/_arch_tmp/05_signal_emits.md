# pyqtSignal emit 列表（发送点）

共 80 项。

| 文件 | 信号名 | 行号 | 上下文代码（截断） |
|---|---|---|---|
| aibridge\ui\activation_dialog.py | verify_requested | 464 | self.verify_requested.emit() |
| aibridge\ui\activation_dialog.py | pay_method_changed | 472 | self.pay_method_changed.emit(method) |
| aibridge\ui\activation_dialog.py | discuss_requested | 477 | self.discuss_requested.emit() |
| aibridge\ui\activation_dialog.py | opened | 483 | self.opened.emit() |
| aibridge\ui\activation_dialog.py | closed | 490 | self.closed.emit() |
| aibridge\ui\activation_dialog.py | activated | 517 | self.activated.emit() |
| aibridge\ui\activation_dialog.py | activation_failed | 522 | self.activation_failed.emit(msg) |
| aibridge\ui\chat_page.py | goto_settings | 219 | link.mousePressEvent = lambda _ev: self.goto_settings.emit() |
| aibridge\ui\chat_page.py | step_clicked | 510 | f.mousePressEvent = lambda _ev, i=idx, p=prompt: self.step_clicked.emit(i, p) |
| aibridge\ui\chat_page.py | card_clicked | 775 | f.mousePressEvent = lambda _ev, iid=item_id: self.card_clicked.emit(iid) |
| aibridge\ui\chat_page.py | goto_workspace | 893 | f.mousePressEvent = lambda _ev: self.goto_workspace.emit("channels") |
| aibridge\ui\chat_page.py | goto_workspace | 953 | f.mousePressEvent = lambda _ev, s=section: self.goto_workspace.emit(s) |
| aibridge\ui\chat_page.py | session_created | 1380 | self.session_created.emit(sid)  # 兼容信号 |
| aibridge\ui\chat_page.py | session_selected | 1388 | self.session_selected.emit(sid)  # 兼容信号 |
| aibridge\ui\chat_page.py | message_sent | 1457 | self.message_sent.emit(self._active_session_id, text) |
| aibridge\ui\chat_page.py | llm_saved | 1518 | self.llm_saved.emit(cfg) |
| aibridge\ui\components\llm_selector.py | provider_changed | 343 | self.provider_changed.emit(provider) |
| aibridge\ui\components\llm_selector.py | test_requested | 376 | self.test_requested.emit(self.current_config()) |
| aibridge\ui\components\llm_selector.py | saved | 379 | self.saved.emit(self.current_config()) |
| aibridge\ui\components\progress_steps.py | jump_requested | 118 | self.jump_requested.emit(self._hover_idx) |
| aibridge\ui\components\toast.py | closed | 177 | self.closed.emit() |
| aibridge\ui\components\toggle_switch.py | toggled | 64 | self.toggled.emit(v) |
| aibridge\ui\graph_view.py | nodeDoubleClicked | 141 | scene.nodeDoubleClicked.emit(self._data.entry_id) |
| aibridge\ui\graph_view.py | nodeClicked | 147 | scene.nodeClicked.emit(self._data.entry_id) |
| aibridge\ui\iteration_page.py | optimize_requested | 320 | self.optimize_requested.emit(self.bc.id) |
| aibridge\ui\iteration_page.py | discuss_requested | 338 | self.discuss_requested.emit(self.bc.id, prompt) |
| aibridge\ui\iteration_page.py | filter_changed | 587 | self.filter_changed.emit(label) |
| aibridge\ui\knowledge_page.py | expanded_changed | 418 | self.expanded_changed.emit(self.entry.id, expanded) |
| aibridge\ui\knowledge_page.py | save_requested | 447 | self.save_requested.emit(self.entry.id, new_values) |
| aibridge\ui\knowledge_page.py | discuss_requested | 452 | self.discuss_requested.emit(self.entry.id, prompt) |
| aibridge\ui\knowledge_page.py | start_stage_requested | 586 | link.mousePressEvent = lambda ev: (self.start_stage_requested.emit(self.stage.stage_idx))  # noqa: E731 |
| aibridge\ui\knowledge_page.py | view_changed | 871 | self.view_changed.emit(view) |
| aibridge\ui\knowledge_page.py | export_requested | 876 | self.export_requested.emit() |
| aibridge\ui\linear_wizard.py | stepValidated | 125 | self.stepValidated.emit(valid) |
| aibridge\ui\linear_wizard.py | openKnowledgeGraph | 1449 | self.openKnowledgeGraph.emit() |
| aibridge\ui\linear_wizard.py | launchBot | 2406 | self.launchBot.emit() |
| aibridge\ui\linear_wizard.py | openDashboard | 2409 | self.openDashboard.emit() |
| aibridge\ui\linear_wizard.py | openKnowledge | 2412 | self.openKnowledge.emit() |
| aibridge\ui\linear_wizard.py | startChat | 2415 | self.startChat.emit() |
| aibridge\ui\linear_wizard.py | goBack | 2740 | self.goBack.emit() |
| aibridge\ui\linear_wizard.py | stepCompleted | 2756 | self.stepCompleted.emit(self._current_step) |
| aibridge\ui\linear_wizard.py | allCompleted | 2761 | self.allCompleted.emit() |
| aibridge\ui\linear_wizard.py | launchBot | 2762 | self.launchBot.emit() |
| aibridge\ui\linear_wizard.py | startChat | 2765 | self.startChat.emit() |
| aibridge\ui\linear_wizard.py | openKnowledge | 2768 | self.openKnowledge.emit() |
| aibridge\ui\linear_wizard.py | launchBot | 2774 | self.launchBot.emit() |
| aibridge\ui\persona_editor.py | content_changed | 170 | self.content_changed.emit(self._section_name, text) |
| aibridge\ui\persona_editor.py | rules_changed | 244 | self.rules_changed.emit(self.get_config()) |
| aibridge\ui\persona_editor.py | persona_applied | 665 | self.persona_applied.emit(self._current_persona.persona_id) |
| aibridge\ui\settings_page.py | clicked | 252 | self.clicked.emit() |
| aibridge\ui\settings_page.py | version_changed | 674 | self.version_changed.emit(v) |
| aibridge\ui\settings_page.py | theme_changed | 717 | self.theme_changed.emit(name) |
| aibridge\ui\settings_page.py | llm_saved | 898 | self.llm_saved.emit(cfg) |
| aibridge\ui\settings_page_v2.py | clicked | 216 | self.clicked.emit(self.theme_id) |
| aibridge\ui\settings_page_v2.py | version_changed | 423 | self.version_changed.emit(ver) |
| aibridge\ui\settings_page_v2.py | theme_changed | 455 | self.theme_changed.emit(theme_id) |
| aibridge\ui\settings_page_v2.py | llm_saved | 618 | self.llm_saved.emit(cfg) |
| aibridge\ui\settings_page_v2.py | settingsSaved | 619 | self.settingsSaved.emit() |
| aibridge\ui\sidebar.py | clicked | 288 | self.clicked.emit(self.page_id) |
| aibridge\ui\sidebar.py | page_changed | 627 | self.page_changed.emit(page_id) |
| aibridge\ui\sidebar.py | theme_toggled | 642 | self.theme_toggled.emit(new_theme) |
| aibridge\ui\task_checklist.py | verifyRequested | 340 | self.verifyRequested.emit(self._stage_id) |
| aibridge\ui\worker_threads.py | failed | 52 | self.failed.emit(self._session_id, str(result.get("error", "未知错误"))) |
| aibridge\ui\worker_threads.py | finished | 54 | self.finished.emit(self._session_id, result) |
| aibridge\ui\worker_threads.py | failed | 57 | self.failed.emit(self._session_id, str(e)) |
| aibridge\ui\worker_threads.py | finished | 80 | self.finished.emit(True, "WCF 连接成功") |
| aibridge\ui\worker_threads.py | finished | 82 | self.finished.emit(False, "WCF 连接失败，请检查 WCF 是否运行") |
| aibridge\ui\worker_threads.py | finished | 85 | self.finished.emit(False, str(e)) |
| aibridge\ui\worker_threads.py | finished | 105 | self.finished.emit(result) |
| aibridge\ui\worker_threads.py | finished | 108 | self.finished.emit({ |
| aibridge\ui\worker_threads.py | finished | 140 | self.finished.emit(file_path) |
| aibridge\ui\worker_threads.py | failed | 142 | self.failed.emit("导出失败：无文件生成（可能知识库为空）") |
| aibridge\ui\worker_threads.py | failed | 145 | self.failed.emit(str(e)) |
| aibridge\ui\workspace_page.py | clicked | 169 | self.clicked.emit(self.channel_id) |
| aibridge\ui\workspace_page.py | toggled | 339 | toggle.toggled.connect(lambda on: self.toggled.emit(task.id, on)) |
| aibridge\ui\workspace_page.py | channel_changed | 729 | self.channel_changed.emit(channel_id) |
| aibridge\ui\workspace_page.py | search_changed | 736 | self.search_changed.emit(self._search) |
| aibridge\ui\workspace_page.py | type_filter_changed | 742 | self.type_filter_changed.emit(key) |
| aibridge\ui\workspace_page.py | status_filter_changed | 746 | self.status_filter_changed.emit(label) |
| aibridge\ui\workspace_page.py | schedule_toggled | 753 | self.schedule_toggled.emit(task_id, enabled) |