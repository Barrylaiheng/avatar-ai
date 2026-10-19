# MVP PDD 总验收文档（表层 · 原型驱动开发 6 阶段闭环）

> **版本**: v1.0
> **生成日期**: 2026-08-09
> **方法论**: 原型驱动开发 PDD（Prototype-Driven Development）— 基于 Matt Pocock 6 阶段闭环
> **参考原型**: [ui_mockup.html](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/ui_mockup.html)
> **验证方式**: pytest 自动化 Test Seams（机器可验证）

---

## 0. PDD 方法论摘要（表层适用）

| 阶段 | 名称 | 关键动作 | 产出物 |
|------|------|---------|--------|
| **1. grill-with-docs** | 组件/页面存在性确认 | 检查原型（Sidebar 路由 + 定位行号区间）+ 判定是否遗留 | 确认在 PDD 白名单 / 标记 deprecated |
| **2. prototype** | 原型规格提取 | 按 HTML 提取：尺寸/颜色/字号/间距/结构/交互/信号/API | 规格对照清单 |
| **3. to-spec** | 编写 Test Seams | 断言机器可验证：尺寸 (px) / 颜色 (token) / 文字 (exact) / 信号 (pyqt) / API (返回值) | `tests/test_{module}_pdd.py` |
| **4. Red** | 运行失败测试 | `pytest test_*_pdd.py` 观察失败项，计算 Red 失败率 | Red 报告（失败项 + 原因分类） |
| **5. Green** | 实现/修复到全部通过 | 按原型规格修正代码，禁止为过测试而硬编码捷径 | `pytest test_*_pdd.py` 100% pass |
| **6. code-review** | 双轴评审 + 全量回归 | 轴1：Fowler 代码异味 / 轴2：规格忠实度 1:1 对齐 → 全量 pytest | 全量测试 0 failed |

**硬规则**（PDD 第零阶段前置检查）：
1. Sidebar 5 页路由 = chat / knowledge / iteration / workspace / settings，**不在列表中的页面一律标记 deprecated，不做 PDD**
2. raw/（即 ui_mockup.html）**不可变**；规格冲突一律以原型为准
3. 修复优先级：实现 bug（类型/属性缺失）> 视觉偏差（尺寸/颜色/间距）> 死代码清理

---

## 1. PDD 覆盖总览

> **283 / 283 Test Seams 全部通过 ✅**
> **14 / 14 有效模块 100% PDD 闭环 ✅**

| 类型 | 编号 | 模块 | 原型行号区间 | Seams 数 | 代码文件 | 测试文件 |
|------|------|------|-------------|---------|---------|---------|
| 页面 | 1 | **ChatPage**（最复杂·收尾） | L1615-1917 | 25 | [chat_page.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/chat_page.py) | [test_chat_page_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_chat_page_pdd.py) |
| 页面 | 2 | **KnowledgePage**（分身知识库） | L1960-2306 | 24 | [knowledge_page.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/knowledge_page.py) | [test_knowledge_page_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_knowledge_page_pdd.py) |
| 页面 | 3 | **WorkspacePage**（工作台） | L1920-1957 | 24 | [workspace_page.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/workspace_page.py) | [test_workspace_page_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_workspace_page_pdd.py) |
| 页面 | 4 | **IterationPage**（迭代系统） | L2309-2382 | 21 | [iteration_page.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/iteration_page.py) | [test_iteration_page_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_iteration_page_pdd.py) |
| 页面 | 5 | **SettingsPage v2**（设置） | L2385-2616 | 20 | [settings_page_v2.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/settings_page_v2.py) | [test_settings_page_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_settings_page_pdd.py) |
| 页面 | 6 | **Sidebar**（侧栏导航·5页路由锚点） | L1569-1607 | 20 | [sidebar.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py) | [test_sidebar_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_sidebar_pdd.py) |
| 弹层 | 7 | **ActivationDialog**（授权弹窗） | L4497 | 27 | [activation_dialog.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/activation_dialog.py) | [test_activation_dialog_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_activation_dialog_pdd.py) |
| 组件 | 8 | **TypingIndicator**（正在输入指示） | L343 | 16 | [typing_indicator.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/typing_indicator.py) | [test_typing_indicator_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_typing_indicator_pdd.py) |
| 组件 | 9 | **ToastManager**（轻量级提示） | L926 | 20 | [toast.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/toast.py) | [test_toast_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_toast_pdd.py) |
| 组件 | 10 | **EmptyState**（空状态） | 全局复用 | 17 | [empty_state.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/empty_state.py) | [test_empty_state_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_empty_state_pdd.py) |
| 组件 | 11 | **LoadingIndicator**（加载指示） | 全局复用 | 20 | [loading_indicator.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/loading_indicator.py) | [test_loading_indicator_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_loading_indicator_pdd.py) |
| 组件 | 12 | **StatCard**（统计卡片） | L954-963 | 20 | [stat_card.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/stat_card.py) | [test_stat_card_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_stat_card_pdd.py) |
| 组件 | 13 | **ToggleSwitch**（开/关切换） | L1480-1491 | 14 | [toggle_switch.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/toggle_switch.py) | [test_toggle_switch_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_toggle_switch_pdd.py) |
| 组件 | 14 | **ProgressSteps**（6段进度） | L456-480 | 15 | [progress_steps.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/progress_steps.py) | [test_progress_steps_pdd.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_progress_steps_pdd.py) |
| | | **合计** | | **283** | | |

---

## 2. 关键指标

### 2.1 通过率与 Red 命中率

| 指标 | 值 | 说明 |
|------|-----|-----|
| PDD Test Seams 总量 | 283 | pytest --collect-only 精确计数（2026-08-09） |
| 通过数 | 283 / 283 (100%) | `pytest tests/test_*_pdd.py` 全绿 |
| 全量（含非PDD） | 294 passed / 0 failed / 0 skipped | 忽略 RAG/阶段信号等权限/环境敏感测试 |
| 平均 Red 失败率 | ~20% | 每 5 个 Seams 能抓出 1 项实现偏差，方法有效 |
| 最高 Red 命中率 | 53%（ProgressSteps：QSizePolicy 未导入崩溃 + 标签不对） | |
| 最低 Red 命中率 | 0%（StatCard、WorkspacePage） | 实现已完全对齐原型 |

### 2.2 按模块的 Seam 分布（可视化）

```
ActivationDialog  ███████████████████████████  27
ChatPage          █████████████████████████  25
WorkspacePage     ████████████████████████  24
KnowledgePage     ████████████████████████  24
StatCard          ████████████████████  20
SettingsPage      ████████████████████  20
LoadingIndicator  ████████████████████  20
Sidebar           ████████████████████  20
Toast             ████████████████████  20
IterationPage     ███████████████████  21
EmptyState        █████████████████  17
TypingIndicator   ████████████████  16
ProgressSteps     ███████████████  15
ToggleSwitch      ██████████████  14
```

---

## 3. 累计修复 Bug 清单（20 项）

> 按修复**严重级别**排序（崩溃 / 数据错误 / 视觉偏差 / 死代码清理）

| 严重 | 模块 | Phase | Bug 描述 | 修复方式 | 影响级别 |
|------|------|-------|---------|---------|---------|
| 🔴 崩溃 | ProgressSteps | P4+5 Red | **QSizePolicy 未导入 → 实例化 NameError** | 在 PyQt6 imports 中加 QSizePolicy | 运行时崩溃 |
| 🔴 崩溃 | EmptyState | P6 代码审查 | `set_text(title=...)` 在 title_label 未创建时 AttributeError | 加 `hasattr(self, "title_label")` 守卫 | 边界崩溃 |
| 🔴 崩溃 | ActivationDialog | 前置 | `_footer_link` 等属性名不统一 → 外部访问时报 AttributeError | 暴露 public 属性 / 加 `_` 前缀 | 边界崩溃 |
| 🟠 数据 | SettingsPage v2 | P4+5 Red | _ThemeCard `.label` / `.selected` 未暴露 → 外部访问 AttributeError | `.label = label` + `@property selected` | API 契约缺失 |
| 🟠 数据 | LoadingIndicator | P4+5 Red | 缺少 `.is_running()` / `.start()` API → 外部无法控制动画 | 新增两个方法（基于 timer 状态） | API 契约缺失 |
| 🟠 数据 | ToastManager | P4+5 Red | Theme 类缺 `BG_ELEVATED` token → Toast 样式 KeyError | Theme 中补 `BG_ELEVATED = "#FFFFFF"` | 运行时崩溃 |
| 🟠 数据 | Sidebar / 阶段进度 | 前置 | STAGE_LABELS 第 1 项 "知识萃取" → 原型 "目标确认" | 纠正为 [目标确认/知识萃取/人格塑造/交互设计/部署交付/持续演化] | 原型不一致 |
| 🟡 视觉 | TypingIndicator | P4+5 Red | 动画总时长 750ms → 原型 1400ms | ANIM_MS 750 → 1400 | 视觉偏快 |
| 🟡 视觉 | TypingIndicator | P4+5 Red | 构造时未 hide() → 默认可见被误判 | `__init__` 尾 `self.hide()` | 初始状态错误 |
| 🟡 视觉 | EmptyState | P4+5 Red | padding 32px → 原型 30px；title font/color 不一致 | padding 30；title 用 TEXT_TERTIARY + 13px | 视觉偏差 |
| 🟡 视觉 | ToggleSwitch | P4+5 Red | 尺寸 36×20 → 原型 40×22；thumb 16→18；开启位置 16→20 | setFixedSize / drawEllipse / 动画终点同步修改 | 视觉偏差 |
| 🟡 视觉 | ToastManager | P4+5 Red | 实现使用独立窗口 → 原型 overlay 子控件 | 重写：父 widget 叠层 + bg_elevated + shadow + in/out 300ms QPropertyAnim | 架构性偏差 |
| 🟡 视觉 | SettingsPage v2 | P4+5 Red | **授权管理 section 完全缺块**（原型 L2415-2438） | 补 _build_license_section：试用进度条 + "立即激活"按钮 | 结构缺块 |
| 🟡 视觉 | IterationPage P4 | 死代码 | 未使用的 import / 中间变量 | 清理（Phase 6 code-review 轴 1） | 可读性 |
| 🟡 视觉 | Toast P6 Review | 死代码 | 原独立窗口版的 window 相关 import / 方法残留 | 清理 | 可读性 |
| 🟡 视觉 | SettingsPage P6 | 死代码 | `__import__("PyQt6.QtCore")` 内联丑导入 | 顶部静态 import | 可读性 |
| 🟢 结构 | DashboardPage | P0 遗留 | **原型无首页 → 标记 deprecated**（不在 Sidebar 路由） | 顶部 deprecation notice | 模块边界 |
| 🟢 结构 | SettingsPage v1 | P0 遗留 | 被 v2 取代 → 标记 deprecated | 顶部 deprecation notice | 模块边界 |
| 🟢 结构 | agent_panel | P0 遗留 | 被 ChatPage 取代 → 标记 deprecated | 顶部 deprecation notice | 模块边界 |
| 🟢 结构 | linear_wizard | P0 遗留 | 原型无 6 步向导 → 标记 deprecated | 顶部 deprecation notice | 模块边界 |

---

## 4. 各模块 Test Seams 详情

> 按 pytest `--collect-only` 输出的真实 Seam 编号顺序列出，每一项都是机器可验证断言。

### 4.1 Sidebar — SB 1-20

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | test_sidebar_exists | Sidebar 对象创建成功 |
| 2 | test_collapse_width_56 | Collapsed 宽度 == 56px |
| 3 | test_logo_size_36 | Logo 容器 36×36 |
| 4 | test_nav_icon_container_24 | 每个 NavItem 图标容器 24×24 |
| 5 | test_nav_item_height_42 | 每个 NavItem 高度 42px |
| 6 | test_logo_bar_height_42 | Logo Bar 高度 ≥ 42px |
| 7 | test_active_bar_3x22 | 激活指示条 3×22 |
| 8 | test_active_bar_visible_when_collapsed | collapsed 状态下激活条仍可见 |
| 9 | test_active_bar_color_primary | 激活条颜色 == PRIMARY token |
| 10 | test_logo_bg_primary_radius_8 | Logo 背景 PRIMARY，圆角 8px |
| 11 | test_logo_has_shadow | Logo 有 box-shadow |
| 12 | test_footer_at_bottom | Footer（激活链接）在 bottom，对齐原型 |
| 13 | test_hover_expand_to_220 | 悬停展开 → 宽度 220 |
| 14 | test_expand_maximum_width_220 | maximumWidth == 220 |
| 15 | test_leave_collapse_to_56 | 离开收回 → 宽度 56 |
| 16 | test_no_delay_on_leave | 收起无 600ms 延迟（防 hover 抖动） |
| 17 | test_rapid_hover_10x_no_crash | 快速 10× hover/leave 不崩溃 |
| 18 | test_resize_no_crash | 父窗口 resize 不崩溃 |
| 19 | test_dark_mode_sidebar_bg | 暗主题 → Sidebar 背景切换 |
| 20 | test_dark_mode_active_bar_color | 暗主题 → 激活条颜色仍 PRIMARY |

### 4.2 ActivationDialog — AD 1-27

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | ad1 overlay 半透明黑色背景 | 背景色 rgba 0,0,0,0.5 |
| 2 | ad2 显示/隐藏切换 | show()/hide() → isVisible 正确 |
| 3 | ad3 对话框宽度 480 / 圆角 16 | sizeHint / geometry 中 width 480 |
| 4 | ad4 阴影与边框 | stylesheet 含 box-shadow / border |
| 5 | ad5 header padding 与渐变分割线 | padding 24，顶部分割线 token |
| 6 | ad6 header 图标 48×48 / PRIMARY bg | 48×48 尺寸 |
| 7 | ad7 标题 17px / weight 700 | stylesheet 含 font-size 17px + 700 |
| 8 | ad8 副标题 13px | stylesheet 含 13px |
| 9 | ad9 关闭按钮右上角 | button 几何位置 (width - 48, ~8) |
| 10 | ad10 关闭按钮触发 closed 信号 | 点击 → closed.emit 收到 |
| 11 | ad11 body padding 24,28 | layout contentsMargins |
| 12 | ad12 QR 区域边框/圆角/背景 | QR frame stylesheet |
| 13 | ad13 QR 图片 120×120 | 尺寸 120 |
| 14 | ad14 价格 28px / 700 / PRIMARY 色 | 字体 size/weight/color |
| 15 | ad15 单价单位 14px | 14px |
| 16 | ad16 支付 Tab 2 项，微信默认 active | 默认选中 Tab |
| 17 | ad17 验证按钮 PRIMARY / 全圆角 | 按钮样式 PRIMARY color, radius full |
| 18 | ad18 验证按钮触发 verify_attempt 信号 | 点击 → 信号发出 |
| 19 | ad19 状态区默认隐藏 | status label 初始 hidden |
| 20 | ad20 show_info → 文字 + info 色 | info 颜色 + 文字设置 |
| 21 | ad21 show_success → activated 信号 | 成功后 activated.emit 收到 |
| 22 | ad22 show_error → failed 信号 | 失败后 failed.emit 收到 |
| 23 | ad23 footer 样式 | border-top, padding |
| 24 | ad24 footer 讨论链接 → discuss_requested 信号 | 点击 → 信号发出 |
| 25 | ad25 show/hide 信号 | 显隐时 show/hide signal 发出 |
| 26 | ad26 快速 10× show/hide 无崩溃 | 10 次切换无异常 |
| 27 | ad27 快速 10× status 切换无崩溃 | info→success→error→info 无异常 |

### 4.3 TypingIndicator — TI 1-16

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | ti1 默认隐藏 | isVisible == False |
| 2 | ti2 三个点 QLabel | 3 个 dots label |
| 3 | ti3 点尺寸 6×6 | 每个 dot size 6 |
| 4 | ti4 点颜色 TEXT_TERTIARY | stylesheet 中 tertiary token |
| 5 | ti5 spacing 4px | layout spacing == 4 |
| 6 | ti6 padding 4,0 | contentsMargins 4,0,4,0 |
| 7 | ti7 动画时长 1400ms | DURATION_MS == 1400 |
| 8 | ti8 无限循环 | Animation.InfiniteLoop |
| 9 | ti9 三点相位延迟 | dot1 0ms / dot2 166ms / dot3 333ms 起步 |
| 10 | ti10 start() 跑动画 | timerStart → start 成功 |
| 11 | ti11 stop() 停动画 | stop → timerStop 无动画 |
| 12 | ti12 stop 重置三点位置 | opacity == 0.3 / scale 0.8 |
| 13 | ti13 is_running() 状态 | 未启动 False / start 后 True |
| 14 | ti14 10× 快速 start/stop 不崩溃 | 10 次循环不异常 |
| 15 | ti15 start 幂等 | 两次 start 不触发重复动画启动异常 |
| 16 | ti16 stop 幂等 | 两次 stop 不异常 |

### 4.4 Toast — TM 1-20

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | tm1 背景 BG_ELEVATED | stylesheet BG_ELEVATED token |
| 2 | tm2 边框 BORDER | border 1px solid BORDER token |
| 3 | tm3 padding 10,20 | contentsMargins 10/20 |
| 4 | tm4 圆角 RADIUS_MD | border-radius == 8px |
| 5 | tm5 font-size 13px | stylesheet FONT_BASE 13px |
| 6 | tm6 图标 16px 颜色对应类型 | icon 尺寸 + success/error/info/warning 色 |
| 7 | tm7 内部 gap 6 | layout spacing 6 |
| 8 | tm8 进场动画 300ms | anim_in duration 300 |
| 9 | tm9 起始 opacity 0 | anim_in startValue == 0 |
| 10 | tm10 结束 opacity 1 | anim_in endValue == 1 |
| 11 | tm11 出场 300ms | anim_out duration 300 |
| 12 | tm12 不是独立窗口 | windowFlags 不包含 Window flag |
| 13 | tm13 pointer-events-none 不阻挡点击 | attribute WA_TransparentForMouseEvents |
| 14 | tm14 位置 bottom=32 / 水平居中 | geometry 中 y == parent.height() - self.height() - 32 |
| 15 | tm15 show_success() 实际创建并显示 Toast | Toast 数量 +1 |
| 16 | tm16 success / error / info / warning 四个 API | 4 个方法均存在 |
| 17 | tm17 默认时长：s 2s / i 2.5 / w 3 / e 4 | DEFAULT_DURATIONS |
| 18 | tm18 并发 max=3，其余排队 | 5 个 success → concurrency == 3，其余 queued |
| 19 | tm19 页面关闭 → 队列清空 | active 关闭后 queue 空 |
| 20 | tm20 高 z-order | z-order 在兄弟控件之上 |

### 4.5 EmptyState — ES 1-17

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | es1 padding 30 | contentsMargins == 30 |
| 2 | es2 居中对齐 | AlignCenter |
| 3 | es3 desc 颜色 TEXT_TERTIARY | tertiary |
| 4 | es4 desc 字号 13px | 13px |
| 5 | es5 title 颜色 TEXT_TERTIARY | tertiary |
| 6 | es6 title 字号 13px | 13px |
| 7 | es7 icon 默认存在 | icon_widget 非 None |
| 8 | es8 action 可选 | 不传 action → no btn |
| 9 | es9 action 点击 → action_clicked signal 发出 | 点击 → received |
| 10 | es10 set_text(title) → 更新 title_label.text | 文字更新 |
| 11 | es11 set_text(description) → 更新 description.text | 文字更新 |
| 12 | es12 set_text(desc=None) → 隐藏 | description.isVisible == False |
| 13 | es13 set_text(desc="") → 隐藏（与 None 语义一致） | description.isVisible == False |
| 14 | es14 仅 desc 最小构造 | title_label 不存在时安全 |
| 15 | es15 无 icon 模式 | icon_widget 不存在不崩溃 |
| 16 | es16 背景透明 | stylesheet background transparent |
| 17 | es17 布局 spacing 合理 | spacing ≥ 8 |

### 4.6 LoadingIndicator — LI 1-20

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | li1 构造后动画运行中 | _timer.isActive == True |
| 2 | li2 spinner 10 个盲文字符 | BRAILLE_FRAMES len == 10 |
| 3 | li3 timer 80ms 间隔 | interval == 80 |
| 4 | li4 tick → 下一帧 | frame_index +1 |
| 5 | li5 tick → spinner 文字变化 | 文字非空，更新成功 |
| 6 | li6 10 tick → 回绕到 0 | wrap |
| 7 | li7 stop → 停止 timer | timer.inactive |
| 8 | li8 stop 幂等 | 2× stop 不异常 |
| 9 | li9 is_running() == timer 状态 | running 状态同步 |
| 10 | li10 set_text → 更新 label.text | 文字更新 |
| 11 | li11 spinner 颜色 PRIMARY | PRIMARY token |
| 12 | li12 spinner 字号 FONT_XL | FONT_XL |
| 13 | li13 文字颜色 TEXT_SECONDARY | secondary |
| 14 | li14 文字字号 FONT_BASE | FONT_BASE |
| 15 | li15 layout spacing 8 | spacing == 8 |
| 16 | li16 padding 16 | contentsMargins == 16 |
| 17 | li17 居中对齐 | AlignCenter |
| 18 | li18 背景透明 | background transparent |
| 19 | li19 start() 重启停止的动画 | stop → start → active |
| 20 | li20 默认文字 "加载中…" | default text |

### 4.7 SettingsPage — SP 1-20

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | sp1 标题 "系统设置" | "系统设置" |
| 2 | sp2 副标题 "大模型与核心连接配置" | sub 文字 |
| 3 | sp3 版本切换 Preview / Stable 两个 | version_btn == 2 |
| 4 | sp4 版本切换 → version_changed 信号 | 点击 Stable → 信号发出 |
| 5 | sp5 主题卡片 *2 | _ThemeCard count == 2 |
| 6 | sp6 Light card.label == "浅色模式" | label 存在且正确 |
| 7 | sp7 Dark card.label == "深色模式" | label 存在且正确 |
| 8 | sp8 Light 默认 selected | light.selected True |
| 9 | sp9 Dark 点击 → theme_changed 信号（含 "dark"） | 点击 → 信号发出 |
| 10 | sp10 主题 section title | section-title "外观主题" |
| 11 | sp11 LLM BaseURL readonly | QLineEdit isReadOnly True |
| 12 | sp12 保存 / 测试按钮（QPushButton 至少 1 个含 "保存"） | 存在 |
| 13 | sp13 API Key Password 显示模式 (echoMode == Password) | 通过父子关系向上找 row，再判断 |
| 14 | sp14 模型下拉至少 2 项 | count ≥ 2 |
| 15 | sp15 WCF section 标题 | "微信连接（WCF）" |
| 16 | sp16 连接模式下拉至少 3 项 | count ≥ 3 |
| 17 | sp17 微信版本状态（含 "版本" 或 "未检测"） | 存在 |
| 18 | sp18 点击"保存" → llm_saved 信号 | 信号发出 |
| 19 | sp19 授权管理 section（含 "授权" / "激活" 文字）| 存在（缺块补） |
| 20 | sp20 主容器是 QScrollArea（settings-body overflow-y）| 存在且 widgetResizable |

### 4.8 IterationPage — IT 1-21

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | it1 标题 "迭代优化" | 标题 |
| 2 | it2 副标题 "BadCase 优化队列" | sub |
| 3 | it3 4 张 StatCard | 4 个 StatCard child |
| 4 | it4 Stat 总数 5 | stat 1.value_label "5" |
| 5 | it5 本周新增 3 | 3 |
| 6 | it6 已解决 12 | 12 |
| 7 | it7 解决率 71% | "71" |
| 8 | it8 队列标题 "待处理 BadCase 队列" | 存在 |
| 9 | it9 筛选下拉 5 项 | count == 5 |
| 10 | it10 5 个 BadCaseItem | 5 |
| 11 | it11 2 个空回复类型徽章 | 2 |
| 12 | it12 4 种 bc 类型（empty / wrong / safety / context）全覆盖 | all 4 present |
| 13 | it13 每项 2 按钮 | QPushButton count per item == 2 |
| 14 | it14 "一键优化" 按钮文字 | "一键优化" |
| 15 | it15 "对话讨论" 按钮文字 | "对话讨论" |
| 16 | it16 question 前缀 "用户问题:" 存在 | prefix |
| 17 | it17 answer 前缀 "分身回复:" 存在 | prefix |
| 18 | it18 filter(empty) → 2 条 | count 2 |
| 19 | it19 filter(all) → 5 条 | count 5 |
| 20 | it20 optimize_requested 信号（点击一键优化 → 信号发出）| emit |
| 21 | it21 set_badcases([]) API → 0 items | API 存在 |

### 4.9 WorkspacePage — WP 1-24

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | wp1 标题 "工作台" | 标题 |
| 2 | wp2 副标题 "消息监控 · 定时推送 · 运行统计" | sub |
| 3 | wp3 2 渠道 tab（微信/公众号）| count == 2 |
| 4 | wp4 微信默认 active | currentIndex == 0 / "微信" |
| 5 | wp5 切到公众号 → 列表切换 | channel_changed 信号 |
| 6 | wp6 3 张 StatCard | 3 |
| 7 | wp7 消息总数 128 | 128 |
| 8 | wp8 平均 23 秒响应 | 23 |
| 9 | wp9 满意度 94% | "94" |
| 10 | wp10 搜索框 placeholder "搜索联系人或消息..." | placeholder text |
| 11 | wp11 3 筛选 chips（私聊/群聊/AI 回复）| count == 3 |
| 12 | wp12 状态下拉 4 项（全部/已回复/未回复/异常）| 4 项 |
| 13 | wp13 初始 5 条消息 | list count == 5 |
| 14 | wp14 私聊筛选 → 3 条 | 3 |
| 15 | wp15 群聊筛选 → 2 条 | 2 |
| 16 | wp16 搜索 "葡萄" → 1 条匹配 | 1 |
| 17 | wp17 公众号 tab 下 → 3 条 | 3 |
| 18 | wp18 "定时推送任务" 标题 | 存在 |
| 19 | wp19 新建定时按钮 | 含 "新建" |
| 20 | wp20 3 个 schedule item | 3 |
| 21 | wp21 新建定时按钮 → new_schedule_requested 信号 | 信号发出 |
| 22 | wp22 ToggleSwitch 切换 → schedule_toggled(id,bool) 信号 | 信号发出 |
| 23 | wp23 所有 pyqtSignal （channel_changed / new_schedule_requested / schedule_toggled / all_signals) | 存在 |
| 24 | wp24 set_messages / set_schedules API 存在 | API 可调用 |

### 4.10 StatCard — SC 1-20

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | sc1 是 QFrame 子类 | isinstance QFrame |
| 2 | sc2 四边 padding 18 | contentsMargins 18 |
| 3 | sc3 title_label == "知识条目" | _title.text |
| 4 | sc4 title 字号 12px | stylesheet 12px |
| 5 | sc5 title 颜色 TEXT_SECONDARY | secondary token |
| 6 | sc6 value_label 存在 | non None |
| 7 | sc7 value == "42" | text |
| 8 | sc8 value 字号 26px | stylesheet 26px |
| 9 | sc9 value weight 700 | stylesheet 700 |
| 10 | sc10 value 颜色 TEXT_PRIMARY | primary token |
| 11 | sc11 set_value(128) → 文字 "128" | text |
| 12 | sc12 set_value("99%") → 文字 "99%" | text |
| 13 | sc13 delta_label.text == "+12%" | 文字 |
| 14 | sc14 delta_positive → SUCCESS 色 | stylesheet success |
| 15 | sc15 set_delta(-, False) → ERROR 色 | stylesheet error |
| 16 | sc16 border-radius 在 stylesheet | present |
| 17 | sc17 "1px solid" border | present |
| 18 | sc18 背景 BG_BASE | BG_BASE color |
| 19 | sc19 delta=None → no delta_label (None) | _delta_label is None |
| 20 | sc20 set_delta(None) → hide | isVisible False |

### 4.11 ToggleSwitch — TS 1-14

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | ts1 size 40×22 | width 40, height 22 |
| 2 | ts2 toggled(bool) 信号 | pyqtBoundSignal |
| 3 | ts3 初始 Unchecked | isChecked == False |
| 4 | ts4 setChecked(True, animate=False) → True | True |
| 5 | ts5 setChecked(False) → False | False |
| 6 | ts6 mousePressEvent(左键) → 切换 | toggle 成功 |
| 7 | ts7 信号 toggled.emit 收到 True | received |
| 8 | ts8 checkState() == Unchecked / Checked Qt enum | enum match |
| 9 | ts9 cursor == PointingHandCursor | cursor shape |
| 10 | ts10 动画 duration 180ms | anim duration |
| 11 | ts11 设同值 → 不二次 emit | count == 0 |
| 12 | ts12 animate=False → position == 20 (原型 translateX 18) | position == 20 |
| 13 | ts13 ToggleSwitch(checked=True) 初始值 | True |
| 14 | ts14 没有 set_delta API（防组件接口污染）| hasattr False |

### 4.12 ProgressSteps — PS 1-15

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | ps1 STAGE_LABELS 长度 == 6 | len 6 |
| 2 | ps2 STAGE_LABELS 内容匹配原型（目标确认→知识萃取→人格塑造→交互设计→部署交付→持续演化）| exact match |
| 3 | ps3 jump_requested(int) 信号 | 存在 |
| 4 | ps4 set_current(3) → current_stage == 3 | OK |
| 5 | ps5 set_current(3) → stages 1/2 is_done True | OK |
| 6 | ps6 set_current(1) → 0 完成步骤 | all False |
| 7 | ps7 set_current(6) → stages 1..5 done | 1..5 True，6 False |
| 8 | ps8 set_current(10) → clamp 6 | current == 6 |
| 9 | ps9 set_current(-1) → clamp 1 | current == 1 |
| 10 | ps10 set_step_done(4, True) → is_done(4) True | OK |
| 11 | ps11 set_step_done(4, False) → False | OK |
| 12 | ps12 越界 (0/7) → 不崩溃、返回 False | safe |
| 13 | ps13 minimumHeight > 0 | height exists |
| 14 | ps14 初始 current == 1 | current_stage == 1 |
| 15 | ps15 mouseTracking True | hasMouseTracking |

### 4.13 KnowledgePage — KP 1-24

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | kp1 标题 "分身知识库" | label 存在 |
| 2 | kp2 副标题 "共 13 个条目" (mock: 3+6+4+0+0) | "13" in text |
| 3 | kp3 2 视图按钮（列表视图/图谱视图）| 两个 btn 存在 |
| 4 | kp4 初始 view == list，stack index 0 | OK |
| 5 | kp5 切图谱视图 → stack index 1 + signal emit(graph) | OK |
| 6 | kp6 "导出文档" 按钮 → export_requested 信号 | 信号发出 |
| 7 | kp7 5 个 StageGroupSection | count == 5 |
| 8 | kp8 标题顺序 == [目标确认, 知识萃取, 人格塑造, 交互设计, 部署交付] | exact match |
| 9 | kp9 statuses == [done, done, active, todo, todo] | match |
| 10 | kp10 counts == [3, 6, 4, 0, 0] | match |
| 11 | kp11 13 张 KnowledgeEntryCard | count == 13 |
| 12 | kp12 Stage 1(目标确认).cards 有 3 张 | len 3 |
| 13 | kp13 任意卡：tag、title、来源 label ≥ 7 个 QLabel 内部 | structure OK |
| 14 | kp14 hint 文字 "展开详情" | "展开详情" or "收起" |
| 15 | kp15 toggle() → expanded + detail visible + hint "收起" | expand 状态正确 |
| 16 | kp16 展开 → 至少 2 个 QPushButton（保存/对话优化）| ≥ 2 |
| 17 | kp17 展开 → detail 区 ≥ 1 QTextEdit（编辑器）| editor 存在 |
| 18 | kp18 点保存 → entry_saved(eid, vals) 信号发出 | 信号发出 |
| 19 | kp19 点对话优化 → discuss_requested 信号发出 | 信号发出 |
| 20 | kp20 交互设计 group: placeholder "尚未开始" + "开始交互设计" | 存在 |
| 21 | kp21 部署交付 group 点击 start → start_stage_requested(5) 发出 | 信号发出 |
| 22 | kp22 所有 5 个 pyqtSignal（view/export/save/discuss/start） | 存在 |
| 23 | kp23 _list_scroll 是 QScrollArea 且 widgetResizable | OK |
| 24 | kp24 stack count == 2（list/graph 两页）| count 2 |

### 4.14 ChatPage — CP 1-25

| 编号 | 测试名 | 断言内容 |
|------|--------|---------|
| 1 | cp1 双栏 chat-area + right-panel 都存在 | non None |
| 2 | cp2 chat-header "AI 面试官" 存在 | 文字存在 |
| 3 | cp3 "当前阶段" + "→" 子标题 | 文字存在 |
| 4 | cp4 _StageBars 有 ≥ 6 QFrame segments + ≥ 6 阶段名 labels | 6 bars + 6 labels |
| 5 | cp5 STAGES 6 个名称 == 原型 6 步 | exact match |
| 6 | cp6 _msg_scroll 是 QScrollArea + widgetResizable | OK |
| 7 | cp7 _input_edit 是 QPlainTextEdit + placeholder 含 "输入你的回复" | OK |
| 8 | cp8 send button 30×30 存在 | count ≥ 1 (30x30) |
| 9 | cp9 QToolButton ×2：📎上传文档 + 💬导入聊天记录 | btn texts |
| 10 | cp10 _api_alert 默认隐藏 | isVisible False |
| 11 | cp11 _typing 是 TypingIndicator 默认 hidden | isinstance + hidden |
| 12 | cp12 默认 session ≥ 1 + active non None | OK |
| 13 | cp13 append_reply → session[sid].messages 数量 +1 | +1 |
| 14 | cp14 right panel 2 tabs: "搭建进度" + "运行看板" | 两个 tabs texts |
| 15 | cp15 右侧 progress steps 6 垂直项（目标确认..持续演化） all present | 6/6 |
| 16 | cp16 "影分身" 品牌徽章（文字存在）| "影分身" in labels |
| 17 | cp17 提取卡片 ≥ 3（"分身角色" or "水果电商"）| found |
| 18 | cp18 goto_settings_requested 信号 | pyqtBoundSignal |
| 19 | cp19 goto_knowledge_requested(str) 信号 | 存在 |
| 20 | cp20 goto_workspace_requested(str) 信号 | 存在 |
| 21 | cp21 message_sent(str, str) 信号 | 存在 |
| 22 | cp22 active_session_id() 返回非空 str | len > 0 |
| 23 | cp23 create_new_session → session 数 +1，title 匹配 | +1, title == "测试会话 PDD" |
| 24 | cp24 append_reply(user) → last message.role == "user" 且 content == "你好" | OK |
| 25 | cp25 根布局是 QHBoxLayout（左右双栏）| isinstance QHBoxLayout |

---

## 5. 遗留模块处置（4 个 deprecated）

> PDD 第零阶段产出：**不在 Sidebar 路由中的模块 → 一律不 PDD**

| 文件 | 判定依据 | 处置 |
|------|---------|------|
| [dashboard.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/dashboard.py) | Sidebar 路由无"首页" | 顶部 `# DEPRECATED` notice，不计入 MVP 验收 |
| [settings_page.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/settings_page.py) | 被 settings_page_v2.py 取代 | 顶部 `# DEPRECATED` notice |
| [agent_panel.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/agent_panel.py) | 被 ChatPage 取代（原型 page-chat） | 顶部 `# DEPRECATED` notice |
| [linear_wizard.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/linear_wizard.py) | 原型无 6 步线性向导 | 顶部 `# DEPRECATED` notice |

---

## 6. 表层完成 — 过渡到"里"层的系统分析前置项

> PDD 表层已凝固；下一阶段进入里层（架构/数据流/业务/集成）之前，需要对 MVP 现有模块做**系统性拆解**，以便建立循环系统（血管=数据流、神经=信号流、免疫=安全/权限边界）。

建议接下来的表层→里层过渡工作项（非 PDD，可直接做）：
1. **模块结构全景图**：src/aibridge/ 按 `ui / agent / bridges / engine / rag / config / security / utils` 8 大子包逐一做依赖有向图
2. **数据流分析**（血管）：WCF 消息 → bridges → engine（intent/safety/llm_generator/message_store） → ui 的每个关键实体
3. **信号流分析**（神经）：`pyqtSignal` 全收集，做 Cross-Module 调用图；发现跨层直接调用即架构异味
4. **安全/权限边界审计**（免疫）：api_key_vault / llm_generator / wcf_adapter 的输入约束和权限边界

---

## 7. 命令行重新执行 PDD 总验收

```powershell
# 仅跑全部 PDD 测试
.\venv\Scripts\python.exe -m pytest tests/test_sidebar_pdd.py `
  tests/test_activation_dialog_pdd.py tests/test_typing_indicator_pdd.py `
  tests/test_toast_pdd.py tests/test_empty_state_pdd.py `
  tests/test_loading_indicator_pdd.py tests/test_settings_page_pdd.py `
  tests/test_iteration_page_pdd.py tests/test_workspace_page_pdd.py `
  tests/test_stat_card_pdd.py tests/test_toggle_switch_pdd.py `
  tests/test_progress_steps_pdd.py tests/test_knowledge_page_pdd.py `
  tests/test_chat_page_pdd.py -v

# 预期结果：283 passed in ~180s
```
