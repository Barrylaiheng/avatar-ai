"""阿凡达AI 存储包。

使用方式：
    from storage import get_conn, transaction, agents_dao, kb_dao, channels_dao, llm_dao, activation_dao, activation_orders_dao, conv_dao, msg_dao
"""

from .db import (
    get_conn,
    transaction,
    new_id,
    now_ts,
    row_to_dict,
    rows_to_dict_list,
    get_app_dir,
    get_db_path,
    reset_db_for_tests,
    DB_FILENAME,
)

# 各模块 DAO 在下一个文件实现
from .dao import (
    AgentsDAO,
    KnowledgeBaseDAO,
    DocumentsDAO,
    ChannelsDAO,
    LLMConfigDAO,
    ActivationDAO,
    ActivationOrdersDAO,
    ConversationDAO,
    ChatMessageDAO,
    RiskConfigDAO,
    PeerProfileDAO,
)

# 全局 DAO 单例（延迟初始化，避免循环 import 问题）
agents_dao = AgentsDAO()
kb_dao = KnowledgeBaseDAO()
docs_dao = DocumentsDAO()
channels_dao = ChannelsDAO()
llm_dao = LLMConfigDAO()
activation_dao = ActivationDAO()
activation_orders_dao = ActivationOrdersDAO()
conv_dao = ConversationDAO()
msg_dao = ChatMessageDAO()
risk_config_dao = RiskConfigDAO()
peer_profile_dao = PeerProfileDAO()
