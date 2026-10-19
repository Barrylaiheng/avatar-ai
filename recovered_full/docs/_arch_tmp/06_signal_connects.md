# pyqtSignal connect 列表（接收点）

共 150 项。

| 文件 | 对象表达式 | 信号名 | 行号 | 上下文代码（截断） |
|---|---|---|---|---|
| aibridge\ui\activation_dialog.py | close_btn | clicked | 169 | close_btn.clicked.connect(self._on_close) |
| aibridge\ui\activation_dialog.py | _pay_wechat | clicked | 313 | self._pay_wechat.clicked.connect(lambda: self._on_pay_tab("wechat")) |
| aibridge\ui\activation_dialog.py | _pay_alipay | clicked | 320 | self._pay_alipay.clicked.connect(lambda: self._on_pay_tab("alipay")) |
| aibridge\ui\activation_dialog.py | _verify_btn | clicked | 350 | self._verify_btn.clicked.connect(self._on_verify) |
| aibridge\ui\activation_dialog.py | link | clicked | 420 | link.clicked.connect(self._on_discuss) |
| aibridge\ui\agent_panel.py | input_field | returnPressed | 136 | self.input_field.returnPressed.connect(self._on_send) |
| aibridge\ui\agent_panel.py | send_btn | clicked | 148 | self.send_btn.clicked.connect(self._on_send) |
| aibridge\ui\chat_page.py | _build_panel | step_clicked | 1050 | self._build_panel.step_clicked.connect(self.step_clicked.emit) |
| aibridge\ui\chat_page.py | _build_panel | card_clicked | 1051 | self._build_panel.card_clicked.connect(self.card_clicked.emit) |
| aibridge\ui\chat_page.py | _dash_panel | goto_workspace | 1052 | self._dash_panel.goto_workspace.connect(self.goto_workspace.emit) |
| aibridge\ui\chat_page.py | _api_alert | goto_settings | 1154 | self._api_alert.goto_settings.connect(self.goto_settings_requested.emit) |
| aibridge\ui\chat_page.py | _right_panel | step_clicked | 1179 | self._right_panel.step_clicked.connect(self._on_step_clicked) |
| aibridge\ui\chat_page.py | _right_panel | card_clicked | 1180 | self._right_panel.card_clicked.connect(self.goto_knowledge_requested.emit) |
| aibridge\ui\chat_page.py | _right_panel | goto_workspace | 1181 | self._right_panel.goto_workspace.connect(self.goto_workspace_requested.emit) |
| aibridge\ui\chat_page.py | send_btn | clicked | 1321 | send_btn.clicked.connect(self._on_send_click) |
| aibridge\ui\chat_page.py | btns | accepted | 1600 | btns.accepted.connect(self.accept) |
| aibridge\ui\chat_page.py | btns | rejected | 1601 | btns.rejected.connect(self.reject) |
| aibridge\ui\components\empty_state.py | empty | action_clicked | 12 | empty.action_clicked.connect(on_create) |
| aibridge\ui\components\empty_state.py | _action_btn | clicked | 115 | self._action_btn.clicked.connect(self.action_clicked.emit) |
| aibridge\ui\components\llm_selector.py | _test_btn | clicked | 131 | self._test_btn.clicked.connect(self._on_test) |
| aibridge\ui\components\llm_selector.py | _save_btn | clicked | 132 | self._save_btn.clicked.connect(self._on_save) |
| aibridge\ui\components\llm_selector.py | btn | clicked | 183 | btn.clicked.connect(lambda _=False, k=key: self.set_provider(k)) |
| aibridge\ui\components\loading_indicator.py | _timer | timeout | 33 | self._timer.timeout.connect(self._tick) |
| aibridge\ui\components\progress_steps.py | steps | jump_requested | 11 | steps.jump_requested.connect(slot)  # 点击某步骤发出信号 |
| aibridge\ui\components\toast.py | _anim_out | finished | 119 | self._anim_out.finished.connect(self._on_anim_out_finished) |
| aibridge\ui\components\toast.py | toast | closed | 213 | toast.closed.connect(lambda: self._on_closed(toast)) |
| aibridge\ui\components\toggle_switch.py | switch | toggled | 7 | switch.toggled.connect(slot) |
| aibridge\ui\components\toggle_switch.py | self | toggled | 44 | self.toggled.connect(self._on_toggled_anim) |
| aibridge\ui\dashboard.py | btn | clicked | 98 | btn.clicked.connect(self.startWizard.emit) |
| aibridge\ui\dashboard.py | continue_btn | clicked | 188 | continue_btn.clicked.connect(self.startWizard.emit) |
| aibridge\ui\graph_view.py | _force_timer | timeout | 202 | self._force_timer.timeout.connect(self._step_force) |
| aibridge\ui\graph_view.py | _scene | nodeClicked | 363 | self._scene.nodeClicked.connect(self.nodeClicked.emit) |
| aibridge\ui\graph_view.py | _scene | nodeDoubleClicked | 364 | self._scene.nodeDoubleClicked.connect(self.nodeDoubleClicked.emit) |
| aibridge\ui\iteration_page.py | _opt_btn | clicked | 223 | self._opt_btn.clicked.connect(self._on_optimize) |
| aibridge\ui\iteration_page.py | _discuss_btn | clicked | 231 | self._discuss_btn.clicked.connect(self._on_discuss) |
| aibridge\ui\iteration_page.py | _filter_combo | currentTextChanged | 537 | self._filter_combo.currentTextChanged.connect(self._on_filter_changed) |
| aibridge\ui\iteration_page.py | item | optimize_requested | 579 | item.optimize_requested.connect(self.optimize_requested.emit) |
| aibridge\ui\iteration_page.py | item | discuss_requested | 580 | item.discuss_requested.connect(self.discuss_requested.emit) |
| aibridge\ui\knowledge_page.py | save_btn | clicked | 356 | save_btn.clicked.connect(self._on_save) |
| aibridge\ui\knowledge_page.py | discuss_btn | clicked | 362 | discuss_btn.clicked.connect(self._on_discuss) |
| aibridge\ui\knowledge_page.py | _btn_list | clicked | 790 | self._btn_list.clicked.connect(lambda: self._switch_view("list")) |
| aibridge\ui\knowledge_page.py | _btn_graph | clicked | 791 | self._btn_graph.clicked.connect(lambda: self._switch_view("graph")) |
| aibridge\ui\knowledge_page.py | export_btn | clicked | 813 | export_btn.clicked.connect(self._on_export) |
| aibridge\ui\knowledge_page.py | section | start_stage_requested | 854 | section.start_stage_requested.connect(self.start_stage_requested.emit) |
| aibridge\ui\knowledge_page.py | card | save_requested | 857 | card.save_requested.connect(self.entry_saved.emit) |
| aibridge\ui\knowledge_page.py | card | discuss_requested | 858 | card.discuss_requested.connect(self.discuss_requested.emit) |
| aibridge\ui\linear_wizard.py | _test_btn | clicked | 343 | self._test_btn.clicked.connect(self._test_connection) |
| aibridge\ui\linear_wizard.py | model_input | textChanged | 509 | model_input.textChanged.connect(self._on_input_changed) |
| aibridge\ui\linear_wizard.py | base_url_input | textChanged | 517 | base_url_input.textChanged.connect(self._on_input_changed) |
| aibridge\ui\linear_wizard.py | model_combo | currentTextChanged | 539 | model_combo.currentTextChanged.connect(self._on_input_changed) |
| aibridge\ui\linear_wizard.py | custom_model_input | textChanged | 548 | custom_model_input.textChanged.connect(self._on_input_changed) |
| aibridge\ui\linear_wizard.py | model_combo | currentTextChanged | 551 | model_combo.currentTextChanged.connect( |
| aibridge\ui\linear_wizard.py | advanced_btn | clicked | 601 | advanced_btn.clicked.connect( |
| aibridge\ui\linear_wizard.py | api_key_input | textChanged | 651 | api_key_input.textChanged.connect(self._on_input_changed) |
| aibridge\ui\linear_wizard.py | toggle_btn | clicked | 673 | toggle_btn.clicked.connect( |
| aibridge\ui\linear_wizard.py | _template_list | itemClicked | 1029 | self._template_list.itemClicked.connect(self._on_template_selected) |
| aibridge\ui\linear_wizard.py | file_btn | clicked | 1198 | file_btn.clicked.connect(self._choose_files) |
| aibridge\ui\linear_wizard.py | folder_btn | clicked | 1224 | folder_btn.clicked.connect(self._choose_folder) |
| aibridge\ui\linear_wizard.py | _distill_btn | clicked | 1306 | self._distill_btn.clicked.connect(self._start_distill) |
| aibridge\ui\linear_wizard.py | view_graph_btn | clicked | 1390 | view_graph_btn.clicked.connect(self._view_knowledge_graph) |
| aibridge\ui\linear_wizard.py | _recheck_btn | clicked | 1527 | self._recheck_btn.clicked.connect(self._recheck_environment) |
| aibridge\ui\linear_wizard.py | _test_wcf_btn | clicked | 1727 | self._test_wcf_btn.clicked.connect(self._test_wcf_connection) |
| aibridge\ui\linear_wizard.py | _whitelist_toggle | toggled | 1894 | self._whitelist_toggle.toggled.connect(self._on_whitelist_toggled) |
| aibridge\ui\linear_wizard.py | add_btn | clicked | 1963 | add_btn.clicked.connect(self._add_whitelist) |
| aibridge\ui\linear_wizard.py | add_btn | clicked | 2015 | add_btn.clicked.connect(self._add_group_config) |
| aibridge\ui\linear_wizard.py | add_btn | clicked | 2067 | add_btn.clicked.connect(self._add_schedule) |
| aibridge\ui\linear_wizard.py | _auto_reply_toggle | toggled | 2084 | self._auto_reply_toggle.toggled.connect(self._on_auto_reply_toggled) |
| aibridge\ui\linear_wizard.py | _delay_spin | valueChanged | 2129 | self._delay_spin.valueChanged.connect(self._on_delay_changed) |
| aibridge\ui\linear_wizard.py | _at_reply_toggle | toggled | 2146 | self._at_reply_toggle.toggled.connect(self._on_at_reply_toggled) |
| aibridge\ui\linear_wizard.py | launch_btn | clicked | 2318 | launch_btn.clicked.connect(self._on_launch_clicked) |
| aibridge\ui\linear_wizard.py | dashboard_btn | clicked | 2348 | dashboard_btn.clicked.connect(self._on_dashboard_clicked) |
| aibridge\ui\linear_wizard.py | knowledge_btn | clicked | 2374 | knowledge_btn.clicked.connect(self._on_knowledge_clicked) |
| aibridge\ui\linear_wizard.py | chat_btn | clicked | 2400 | chat_btn.clicked.connect(self._on_chat_clicked) |
| aibridge\ui\linear_wizard.py | step6 | openDashboard | 2486 | step6.openDashboard.connect(self._on_open_dashboard) |
| aibridge\ui\linear_wizard.py | step6 | openKnowledge | 2487 | step6.openKnowledge.connect(self._on_open_knowledge) |
| aibridge\ui\linear_wizard.py | step6 | startChat | 2488 | step6.startChat.connect(self._on_start_chat) |
| aibridge\ui\linear_wizard.py | step6 | launchBot | 2489 | step6.launchBot.connect(self._on_launch_bot) |
| aibridge\ui\linear_wizard.py | step3 | openKnowledgeGraph | 2494 | step3.openKnowledgeGraph.connect(self._on_open_knowledge) |
| aibridge\ui\linear_wizard.py | _back_btn | clicked | 2545 | self._back_btn.clicked.connect(self._on_back_clicked) |
| aibridge\ui\linear_wizard.py | _skip_btn | clicked | 2581 | self._skip_btn.clicked.connect(self._on_skip_clicked) |
| aibridge\ui\linear_wizard.py | _prev_btn | clicked | 2656 | self._prev_btn.clicked.connect(self._on_prev_clicked) |
| aibridge\ui\linear_wizard.py | _next_btn | clicked | 2690 | self._next_btn.clicked.connect(self._on_next_clicked) |
| aibridge\ui\main_window.py | sidebar | page_changed | 156 | self.sidebar.page_changed.connect(self._switch_page) |
| aibridge\ui\main_window.py | sidebar | theme_toggled | 157 | self.sidebar.theme_toggled.connect(self._on_theme_toggled) |
| aibridge\ui\main_window.py | page | message_sent | 196 | page.message_sent.connect(self._on_chat_message_sent) |
| aibridge\ui\main_window.py | page | kb_toggled | 197 | page.kb_toggled.connect(self._on_chat_kb_toggled) |
| aibridge\ui\main_window.py | page | llm_saved | 198 | page.llm_saved.connect(self._on_chat_llm_saved) |
| aibridge\ui\main_window.py | page | settingsSaved | 212 | page.settingsSaved.connect(self._on_settings_saved) |
| aibridge\ui\main_window.py | page | llm_saved | 214 | page.llm_saved.connect(self._on_settings_llm_saved) |
| aibridge\ui\main_window.py | page | wcf_test_requested | 215 | page.wcf_test_requested.connect(self._on_settings_wcf_test) |
| aibridge\ui\main_window.py | page | discuss_requested | 226 | page.discuss_requested.connect(self._on_knowledge_discuss) |
| aibridge\ui\main_window.py | page | entry_saved | 228 | page.entry_saved.connect(self._on_knowledge_entry_saved) |
| aibridge\ui\main_window.py | page | export_requested | 229 | page.export_requested.connect(self._on_knowledge_export) |
| aibridge\ui\main_window.py | page | channel_changed | 241 | page.channel_changed.connect(self._on_workspace_channel_changed) |
| aibridge\ui\main_window.py | page | search_changed | 242 | page.search_changed.connect(self._on_workspace_search_changed) |
| aibridge\ui\main_window.py | page | status_filter_changed | 243 | page.status_filter_changed.connect(self._on_workspace_status_filter) |
| aibridge\ui\main_window.py | page | schedule_toggled | 245 | page.schedule_toggled.connect(self._on_workspace_schedule_toggled) |
| aibridge\ui\main_window.py | page | new_schedule_requested | 246 | page.new_schedule_requested.connect(self._on_workspace_new_schedule) |
| aibridge\ui\main_window.py | page | optimize_requested | 258 | page.optimize_requested.connect(self._on_iteration_optimize) |
| aibridge\ui\main_window.py | page | discuss_requested | 259 | page.discuss_requested.connect(self._on_iteration_discuss) |
| aibridge\ui\main_window.py | worker | finished | 278 | worker.finished.connect(lambda sid, result: self._on_chat_reply_ready(sid, result)) |
| aibridge\ui\main_window.py | worker | failed | 279 | worker.failed.connect(lambda sid, err: self._on_chat_reply_failed(sid, err)) |
| aibridge\ui\main_window.py | worker | finished | 334 | worker.finished.connect(self._on_wcf_test_done) |
| aibridge\ui\main_window.py | worker | finished | 410 | worker.finished.connect(self._on_knowledge_export_done) |
| aibridge\ui\main_window.py | worker | failed | 411 | worker.failed.connect(lambda err: self._toast_error(f"导出失败: {err}")) |
| aibridge\ui\main_window.py | worker | finished | 436 | worker.finished.connect(self._on_iteration_optimize_done) |
| aibridge\ui\persona_editor.py | _text_edit | textChanged | 164 | self._text_edit.textChanged.connect(self._on_text_changed) |
| aibridge\ui\persona_editor.py | _max_chars_spin | valueChanged | 211 | self._max_chars_spin.valueChanged.connect(self._emit_changed) |
| aibridge\ui\persona_editor.py | _force_question_check | stateChanged | 219 | self._force_question_check.stateChanged.connect(self._emit_changed) |
| aibridge\ui\persona_editor.py | _max_steps_spin | valueChanged | 229 | self._max_steps_spin.valueChanged.connect(self._emit_changed) |
| aibridge\ui\persona_editor.py | _term_explain_check | stateChanged | 238 | self._term_explain_check.stateChanged.connect(self._emit_changed) |
| aibridge\ui\persona_editor.py | _persona_list | currentItemChanged | 362 | self._persona_list.currentItemChanged.connect(self._on_persona_selected) |
| aibridge\ui\persona_editor.py | _new_btn | clicked | 379 | self._new_btn.clicked.connect(self._on_new_persona) |
| aibridge\ui\persona_editor.py | _delete_btn | clicked | 394 | self._delete_btn.clicked.connect(self._on_delete_persona) |
| aibridge\ui\persona_editor.py | _hard_rules_widget | rules_changed | 470 | self._hard_rules_widget.rules_changed.connect(self._on_hard_rules_changed) |
| aibridge\ui\persona_editor.py | template_btn | clicked | 488 | template_btn.clicked.connect(self._on_load_template) |
| aibridge\ui\persona_editor.py | preview_btn | clicked | 512 | preview_btn.clicked.connect(self._on_preview) |
| aibridge\ui\persona_editor.py | save_btn | clicked | 531 | save_btn.clicked.connect(self._on_save) |
| aibridge\ui\persona_editor.py | apply_btn | clicked | 548 | apply_btn.clicked.connect(self._on_apply) |
| aibridge\ui\settings_page.py | _btn_wechat | clicked | 573 | self._btn_wechat.clicked.connect(lambda: self._on_version_clicked("wechat")) |
| aibridge\ui\settings_page.py | _btn_oa | clicked | 574 | self._btn_oa.clicked.connect(lambda: self._on_version_clicked("oa")) |
| aibridge\ui\settings_page.py | c | clicked | 696 | c.clicked.connect(lambda n=name: self._on_theme_card_clicked(n)) |
| aibridge\ui\settings_page.py | _llm_eye | clicked | 850 | self._llm_eye.clicked.connect(self._toggle_apikey_visible) |
| aibridge\ui\settings_page.py | _llm_save_btn | clicked | 873 | self._llm_save_btn.clicked.connect(self._on_llm_saved) |
| aibridge\ui\settings_page_v2.py | _ver_wechat | clicked | 394 | self._ver_wechat.clicked.connect(lambda: self._switch_version("wechat")) |
| aibridge\ui\settings_page_v2.py | _ver_oa | clicked | 395 | self._ver_oa.clicked.connect(lambda: self._switch_version("oa")) |
| aibridge\ui\settings_page_v2.py | _tc_light | clicked | 439 | self._tc_light.clicked.connect(self._on_theme_card_click) |
| aibridge\ui\settings_page_v2.py | _tc_dark | clicked | 440 | self._tc_dark.clicked.connect(self._on_theme_card_click) |
| aibridge\ui\settings_page_v2.py | activate_btn | clicked | 525 | activate_btn.clicked.connect(self._on_activate_clicked) |
| aibridge\ui\settings_page_v2.py | _apikey_eye | clicked | 573 | self._apikey_eye.clicked.connect(self._toggle_apikey_visibility) |
| aibridge\ui\settings_page_v2.py | save_btn | clicked | 599 | save_btn.clicked.connect(self._on_save_llm) |
| aibridge\ui\settings_page_v2.py | test_btn | clicked | 678 | test_btn.clicked.connect(self.oa_test_requested.emit) |
| aibridge\ui\sidebar.py | _collapse_timer | timeout | 345 | self._collapse_timer.timeout.connect(self.collapse) |
| aibridge\ui\sidebar.py | _anim | valueChanged | 352 | self._anim.valueChanged.connect(self._on_anim_value_changed) |
| aibridge\ui\sidebar.py | item | clicked | 387 | item.clicked.connect(self._on_nav_clicked) |
| aibridge\ui\sidebar.py | item | clicked | 418 | item.clicked.connect(self._on_nav_clicked) |
| aibridge\ui\sidebar.py | f | clicked | 509 | f.clicked.connect(lambda _pid: self._toggle_theme()) |
| aibridge\ui\task_checklist.py | _checkbox | toggled | 73 | self._checkbox.toggled.connect(self._on_toggled) |
| aibridge\ui\task_checklist.py | _verify_btn | clicked | 275 | self._verify_btn.clicked.connect(self._on_verify) |
| aibridge\ui\task_checklist.py | _checkbox | toggled | 292 | item._checkbox.toggled.connect(self._update_progress) |
| aibridge\ui\worker_threads.py | worker | finished | 10 | worker.finished.connect(callback)   # callback(session_id, result_dict) |
| aibridge\ui\worker_threads.py | worker | failed | 11 | worker.failed.connect(callback)     # callback(session_id, error_str) |
| aibridge\ui\workspace_page.py | toggle | toggled | 339 | toggle.toggled.connect(lambda on: self.toggled.emit(task.id, on)) |
| aibridge\ui\workspace_page.py | _tab_wechat | clicked | 454 | self._tab_wechat.clicked.connect(self._switch_channel) |
| aibridge\ui\workspace_page.py | _tab_oa | clicked | 455 | self._tab_oa.clicked.connect(self._switch_channel) |
| aibridge\ui\workspace_page.py | _search_box | textChanged | 532 | self._search_box.textChanged.connect(self._on_search_changed) |
| aibridge\ui\workspace_page.py | chip | clicked | 542 | chip.clicked.connect(lambda _, k=key: self._on_type_filter(k)) |
| aibridge\ui\workspace_page.py | _status_combo | currentTextChanged | 573 | self._status_combo.currentTextChanged.connect(self._on_status_filter) |
| aibridge\ui\workspace_page.py | new_btn | clicked | 654 | new_btn.clicked.connect(self.new_schedule_requested.emit) |
| aibridge\ui\workspace_page.py | item | toggled | 711 | item.toggled.connect(self._on_schedule_toggled) |