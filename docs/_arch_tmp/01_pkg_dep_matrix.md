# 子包级内部依赖矩阵 (import-level)

行=源包，列=目标包；数字=源包中跨包引用该目标包的文件数（0 省略）。

| 源 \ 目标 | root | ui | bridges | engine | rag | database | config | security | utils |
|---|---|---|---|---|---|---|---|---|---|
| root | · | 1 | 1 | 1 | 1 | 1 | 1 |  |  |
| ui |  | · |  |  |  | 1 |  |  |  |
| bridges |  |  | · |  |  |  |  |  |  |
| engine |  |  |  | · |  | 4 | 3 |  | 5 |
| rag |  |  |  | 1 | · | 2 | 3 |  | 4 |
| database |  |  |  |  |  | · |  |  | 1 |
| config |  |  |  |  |  |  | · | 1 | 1 |
| security |  |  |  |  |  |  |  | · |  |
| utils |  |  |  |  |  |  |  |  | · |

## 跨包引用明细


### config → security（1 处）

- aibridge\config\config_manager.py -> aibridge.security.api_key_vault

### config → utils（1 处）

- aibridge\config\config_manager.py -> aibridge.utils.common

### database → utils（1 处）

- aibridge\database\database_manager.py -> aibridge.utils.common

### engine → config（3 处）

- aibridge\engine\llm_generator.py -> aibridge.config.config_manager
- aibridge\engine\message_processor.py -> aibridge.config.config_manager
- aibridge\engine\schedule_manager.py -> aibridge.config.config_manager

### engine → database（4 处）

- aibridge\engine\context_assembler.py -> aibridge.database.database_manager
- aibridge\engine\iteration_engine.py -> aibridge.database.database_manager
- aibridge\engine\message_processor.py -> aibridge.database.database_manager
- aibridge\engine\safety_shield.py -> aibridge.database.database_manager

### engine → utils（5 处）

- aibridge\engine\context_assembler.py -> aibridge.utils.common
- aibridge\engine\iteration_engine.py -> aibridge.utils.common
- aibridge\engine\llm_generator.py -> aibridge.utils.common
- aibridge\engine\safety_shield.py -> aibridge.utils.common
- aibridge\engine\schedule_manager.py -> aibridge.utils.common

### rag → config（3 处）

- aibridge\rag\chromadb_manager.py -> aibridge.config.config_manager
- aibridge\rag\knowledge_base_manager.py -> aibridge.config.config_manager
- aibridge\rag\rag_engine.py -> aibridge.config.config_manager

### rag → database（2 处）

- aibridge\rag\knowledge_base_manager.py -> aibridge.database.database_manager
- aibridge\rag\rag_engine.py -> aibridge.database.database_manager

### rag → engine（1 处）

- aibridge\rag\rag_engine.py -> aibridge.engine.intent_router

### rag → utils（4 处）

- aibridge\rag\chromadb_manager.py -> aibridge.utils.common
- aibridge\rag\document_parser.py -> aibridge.utils.common
- aibridge\rag\knowledge_base_manager.py -> aibridge.utils.common
- aibridge\rag\wiki_manager.py -> aibridge.utils.common

### root → bridges（5 处）

- aibridge\app_engine.py -> aibridge.bridges.message_router
- aibridge\app_engine.py -> aibridge.bridges.internal_message
- aibridge\app_engine.py -> aibridge.bridges.base_adapter
- aibridge\app_engine.py -> aibridge.bridges.wcf_adapter
- aibridge\app_engine.py -> aibridge.bridges.wcf_adapter

### root → config（1 处）

- aibridge\app_engine.py -> aibridge.config.config_manager

### root → database（2 处）

- aibridge\app_engine.py -> aibridge.database.database_manager
- aibridge\app_engine.py -> aibridge.database.database_migrator

### root → engine（8 处）

- aibridge\app_engine.py -> aibridge.engine.safety_shield
- aibridge\app_engine.py -> aibridge.engine.intent_router
- aibridge\app_engine.py -> aibridge.engine.context_assembler
- aibridge\app_engine.py -> aibridge.engine.llm_generator
- aibridge\app_engine.py -> aibridge.engine.message_store
- aibridge\app_engine.py -> aibridge.engine.iteration_engine
- aibridge\app_engine.py -> aibridge.engine.aigc_marker
- aibridge\app_engine.py -> aibridge.engine.schedule_manager

### root → rag（2 处）

- aibridge\app_engine.py -> aibridge.rag.rag_engine
- aibridge\app_engine.py -> aibridge.rag.knowledge_base_manager

### root → ui（2 处）

- aibridge\main.py -> aibridge.ui.main_window
- aibridge\main.py -> aibridge.ui.theme

### ui → database（1 处）

- aibridge\ui\persona_editor.py -> aibridge.database.database_manager