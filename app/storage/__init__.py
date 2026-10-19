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
    AgentAppDAO,
    AppCredentialDAO,
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
agent_app_dao = AgentAppDAO()
app_credential_dao = AppCredentialDAO()

# ====== 双名归一（关键：保证全进程只有一条 sqlite 连接）======
# 本项目历史上存在两条 import 路径：
#   `app.storage.*`（打包 bootloader / 新代码，如 app/apps/_scheduler_common.py）
#   `storage.*`     （源码期旧代码，如 app/bridge.py 的 `from storage import ...`）
# 若两者各自导入一次，同一份 db.py 会被执行两遍 → 进程内出现两条 sqlite 连接，
# 各自持有写锁互斥 → 间歇性 `database is locked`（写操作随机失败）。
# 这里把「包」与「db 子模块」双向登记为同一对象；db 是连接持有者，必须唯一。
import sys as _sys

_this_pkg = _sys.modules[__name__]
_other_pkg = "storage" if __name__ == "app.storage" else "app.storage"
_sys.modules.setdefault(_other_pkg, _this_pkg)

_db_mod = _sys.modules.get(__name__ + ".db")
if _db_mod is not None:
    _sys.modules.setdefault(_other_pkg + ".db", _db_mod)
