# SCAI MVP · UI/UX 视觉审计报告（v1.1）

> **定位**：本文档整合了 HTML 原型（`ui_mockup.html`）与 PyQt6 实现的全部差异，包括设计 Token 对比、结构性差异、渲染引擎系统性差距、Sidebar 精确规格。**v1.1 已对照当前代码逐行标注修复状态**，开发侧可按"待修复"条目逐条推进。
>
> **对比基准**：`ui_mockup.html`（唯一真理来源） vs `src/aibridge/ui/` 代码实现（v1.1 核对时间：2026-08-17）
>
> **产出方**：UI/UX 侧 → 交付开发侧

---

## 状态标记说明

| 标记 | 含义 | 下一步 |
|------|------|--------|
| ✅ 已修复 | 代码已实现，与原型对齐 | 无需操作 |
| ⚠️ 待修复 | 代码仍与原型/规范不一致 | 纳入本期修复 |
| ℹ️ 设计变更 | 功能已扩展（比原型更完整），设计侧需更新原型 | UIUX 补画到原型 |

---

## 目录

- [第一部分：设计 Token 对比](#第一部分设计-token-对比)
- [第二部分：侧边栏结构对比](#第二部分侧边栏结构对比)
- [第三部分：页面级差异](#第三部分页面级差异)
- [第四部分：交互细节差异](#第四部分交互细节差异)
- [第五部分：渲染引擎系统性差异](#第五部分渲染引擎系统性差异)
- [第六部分：Sidebar 精确规格（6 问 6 答 + 10 项修正）](#第六部分sidebar-精确规格)
- [第七部分：code 侧描述与代码不一致提醒](#第七部分code-侧描述与代码不一致提醒)
- [优先修复建议（Top 5 待修复项）](#优先修复建议)

---

## 第一部分：设计 Token 对比

**结论：设计 Token 层面 100% 一致，无需修改。**

| # | 维度 | HTML 原型值 | PyQt6 实现值 | 状态 |
|---|------|-----------|-------------|------|
| T1 | 主色 primary | `#022762` | `#022762` | ✅ |
| T2 | 主色 hover | `#03387A` | `#03387A` | ✅ |
| T3 | 主色 light | `#E8EEF7` | `#E8EEF7` | ✅ |
| T4 | 青色 cyan | `#0891B2` | `#0891B2` | ✅ |
| T5 | 文字主色 | `#1A1D29` | `#1A1D29` | ✅ |
| T6 | 侧边栏背景 | `#FAFBFC` | `#FAFBFC` | ✅ |
| T7 | 字体族 | `Noto Sans CJK SC, Microsoft YaHei UI...` | 完全相同 | ✅ |
| T8 | 基础字号 | 13px | 13px | ✅ |
| T9 | 页面标题字号 | 20px / 700 | 20px / 700 | ✅ |
| T10 | 间距系统 | 4/8/12/16/24/32/48 | 完全相同 | ✅ |
| T11 | 圆角系统 | 4/6/8/12/9999 | 完全相同 | ✅ |
| T12 | 阴影值 | sm/md/lg/glow | 完全相同 | ✅ |
| T13 | 暗色主题 primary | `#7BA0C8` | `#7BA0C8` | ✅ |
| T14 | 暗色主题背景 | `#0A0E1A` / `#121828` | 完全相同 | ✅ |
| T15 | 六阶段色 | stage1-6 六色 | 完全相同 | ✅ |

---

## 第二部分：侧边栏结构对比

| # | 维度 | HTML 原型 | PyQt6 实际实现（代码行号） | 状态 |
|---|------|----------|---------------------------|------|
| S1 | Tab 数量 | 5 个（对话/知识库/迭代/工作台/设置） | **6 个**（chat/persona/knowledge/iteration/workspace/settings）。[sidebar.py#L443-L452](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L443-L452) | ℹ️ 设计变更（新增人设 Tab） |
| S2 | Tab 顺序 | 对话→分身知识库→迭代→工作台→设置 | 对话→人设→分身知识库→迭代→工作台→设置（底部 footer=设置） | ℹ️ 设计变更（插入人设 Tab） |
| S3 | 折叠宽度 | 56px | 56px（`Theme.SIDEBAR_WIDTH_COLLAPSED`） | ✅ |
| S4 | 展开宽度 | 220px | 220px（`Theme.SIDEBAR_WIDTH_EXPANDED`） | ✅ |
| S5 | 动画时长 | 250ms | 250ms（`Theme.SIDEBAR_ANIM_DURATION_MS`） | ✅ |
| S6 | 缓动函数 | `cubic-bezier(0.4, 0, 0.2, 1)` | `QEasingCurve.Type.InOutCubic`（≈ 原型曲线）。[sidebar.py#L474](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L474) | ✅ |
| S7 | Active 蓝条 | 3px × 22px, `#022762`, radius 9999px | 3px × 22px, primary 色, 9999px。[sidebar.py#L136-L137](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L136-L137) | ✅ |
| S8 | 图标尺寸 | SVG 18×18, 容器 24×24, stroke-width 2 | 18×18 SVG, 24×24 wrap, stroke=2。[sidebar.py#L149-L157](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L149-L157) | ✅ |
| S9 | Hover 离开 | 立即收起（纯 CSS :hover，无延迟） | leaveEvent 立刻 collapse()。[sidebar.py#L797-L801](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L797-L801) | ✅ |
| S10 | Badge 数字 | 迭代=5, 工作台=3 | NAV_ITEMS 已配置 iteration badge=5, workspace badge=3。[sidebar.py#L447-L448](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L447-L448) | ✅ |
| S11 | Logo 区 | 36×36 深蓝底 + 白色 SVG + 阴影 | 36×36 logo_box + logo_light.svg + QGraphicsDropShadowEffect 调优。[sidebar.py#L564-L596](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L564-L596) | ✅ |
| S12 | 主题切换 | footer 有 theme-toggle | footer 有 NavItem 风格 theme toggle + 文字/图标切换。[sidebar.py#L629-L789](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L629-L789) | ✅ |
| S13 | _collapse_timer 冗余 | 无（纯 CSS） | 代码已删除未使用 timer（仅保留 closeEvent 兜底判断）。[sidebar.py#L467](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L467) | ✅ |

---

## 第三部分：页面级差异

| # | 差异点 | HTML 原型设计 | PyQt6 实际实现 | 状态 | 修复/建议 |
|---|--------|-------------|---------------|------|----------|
| P1 | **首启引导** | 单步弹窗（380px 宽，只填 API Key，标题"连接 AI 引擎"） | **3 步独立向导窗口**（640×480）：Step1 LLM 配置(含 provider/model/测试连接) → Step2 人设确认 → Step3 完成页。[first_run_wizard.py#L34-L426](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/first_run_wizard.py#L34-L426) | ℹ️ 设计变更（功能扩展） | 项目记忆硬约束："首启向导必须包含 LLM 配置页、人设确认页和完成页" → 代码实现正确。**UIUX 侧补画 Step2/Step3 到原型** |
| P2 | **AIGC 徽标** | 聊天气泡中无 AIGC 徽标，仅设置页有开关 | AI 气泡右下角有绿色"AI 生成"徽标 + 元数据（人设名/RAG 命中/Tool Calls） | ℹ️ 合规新增 | 7月15日法规强制标识，合理。UIUX 补画徽标到原型 |
| P3 | **底部状态栏** | 无底部状态栏 | PyQt6 有 QStatusBar：左侧切页提示 / 右侧引擎状态 + 渠道状态。[main_window.py#L138-L159](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/main_window.py#L138-L159) | ℹ️ 新增合理 | UIUX 补画状态栏到原型 |
| P4 | **降级横幅** | 有 `.api-alert-bar`（warning 浅色底） | PyQt6 有 DegradedBanner（llm_key_missing + oa_cloud_disconnected 等提示），含"前往设置"跳转。[main_window.py#L169-L172](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/main_window.py#L169-L172) | ✅ | — |
| P5 | **人设 Tab** | 无（原型 5 个 Tab） | 已完整实现：Sidebar 新增 persona NavItem + PersonaEditor（七段结构）+ main_window 桥接保存信号。**UIUX 审计 83b 已补齐 5 套业务预设：**PRESET_PERSONAS（鲜果小助手/职业成长导师/B2B 销售顾问/售后客服专员/内容创作顾问）+ QComboBox 下拉 + 深拷贝载入。[persona_editor.py#L117-L175](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/persona_editor.py#L117-L175) + [persona_editor.py#L558-L602](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/persona_editor.py#L558-L602) + [persona_editor.py#L818-L849](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/persona_editor.py#L818-L849) | ✅（完整） | UIUX 原型需补画人设 Tab 和预设选择器面板 |
| P6 | **工作台三层结构** | 渠道状态 + 定时任务管理 + 消息记录（三层架构） | main_window 已桥接三层数据拉取：ChannelStats(渠道统计) + ScheduleTaskData(定时任务) + MessageItemData(消息记录)。WorkspacePage 页面需确认内容展示。[main_window.py#L675-L801](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/main_window.py#L675-L801) | ✅（桥接已实现） | 需真机确认 WorkspacePage 视觉布局是否与原型三层卡片一致 |
| P7 | **Badge 未显示** | 导航栏迭代=5、工作台=3 | NAV_ITEMS 默认值已配置（L447-448），运行时可动态 set_badge | ✅ | — |
| P8 | **激活弹窗** | 完整设计：480px，圆角 16px，QR 码 120×120，¥299，微信/支付宝切换，激活码输入，渐变 header，关闭按钮，footer"通过对话激活" | **已完整实现**：480px act-box + 渐变 header（qlineargradient 135°）+ QR 区占位 + ¥299 永久标签 + 微信/active 切换 + "我已付费自动激活"按钮 + 半透明 overlay 遮罩 rgba(0,0,0,0.5)。[activation_dialog.py#L51-L149](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/activation_dialog.py#L51-L149) | ✅（规格已对齐） | 需真机确认：QR 码是否正确渲染、支付方式切换 hover 效果、header 渐变角度 |
| P9 | **知识页导入按钮** | 有"导入文档"按钮（原型 L1959-2306） | 已修复：KnowledgePage 删除了"📥 导入文档"按钮，仅保留"📄 导出文档"按钮。import_requested 信号保留（供其他入口触发），_on_import 方法已删除。[knowledge_page.py#L800-L803](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/knowledge_page.py#L800-L803) + [knowledge_page.py#L880-L881](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/knowledge_page.py#L880-L881) | ✅ 已修复 | 代码已对齐项目记忆硬约束。UIUX 原型需同步移除知识页"导入文档"按钮 |

---

## 第四部分：交互细节差异

| # | 差异点 | HTML 原型 | PyQt6 实际实现 | 状态 | 修复/建议 |
|---|--------|----------|---------------|------|----------|
| I1 | **缓动函数** | `cubic-bezier(0.4, 0, 0.2, 1)`（Material Design 标准） | `QEasingCurve.Type.InOutCubic`，已对齐 sidebar 和 NavItem hover。[sidebar.py#L474](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L474) + [sidebar.py#L346](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L346) | ✅ | — |
| I2 | **_collapse_timer 延迟** | 无延迟，立即收起 | leaveEvent 直接 collapse()，未使用延迟。[sidebar.py#L797-L801](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L797-L801) | ✅ | — |
| I3 | **聊天消息入场动画** | `@keyframes msgIn`（translateY 8px→0, opacity 0→1, 0.3s） | 已实现 opacity 渐入（QGraphicsOpacityEffect + QPropertyAnimation 300ms OutCubic）。translateY 因 Qt layout 约束省略。[chat_page.py#L392-L403](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/chat_page.py#L392-L403) | ✅（部分实现） | 真机确认淡入效果。translateY 8px 在 Qt layout 下不可行，opacity 渐入覆盖 80% 视觉效果 |
| I4 | **Toast 位置** | 底部居中（bottom 32px, translateX -50%） | 已确认：`x = (pw - tw) // 2`（水平居中）+ `y = ph - th - 32`（距底 32px）。[toast.py#L148-L157](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/toast.py#L148-L157) | ✅ | — |
| I5 | **Modal 遮罩毛玻璃** | `rgba(0,0,0,0.4)` + `backdrop-filter: blur(2px)` | PyQt6 不支持 backdrop-filter。R5 修复：overlay 透明度从 0.5→0.55 补偿无 blur。[activation_dialog.py#L82-L86](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/activation_dialog.py#L82-L86) | ✅（已优化） | — |

---

## 第五部分：渲染引擎系统性差异

> **核心结论**：不是"值不对"，是"渲染引擎不同导致同样的值出来的效果不同"。以下 6 条是 PyQt6 vs 浏览器的系统性差距，需针对性优化。

| # | 系统性差距 | HTML/CSS | PyQt6 优化状态（代码位置） | 状态 | 进一步建议 |
|---|----------|----------|--------------------------|------|----------|
| R1 | **阴影质感（最大视觉差距）** | CSS `box-shadow` 多层叠加，极其柔和有空气感 | 全部阴影已调优（blurRadius×0.7, alpha×0.5 策略）：Logo(sidebar blur=4,alpha=25) + 激活弹窗(blur=80,alpha=51) + ChatPage Logo(blur=6,alpha=23) + StatCard hover(blur=8,alpha=9) + Toast(blur=14,alpha=16)。[sidebar.py#L590-L596](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L590-L596) + [chat_page.py#L794-L800](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/chat_page.py#L794-L800) + [stat_card.py#L136-L139](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/stat_card.py#L136-L139) + [toast.py#L96-L101](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/toast.py#L96-L101) | ✅（全部调优） | 真机确认阴影柔和度。如有组件仍偏硬，按同样策略微调 |
| R2 | **字体渲染（中文字糊）** | DirectWrite/GDI，500/600/700 间差别清晰 | main.py 已设置：AA_EnableHighDPIscaling + AA_UseHighDpiPixmaps + QFont.PreferAntialias。[main.py#L94-L95](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/main.py#L94-L95) + [main.py#L107-L109](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/main.py#L107-L109) | ✅（优化已到位） | 真机观察字体粗细。若 500 仍显粗 → 中文字重降级 400 并用更深文字色补偿 |
| R3 | **hover 过渡缺失（生硬跳变）** | `transition: all 0.15s` 平滑过渡 | NavItem 150ms QTimer 逐帧插值 + **ChatPage 发送按钮已替换为 HoverButton**（QVariantAnimation 150ms InOutCubic 背景色插值）。[sidebar.py#L305-L424](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L305-L424) + [components/__init__.py#L17-L64](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/components/__init__.py#L17-L64) + [chat_page.py#L1495-L1505](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/chat_page.py#L1495-L1505) | ✅（关键按钮已实现） | Settings 页保存按钮仍用 QSS :hover（即时切换），后续可批量替换为 HoverButton |
| R4 | **圆角和边框精度** | 小圆角锐利、1px 边框清晰 | 已启用 HighDPI（L94-L95），QSS border-radius 与原型对齐 | ✅（基础已保障） | 真机观察 4px/6px 小圆角是否有锯齿。如锯齿明显，考虑全局设置 `AA_UseHighDpiPixmaps` 之外再加 `renderHints` |
| R5 | **毛玻璃 / 渐变缺失** | `backdrop-filter: blur(2px/4px)` + `linear-gradient` | 毛玻璃：不可用 → 半透明黑 rgba(0,0,0,0.5) 替代（R5 激活弹窗已实现）。渐变：Header 用 `qlineargradient(x1:0,y1:0,x2:1,y2:1)` 135° 手写实现。[activation_dialog.py#L131-L144](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/activation_dialog.py#L131-L144) | ✅（合理近似） | 其他渐变背景（如 Persona Tab hero 区）如未实现，用相同 qlineargradient 模式补齐 |
| R6 | **动画流畅度（低端显卡抖动）** | GPU 加速丝滑；sidebar width CSS transition 自动布局 | QPropertyAnimation maximumWidth + valueChanged resize width。[sidebar.py#L469-L696](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L469-L696) | ✅（动画逻辑正确） | 项目记忆硬约束 `QT_OPENGL=software` 防崩溃。低端机器若仍抖动，可将 250ms 降到 200ms 减少帧数 |

---

## 第六部分：Sidebar 精确规格

> **说明**：本节回答 code 侧之前的 6 个规格问题，并修正当时默认答案中的错误。已对照 [sidebar.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py) 当前实现逐行验证。

### 6.1 对 code 侧 10 个默认答案的修正

| # | code 侧当时答案 | 正确？ | 修正（基于源码 Ln） | 当前代码实现状态 |
|---|---|---|---|---------------|
| G1 | 56px / 220px | ✅ 正确 | `Theme.SIDEBAR_WIDTH_COLLAPSED` / `_EXPANDED` | ✅ 完全匹配 |
| G2 | 200ms ease-out | ❌ 错误 | **250ms**，缓动 `InOutCubic`。[sidebar.py#L472-L474](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L472-L474) | ✅ 已修复为 250ms |
| G3 | 3px × 20px | ❌ 高度错误 | **3px × 22px**。[sidebar.py#L136-L137](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L136-L137) | ✅ 已为 22px |
| G4 | 延迟 300ms | ❌ 错误 | **无延迟，立刻收起**。[sidebar.py#L797-L801](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L797-L801)（leaveEvent 直接 collapse） | ✅ 已无延迟 |
| G5 | hover 临时 + click 永久 | ❌ 错误 | **只有 hover，没有 click 锁死**。Sidebar 未实现"点击展开/折叠"按钮。展开/折叠完全由 enterEvent/leaveEvent 驱动 | ✅ 纯 hover 驱动 |
| G6 | 不需要键盘支持 | ✅ 正确 | 原型无键盘支持 | ✅ 未接入 |
| G7-G9 | 开发侧自定（焦点管理、可访问性、Tooltip） | ✅ 正确 | UI/UX 侧不参与 | — |
| G10 | 精度绝对优先 1:1 | ✅ 正确 | — | — |

### 6.2 六个精确回答（与源码对齐验证）

#### Q1 — 折叠/展开动画参数

| 参数 | 精确值（原型） | 源码实际值（代码位置） | 匹配？ |
|---|---|---------------------|--------|
| 动画时长 | **250ms** | 250ms（`Theme.SIDEBAR_ANIM_DURATION_MS`）。[sidebar.py#L472](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L472) | ✅ |
| 缓动函数 | **cubic-bezier(0.4, 0, 0.2, 1)** | `QEasingCurve.Type.InOutCubic`（视觉等价）。[sidebar.py#L474](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L474) | ✅ |
| 文字渐显 | **有**，opacity 0→1，时长 **200ms** | 通过 `NavItem.set_collapsed` → `_label_widget.setVisible()` 显隐切换。文字无逐帧 opacity 插值，直接显/隐 | 🟡 近似 |
| 实现机制 | CSS transition width | QPropertyAnimation `b"maximumWidth"` + valueChanged 回调手动 `resize(width, height)`。[sidebar.py#L469-L475](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L469-L475) + [sidebar.py#L689-L696](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L689-L696) | ✅ 效果等价 |

#### Q2 — 离开 Sidebar 的行为

**A. 立刻收起，无延迟，250ms 动画收回。**

源码依据：[sidebar.py#L797-L801](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L797-L801)
```python
def leaveEvent(self, ev):
    if self._hover_expand_enabled:
        self.collapse()  # 不经过 QTimer.delay，直接走动画
```

鼠标移出即触发 `leaveEvent` → `collapse()` → 设置 `_anim.startValue = maximumWidth(), endValue = 56` → 250ms `InOutCubic` 动画收回。同时所有 NavItem 通过 `set_collapsed(True)` 隐藏 label/badge。

#### Q3 — 是否有"永久展开"手动按钮

**没有。** 原型里不存在展开/折叠按钮，Sidebar 源码中也没有 hamburger / chevron 按钮。Sidebar 结构只有三块（[sidebar.py#L487-L549](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L487-L549)）：

1. `_build_logo_bar()` — Logo + 产品名文字
2. `_nav_container` — NAV_ITEMS 导航项（chat/persona/knowledge/iteration/workspace）
3. `footer` — 分隔线 + theme-toggle + settings NavItem

**展开/折叠完全由鼠标 hover 驱动**（enterEvent → expand，leaveEvent → collapse），完全等价于原型的纯 CSS `.sidebar:hover { width: var(--sidebar-expanded-w); }` 行为。

#### Q4 — Active 左蓝条精确规格

| 参数 | 精确值（原型） | 源码实际值（代码位置） | 匹配？ |
|---|---|---------------------|--------|
| 宽度 | **3px** | 3px。`_active_bar.setFixedWidth(3)` [sidebar.py#L136](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L136) | ✅ |
| 高度 | **22px** | 22px。`_active_bar.setFixedHeight(22)` [sidebar.py#L137](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L137) | ✅ |
| 颜色 | **`#022762`（浅色）/ `#7BA0C8`（深色）** | `get_token("PRIMARY")` 动态取色。[sidebar.py#L265-L273](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L265-L273) | ✅ |
| 位置 | `left: -8px; top: 50%; translateY(-50%)` | bar_box 包裹，`AlignVCenter` 垂直居中，左加 bar + 8-3=5px 间距。[sidebar.py#L141-L146](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L141-L146) | ✅ |
| 圆角 | **9999px（全圆角）** | `border-radius: 9999px`。[sidebar.py#L266](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L266) | ✅ |
| 折叠态是否显示 | **是**（`.active::before` 无 hover 条件） | `_active_bar.show()` / `hide()` 仅依赖 `_active` 状态，折叠态不 hide。[sidebar.py#L226](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L226) + `set_collapsed()` 不再隐藏 bar | ✅ |
| 暗色发光 | `box-shadow: 0 0 8px var(--primary-glow)` | 未实现暗色 glow 效果。当前仅纯色 | 🟡 不影响 MVP |

#### Q5 — 折叠态视觉细节

| 参数 | 精确值（原型） | 源码实际值（代码位置） | 匹配？ |
|---|---|---------------------|--------|
| 图标 SVG 尺寸 | **18px × 18px**，`stroke-width: 2` | `_colored_svg(..., size=18)` + ICON_SVGS `stroke-width="2"`。[sidebar.py#L153-L157](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L153-L157) | ✅ |
| 图标容器尺寸 | **24px × 24px** | `_icon_wrap.setFixedSize(24, 24)`。[sidebar.py#L149-L150](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L149-L150) | ✅ |
| 水平居中 | **是** | bar_box + _icon_wrap 通过 layout 对齐。折叠态 badge 隐藏保持居中。[sidebar.py#L223-L225](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L223-L225) | ✅ |
| Active 蓝条折叠态显示 | **是** | `_active_bar` 不随折叠隐藏。见 Q4 | ✅ |
| Tooltip | **没有**，使用文字 opacity 隐藏 | 无原生 Tooltip，`_label_widget` 用 setVisible 显隐。没有 hover 弹出 Tooltip | ✅ |

#### Q6 — 底部区域

原型底部**没有"账号切换"功能**，只有两个元素。代码实现：

| 元素 | 功能 | 固定底部？ | 源码位置 | 匹配？ |
|---|---|---|--------|--------|
| 主题切换按钮 | 切换亮色/暗色主题（文字/图标随主题同步刷新：亮色→"切换暗色"+🌙，暗色→"切换亮色"+☀️） | 是（footer 中） | [sidebar.py#L629-L789](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L629-L789) | ✅ |
| 设置导航项 | 跳转 settings 页（page_id=settings，作为 NavItem 加入 footer） | 是（footer 中，theme 下） | [sidebar.py#L533-L543](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L533-L543) | ✅ |

**固定底部原理**：Sidebar root = QVBoxLayout，`_nav_container` 通过 `addWidget(nav_wrap, 1)` 取得 `stretch=1`，自动撑满中间空间，footer（stretch=0）自然贴底。与原型 `flex: 1` 语义等价。

---

## 第七部分：code 侧描述与代码不一致提醒

> **注意**：本节为 v1.0 记录的"描述不一致"，v1.1 代码已修复其中 2/3，剩下 1 条为**知识页导入按钮硬冲突**。

| # | code 侧描述 | 当前实际代码 | 状态 | 建议 |
|---|------------|-------------|------|------|
| C1 | "6 个 Tab：💬 对话 / 🎭 人设 / 📚 知识 / ⚙️ 设置 / 🗂️ 工作台 / 🔄 迭代"（旧审计报告不一致） | sidebar.py NAV_ITEMS 实际 6 个：chat/persona/knowledge/iteration/workspace + FOOTER_ITEMS settings。[sidebar.py#L443-L452](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/sidebar.py#L443-L452)。main_window PAGE_ORDER 也为 6。[main_window.py#L33](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/main_window.py#L33) | ✅ **已对齐** | v1.0 描述不准确，v1.1 代码已修复此不一致 |
| C2 | 旧描述："Tab 顺序：对话/人设/知识/设置/工作台/迭代"（底部无 settings） | NAV_ITEMS 顺序：chat→persona→knowledge→iteration→workspace（5 个主 Tab），settings 在 footer FOOTER_ITEMS。PAGE_ORDER 顺序：`["chat", "persona", "knowledge", "iteration", "workspace", "settings"]` | ✅ **已对齐** | 实际顺序与 code 侧描述（6 个 Tab）几乎一致，仅 settings 固定底部而非主导航区 |
| C3 | "知识 Tab 右上有「导入文档」按钮" vs 项目记忆：**知识页不应有导入按钮，统一对话页** | KnowledgePage 已删除"📥 导入文档"按钮和 _on_import 方法，仅保留"📄 导出文档"按钮。import_requested 信号保留为公共接口。[knowledge_page.py#L800-L803](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/knowledge_page.py#L800-L803) + [knowledge_page.py#L880-L881](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/knowledge_page.py#L880-L881) | ✅ **已修复** | 代码已对齐项目记忆硬约束。原型需同步更新：删除知识页"导入文档"按钮 |

---

## 优先修复建议

### Top 5 待修复项（按严重度 + 工作量排序）

| 优先级 | 编号 | 问题 | 修复方向 | 涉及文件 | 预估工作量 |
|--------|------|------|---------|---------|-----------|
| **P1** | P1 | 首启引导标题不一致：原型标题"连接 AI 引擎"（单步）vs 代码实际"欢迎使用 影分身 AI · 首次启动引导"（3 步 640×480） | **确认**：项目记忆硬约束为 3 步（LLM+人设+完成），因此代码是对的。需更新 HTML 原型补画 Step2/Step3，保持标题"欢迎使用 影分身 AI · 首次启动引导" | UIUX 侧原型 + `first_run_wizard.py`（若尺寸需缩小：640→380 则改） | 小-中 |
| **P1** | P8 | 激活弹窗 QR 码、支付方式切换 hover 效果、header 渐变角度真机验证 | 真机启动后检查：QR 码是否正常显示、微信/支付宝 tab 切换的 hover 反馈、header 135° 渐变是否方向正确（与截图对比） | `activation_dialog.py` | 小 |
| **P1** | P6 | 工作台三层卡片视觉布局 — 桥接已通（渠道状态/定时任务/消息记录），需真机对比原型确认排版 | 真机打开工作台 Tab，对照原型的三层卡片布局检查：各卡片高度/间距/数据项字段是否对齐。如有偏差记录具体像素值 | `workspace_page.py` | 小-中 |
| **P2** | R3-ext | Settings 页保存按钮及其他按钮仍用 QSS :hover（即时切换），未替换为 HoverButton | 后续可批量将 `_style_btn_primary` 返回的 QPushButton 替换为 HoverButton，或修改该方法内部逻辑 | `settings_page.py` / `persona_editor.py` | 中 |
| **P2** | R2 | 字体渲染 — HighDPI 已启用，真机观察 500 字重是否偏粗 | 真机查看中文字体渲染效果。若 500 显粗 → 全局中文字重降级 400 + 更深文字色补偿 | `main.py` / `theme.py` | 小 |

### 按严重度分组（剩余低优/细节任务）

**🟠 中（次要影响视觉一致性）**：
- P6：Workbench 三层卡片视觉布局 vs 原型真机核对
- I3：ChatPage 消息入场动画（`@keyframes msgIn` translateY + opacity）
- I4：Toast 底部居中验证（bottom 32px / translateX -50%）
- R5：Modal 遮罩透明度 — 从 0.5 调到 0.55~0.6 补偿无 blur

**🟡 低（细节打磨，MVP 后再修）**：
- Q4 R4 暗色发光（蓝条 box-shadow）— MVP 不必须
- R4：小圆角锯齿（4px/6px）— 若 HighDPI 开启后仍明显再修
- R6：低端显卡流畅度 — 只有真机反馈卡顿后才降动画时长
- I5 其他交互组件（checkbox、radiobutton、combobox dropdown）hover 过渡

---

## CHANGELOG

| 版本 | 改动者 | 日期 | 说明 |
|------|--------|------|------|
| V1.0 | UI/UX 侧 | 2026-08-17 | 初稿：整合差异清单 + 渲染引擎差距 + Sidebar 精确规格，形成完整审计报告 |
| V1.1 | 开发侧核对 | 2026-08-17 | 对照源码逐行标注修复状态（已修复/设计变更/待修复）；新增 Top 5 待修复项涉及文件和修复方向；同步 code 侧不一致 2/3 已修复 |
| V1.2 | 开发侧修复 | 2026-08-17 | **修复 2 项 P0/P1**：(1) C3/P9 知识页移除"导入文档"按钮（对齐项目记忆硬约束）；(2) 83b/P5 人设 Tab 补齐 5 套业务场景预设（鲜果/导师/销售/售后/内容）+ QComboBox 下拉选择器 + 深拷贝载入逻辑。同步 P5 状态→✅完整、C3→✅已修复，Top5 列表去除已修复项 |
| V1.3 | 开发侧修复 | 2026-08-17 | **修复 4 项渲染/交互**：(1) R1 阴影质感全部调优（ChatPage Logo/StatCard/Toast 按 blurRadius×0.7+alpha×0.5 策略）；(2) R3 ChatPage 发送按钮替换为 HoverButton（QVariantAnimation 150ms InOutCubic）；(3) I3 消息入场动画（QGraphicsOpacityEffect 300ms OutCubic 淡入）；(4) I5/R5 遮罩透明度 0.5→0.55 补偿无 blur。同步 R1→✅、R3→✅关键按钮、I3→✅、I4→✅、I5→✅ |
