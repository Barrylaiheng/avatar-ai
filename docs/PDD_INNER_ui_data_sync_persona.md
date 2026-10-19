# PDD 规格：模块 M12 · UI Data Sync（人设回显数据流）

> **PDD 阶段**：已闭环 ✓（Grill → Prototype → Spec → Tickets → Implement+TDD → Review）
> **所属层级**：里层（Engine ↔ UI 桥接数据流契约）
> **前置 PDD 模块**：M7（UI↔Engine 数据流契约）、M10（App Bootstrap Wiring 真实组件装配）、M11（Persona Injection Chain）
> **Grill 总数**：13 条 → **pytest 固化 22 条，全部 100% 通过**
> **原型通过率**：24/24 断言全部 PASS

---

## 1. Grill 清单（用户验收问题，大白话，可机器断言）

| Grill | 验收问题 | 对应 Test Seam |
|---|---|---|
| **H1** | AppEngine 提供 `get_current_persona_dict()` 接口，UI 层只读这个接口（不直接碰 ConfigManager 私有对象），返回 8 字段字典 | test_H1_8_fields_present |
| **H2** | 未自定义人设时，get_current_persona_dict() 返回合理默认值，不返回 None 或空字符串 | test_H2_default_name / default_type / default_tone / uninitialized_engine_still_returns_defaults |
| **H3** | ChatPage 顶栏标题从 Engine 读取，不再是写死字符串"AI 面试官 · 数字分身搭建引导"；格式为 `"{name} · {type}"` | test_H3_title_initial_format |
| **H4** | ChatPage 顶栏 subtitle 从 Engine 读取，description 为空时显示默认引导文案，不显示 None 或"当前阶段…"写死字符串 | test_H4_sub_initial_when_empty_description + H12 空值兜底 |
| **H5** | save_persona 成功后，**不切换页面不重启 App**，ChatPage 顶栏 title 和 subtitle **立刻刷新**为新人设值（热更新） | test_H5_chatpage_refreshes_immediately_via_callback |
| **H6** | AppEngine 暴露"人设保存成功"回调钩子 → 任何 UI 都能注册，不会出现"PersonaEditor 自己 toast 完了 ChatPage 蒙在鼓里" | test_H6_callback_fires_once_on_save / H6_callback_does_not_fire_when_no_fields_changed |
| **H7** | 连续两次 save_persona，回调触发顺序正确，ChatPage 最终显示**最后一次**保存的人设 | test_H7_final_value_after_saves |
| **H8** | 打开 PersonaEditor 且左侧列表**未选中**任何 persona 时，4 个输入框（name/description/tone/type）自动回显 ConfigManager 中激活人设的值（实际 setText 填充，不是 placeholder） | test_H8_4_fields_filled_without_selection |
| **H9** | PersonaEditor 打开时读的回显值 == Engine 当前激活人设 dict，两者完全一致，不出现"编辑器改 A，Engine 跑 B" | test_H9_echo_exactly_matches_engine_current |
| **H10** | **失败原子性**：save_persona 返回 False 时（Engine 未初始化），get_current_persona_dict() 仍返回旧值，不会被污染成半新半旧 | test_H10_save_returns_false_when_uninitialized |
| **H11** | 跨重启持久化：销毁旧 AppEngine → 新实例读同一个 SCAI_DATA_DIR → 4 核心字段（name/type/tone/description）与上次 save 完全一致 | test_H11_new_engine_reads_old_values |
| **H12** | 空值处理：description 空时显示默认引导文案；长 description（>40 字）省略号截断；长 tone 在 Workbench 卡截断；不出现 None 字面量；Whitespace-only 视为空 | test_H12_empty_description / H12_whitespace / H12_long_description / H12_long_tone |
| **H13** | Workbench 新增"当前人设"卡片组件（emoji 头像 + 名称 + type + tone），数据从 Engine 读；save_persona 后卡片**立即刷新** | test_H13_initial_values_from_engine / H13_card_hot_refresh / H13_avatar_only_first_glyph |

---

## 2. 探查结论（C-1 阶段的根因）

C-1 阶段探查 3 处 UI 文件（chat_page.py / workspace_page.py / persona_editor.py）后确认的**断点根因**：

### 2.1 ChatPage 顶栏（[chat_page.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/chat_page.py#L1229-L1269)）
- **R1.1**：`title = QLabel("AI 面试官 · 数字分身搭建引导")` / `sub = QLabel("当前阶段：知识萃取 → 人格塑造")` —— 两处都是**局部变量 + 写死字符串**，与 Engine 的 persona 配置无任何关联，也没保存为 self，无法被后续逻辑修改。
- **R1.2**：ChatPage init 末尾**没有注册人设变化回调**，即使 PersonaEditor 调用了 Bridge.save_persona，ChatPage 也完全收不到通知。

### 2.2 Workbench 工作台（[workspace_page.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/workspace_page.py#L344-L421)）
- **R2.1**：`_build_stats_row` 只放了 3 张 StatCard，**整个 UI 完全没有"当前人设"区块**，用户不知道当前生效的人设到底是什么。
- **R2.2**：init 末尾同样没有注册回调钩子。

### 2.3 PersonaEditor 人设编辑器（[persona_editor.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/persona_editor.py#L261-L290)）
- **R3.1**：人设信息 GroupBox 中只包含 name / description 两个 LineEdit，**缺少 tone / type 输入控件** → 用户在 PersonaEditor 里根本看不到 tone 和 type 两个字段，更别说修改了。
- **R3.2**：`_load_persona_to_ui()` 仅把 name/description 填回输入框，tone/type 字段完全丢失，旧版本 SevenSectionPersona 缺字段时也没兜底。
- **R3.3**：init 末尾 `_setup_ui(); _load_personas();` 之后**没有加载"Engine 当前激活人设"** → 如果用户之前在 PersonaEditor 之外 save 过人设（比如通过 Bridge 直接调 save_persona），打开编辑器会看到空白输入框，实际生效人设是另一套（H9 不一致风险）。
- **R3.4**：保存到 AppEngine 的 persona_dict 只传了 `name / persona_id + to_prompt()`，tone/type 没传 → save_persona 虽然有 persona.tone/persona.type 配置，但完全不会被 PersonaEditor 的保存按钮更新。

### 2.4 Engine 层 AppEngine（[app_engine.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py#L42-L504)）
- **R4.1**：**没有"UI 层读人设"的标准接口**，UI 只能各自去读 ConfigManager `_config.get("persona.xxx")` —— 导致 ChatPage 是写死字符串，PersonaEditor 是读 persona 表（读 DB，不读 Config），Workbench 没做，三处 UI 用了三个不同的数据源。
- **R4.2**：save_persona **没有跨模块通知机制**，PersonaEditor 自己调完 Bridge.save_persona 就 Toast 完了，但 ChatPage/Workbench 收不到任何通知，自然无法热更新。
- **R4.3**：save_persona 之前的"增量语义"其实是"有 key 就 set，不管新旧值是否相等"，导致用户点保存按钮却没有改任何字段时，也会触发 `save_config()` 磁盘 IO 和回调通知，性能差且 UI 会无意义刷新。

---

## 3. 修复方案（M12 13 Grill 对应技术决策）

### 3.1 Engine 层新增 4 个公开接口（对应 H1/H2/H6/H10）
在 `AppEngine` 中新增：
1. **`get_current_persona_dict() -> Dict[str, Any]`**（H1/H2）：**UI 层读人设唯一入口**，返回 8 字段字典，_config 为 None 时也能返回默认值（不崩 UI 启动期）。
2. **`register_persona_changed_callback(callback) -> bool`**（H6）：UI 注册人设变更钩子。
3. **`unregister_persona_changed_callback(callback) -> int`**（H6）：UI 页关闭/析构时注销，避免 Qt dangling pointer 警告。
4. **`save_persona()` 内部增加"新旧值 diff 比较"**（H6/H7）：`old_val == new_val` 时跳过 `_config.set()`，不标记 `changed_any`，减少无意义写盘 + 无意义回调。

### 3.2 ChatPage 顶栏修复（对应 H3/H4/H5/H12）
1. 将 `_build_chat_header` 内部的 title/sub 从局部变量改为 `self._header_title_label` / `self._header_sub_label`。
2. 初值改为"影分身 AI · AI 数字分身" + "默认人设，点击左侧 Persona 编辑器调整"，不再是阶段化写死字符串。
3. 新增 `refresh_persona_header(persona_dict=None)` 方法：若传了 persona_dict（回调钩子参数）就用，否则调 `_app_engine.get_current_persona_dict()`，然后按规则拼接 title/sub（>40 字省略号，≤3 字走默认文案）。
4. ChatPage init 末尾**立即调用** `refresh_persona_header()`，并注册 `_app_engine.register_persona_changed_callback(self.refresh_persona_header)`，实现热更新。

### 3.3 PersonaEditor 人设编辑器修复（对应 H8/H9 + tone/type 字段）
1. **人设信息 GroupBox 增加 tone / type 两个 QLineEdit**（`_tone_edit`、`_type_edit`）。
2. `_load_persona_to_ui(persona)` 增加 tone/type 回填，用 `getattr(persona, "tone", "")` 兼容旧版本 SevenSectionPersona dataclass 缺字段。
3. `_collect_persona_from_ui()` 增加把 `self._tone_edit.text()` / `self._type_edit.text()` 回写到 `self._current_persona.tone` / `.type`（同样用 hasattr 兼容）。
4. 保存按钮同步到 Engine 的 persona_dict 里追加 tone/type 两个 key。
5. 新增 `_fill_active_persona_from_engine_if_no_selection()`（H8/H9）：_load_personas() 后如果左侧列表为空或无选中项，就从 `_app_engine.get_current_persona_dict()` 回填 4 个核心字段，保证"打开编辑器就能看到当前生效人设"。
6. init 末尾追加 `self._fill_active_persona_from_engine_if_no_selection()`。

### 3.4 WorkspacePage 工作台修复（对应 H13）
1. 在 `_build_stats_row` 的 QGridLayout **row=1, span 3 列** 位置新增 `ws-current-persona-card` QFrame。
2. 卡片包含：44×44 emoji 头像（QFrame 风格）+ 标题栏（name + "当前人设"tag）+ type（subtitle）+ 语气（"语气：xxx"，超 40 字省略号）。
3. 保存 4 个 Label 为 self：`_pc_avatar` / `_pc_title_label` / `_pc_type_label` / `_pc_tone_label`。
4. 新增 `refresh_persona_card(persona_dict=None)` 方法（H13 热更新）：逻辑与 ChatPage.refresh 同构；avatar 只取第 1 个 glyph，避免用户误输入长文本撑坏 UI。
5. WorkspacePage init 末尾**立即调用** refresh，并注册回调钩子。

### 3.5 失败原子性 & 持久化（对应 H10/H11）
通过 SCAI_DATA_DIR 环境变量 + pytest tmp_path fixture 隔离：
- **H10**：AppEngine 不 initialize 直接 save_persona，save_persona 最前面 `if not self._initialized: return False`，整个方法完全跳过 `_config.set()`，天然不会污染数据。
- **H11**：用同一 tmp_path 下 e1.initialize → save_persona → shutdown → del e1 → e2.initialize → get_current_persona_dict 读回来完全一致，底层通过 ConfigManager 的 JSON/YAML 持久化 + config path 从 get_data_dir()（SCAI_DATA_DIR）保证。

---

## 4. 接口契约（Ticket 级）

### 4.1 AppEngine 新增接口（M12 Engine → UI 契约）
```python
class AppEngine:
    def get_current_persona_dict(self) -> Dict[str, Any]:
        """返回 8 字段字典，键集合固定，不返回 None。"""
        ...

    def register_persona_changed_callback(
        self,
        callback: Callable[[Dict[str, Any]], None],
    ) -> bool:
        """注册人设回调，重复注册会重复调用，返回注册是否成功（callback 必须 callable）。"""
        ...

    def unregister_persona_changed_callback(
        self,
        callback: Callable[[Dict[str, Any]], None],
    ) -> int:
        """注销人设回调，返回移除的数量（没注册返回 0）。"""
        ...

    # save_persona 已存在，新增行为：
    # 1) 新旧值比较，相同则跳过 set，changed_any 不设 True
    # 2) changed_any=True 且 save_config 成功后，遍历 _persona_changed_callbacks 逐个调用（单 callback 异常不影响其它）
```

### 4.2 UI 层 3 个页面的新增方法
```python
class ChatPage(QWidget):
    _header_title_label: QLabel   # 原局部变量 → self
    _header_sub_label: QLabel     # 原局部变量 → self
    def refresh_persona_header(self, persona_dict: Optional[Dict[str, Any]] = None) -> None: ...

class PersonaEditorPanel(QWidget):
    _tone_edit: QLineEdit         # 新增
    _type_edit: QLineEdit         # 新增
    def _fill_active_persona_from_engine_if_no_selection(self) -> None: ...  # 新增

class WorkspacePage(QWidget):
    _pc_avatar: QLabel            # 新增
    _pc_title_label: QLabel       # 新增
    _pc_type_label: QLabel        # 新增
    _pc_tone_label: QLabel        # 新增
    def refresh_persona_card(self, persona_dict: Optional[Dict[str, Any]] = None) -> None: ...  # 新增
```

---

## 5. 关键技术决策（非显而易见 / 有坑点的地方，类似 Code Review Why）

| 决策 ID | 决策内容 | 为什么这样做（坑点 / 设计权衡） |
|---|---|---|
| **D1** | UI 层绝对禁止直接 import `aibridge.config.config_manager.ConfigManager` 并构造实例读人设；所有读人设必须走 `AppEngine.get_current_persona_dict()` | **Why**：ChatPage / PersonaEditor / WorkspacePage 三处如果各自构造 ConfigManager，会拿到三个**独立对象**，A 页面写入的缓存 B 页面读不到（除非 save_config + reload）。走 Engine 单例 + 一个接口统一读，能天然保证一致性。 |
| **D2** | save_persona 回调钩子入参传 `latest: Dict[str, Any]`（**最新**的 persona_dict），而不是"之前 vs 之后 diff"、也不是 AppEngine self 引用 | **Why**：1) UI 代码不需要计算 diff，直接用最新值刷新就行；2) 回调不需要知道 AppEngine 内部引用，减少对 Engine 私有状态的依赖；3) 防止回调函数误操作修改 AppEngine 内部 _config。 |
| **D3** | refresh_persona_header / refresh_persona_card 接收**可选参数** `persona_dict=None`，为 None 时再主动从 Engine 读 | **Why**：两种路径都覆盖 —— ① init 场景（没人调回调）主动走 Engine 拉初始值；② 回调场景（Engine 回调钩子**直接传入最新值**）少一次函数调用。且两种路径用同一套字符串格式化逻辑，消除"init 路径和回调路径显示规则不一致"的风险。 |
| **D4** | save_persona 增加**新旧值 diff 比较**，完全相同则跳过 set 且 changed_any 不 True | **Why**：PersonaEditor 的保存按钮即使被用户"乱点"不改值，也不会触发：① 磁盘 JSON/YAML 持久化的无意义 IO（减少 SSD 写 + 线程锁持有时间）；② 3 处 UI 的 setText 无意义重绘；③ 后续 ContextAssembler.reload_persona() 带来的内存分配。 |
| **D5** | tone / type 字段在 PersonaEditor 新增为**独立 QLineEdit**，而不是 Tab 中新增 SectionEditor | **Why**：tone/type 是 save_persona 里 4 个核心字段中的 2 个，属于"人设元信息"（和 name/description 同层级），不是七段结构里的 section。放在 GroupBox 顶部和 name 同排更符合 UI 逻辑，也符合 D1 中"Engine 读回 4 核心字段 → 4 个输入框回显"的一一对应关系。 |
| **D6** | PersonaEditor `_collect_persona_from_ui()` 写入 `self._current_persona.tone/.type` 时用 `hasattr` 检查 | **Why**：SevenSectionPersona dataclass 在**某些分支/老版本**里可能没有 tone / type 字段，直接写会 AttributeError。用 hasattr + getattr + setattr 三路防御，**保证向后兼容**，不破坏旧的 persona 表结构/反序列化逻辑。 |
| **D7** | Workbench 当前人设卡的 avatar 字段**只取第一个 glyph**，并且默认值是 🎭 | **Why**：avatar 字段设计是 emoji，但用户可能手误输入一串中文（比如输入头像"🐱"结果输成"猫头"）。取第一个 glyph 能保证 UI 永远是一个字符大小（44×44），不会把卡片撑变形。 |
| **D8** | ChatPage subtitle 的 description 判断阈值是 `len(desc) > 3`（不是 0 / 1） | **Why**：用户可能误输入 1-2 个无意义字符（"A "、"ok"这种），显示"默认人设，点击左侧 Persona 编辑器调整"更符合产品预期；而 `len(desc) > 40` 时加省略号是因为 ChatPage header 高度 + 子标题只有一行，截断避免换行。 |
| **D9** | 回调钩子**捕获单 callback 异常后继续执行下一个**（try/except 内层 cb），而不是遇到第一个错就整体中断 | **Why**：ChatPage 回调钩子如果因为 Qt widget 析构导致异常，不能让 WorkspacePage 的回调钩子也被跳过 —— 这样 UI 会出现"ChatPage 已销毁没事，但 Workspace 竟然没刷新"的神秘 bug，排查极难。外层再加一次 try/except 包住 `get_current_persona_dict()`，保证回调循环不崩。 |

---

## 6. pytest 22 条 × Grill 映射表

| Grill | pytest 用例 | 文件位置 |
|---|---|---|
| H1 | TestH1H2CurrentPersonaDict.test_H1_8_fields_present | test_inner_ui_data_sync_persona_pdd.py |
| H2 | TestH1H2CurrentPersonaDict.test_H2_default_name / test_H2_default_type / test_H2_default_tone / test_H2_uninitialized_engine_still_returns_defaults | ↑ |
| H3 | TestH3H4ChatPageHeaderInitial.test_H3_title_initial_format | ↑ |
| H4 | TestH3H4ChatPageHeaderInitial.test_H4_sub_initial_when_empty_description + TestH12EmptyAndLongDescriptionDisplay.test_H12_empty_description_shows_default_guide_text | ↑ |
| H5 | TestH5H6PersonaChangedCallbackAndHotRefresh.test_H5_chatpage_refreshes_immediately_via_callback | ↑ |
| H6 | TestH5H6PersonaChangedCallbackAndHotRefresh.test_H6_callback_fires_once_on_save / test_H6_callback_does_not_fire_when_no_fields_changed | ↑ |
| H7 | TestH7SequentialSaveKeepsLastValue.test_H7_final_value_after_saves | ↑ |
| H8 | TestH8H9PersonaEditorEchoOnOpen.test_H8_4_fields_filled_without_selection | ↑ |
| H9 | TestH8H9PersonaEditorEchoOnOpen.test_H9_echo_exactly_matches_engine_current | ↑ |
| H10 | TestH10SaveFailureAtomicity.test_H10_save_returns_false_when_uninitialized | ↑ |
| H11 | TestH11CrossRestartPersistence.test_H11_new_engine_reads_old_values | ↑ |
| H12 | TestH12EmptyAndLongDescriptionDisplay.test_H12_empty_description_shows_default_guide_text / test_H12_whitespace_only_description_shows_default_guide_text / test_H12_long_description_ellipsis / test_H12_long_tone_ellipsis_in_workspace_card | ↑ |
| H13 | TestH13WorkspacePersonaCard.test_H13_initial_values_from_engine / test_H13_card_hot_refresh_via_callback_after_save / test_H13_avatar_only_first_glyph_prevents_long_text | ↑ |

---

## 7. 已交付物清单

| 类别 | 文件 | 说明 |
|---|---|---|
| **规格文档** | docs/PDD_INNER_ui_data_sync_persona.md | 本文件 |
| **原型脚本** | _prototypes/ui_data_sync_persona_prototype.py | 24 断言，24/24 PASS |
| **pytest 固化** | tests/test_inner_ui_data_sync_persona_pdd.py | 22 用例，22/22 PASS |
| **Engine 修改** | [src/aibridge/app_engine.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py) | 新增 4 接口（3 public + 1 save_persona diff 优化） |
| **ChatPage 修改** | [src/aibridge/ui/chat_page.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/chat_page.py) | title/sub 存 self + refresh_persona_header + init 回调注册 |
| **PersonaEditor 修改** | [src/aibridge/ui/persona_editor.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/persona_editor.py) | tone/type 输入框 + 打开时回显激活人设 + 保存同步 tone/type |
| **WorkspacePage 修改** | [src/aibridge/ui/workspace_page.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/workspace_page.py) | 新增"当前人设"卡片 + refresh_persona_card + init 回调注册 |

---

## 8. 回归基线

**inner_* 全量回归：188 passed，0 failed，343 deselected（外层用例自动忽略），耗时 27.47s** —— 模块 M12 上线后，M1~M11 已有的 166 条 inner_* pytest 没有出现任何回归，save_persona 的"新旧值 diff 比较"也未改变旧有调用的行为（旧代码不传 key 的字段依旧保持原值，增量语义保持向后兼容）。
