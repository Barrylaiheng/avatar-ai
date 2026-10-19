# PDD · 模块 11：Persona Injection Chain（人设注入链路）

> **模块编码**：INNER-11  
> **负责范围**：`PersonaEditor.save_persona()` → `ConfigManager.persona.*` → `AppEngine.process_message()` → `role_config` → `PromptAssembler.assemble()` → LLM System Prompt 的全链路人设字段正确注入。  
> **业务问题**：用户在 PersonaEditor 填了人设名字/描述/语气，但 LLM 回答的自称、口吻、人设边界对不上——等于"填了白填"。
>
> **验收要求**：15 条 Grill Seams 全部通过（P11 需真实 LLM Key 时跳过，其余 14 条无 API Key 也能断言 Prompt 文本）。

---

## 1. Grill 清单（15 条，大白话）

| Grill ID | 验收问题 |
|----------|----------|
| **P1**  | save_persona 后，不重启应用，下一次 process_message 用的 system prompt **包含新人设名**（热更新生效） |
| **P2**  | 人设 description **进入 system prompt**（不是只存配置不读） |
| **P3**  | 人设 tone **进入 system prompt**（不是永远硬编码"专业、友好、简洁"） |
| **P4**  | 人设 type 字段拼接进身份段（如"你是一个 {type}，名叫 {name}"） |
| **P5**  | PromptAssembler 读取 `role_config.identity` / `tone` / `rules` 字段——AppEngine 传的 role_config **正确对齐这些字段名**（不再错位传 name/type/description） |
| **P6**  | 未自定义人设时，使用合理默认值：name="影分身 AI"，type="AI 数字分身"，tone="专业、友好、简洁" |
| **P7**  | 某人设字段为空字符串时，**不在 Prompt 里产生空段落**或 "None" 字面量（例如 tone="" 就不输出【语气风格】段落，由 PromptAssembler 侧 `if tone:` 判断） |
| **P8**  | `save_persona({"name":"X"})` 只改 name，其他字段（description/tone/type）**保留旧值不被清空**（增量语义，不是整对象覆盖） |
| **P9**  | 保存人设后，`PromptAssembler.assemble()` 产出的 system prompt 文本中，**可以搜到人设 description 内的唯一随机关键词**（证明注入的是最新值，不是历史缓存） |
| **P10** | AppEngine 构造 role_config 时，**不再硬编码** tone/type/description 固定字符串（"通用客服" / "智能客服代理系统"），全部走 ConfigManager.persona.* 读取 |
| **P11** | 有 LLM API Key 时，让 LLM 回答"你叫什么名字"，回答里**包含新人设名**（端到端语义验证，非 CI 必跑） |
| **P12** | 人设 avatar / background_story 等附加字段——**background_story** 能进入 identity 段落，前缀为"【背景】"（扩展兼容） |
| **P13** | 连续多次 save_persona（改 name→改 tone→改 description），最终 Prompt 是**最后一次保存的完整人设**，不会有旧 name 残留 |
| **P14** | 无 API Key 的 fallback 场景——即使没调 LLM，process_message 返回的 `persona_name` 字段也是保存过的正确人设名，role_config.tone 也是保存过的正确值 |
| **P15** | 全链路：save_persona → process_message → PromptAssembler.assemble → 最终 messages[0]（system role）content 包含人设 name/type/description/tone/background_story 全部关键字 |

---

## 2. 修复前的根因探查（B-1 结论）

**断点 1：role_config 字段错位（P5 根因）**

```
AppEngine.process_message() 构造的 role_config：
   { name, type, description, tone (硬编码"专业、友好、简洁") }
       ↓ 传进去
PromptAssembler._build_system_prompt() 读取的 key：
   role_config.get("identity", "")    ← 永远拿不到 → 【角色身份】段落缺失
   role_config.get("tone", "")        ← 能拿到但一直是硬编码
   role_config.get("rules", "")       ← 永远拿不到 → 【角色规则】段落缺失
```

**结果**：name/type/description 拼的身份描述**完全没进 Prompt**，LLM 一直按默认 system prompt 回答。

**断点 2：save_persona 非增量（P8/P13 根因）**

```python
# 原实现：persona_dict.get("description", "") → 只要 persona_dict 里没传 description，就 set 成空字符串
self._config.set("persona.description", str(persona_dict.get("description", "")))
self._config.set("persona.tone",        str(persona_dict.get("tone", "专业、友好")))  # 还顺便 reset tone
```

**结果**：UI 层 PersonaEditor 做了"只改名字不改其他字段"的体验，调用 save_persona({"name": new}) 后，description/tone 被清空 → 用户体验 bug。

**断点 3：无测试隔离机制 → 用例间互相污染（P6/P13 原型初期失败根因）**

`get_data_dir()` 忽略 `SCAI_DATA_DIR` 环境变量，所有测试永远用 `项目根/data/` 真实目录。

---

## 3. 修复内容（B-3 + B-4）

### 3.1 `AppEngine.process_message()` role_config 构造逻辑

**位置**：[app_engine.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py) 原 role_config 4 行硬编码替换为：

1. 从 ConfigManager 读取所有 persona.* 字段，缺项走合理默认值（不是硬编码固定字符串）
2. 组装 **identity 文本**（对齐 PromptAssembler 读取的 `role_config.identity`）：
   - 首句：`你是一个{p_type}，名叫「{p_name}」。`
   - 第二段：用户自定义 description（如有）
   - 第三段：`【背景】{background_story}`（如有）
   - 第四段：`【语言特点】{language_style}`（如与 tone 不重复且有）
3. role_config 字段契约对齐 PromptAssembler：**identity / tone / rules**（同时保留 name/type/description 做向后兼容冗余）

### 3.2 `AppEngine.save_persona()` 改为增量语义

**位置**：[app_engine.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py)

修改前：`persona_dict.get(key, default)` 对每个字段 set（**无论用户是否提供该 key**）。  
修改后：先判断 `if input_key in persona_dict:` 再执行 set。未提供的 key 保持 config 原值不变。允许用户显式传 `""` 空字符串以清空某字段（`description=""` → `persona.description = ""`）。

### 3.3 `get_data_dir()` 支持 `SCAI_DATA_DIR` 环境变量

**位置**：[common.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/utils/common.py)

优先级：`SCAI_DATA_DIR` env > PyInstaller `_MEIPASS` > 源码模式 `项目根/data/`。用于 pytest / 原型的跨用例隔离，避免测试污染真实数据。

---

## 4. Test Seams → pytest 用例映射

| Grill | pytest 类/方法 | 断言策略 |
|-------|----------------|----------|
| P1    | `TestP1HotUpdateName.test_persona_name_hot_in_system_prompt` | save 后 capture role_config → assemble system prompt → assert "老王CPS分身" in prompt |
| P2    | `TestP2DescriptionInPrompt.test_description_keywords_in_system` | save desc 含 "抖音带货"/"ROI" → assemble → assert both keywords present |
| P3    | `TestP3ToneFromConfig.test_custom_tone_in_role_config_and_prompt` | save tone = 东北味 → assert role_cfg.tone ≠ 默认硬编码 → prompt 有任意 tone 关键词 |
| P4    | `TestP4TypeInIdentity.test_type_appears_in_role_config_identity` | save type=情感咨询师 → identity 含"情感咨询师"，首句以"你是一个"开头含 name |
| P5    | `TestP5RoleConfigContract.test_required_keys_present_and_identity_nonempty` | role_config 必须有 identity/tone/rules；identity 非空且含"你是一个"身份句 |
| P6    | `TestP6DefaultPersona.test_defaults_name_type_tone` | **不调 save** → role_cfg 默认 name=影分身 AI, type=AI 数字分身, tone=专业友好简洁 |
| P7    | `TestP7NoEmptyOrNoneParagraphs.test_no_none_literal_and_no_three_newlines` | save 多个空字段 → assemble prompt → 无 "None" 字面量 → 无 3+ 连续空行 |
| P8    | `TestP8IncrementalSave.test_rename_preserves_other_fields` | 先全量 save → 再 save({"name": "新名字"}) → identity 仍有原 description，tone 不变 |
| P9    | `TestP9KeywordSearchHit.test_unique_random_string_in_prompt` | save description 含唯一随机串 pid_rand → assemble → assert 唯一串 in prompt |
| P10   | `TestP10NoHardcodeRemnants.test_old_hardcode_strings_absent` | save 自定义 type/desc → identity 不含 "通用客服" / "智能客服代理系统" |
| P12   | `TestP12BackgroundStoryExtraField.test_background_story_with_prefix` | save background_story → identity 有 "【背景】" 前缀 + 有关键内容 |
| P13   | `TestP13MultipleSaveFinal.test_final_values_no_residual_old_name` | 连调 3 次 save → 最终值=最后一次（name/description/tone 正确），旧 name"第1版"消失 |
| P14   | `TestP14FallbackStillCorrectPersona.test_fallback_persona_name_and_role_config_tone` | save 人设 → process_message（走 fallback） → result.persona_name 正确 + internal role_cfg.tone 正确 |
| P15   | `TestP15FullChain.test_end_to_end_all_keywords_present` | 全量人设 save → capture → assemble(+ empty rag) → prompt 含 name/description 关键字/type/tone 关键词/背景关键字 |
| P11   | — | 需要真实 LLM Key，仅作为有 Key 时的手工验证，不进 CI |

---

## 5. 开发任务清单（已完成）

- [x] T-1：探查 ContextAssembler + PromptAssembler._build_system_prompt 对 role_config 的契约字段
- [x] T-2：AppEngine.process_message() 重写 role_config 构造：
  - [x] 读 persona.* 所有配置（7 字段 + 4 扩展）
  - [x] 组装 identity 首句 + description + 【背景】+【语言特点】
  - [x] role_config 对齐 identity/tone/rules 契约，加 name/type/description 向后兼容冗余
  - [x] 移除原硬编码 "通用客服" / "智能客服代理系统" / "专业、友好、简洁"
- [x] T-3：AppEngine.save_persona() 改为增量语义（`if key in dict:` 判断后再 set）
- [x] T-4：`get_data_dir()` 增加 SCAI_DATA_DIR 环境变量支持
- [x] T-5：编写 persona_injection_chain_prototype.py 原型（14 Seams + capture_role_config hook）
- [x] T-6：原型 14/14 通过，写入 tests/test_inner_persona_injection_pdd.py 固化为 pytest
- [x] T-7：pytest 14/14 全绿

---

## 6. 原型 + 测试执行

- **原型**：`_prototypes/persona_injection_chain_prototype.py`  
  执行：`python _prototypes/persona_injection_chain_prototype.py`  
  结果：**14/14（100%）通过**

- **pytest**：`tests/test_inner_persona_injection_pdd.py`  
  执行：`python -m pytest tests/test_inner_persona_injection_pdd.py -v`  
  结果：**14 passed in 15.94s**（全绿）

---

## 7. 下一个模块展望

> 模块 11 打通了"人设注入 Prompt"链路，但还有一个业务场景没覆盖：**人设切换后 LLM 调用前，人设名 + 人设配置还要同步到 UI 层的多处显示位置**（ChatPage 顶栏头像名称、Workbench 底部人设卡片、PersonaEditor 读取时回显默认值）。这部分属于表层 UI ↔ Engine 桥接的回显契约，可纳入下一模块 **UI Data Sync（模块 12）**。
>
> 另一方向是做一次**系统性回归**：把模块 7/7'/10/11 的 pytest 合跑一遍，确认模块 10 App Bootstrap 的 28 条 Test Seams 不被人设修复代码破坏（这一步是 PDD 标准流程，不跳过）。
