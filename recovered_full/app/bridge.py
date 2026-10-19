"""JS-Python bridge: Python 业务逻辑处理层。

基于 QWebChannel 双向通信 + 存储层 DAO。
"""

from __future__ import annotations
import datetime
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

# 允许从 app 目录 import storage
_app_dir = Path(__file__).parent
_project_root = _app_dir.parent
sys.path.insert(0, str(_app_dir))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
from storage import (
    agents_dao, kb_dao, docs_dao, channels_dao, llm_dao, activation_dao,
    activation_orders_dao, conv_dao, msg_dao, risk_config_dao,
    peer_profile_dao,
    now_ts,
)
from storage.cloud_license import poll_license, _bg_refresh
from storage.retriever import UnifiedRetriever, ANCHOR_RULES, MANAGER_PROMPT
from storage.doc_parser import parse_document
from storage.llm_provider import LLMProvider

from channel.wcf_client import WcfClient, WcfMessage
from channel.oa_client import OaClient
from channel.wecom_client import WecomClient
from channel.feishu_client import FeishuClient
from channel.dingtalk_client import DingtalkClient
from channel.message_pipeline import MessagePipeline
from app_registry import APPS, get_app, list_apps


def fmt_date_short(ts):
    """unix 时间戳 → '09-02 14:30' 极简格式（和前端保持一致，用于优化历史摘要展示）"""
    try:
        dt = datetime.fromtimestamp(int(ts))
        return f"{dt.month:02d}-{dt.day:02d} {dt.hour:02d}:{dt.minute:02d}"
    except Exception:
        return "历史版本"


# ================================================================
# 渠道 code → 中文显示名（与前端 _chLabel 保持一致）
# ================================================================
_CHANNEL_LABELS: dict = {
    "wcf": "微信",
    "wecom": "企微",
    "oa": "服务号",
    "feishu": "飞书",
    "dingtalk": "钉钉",
}


# ================================================================
# 产品名（硬编码，告诉 LLM 它跑在哪个系统里）
# ================================================================
PRODUCT_NAME: str = "阿维达 AI 数字分身"



# ================================================================
# 【智能记忆·自动提炼】全局配置（完全对齐小智 AI 开源方案）
# ================================================================
# 触发阈值：每积累 N 条消息就异步跑一次 LLM 提炼记忆
#   · 小智 Java 版摘要模式默认 8 条；Python mem_local_short 要求 ≥2 条
#   · MVP 取 10（每 5 轮对话一来一回 = 10 条消息），性价比最优
MEMORY_REFINE_THRESHOLD: int = 10

# LLM 提炼提示词（system prompt）：精简版"小智时空记忆编织者"
#   · 3 维权重评分：时效性 40% + 情感强度 35% + 关联密度 25%
#   · 输出 JSON 严格对齐 MVP 现有 memories 结构（user_profile / episodic 双 Tab）
#   · 要求 LLM 自己 merge"旧记忆 + 新对话"，不是每次重来
MEMORY_REFINE_SYSTEM_PROMPT: str = """你是「智能记忆提炼助手」。你的任务是从人类和 AI 的近期对话历史中，提炼出值得跨会话记住的结构化信息，并与已有旧记忆合并，输出一段严格的 JSON。

## 三维度记忆评估（提炼时请优先保留高分信息）
| 维度         | 权重 | 判定标准 |
|-------------|-----|---------|
| 时效性       | 40% | 越新鲜的信息越要留；超过 30 天未再提及的低关联度内容可以删 |
| 情感强度     | 35% | 用户表达情绪（开心/难过/在意/愤怒）的话，必须优先留下 |
| 关联密度     | 25% | 和其他已知信息关联越多（比如"不吃香菜"和"今晚吃火锅"关联），越不能丢 |

## 记忆分类规范（必须严格遵守）
你输出的 JSON 必须包含且只包含以下 3 个字段：
{
  "enabled": true,          // 固定为 true（只要在提炼就说明用户开了记忆开关）
  "user_profile": [         // ← 长期稳定特征：身份/偏好/习惯/长期目标
    {"title": "一句话小标题（≤12字）", "content": "详细内容（≤200字）"},
    ...
  ],
  "episodic": [             // ← 近期重点（≈30天内的短期记忆）：最近聊过的具体事件/进度/待跟进/未完成承诺
    {"title": "一句话小标题（≤12字）", "content": "详细内容（≤200字）"},
    ...
  ]
}

分类规则：
1. 名字/性别/年龄/职业/所在地/饮食习惯/不喜欢的东西/长期学习目标/性格 → 放 user_profile
2. "我昨天面试了腾讯" "下周要考试" "约了朋友周五吃饭" "刚和男朋友吵架了" 这种有时效性的具体事件 → 放 episodic
3. 如果旧记忆 user_profile 里有"职业：学生"，而本轮新对话用户说"我刚毕业入职字节了" → 更新为"职业：字节跳动员工（202X 起）"，不要保留冲突旧版
4. 如果旧记忆 episodic 里的事件已经过去且今后不会再聊（比如"下周一考试"已经过了） → 直接删掉，不再保留
5. 语义高度重复的两条要合并成一条；标题不要重复
6. 任何没有明确事实价值的闲聊（比如"哈哈哈""好的""嗯"）不要提炼
7. 每类条目总数各自 ≤15 条；超过时按三维度权重分低→高淘汰

## 输出规范（非常重要，必须严格遵守）
1. 你只能输出一段合法 JSON，**不能**有任何其他文字解释、前言、后记、Markdown 标题
2. 可以用 ```json ... ``` 代码块包裹，也可以直接输出裸 JSON，两者皆可
3. 字段名必须是英文 enabled / user_profile / episodic，且每个条目只有 title 和 content 两个字段，**不能多加别的字段**
4. 如果本轮对话完全没有值得提炼的信息 → 也必须输出 JSON，只是 user_profile / episodic 保持和输入里的"旧记忆"一致即可（哪怕是空数组），**绝对不能输出空字符串或 null**
"""


class BridgeServer(QObject):
    """Python 端桥接对象，通过 QWebChannel 暴露给 JS。"""

    # Python → JS 信号
    pong = pyqtSignal(str)   # 回传 call 调用的结果（JSON 字符串）
    push = pyqtSignal(str, str)  # Python 主动推送 (action, payload_json)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 上次推送的激活快照（signature），用于只在变化时推送前端权益卡片
        self._last_act_sig = None
        # 需要"微信渠道特殊版"权限的动作（call 时统一 gate）
        self._WECHAT_ACTIONS = {
            'configure_oa', 'get_oa_verify_status', 'get_oa_status',
            'get_oa_saved_config', 'start_oa', 'stop_oa', 'get_oa_contacts',
            'oa_push_check', 'oa_env_check',
            'get_wcf_status', 'fetch_wcf_contacts', 'fetch_wcf_avatar',
            'stop_wcf', 'test_oa', 'get_wcf_health', 'test_wcf', 'start_wcf',
        }
        # RAG 检索器单例（L1 关键词 + L2 hash 占位）
        self._retriever = UnifiedRetriever()
        self._index_ready = False
        # 主窗口引用（QFileDialog 的 parent）
        self._parent_window = None
        # WCF 客户端 + 消息处理流水线（单例，App 启动就启后台线程，绝不主动开微信）
        self.wcf_client = WcfClient()
        self.pipeline: MessagePipeline | None = None
        # 公众号客户端（多渠道支持，配置后才启动）
        self.oa_client = OaClient()
        self.oa_pipeline: MessagePipeline | None = None
        # 企微客户端（CLI 轮询模式）
        self.wecom_client = WecomClient()
        self.wecom_pipeline: MessagePipeline | None = None
        # 飞书客户端（lark-cli event consume 实时流）
        self.feishu_client = FeishuClient()
        self.feishu_pipeline: MessagePipeline | None = None
        # 钉钉客户端（dws CLI 轮询模式）
        self.dingtalk_client = DingtalkClient()
        self.dingtalk_pipeline: MessagePipeline | None = None
        # 【智能记忆】异步提炼线程池（不阻塞用户回复，最多 2 个并发跑提炼，避免爆 LLM API）
        self._memory_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="memory_refine",
        )
        # LicenseSync：启动后台线程，3s 后首次同步云端授权状态
        import threading as _t
        print('[BridgeServer] 即将启动 LicenseSync 后台线程...', flush=True)
        _t.Thread(target=self._bg_sync_activation, name='LicenseSync', daemon=True).start()
        print('[BridgeServer] LicenseSync 线程已 start()', flush=True)

    def _bg_sync_activation(self):
        """后台线程：启动时先立即同步一次，之后每 60s 查一次云端授权状态，
        变了自动 push 前端权益卡片。"""
        import time as _t
        import datetime as _dt
        print('[LicenseSync] 后台线程启动，3s 后首次同步...', flush=True)
        _t.sleep(3)
        while True:
            try:
                self._get_effective_activation()
            except Exception as e:
                print(f'[LicenseSync] 后台同步异常: {e}', flush=True)
            _t.sleep(60)

    def set_parent_window(self, window):
        """设置主窗口引用（QFileDialog / 弹窗的 parent）。"""
        self._parent_window = window

    def start_channel_modules(self):
        """启动 WCF 后台线程 + 注册消息处理流水线 + 恢复服务号配置。

        设计：WCF 自己的线程每 5s 才探活一次，绝不主动调用 new Wcf() 导致拉起微信。
        服务号自动恢复：读 SQLite → 有完整凭据（AppID+Secret+Token+端口）→ 后台线程起 Flask。
        """
        self.pipeline = MessagePipeline(
            channel_client=self.wcf_client,
            agents_dao=agents_dao,
            channels_dao=channels_dao,
            conv_dao=conv_dao,
            msg_dao=msg_dao,
            llm_dao=llm_dao,
            send_message_fn=self._handle_send_message,
            risk_config_dao=risk_config_dao,
            quick_llm_fn=self.quick_llm_call,
        )
        self.wcf_client.start()

        # 服务号自动恢复——扔后台线程做（Flask 启动要等端口，别卡 UI）
        import threading as _t
        _t.Thread(target=self._auto_restore_oa, name="OA-AutoRestore", daemon=True).start()

        # 企微：有绑定就启动 pipeline + 轮询
        if self.wecom_client.connected:
            self.wecom_pipeline = MessagePipeline(
                channel_client=self.wecom_client,
                agents_dao=agents_dao,
                channels_dao=channels_dao,
                conv_dao=conv_dao,
                msg_dao=msg_dao,
                llm_dao=llm_dao,
                send_message_fn=self._handle_send_message,
                risk_config_dao=risk_config_dao,
            quick_llm_fn=self.quick_llm_call,
            )
            self.wecom_client.start()
            print("[Bridge] 企微 pipeline + 轮询已启动", flush=True)

        # 飞书：有绑定就启动 pipeline + event consume
        if self.feishu_client.connected:
            self.feishu_pipeline = MessagePipeline(
                channel_client=self.feishu_client,
                agents_dao=agents_dao,
                channels_dao=channels_dao,
                conv_dao=conv_dao,
                msg_dao=msg_dao,
                llm_dao=llm_dao,
                send_message_fn=self._handle_send_message,
                risk_config_dao=risk_config_dao,
            quick_llm_fn=self.quick_llm_call,
            )
            self.feishu_client.start()
            print("[Bridge] 飞书 pipeline + event consume 已启动", flush=True)

        # 钉钉：有绑定就启动 pipeline + 轮询
        if self.dingtalk_client.connected:
            self.dingtalk_pipeline = MessagePipeline(
                channel_client=self.dingtalk_client,
                agents_dao=agents_dao,
                channels_dao=channels_dao,
                conv_dao=conv_dao,
                msg_dao=msg_dao,
                llm_dao=llm_dao,
                send_message_fn=self._handle_send_message,
                risk_config_dao=risk_config_dao,
            quick_llm_fn=self.quick_llm_call,
            )
            self.dingtalk_client.start()
            print("[Bridge] 钉钉 pipeline + 轮询已启动", flush=True)

    def _auto_restore_oa(self):
        """后台线程：读 SQLite 里的服务号配置，自动起 Flask + 搭 pipeline。

        恢复条件：AppID + AppSecret + Token + 明确端口（>0）。
        不满足条件就静默跳过——用户自己在 UI 上配置。
        """
        import json as _json
        try:
            row = channels_dao.get("oa")
            if not row or not row.get("config_json"):
                print("[Bridge] OA 自动恢复：无保存配置，跳过", flush=True)
                return
            cfg = _json.loads(row["config_json"])
            app_id = cfg.get("app_id", "")
            app_secret = cfg.get("app_secret", "")
            token = cfg.get("token", "")
            aes_key = cfg.get("encoding_aes_key", "")
            port_raw = cfg.get("callback_port") or cfg.get("port")
            url = cfg.get("url", "")

            if not (app_id and app_secret and token):
                print("[Bridge] OA 自动恢复：凭据不完整，跳过", flush=True)
                return
            if not port_raw or int(port_raw) <= 0:
                print(f"[Bridge] OA 自动恢复：端口无效（port={port_raw}），跳过", flush=True)
                return

            port = int(port_raw)
            print(f"[Bridge] OA 自动恢复：app_id={app_id} port={port} url={url}", flush=True)

            # 灌进 oa_client
            self.oa_client.configure(
                app_id=app_id, app_secret=app_secret,
                token=token, encoding_aes_key=aes_key,
            )
            self.oa_client.callback_port = port

            # 起 Flask（start 里会等端口 + 验 API 凭据）
            status = self.oa_client.start()
            print(f"[Bridge] OA Flask 启动结果: {status}", flush=True)

            if status.get("flask_running") and status.get("api_verified"):
                # Flask 跑起来了 → 搭 pipeline
                self.oa_pipeline = MessagePipeline(
                    channel_client=self.oa_client,
                    agents_dao=agents_dao,
                    channels_dao=channels_dao,
                    conv_dao=conv_dao,
                    msg_dao=msg_dao,
                    llm_dao=llm_dao,
                    send_message_fn=self._handle_send_message,
                    risk_config_dao=risk_config_dao,
            quick_llm_fn=self.quick_llm_call,
                )
                print("[Bridge] OA pipeline 已挂载", flush=True)
            else:
                err = status.get("error", "")
                print(f"[Bridge] OA 自动恢复失败: {err}", flush=True)
        except Exception as e:
            print(f"[Bridge] OA 自动恢复异常: {e}", flush=True)

        # 启动定时消息调度器（应用市场 · 定时消息 runner）
        try:
            from app.apps.schedule_message.runner import start_scheduler
            start_scheduler()
        except Exception as e:
            print(f"[Bridge] Schedule 启动失败: {e}", flush=True)

    def stop_channel_modules(self):
        if self.pipeline is not None:
            self.pipeline.shutdown(wait=False)
        self.wcf_client.stop()
        if self.oa_pipeline is not None:
            self.oa_pipeline.shutdown(wait=False)
        self.oa_client.stop()
        if self.wecom_pipeline is not None:
            self.wecom_pipeline.shutdown(wait=False)
        self.wecom_client.stop()
        if self.feishu_pipeline is not None:
            self.feishu_pipeline.shutdown(wait=False)
        self.feishu_client.stop()
        if self.dingtalk_pipeline is not None:
            self.dingtalk_pipeline.shutdown(wait=False)
        self.dingtalk_client.stop()


    # ---------- 对外槽 ----------

    def _handle_open_in_app(self, payload: dict):
        """用系统默认浏览器打开外部 URL（API Key 注册页等）。"""
        url = (payload.get("url") or "").strip()
        if not url:
            return {"opened": False, "reason": "no_url"}
        import webbrowser
        webbrowser.open(url, new=2)
        return {"opened": True, "url": url}

    # 会跑 LLM / 耗时网络调用的 action —— 扔后台线程，主线程先 emit 占位保持 UI 流畅
    _HEAVY_ACTIONS = frozenset({
        "refine_memory_preview",
        "confirm_apply_optimize",
        "rollback_optimize",
        "send_message",
        "send_message_streaming",
        "batch_refine_memory",
        "refresh_memory",
        "import_memory",
        "get_public_ip",
        "prepare_feedback_package",
        "start_oa",
        "generate_wecom_qr",
        "fetch_wecom_contacts",
        "get_feishu_status",
        "generate_feishu_qr",
        "unbind_feishu",
        "fetch_feishu_contacts",
        "save_feishu_agent_contacts",
        "get_feishu_agent_contacts",
        "generate_feishu_user_auth",
        "poll_feishu_user_auth",
        "get_feishu_user_auth_status",
        "get_dingtalk_status",
        "generate_dingtalk_qr",
        "unbind_dingtalk",
        "fetch_dingtalk_contacts",
        "save_dingtalk_agent_contacts",
        "get_dingtalk_agent_contacts",
        # 历史记录：export_history_contact 会 list_all(limit=10000) 后逐段拉消息 + 写盘，
        # 是本地 IO 里最重的一个，扔后台避免「导出中」时主线程卡死。
        # 注意：get_all_history / get_history_session 是轻量本地查询，刻意保持同步——
        # 二者依赖「同一 action 的响应按请求顺序回」来做竞态防护，放后台线程会打乱该前提。
        "export_history_contact",
    })

    @pyqtSlot(str, str)
    def call(self, action: str, payload_json: str):
        """JS 调用入口（QWebChannel 槽）。"""
        import threading
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except json.JSONDecodeError:
            payload = {}

        print(f"[Bridge] JS→Python: action={action}, payload={payload}", flush=True)

        handler = getattr(self, f"_handle_{action}", None)
        if handler is None:
            self.pong.emit(json.dumps({"ok": False, "action": action, "error": f"未知操作: {action}"}, ensure_ascii=False))
            return

        try:
            if action in self._WECHAT_ACTIONS:
                self._require_perm("wechat", msg="微信渠道需要特殊版解锁")
        except PermissionError as e:
            self.pong.emit(json.dumps({
                "ok": False, "action": action, "error": str(e), "need_activate": True,
            }, ensure_ascii=False))
            return

        if action in self._HEAVY_ACTIONS:
            # 后台线程执行 —— 主线程立即返回，避免 UI「未响应」
            # payload 里如果有 request_id，emit pong 时用它做 action，
            # 这样前端多次并发 call 不会互相覆盖 callback key
            req_id = payload.get("request_id")
            def _run_heavy():
                try:
                    data = handler(payload)
                    emit_action = req_id or action
                    result = {"ok": True, "action": emit_action, "data": data}
                    print(f"[Bridge] action={action} → ok (后台, req_id={req_id}) | 返回: {json.dumps(result, ensure_ascii=False)[:300]}", flush=True)
                except PermissionError as e:
                    emit_action = req_id or action
                    result = {"ok": False, "action": emit_action, "error": str(e), "need_activate": True}
                    print(f"[Bridge] action={action} 拒绝: {e}", flush=True)
                except Exception as e:
                    emit_action = req_id or action
                    result = {"ok": False, "action": emit_action, "error": str(e)}
                    print(f"[Bridge] action={action} 异常: {e}", flush=True)
                self.pong.emit(json.dumps(result, ensure_ascii=False))
            threading.Thread(target=_run_heavy, daemon=True).start()
            return

        # 轻量 action 保持同步，直接在主线程跑
        try:
            data = handler(payload)
            result = {"ok": True, "action": action, "data": data}
            print(f"[Bridge] action={action} → ok | 返回: {json.dumps(result, ensure_ascii=False)[:300]}", flush=True)
        except Exception as e:
            result = {"ok": False, "action": action, "error": str(e)}
            print(f"[Bridge] action={action} 异常: {e}", flush=True)

        self.pong.emit(json.dumps(result, ensure_ascii=False))

    def send_to_js(self, action: str, payload: dict):
        """Python 主动推送消息到 JS。"""
        self.push.emit(action, json.dumps(payload, ensure_ascii=False))

    def bootstrap_payload(self) -> dict:
        """JS 桥接就绪时推送的首包。"""
        return {
            "status": "Python bridge connected",
            **self._handle_ready({}),
        }

    # ---------- 桥接测试 ----------
    def _handle_ping(self, payload):
        return {"message": "pong", "echo": payload, "server_ts": now_ts()}

    def _handle_ready(self, payload):
        # JS 首次连接就绪：返回首启状态、当前 LLM 列表、激活状态、机器码等
        # 启动时主动做一次离线 license 校验：license.dat 签名 + 机器码匹配 → 同步 SQLite
        from storage.license import verify_license_file
        if verify_license_file():
            # license.dat 有效但 SQLite 未标记激活 → 同步状态
            s = activation_dao.get_status()
            if not bool(s.get("activated")):
                from storage.license import read_license_file
                data = read_license_file() or {}
                if data.get("machine_code") and data.get("license_key"):
                    try:
                        activation_dao.activate(
                            data["license_key"], data["machine_code"]
                        )
                    except Exception as e:
                        print(f"[Bridge] 离线 license 同步失败: {e}", flush=True)
        # RAG 索引重建 + 每日记忆整理扔后台线程，不阻塞 UI 渲染
        import threading as _t
        _t.Thread(target=self._rebuild_index_from_db, name="RAG-IndexRebuild", daemon=True).start()
        _t.Thread(target=self._maybe_daily_memory_refine, name="Memory-DailyRefine", daemon=True).start()
        # 云端授权后台刷新线程（fail-silent，不影响启动）
        try:
            from storage.machine import get_machine_code as _get_mc
            _t.Thread(target=_bg_refresh, args=(_get_mc(),), name="CloudLicense-BgRefresh", daemon=True).start()
        except Exception as _e:
            print(f"[Bridge] bg_refresh 线程启动跳过: {_e}", flush=True)
        return {
            "status": "connected",
            "first_run": self._is_first_run(),
            "default_llm_id": (llm_dao.get_default() or {}).get("id"),
            "activation": self._get_effective_activation(),
            "machine_code": self._handle_get_machine_code({}).get("machine_code"),
            "retriever_stats": self._retriever.stats(),
        }

    # ---------- 机器码 / 激活 ----------
    def _handle_get_machine_code(self, payload):
        """返回当前机器码（前端展示用）。"""
        from storage.machine import get_machine_code
        return {"machine_code": get_machine_code()}

    @staticmethod
    def _is_first_run() -> bool:
        """首启判定：无任何 LLM 配置视为首次启动。"""
        return len(llm_dao.list_all()) == 0

    # ---------- 智能体管理 ----------
    def _handle_get_agents(self, payload):
        return {"agents": agents_dao.list_all()}

    def _handle_get_agent(self, payload):
        aid = payload.get("id")
        return {"agent": agents_dao.get(aid) if aid else None}

    # ---------- 智能体 ----------
    # System Prompt token 上限：免费版/正式版统一 2048
    # system prompt 越简单越好，没必要做差异化限制。
    # 行业最佳实践 sweet spot 是 80~800 tokens，超过 1500~2000 指令遵循率开始滑坡。
    # 2048 给了充足的"人设 + 风格 + 护栏 + few-shot 例子"空间，
    # 但又限制住"不付费就把整份业务知识全粘进 prompt 绕过知识库"的路径。
    _ROLE_PROMPT_TOKEN_LIMIT = 2048

    @staticmethod
    def _estimate_prompt_tokens(text: str) -> int:
        """和前端 window._estimatePromptTokens 完全同算的估算器（保前后端结果一致）。

        规则（不装 tiktoken 的轻量方案，实际偏大保守一点）：
        - CJK/假名/谚文/其他多字节 Unicode 字符：≈0.6 字 = 1 token
        - ASCII（英数/空格/标点）：≈4 字符 = 1 token
        - 每个换行 +1 token

        由于 Python 的 math.ceil 与 JS 的 Math.ceil 语义完全一致，两端结果应该一致。
        """
        if not text:
            return 0
        import math
        cjk = 0
        ascii_ = 0
        nl = 0
        for ch in text:
            code = ord(ch)
            if code == 10 or code == 13:
                nl += 1
                continue
            if (
                0x3400 <= code <= 0x4DBF  # CJK Ext A
                or 0x4E00 <= code <= 0x9FFF  # CJK Unified
                or 0x3040 <= code <= 0x30FF  # Hiragana + Katakana
                or 0xAC00 <= code <= 0xD7AF  # Hangul
                or 0xF900 <= code <= 0xFAFF  # CJK Compatibility
            ):
                cjk += 1
            elif code <= 0x7F:
                ascii_ += 1
            else:
                # 其他 Unicode（emoji 等）→ 按汉字级别保守算
                cjk += 1
        return math.ceil(cjk / 0.6) + math.ceil(ascii_ / 4.0) + nl

    def _assert_system_prompt_tokens(self, payload, action_name: str):
        """角色介绍（System Prompt）tokens 闸门：统一 4096 上限，超了直接拒绝。

        前后端双保险——前端 saveAgent 已经算一次并拦，但 DevTools 改 payload 必须这里也拦。
        """
        sp = (payload.get("system_prompt") or "").strip()
        if not sp:
            return
        used = self._estimate_prompt_tokens(sp)
        if used <= self._ROLE_PROMPT_TOKEN_LIMIT:
            return
        raise PermissionError(
            f"角色介绍过长：已使用 {used} tokens，上限 {self._ROLE_PROMPT_TOKEN_LIMIT}。"
            f"System Prompt 越简洁越好用，建议精简人设描述。"
        )

    def _assert_kb_bind_allowed(self, payload, action_name: str):
        """免费版闸门 A：未激活用户禁止 kb_ids 非空（create/update_agent 共用）。"""
        kb_ids = payload.get("kb_ids") or []
        if not kb_ids:
            return  # 空数组无限制（免费版本就可以建"空壳智能体"）
        self._require_perm("kb", msg="免费版智能体不能绑定知识库，升级入门版后才能使用")

    def _assert_learning_allowed(self, payload, action_name: str):
        """免费版闸门 A'：未激活用户禁止 memories.enabled=true 或 memories 非空（create/update_agent 共用）。
        一刀切：整个「智能学习（记忆系统）」是正式版独占功能，免费版完全不能存任何记忆条目。
        """
        memories_raw = payload.get("memories")
        if not memories_raw:
            return  # 完全没传 memories 字段 → 不限制（默认空结构）
        mem = self._parse_memory_json_safe(memories_raw)
        if not mem.get("enabled") and not mem.get("user_profile") and not mem.get("episodic"):
            return  # 全空结构 + enabled=false → 允许
        self._require_perm("memory", msg="升级标准版解锁记忆与进化")

    def _handle_create_agent(self, payload):
        self._require_perm("agent", msg="智能体数量已达上限，升级入门版解锁更多")
        self._assert_system_prompt_tokens(payload, "create_agent")
        self._assert_kb_bind_allowed(payload, "create_agent")
        self._assert_learning_allowed(payload, "create_agent")
        agent = agents_dao.create(payload)
        return {"created": bool(agent), "agent": agent}

    def _handle_update_agent(self, payload):
        self._assert_system_prompt_tokens(payload, "update_agent")
        self._assert_kb_bind_allowed(payload, "update_agent")
        self._assert_learning_allowed(payload, "update_agent")
        aid = payload.get("id")
        if not aid:
            raise ValueError("缺少 id")
        agent = agents_dao.update(aid, payload)
        return {"updated": bool(agent), "agent": agent}

    def _handle_rename_agent(self, payload):
        aid = payload.get("id")
        name = (payload.get("name") or "").strip()
        if not aid or not name:
            raise ValueError("缺少 id 或 name")
        agent = agents_dao.rename(aid, name)
        return {"renamed": bool(agent), "agent": agent}

    def _handle_delete_agent(self, payload):
        aid = payload.get("id")
        if not aid:
            raise ValueError("缺少 id")
        ok = agents_dao.delete(aid)
        return {"deleted": ok, "id": aid}

    def _handle_get_agent_recent(self, payload):
        """获取所有智能体的最近对话时间（用于卡片展示）。"""
        agents = agents_dao.list_all()
        result = {}
        for a in agents:
            aid = str(a.get("id", ""))
            convs = conv_dao.list_all(agent_id=aid, limit=1)
            latest_ts = None
            if convs:
                latest_conv = convs[0]
                latest_ts = latest_conv.get("updated_at") or latest_conv.get("created_at")
            result[aid] = latest_ts
        return {"recent": result}

    # ---------- LLM 配置 ----------
    def _handle_get_llm_providers(self, payload):
        """获取 LLM 配置列表（前端叫服务商列表，这里是用户保存的配置+内置可选模板）。"""
        saved = llm_dao.list_all()
        default = llm_dao.get_default()
        templates = [
            {"provider": "智谱AI",      "base_url": "https://open.bigmodel.cn/api/paas/v4",              "model": "glm-4-flash"},
            {"provider": "月之暗面",     "base_url": "https://api.moonshot.cn/v1",                        "model": "moonshot-v1-8k"},
            {"provider": "通义千问",     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",  "model": "qwen-turbo"},
            {"provider": "腾讯混元",     "base_url": "https://api.hunyuan.cloud.tencent.com/v1",          "model": "hunyuan-turbos-latest"},
            {"provider": "字节豆包",     "base_url": "https://ark.cn-beijing.volces.com/api/v3",           "model": "doubao-seed-1-6-251015"},
            {"provider": "自定义",       "base_url": "",                                                    "model": ""},
        ]
        return {
            "configs": saved,
            "default_id": default["id"] if default else None,
            "templates": templates,
        }

    def _handle_save_llm_provider(self, payload):
        cfg = llm_dao.upsert(payload)
        return {"saved": True, "config": cfg}

    def _handle_delete_llm_provider(self, payload):
        cid = payload.get("id")
        if not cid:
            raise ValueError("缺少 id")
        ok = llm_dao.delete(cid)
        return {"deleted": ok, "id": cid}

    def _handle_skip_llm_setup(self, payload):
        """首启向导跳过 LLM 配置：写入占位记录，允许先进入主界面。

        用户可以先看界面再到「设置 → LLM 配置」中新增真实配置。
        占位记录：名称="稍后配置"，其余字段空串，is_default=1。
        后续用户新增真实配置时，这条占位记录可在设置页手动删除，或新增时通过
        set_default 切换（默认切换时原默认会被取消 default 标记）。
        """
        placeholder = {
            "name": "稍后配置",
            "provider": "Skip",
            "base_url": "",
            "api_key": "",   # 空 key，llm_dao.upsert 内 DPAPI 会加密空串
            "model": "",
            "is_default": 1,
        }
        cfg = llm_dao.upsert(placeholder)
        return {"skipped": True, "config": cfg}

    def _handle_set_default_llm_provider(self, payload):
        cid = payload.get("id")
        if not cid:
            raise ValueError("缺少 id")
        cfg = llm_dao.get(cid)
        if not cfg:
            raise ValueError("配置不存在")
        # 复用 upsert 语义：is_default=True 时会自动清其他默认
        llm_dao.upsert({**cfg, "is_default": True})
        return {"ok": True, "default_id": cid}

    def _handle_test_llm_connection(self, payload):
        """真实 LLM 连接测试：用 LLMProvider 发 ping 消息测连通 + 延迟。

        入参（前端表单或已保存配置）：
            provider  : 服务商标识（DeepSeek/OpenAI/...，仅展示用）
            base_url  : API 接口地址
            api_key   : API 密钥（明文，前端缓存或表单输入）
            model     : 模型名称
        返回：{connected, latency_ms, reason, model}
        """
        provider = (payload.get("provider") or "").strip()
        base_url = (payload.get("base_url") or "").strip()
        model    = (payload.get("model") or "").strip()
        api_key  = (payload.get("api_key") or "").strip()
        if not base_url or not model or not api_key:
            return {"connected": False, "latency_ms": 0,
                    "reason": "参数不完整（接口地址/密钥/模型）", "model": model}
        p = LLMProvider(base_url, api_key, model)
        r = p.test_connection()
        r["provider"] = provider
        return r

    # ---------- 知识库 ----------
    def _handle_get_kb_list(self, payload):
        return {"kb_list": kb_dao.list_all()}

    def _handle_get_kb(self, payload):
        kid = payload.get("id")
        if not kid:
            return None
        kb = kb_dao.get(kid)
        docs = docs_dao.list_by_kb(kid) if kb else []
        return {"kb": kb, "docs": docs}

    def _handle_create_kb(self, payload):
        kb = kb_dao.create(payload)
        return {"created": bool(kb), "kb": kb}

    def _handle_update_kb(self, payload):
        kid = payload.get("id")
        if not kid:
            raise ValueError("缺少 id")
        kb = kb_dao.update(kid, payload)
        return {"updated": bool(kb), "kb": kb}

    def _handle_delete_kb(self, payload):
        kid = payload.get("id")
        if not kid:
            raise ValueError("缺少 id")
        ok = kb_dao.delete(kid)
        return {"deleted": ok, "id": kid}

    def _handle_add_kb_document(self, payload):
        """加入知识库文档：调用 doc_parser 解析 → 切片 → 写 docs_dao + 喂 UnifiedRetriever。

        入参：
            kb_id      : 知识库 ID（必填）
            file_path  : 文件绝对路径（必填）
            name       : 文件名（不传则从路径取 stem）
            size_bytes : 文件字节数（不传则从文件 stat 读）
        """
        kb_id = payload.get("kb_id")
        file_path = payload.get("file_path")
        if not kb_id:
            raise ValueError("缺少 kb_id")
        if not file_path:
            raise ValueError("缺少 file_path")

        p = Path(file_path)
        name = (payload.get("name") or "").strip() or p.name
        size_bytes = int(payload.get("size_bytes") or 0) or (
            p.stat().st_size if p.exists() else 0
        )

        # 先写一条 pending 记录，拿到 doc_id
        doc = docs_dao.create({
            "kb_id": kb_id,
            "name": name,
            "file_path": file_path,
            "size_bytes": size_bytes,
            "chunk_count": 0,
            "status": "pending",
        })
        did = doc["id"]

        # 调用 doc_parser 解析
        parsed = parse_document(file_path)
        if parsed.get("error"):
            docs_dao.update_status(did, "error", error=parsed["error"])
            return {
                "added": False,
                "doc": docs_dao.get(did),
                "error": parsed["error"],
            }

        chunks = parsed["chunks"]
        # ===== 关键修复：将切片内容真实落库到 kb_chunk 表 =====
        saved_count = docs_dao.save_chunks(did, kb_id, chunks)
        # 喂 UnifiedRetriever（按 doc_id/kb_id 隔离）
        info = self._retriever.add_text(
            parsed["text"],
            source=p.stem,
            kb_id=kb_id,
            doc_id=did,
        )
        # 更新 docs_dao：写入 chunk_count + status=ok
        doc = docs_dao.update_status(did, "ok", chunk_count=len(chunks))
        return {
            "added": True,
            "doc": doc,
            "chunk_count": len(chunks),
            "chunk_ids": info.get("chunk_ids", []),
            "chunks_saved": saved_count,  # 确认落库数量
        }

    def _handle_update_kb_document(self, payload):
        did = payload.get("id")
        if not did:
            raise ValueError("缺少 id")
        status = payload.get("status")
        chunk_count = payload.get("chunk_count")
        error = payload.get("error", "")
        doc = docs_dao.update_status(did, status, chunk_count=chunk_count, error=error)
        return {"updated": bool(doc), "doc": doc}

    def _handle_delete_kb_document(self, payload):
        did = payload.get("id")
        if not did:
            raise ValueError("缺少 id")
        # 同步删除 UnifiedRetriever 中该文档的所有 chunks
        removed = self._retriever.remove_document(did)
        ok = docs_dao.delete(did)
        return {"deleted": ok, "id": did, "chunks_removed": removed}

    def _handle_search_kb(self, payload):
        """RAG 检索：L1 关键词 + L2 向量融合排序。

        入参：
            query  : 查询文本（必填）
            top_k  : 返回条数（默认 5）
            kb_ids : 限定知识库 ID 列表（可选，不传则全局检索）
        """
        query = (payload.get("query") or "").strip()
        if not query:
            return {"results": [], "stats": self._retriever.stats()}
        top_k = int(payload.get("top_k") or 5)
        kb_ids = payload.get("kb_ids") or None
        results = self._retriever.search(query, top_k=top_k, kb_ids=kb_ids)
        return {
            "query": query,
            "top_k": top_k,
            "results": results,
            "stats": self._retriever.stats(),
        }

    def _handle_build_kb_graph(self, payload):
        """基于指定知识库的真实切片，构造知识图谱 nodes + edges。

        目标：完全替换前端的静态「智能家电客服」mock 数据。

        算法（零 jieba 外部依赖，纯正则 + n-gram + 停用词 + 分类启发）：
          1. 从 kb_chunk 表拉该 kb_id 所有切片；按 doc_id 聚合得到每个文档的全量文本；
          2. 节点分层：
             - core    : 1 个（知识库名称）
             - chapter : 每个文档 1 个（文档名，可去除扩展名）
             - section : 每文档里显式的 "第N章/第N节/1.1、1.2..." 等标题（正则抽取）
             - keyword : 每文档中文 2~4-gram 打分排名 Top-N（去停用词 + 去纯数字/标点）
             - entity  : 正则 + 后缀白名单抽取的 人名/机构/价格/产品型号 等命名实体
          3. 边：
             - core ↔ 每个 chapter
             - chapter ↔ 该文档下的 section / 高频 keyword / 相关 entity
             - section ↔ section 内命中的 keyword / entity
             - 同文档 keyword 之间 top co-occurrence（跨 2 个 chunk 都出现过的词两两连边，
               每文档最多连 6 条，防止爆炸）
          4. 总量限制：总节点 ≤ 48（超过时按类别权重截断 core/chapter/section/entity 优先保），
             总边 ≤ 96。
        """
        import sqlite3 as _sqlite3
        from collections import Counter, defaultdict
        from urllib.parse import quote

        # ======== 类型健壮性修复：任何 Row / dict / 意外 str 输入都先转 dict。
        #   历史教训：sqlite3.Row 支持 r[key] 但 **不支持 r.get(key)**，
        #   真实运行里 dao 偶发返回 Row（或某些连接没走 row_factory 统一封装）
        #   或 payload 被二次 JSON 化后变成字符串，都会导致：
        #     AttributeError: 'str' object (或 'sqlite3.Row') has no attribute 'get'
        #   这就是用户现在看到的报错。这里在函数入口处统一"净化"：
        def _as_dict(obj, defaults=None):
            """把 dict / sqlite3.Row / Mapping-like 对象统一成 dict；意外 str/None 转成 {}。
            对于完全非映射对象返回 defaults（默认 {}），绝不抛 AttributeError。"""
            if obj is None:
                return dict(defaults) if defaults else {}
            # 先处理 dict 原生子类
            if isinstance(obj, dict):
                if not defaults:
                    return dict(obj)
                merged = dict(defaults)
                merged.update(obj)
                return merged
            # sqlite3.Row：支持 keys() / 下标
            if isinstance(obj, _sqlite3.Row):
                d = {k: obj[k] for k in obj.keys()}
                if defaults:
                    m = dict(defaults)
                    m.update(d)
                    return m
                return d
            # 其它对象：实现了 keys() + __getitem__ 的类映射（OrderedDict / UserDict / Pydantic 旧对象）
            if hasattr(obj, 'keys') and callable(getattr(obj, 'keys')):
                try:
                    ks = list(obj.keys())
                    d = {}
                    for k in ks:
                        try: d[k] = obj[k]
                        except Exception: pass
                    if defaults:
                        m = dict(defaults)
                        m.update(d)
                        return m
                    return d
                except Exception:
                    pass
            # 意外的字符串/字节/列表：兜底返回空 dict（或 defaults）
            return dict(defaults) if defaults else {}

        def _as_list_of_dicts(iterable):
            """list_chunks_by_kb / list_by_kb 的返回统一成 list[dict]，单条非映射就静默丢弃并打印 warning。"""
            if not iterable:
                return []
            out = []
            for idx, x in enumerate(iterable):
                d = _as_dict(x)
                if not d and x is not None and not isinstance(x, dict) and not isinstance(x, _sqlite3.Row):
                    # 只有完全不是映射的情况才警告
                    print(f"[Bridge][build_kb_graph] 警告：切片 #{idx} 不是 dict/Row（实际 {type(x).__name__}），已跳过。raw[:80]={str(x)[:80]!r}", flush=True)
                    continue
                # _as_dict 对 None/""/[] 也会返回 {}，正常空记录保留（空 content 也应参与聚合）
                out.append(d)
            return out

        # ======== 入口统一净化 3 个对象：payload / kb / all_chunks ========
        #   修复用户当前报错 "'str' object has no attribute 'get'" ——
        #   前端 JSON.stringify 后传过来的 payload 可能被某处二次序列化或 fallback 时
        #   把 kbId 直接包成字符串 payload（不是 dict）也走这里了。
        if isinstance(payload, str):
            try:
                import json as _json
                payload = _json.loads(payload) if payload else {}
            except Exception:
                payload = {}
        payload = _as_dict(payload, {})

        kb_id = payload.get("kb_id") or payload.get("id")
        if not kb_id:
            raise ValueError("缺少 kb_id")
        kb_raw = kb_dao.get(kb_id)
        kb = _as_dict(kb_raw)
        if not kb or not kb.get("id"):
            return {"nodes": [], "edges": [], "meta": {"kb_id": kb_id, "error": "kb not found"}}

        # 1. 拉真实切片 + 按 doc_id 聚合（净化后保证 list[dict]）
        raw_chunks = docs_dao.list_chunks_by_kb(kb_id)
        all_chunks = _as_list_of_dicts(raw_chunks)
        if not all_chunks:
            # 空知识库：返回仅 core 节点，便于前端友好提示（但节点数=0前端会走空态）
            return {"nodes": [], "edges": [], "meta": {"kb_id": kb_id, "docs": 0, "chunks": 0}}

        docs = defaultdict(list)
        doc_name_map = {}
        for c in all_chunks:
            # 到这里 c 已经是纯 dict：c.get / c["..."] 两种方式都不会 AttributeError 了
            doc_id = c.get("doc_id")
            if not doc_id:
                continue
            docs[doc_id].append(c.get("content") or "")
            doc_name_map[doc_id] = (c.get("doc_name")
                                    or c.get("document_name")
                                    or c.get("name")
                                    or c.get("doc_id")
                                    or "未命名文档")

        # ------- 中文 n-gram + 停用词工具（本函数局部工具，避免全局污染）-------
        _CN_STOPWORDS = set("""
的 了 和 是 在 也 就 都 而 及 与 或 一个 一些 一下 一样 一种 可以 已经 因为 但是 不过
如果 这样 那样 这个 那个 这些 那些 所有 我们 你们 他们 它们 自己 什么 怎么 为什么 因此
以及 对于 关于 然后 还有 同时 并且 不是 不会 不能 不要 没有 进行 通过 提供 包含 拥有
基于 根据 目前 现在 之前 之后 比如 例如 其中 以及 以及
""".split())
        # 英文停用词（MD/HTML 结构里常见）
        _EN_STOPWORDS = {"the", "and", "for", "with", "you", "that", "this", "from", "have", "are",
                         "was", "were", "been", "will", "would", "your", "our", "its", "they", "their"}

        def _tokenize(text: str):
            """纯中文+ASCII混合的轻量分词：中文按2-4字窗口，英文/数字按空格/标点切成词。

            优化：n-gram 中必须至少包含一个"有意义汉字"——排除 全是"的/一/个/是/了"
            这类最常用单字组成的 2-gram（否则「的一」「一个」「一是」这类组合会
            以 tf>10 的频率占满关键词列表）。
            """
            toks = []
            BAD_CN_CHARS = set("的一是了在和就都也就与及有这那为会可要从对我你他她它到被")
            for segment in re.split(r"[\s\u3000\u00a0]+|(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])(?=[\u4e00-\u9fff])", text):
                if not segment:
                    continue
                if re.fullmatch(r"[A-Za-z0-9_\.\-]+", segment):
                    w = segment.lower().strip(".-")
                    if 2 <= len(w) <= 16 and w not in _EN_STOPWORDS and not w.isdigit():
                        toks.append(w)
                else:
                    cn_chars = re.findall(r"[\u4e00-\u9fff]", segment)
                    for L in (2, 3, 4):
                        for i in range(0, len(cn_chars) - L + 1):
                            ngram = "".join(cn_chars[i:i + L])
                            if ngram in _CN_STOPWORDS:
                                continue
                            # 过滤：全由 BAD_CN_CHARS 组成 → 丢弃
                            if all(ch in BAD_CN_CHARS for ch in ngram):
                                continue
                            # 过滤：n-gram 里有 BAD_CN_CHARS 超过一半 → 丢弃（比如"的产品"、"一个产"）
                            if sum(1 for ch in ngram if ch in BAD_CN_CHARS) * 2 > len(ngram):
                                continue
                            if "\u4e00" <= ngram[0] <= "\u9fff":
                                toks.append(ngram)
            return toks

        def _extract_entities(text: str, doc_label: str) -> list[tuple[str, str]]:
            """返回 [(label, category)]；category ∈ {entity_price, entity_org, entity_person, entity_product}。

            本函数做了去噪处理：
              - 价格/产品型号不做清洗，直接保留。
              - 「XX公司/XX团队/XX事业部」这类后缀：要求匹配主体部分（2~6 字）完全在
                一组"机构前缀/核心词"集合内（核心词白名单 + 机构白名单），避免把
                「分别来自哪几家公司」「设有分公司」这类句内非机构名当成 org。
              - 人名前缀 CEO/CTO/CPO 等只抓 2~3 字纯中文名主体 + 非机构/人名黑名单。
              - 机构词白名单（硬匹配）优先级最高，保证大厂/知名院校名能命中。
            """
            found = []  # (label, cat)
            ORG_PREFIX_CORES = {
                "腾讯", "微信", "阿里", "阿里巴巴", "淘宝", "字节跳动", "抖音", "火山",
                "百度", "京东", "小米", "华为", "美团", "拼多多", "滴滴", "网易",
                "蚂蚁", "蚂蚁金服", "蚂蚁集团", "用户增长", "AI",
                "核心", "创始", "研发", "清华", "北大", "中科院", "浙大", "深圳",
                "北京", "上海", "CMU", "中科院", "科学院",
            }
            PERSON_STOP = {"曾任", "历任", "曾在", "先后", "担任", "兼任"}

            # 1) 价格
            for m in re.finditer(r"¥?\s*\d+(?:\.\d+)?\s*元(?:/[年月天])?", text):
                found.append((m.group(0).replace(" ", ""), "entity_price"))
            # 2) 产品型号
            for m in re.finditer(r"\b[A-Z]{1,6}\d{2,4}\w*\b", text):
                found.append((m.group(0), "entity_product"))
            # 3) 机构后缀白名单（严格清洗：主体必须命中 ORG_PREFIX_CORES，且不含"的/哪/几"等问句/助词噪声）
            ORG_BODY_STOP = {"的", "哪", "几", "分别", "设有", "来自", "介绍", "毕业于", "现有", "全职",
                             "超过", "担任", "曾任", "历任", "先后", "以上", "占比", "核心",
                             "创始", "研发", "销售", "管理", "运营", "产品", "工程", "设计",
                             "总部", "分公司"}  # 分公司本身是地理词，不是机构主体
            for suffix in ("公司", "集团", "事业部", "实验室", "Lab", "LAB", "团队", "大学", "学院", "研究院"):
                p = re.compile(rf"([\u4e00-\u9fffA-Za-z0-9]{{2,12}}?){re.escape(suffix)}")
                for m in p.finditer(text):
                    core = m.group(1)
                    core_plain = core.strip()
                    # 主体里含有问句/助词噪声字 → 直接丢弃（避免把"分别来自哪几家公司"当 org）
                    if any(ch in core_plain for ch in ORG_BODY_STOP):
                        continue
                    # 长度过滤：主体长度 2~8 更合理（中文公司名不会一大串）
                    if not (2 <= len(core_plain) <= 10):
                        continue
                    # 核心词白名单：主体要命中核心前缀（腾讯/微信/阿里/字节/AI 等）
                    if not any(k in core_plain for k in ORG_PREFIX_CORES):
                        continue
                    label = core_plain + suffix
                    found.append((label, "entity_org"))
            # 4) 机构/院校白名单（特殊词，无后缀也要命中）
            for org in ("中科院", "清华大学", "北京大学", "浙江大学", "清华", "北大", "浙大",
                        "微信事业部", "AI Lab", "用户增长团队", "腾讯", "阿里",
                        "阿里巴巴", "字节跳动", "淘宝", "抖音"):
                if org in text:
                    found.append((org, "entity_org"))
            # 5) 人名（CEO/CTO/CPO + 2-3字中文名）
            for m in re.finditer(
                r"(CEO|CTO|CPO|创始人|首席执行官|首席技术官|首席产品官)\s*([\u4e00-\u9fff]{2,3})",
                text,
            ):
                name = m.group(2)
                if name in PERSON_STOP:
                    continue
                found.append((name, "entity_person"))
            # 去重
            seen = set()
            uniq = []
            for label, cat in found:
                lbl = label.strip()
                if len(lbl) < 2:
                    continue
                key = (lbl, cat)
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(key)
            return uniq

        def _extract_section_titles(text: str) -> list[str]:
            """抽取显式章节标题，如「第一章 xxx」「1.1 xxx」。

            关键：对「第一章」这类模式，只抓「章/节」+ 后面紧跟的 4~14 字作为标题主体，
                 避免因切片「章」标题后面紧接着正文（比如 CSV 的 正文 列 直接接一长段）
                 导致整条 section label 变成"章标题 + 大半段正文"。
            """
            result = []
            seen = set()

            # 模式1：第一章/第一节 + 短标题（章 或 节 后不超过 18 字就遇到中文句号或逗号就截断）
            pat_zh = re.compile(r"第[一二三四五六七八九十百]+[章节]\s*.{0,26}?")
            for m in pat_zh.finditer(text):
                s = m.group(0).strip()
                if len(s) < 2:
                    continue
                # 如果包含中文句号/逗号，截断到句号前
                for sep in "。，；;,.\n":
                    if sep in s:
                        s = s.split(sep)[0]
                s = re.sub(r"\s+", " ", s).strip()
                s = s[:22]
                if len(s) >= 2 and s not in seen:
                    seen.add(s)
                    result.append(s)

            # 模式2：数字编号 1.1 / 2.3.4 + 标题 （最多取编号+14字标题主体，避免吞并正文）
            pat_num = re.compile(r"\d+(?:\.\d+)+\s+.{0,22}")
            for m in pat_num.finditer(text):
                s = m.group(0).strip()
                for sep in "。，；;,.\n|":
                    if sep in s:
                        s = s.split(sep)[0]
                s = re.sub(r"\s+", " ", s).strip()[:22]
                if len(s) >= 2 and s not in seen:
                    seen.add(s)
                    result.append(s)

            # 模式3：Markdown bullet（只取第一个字符 2~14 字；不抓整段）
            pat_md = re.compile(r"^\s*[-*]\s+[\u4e00-\u9fffA-Za-z0-9]{2,14}", flags=re.MULTILINE)
            for m in pat_md.finditer(text):
                s = m.group(0).strip(" \t\r\n-*").strip()
                if len(s) >= 2 and s not in seen:
                    seen.add(s)
                    result.append(s)

            return result[:10]

        # ------- 2. 逐文档遍历，收集素材 -------
        nodes_map: dict[str, dict] = {}   # id -> node dict
        edges_list: list[tuple[str, str]] = []

        def _add_node(nid: str, label: str, category: str, desc: str = ""):
            if nid in nodes_map:
                return
            if len(label) > 24:
                label = label[:22] + "…"
            nodes_map[nid] = {
                "id": nid,
                "label": label,
                "category": category,
                "desc": desc or label,
            }

        def _add_edge(a: str, b: str):
            if a == b:
                return
            key = (a, b) if a < b else (b, a)
            edges_list.append(key)

        core_id = "core"
        _add_node(core_id, kb.get("name") or f"知识库 {kb_id[:8]}", "core",
                  f"当前知识库 · 共 {len(docs)} 文档 {len(all_chunks)} 切片")

        # 限制数量的配额（避免图爆炸）
        MAX_KEYWORDS_PER_DOC = 5
        MAX_ENTITIES_PER_DOC = 8
        MAX_SECTION_PER_DOC  = 4   # 每文档最多保留 4 条章节标题（9文档×4=36上限，留余 node 给关键词/实体）
        MAX_COOC_EDGES_PER_DOC = 6
        GLOBAL_SECTION_LABEL_MAX = 18  # 全局章节标签最多留 18 条（9文档 × 重复2次 CSV 模板 的去重后就合理了）

        # 为了 category=keyword 的 node 去重（不同文档可能产出同名 keyword → 合并成一个节点，再连各自的 chapter）
        keyword_to_docs: dict[str, set[str]] = defaultdict(set)

        # 全局章节标签去重（多份 CSV/模板会产出"第一章 产品介绍"的重复 section，全局只保留一条连多个 chapter）
        section_label_to_id: dict[str, str] = {}

        for doc_id, doc_chunks in docs.items():
            doc_label_raw = doc_name_map.get(doc_id) or f"文档 {doc_id[:8]}"
            doc_label = re.sub(r"\.(txt|md|markdown|csv|html?|json|log|pdf|docx|pptx|xlsx|epub|doc|ppt)$",
                               "", doc_label_raw, flags=re.IGNORECASE)
            if len(doc_label) > 22:
                doc_label = doc_label[:20] + "…"
            chapter_id = f"ch_{doc_id}"
            _add_node(chapter_id, doc_label, "chapter",
                      f"文档：{doc_label_raw} · 切片 {len(doc_chunks)} 段")
            _add_edge(core_id, chapter_id)

            full_text = "\n".join(doc_chunks)

            # ---- section 标题
            section_titles = _extract_section_titles(full_text)[:MAX_SECTION_PER_DOC]
            section_ids = []
            for title in section_titles:
                if title in section_label_to_id:
                    sid = section_label_to_id[title]
                else:
                    if len(section_label_to_id) >= GLOBAL_SECTION_LABEL_MAX:
                        break  # 超过全局章节上限，不再加新章节节点
                    sid = f"sec_{doc_id}_{len(section_label_to_id)}"
                    _add_node(sid, title, "section", f"章节标题：{title}")
                    section_label_to_id[title] = sid
                _add_edge(chapter_id, sid)
                section_ids.append(sid)

            # ---- 关键词：chunk 级 token 计数（避免把跨 chunk 的噪声放大）
            tf_global = Counter()
            chunk_token_sets = []  # 每 chunk 的 token 集合，用于 co-occurrence
            for chunk_text in doc_chunks:
                toks = _tokenize(chunk_text)
                tf_global.update(toks)
                chunk_token_sets.append(set(toks))

            # 关键词打分 = tf * (1.0 + 0.3 * len(tok)) + df * 0.6
            # 门槛要求：df ≥ 1，tf + df ≥ 4（纯"只在某 chunk 出现 1 次"的 1-gram 噪声直接丢）
            doc_token_df = Counter()
            for st in chunk_token_sets:
                doc_token_df.update(st)
            scored = []
            for tok, tf in tf_global.items():
                df = doc_token_df[tok]
                if tf + df < 3:
                    continue
                if re.fullmatch(r"[0-9零〇一二三四五六七八九十百千两\.]+", tok):
                    continue
                if len(tok) < 2 or len(tok) > 6:
                    continue
                score = tf * (1.0 + 0.3 * len(tok)) + df * 0.6
                scored.append((score, tok))
            scored.sort(reverse=True)
            kw_per_doc = []
            for _, tok in scored[:MAX_KEYWORDS_PER_DOC * 3]:
                if len(kw_per_doc) >= MAX_KEYWORDS_PER_DOC:
                    break
                # 去重：同一个 2-gram 是另一个 3-gram 的子串时，保留更长的
                if any(tok in k and tok != k for k in kw_per_doc):
                    continue
                if any(k in tok and tok != k for k in kw_per_doc):
                    continue
                kw_per_doc.append(tok)
            for kw in kw_per_doc:
                kwid = f"kw_{quote(kw, safe='')}"  # URL encode 中文做 id
                _add_node(kwid, kw, "keyword", f"关键词：{kw}")
                _add_edge(chapter_id, kwid)
                keyword_to_docs[kw].add(doc_id)

            # 每文档内 co-occurrence 边：任意两关键词在同一个 chunk 同时出现的，两两连一次
            # （只连 kw_per_doc 内部，避免外部同名词污染；连边时按 df 乘积最大的 前 N 条）
            cooc = []
            for i in range(len(kw_per_doc)):
                for j in range(i + 1, len(kw_per_doc)):
                    a, b = kw_per_doc[i], kw_per_doc[j]
                    pair_df = 0
                    for st in chunk_token_sets:
                        if a in st and b in st:
                            pair_df += 1
                    if pair_df > 0:
                        cooc.append((pair_df, a, b))
            cooc.sort(reverse=True)
            for _, a, b in cooc[:MAX_COOC_EDGES_PER_DOC]:
                _add_edge(f"kw_{quote(a, safe='')}", f"kw_{quote(b, safe='')}")

            # ---- entities
            entities = _extract_entities(full_text, doc_label)[:MAX_ENTITIES_PER_DOC]
            for label, cat in entities:
                eid = f"ent_{quote(label, safe='')}_{cat}"
                cat_short = "entity"  # 前端 color category 统一叫 entity，价格/组织/人不再细分颜色
                _add_node(eid, label, cat_short, f"实体：{label} ({cat})")
                _add_edge(chapter_id, eid)
                # 若某个 section 标题里含该实体 label 片段，也连到 section
                short_lbl = label[:3]
                for sid in section_ids:
                    if short_lbl in nodes_map[sid]["label"]:
                        _add_edge(sid, eid)

        # ------- 3. 跨文档 keyword 合并边：如果 2 个文档都拥有同一个 keyword，把它们通过 keyword 自然连
        # （已经由 chapter -> kwid 完成了；只要 keyword id 相同，天然就连上了，不用额外边）

        # ------- 4. 去重 + 限总量 -------
        edges_uniq = sorted(set(edges_list))

        def _cat_weight(cat: str) -> int:
            # 截断优先级：核心/章节/章节标题/实体 优先保；keyword 最多，可被截
            return {"core": 1, "chapter": 2, "section": 3, "entity": 4, "keyword": 5}.get(cat, 9)

        MAX_NODES = 60
        MAX_EDGES = 110
        if len(nodes_map) > MAX_NODES:
            ordered = sorted(nodes_map.values(), key=lambda n: (_cat_weight(n["category"]), -len(n["label"])))
            keep = ordered[:MAX_NODES]
            keep_ids = {n["id"] for n in keep}
            nodes_map = {n["id"]: n for n in keep}
            edges_uniq = [(a, b) for a, b in edges_uniq if a in keep_ids and b in keep_ids]
        if len(edges_uniq) > MAX_EDGES:
            # 截断边：core/chapter 相关边优先保
            def _e_priority(e):
                a, b = e
                ca = nodes_map.get(a, {}).get("category", "?")
                cb = nodes_map.get(b, {}).get("category", "?")
                return min(_cat_weight(ca), _cat_weight(cb))
            edges_uniq.sort(key=_e_priority)
            edges_uniq = edges_uniq[:MAX_EDGES]

        nodes_out = list(nodes_map.values())
        edges_out = [{"source": a, "target": b} for a, b in edges_uniq]
        return {
            "nodes": nodes_out,
            "edges": edges_out,
            "meta": {
                "kb_id": kb_id,
                "kb_name": kb.get("name"),
                "docs": len(docs),
                "chunks": len(all_chunks),
                "nodes": len(nodes_out),
                "edges": len(edges_out),
            },
        }

    def _handle_get_kb_document_chunks(self, payload):
        """返回某文档的切片预览（优先从数据库读取真实落库数据，回退到文件重新解析）。"""
        did = payload.get("doc_id") or payload.get("id")
        if not did:
            raise ValueError("缺少 doc_id")
        
        # ===== 关键修复：优先从数据库读取真实切片 =====
        db_chunks = docs_dao.get_chunks_by_doc(did)
        if db_chunks:
            preview_len = int(payload.get("preview") or 120)
            chunks = []
            for c in db_chunks:
                content = c.get("content") or ""
                chunks.append({
                    "position": c.get("sort_order", 0),
                    "char_count": c.get("char_count") or len(content),
                    "preview": content[:preview_len].replace("\n", " "),
                })
            return {
                "doc_id": did,
                "chunk_count": len(chunks),
                "chunks": chunks,
                "source": "database",  # 标记来源为数据库
            }

        # 回退：数据库没数据时，从文件重新解析（兼容旧数据或异常情况）
        doc = docs_dao.get(did)
        if not doc:
            raise ValueError(f"文档不存在: {did}")
        file_path = doc.get("file_path") or ""
        if not file_path or not Path(file_path).exists():
            return {
                "doc_id": did,
                "file_path": file_path,
                "chunks": [],
                "error": "数据库无切片且文件不存在",
            }
        preview_len = int(payload.get("preview") or 120)
        parsed = parse_document(file_path)
        if parsed.get("error"):
            return {"doc_id": did, "file_path": file_path, "chunks": [],
                    "error": parsed["error"]}
        chunks = []
        for c in parsed["chunks"]:
            content = c.get("content") or ""
            chunks.append({
                "position": c.get("position", 0),
                "char_count": c.get("char_count") or len(content),
                "preview": content[:preview_len].replace("\n", " "),
            })
        return {
            "doc_id": did,
            "file_path": file_path,
            "chunk_count": len(chunks),
            "chunks": chunks,
            "source": "file",
        }

    def _rebuild_index_from_db(self) -> dict:
        """启动时从 kb_document 表恢复 UnifiedRetriever 索引。

        策略：遍历 status=ok 的文档记录，按 file_path 重新解析 + 喂索引。
        文件不存在的跳过（不报错），保留 SQLite 记录。
        """
        if self._index_ready:
            return {"rebuilt": False, "reason": "already_ready"}
        # 拉取所有知识库的所有文档
        all_kbs = kb_dao.list_all()
        added_docs = 0
        added_chunks = 0
        missing_files = 0
        for kb in all_kbs:
            kid = kb["id"]
            for doc in docs_dao.list_by_kb(kid):
                if doc.get("status") != "ok":
                    continue
                fp = doc.get("file_path") or ""
                if not fp or not Path(fp).exists():
                    missing_files += 1
                    continue
                parsed = parse_document(fp)
                if parsed.get("error"):
                    continue
                self._retriever.add_text(
                    parsed["text"],
                    source=Path(fp).stem,
                    kb_id=kid,
                    doc_id=doc["id"],
                )
                added_docs += 1
                added_chunks += len(parsed["chunks"])
        self._index_ready = True
        print(
            f"[Bridge] RAG 索引恢复完成: docs={added_docs} "
            f"chunks={added_chunks} missing_files={missing_files}",
            flush=True,
        )
        return {
            "rebuilt": True,
            "docs_added": added_docs,
            "chunks_added": added_chunks,
            "missing_files": missing_files,
            "stats": self._retriever.stats(),
        }

    # ---------- 文件选择通道（QFileDialog） ----------
    def _handle_pick_kb_document_file(self, payload):
        """弹出原生文件选择框，返回选中文件的绝对路径。

        HTML <input type=file> 受浏览器安全限制拿不到本地真实路径，
        必须走 Python QFileDialog 通道。

        入参：无（或 filters 自定义过滤）
        返回：
            {picked: True, file_path, name, size_bytes}  选中文件
            {picked: False, reason: 'canceled'}  用户取消
        """
        from PyQt6.QtWidgets import QFileDialog

        # 文件过滤器（对齐 doc_parser 支持的格式）
        filters = "知识库文档 (*.txt *.md *.markdown *.csv *.html *.htm *.json *.log *.pdf *.docx *.pptx *.xlsx *.epub);;所有文件 (*.*)"

        file_path, _ = QFileDialog.getOpenFileName(
            self._parent_window,
            "选择知识库文档",
            "",  # 默认目录（空 = 用户上次目录）
            filters,
        )
        if not file_path:
            return {"picked": False, "reason": "canceled"}

        p = Path(file_path)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        return {
            "picked": True,
            "file_path": str(p),
            "name": p.name,
            "size_bytes": size,
        }

    def _handle_pick_export_path(self, payload):
        """弹「另存为」对话框，选择导出知识库 zip 的保存路径。

        完全镜像现有已验证可用的 _handle_save_issues_file 的调用方式：
            file_path, _ = QFileDialog.getSaveFileName(
                self._parent_window,
                "导出标注问题为 JSON",
                default_name,   # ← 只传文件名，不带目录
                "JSON 文件 (*.json);;所有文件 (*.*)",
            )

        getSaveFileName 的 parent / default 组合在不同机器上有差异，
        所以这里：
          1) 先试 parent=_parent_window + default 只传文件名（对齐 save_issues_file）
          2) 如果抛错 → 重试 parent=None + default 只传文件名
          3) 再不行 → 重试 parent=None + default 传完整 desktop 路径
        确保至少一种组合能弹出对话框。
        """
        from PyQt6.QtWidgets import QFileDialog

        kb_name = payload.get("kb_name") if isinstance(payload, dict) else ""
        default_name = payload.get("defaultName") if isinstance(payload, dict) else None

        def _slug(t, maxlen=40):
            s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", t or "", flags=re.UNICODE).strip("-")
            return (s[:maxlen].lower() or "knowledge-base")

        if not default_name:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            if kb_name:
                default_name = _slug(kb_name, 40) + "_KB_" + stamp + ".zip"
            else:
                default_name = "knowledge-base_KB_" + stamp + ".zip"

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        default_full = os.path.join(desktop, default_name)
        filters = "ZIP 压缩包 (*.zip);;所有文件 (*.*)"

        # 依次尝试 3 种 getSaveFileName 调用姿势，只要能不异常就用它的返回值
        attempts = [
            ("parent=mainwin, default=name",
             lambda: QFileDialog.getSaveFileName(
                 self._parent_window, "导出知识库", default_name, filters)),
            ("parent=None, default=name",
             lambda: QFileDialog.getSaveFileName(
                 None, "导出知识库", default_name, filters)),
            ("parent=None, default=full",
             lambda: QFileDialog.getSaveFileName(
                 None, "导出知识库", default_full, filters)),
        ]

        save_path = None
        last_err = None
        for tag, fn in attempts:
            try:
                print(f"[Bridge][pick_export_path] try {tag} ...", flush=True)
                result, _ = fn()
                print(f"[Bridge][pick_export_path] try {tag} OK, result={result!r}", flush=True)
                save_path = result
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f"[Bridge][pick_export_path] try {tag} FAIL: {e!r}", flush=True)
                continue

        if last_err is not None:
            # 3 种姿势全失败 → 抛出异常给 Bridge.call 层统一包成 ok=False, error
            raise RuntimeError(
                f"QFileDialog 不可用 ({len(attempts)} 次尝试都失败: {last_err!r}). "
                "请确认桌面存在或尝试重启应用."
            )

        if not save_path:
            print("[Bridge][pick_export_path] 用户取消", flush=True)
            return {"picked": False, "reason": "canceled"}
        p = Path(save_path)
        if not p.suffix:
            p = p.with_suffix(".zip")
            save_path = str(p)
        print(f"[Bridge][pick_export_path] 已选: {save_path}", flush=True)
        return {"picked": True, "save_path": save_path, "name": p.name}

    def _handle_pick_history_export_path(self, payload):
        """弹「另存为」对话框：选择导出单个联系人对话 Markdown 的保存路径。

        100% 镜像已验证可用的 _handle_pick_export_path 同结构：
          3 种 parent/default 调用姿势逐个尝试 → 失败抛 RuntimeError → 成功返回 picked/save_path。
        区别：
          - 默认文件名：YYYYMMDD_HHMMSS_<peer_name_slug>_<agent_name_slug>.md
          - 过滤器：Markdown (*.md) / TXT (*.txt) / 所有文件
          - 对话框标题：导出对话

        入参 payload：peer_name, agent_name（用于默认文件名）
        返回：
          {picked: True,  save_path: "绝对路径", name: 文件名}
          {picked: False, reason: "canceled"}
          （3 种 fallback 全失败时 抛 RuntimeError 由 Bridge.call 包成 ok=False, error）
        """
        from PyQt6.QtWidgets import QFileDialog

        peer_name = (payload.get("peer_name") if isinstance(payload, dict) else "") or "联系人"
        agent_name = (payload.get("agent_name") if isinstance(payload, dict) else "") or "智能体"

        def _slug(t, maxlen=30):
            s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", t or "", flags=re.UNICODE).strip("-")
            return (s[:maxlen].lower() or "contact")

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{stamp}_{_slug(peer_name, 28)}_{_slug(agent_name, 24)}.md"

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        default_full = os.path.join(desktop, default_name)
        filters = "Markdown 文档 (*.md);;文本文件 (*.txt);;所有文件 (*.*)"

        attempts = [
            ("parent=mainwin, default=name",
             lambda: QFileDialog.getSaveFileName(self._parent_window, "导出对话", default_name, filters)),
            ("parent=None, default=name",
             lambda: QFileDialog.getSaveFileName(None, "导出对话", default_name, filters)),
            ("parent=None, default=full",
             lambda: QFileDialog.getSaveFileName(None, "导出对话", default_full, filters)),
        ]
        save_path = None
        last_err = None
        for tag, fn in attempts:
            try:
                print(f"[Bridge][pick_history_export_path] try {tag} ...", flush=True)
                result, _ = fn()
                print(f"[Bridge][pick_history_export_path] try {tag} OK, result={result!r}", flush=True)
                save_path = result
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f"[Bridge][pick_history_export_path] try {tag} FAIL: {e!r}", flush=True)
                continue
        if last_err is not None:
            raise RuntimeError(
                f"QFileDialog 不可用 ({len(attempts)} 次尝试都失败: {last_err!r}). "
                "请确认桌面存在或尝试重启应用."
            )
        if not save_path:
            print("[Bridge][pick_history_export_path] 用户取消", flush=True)
            return {"picked": False, "reason": "canceled"}
        p = Path(save_path)
        if not p.suffix:
            p = p.with_suffix(".md")
            save_path = str(p)
        print(f"[Bridge][pick_history_export_path] 已选: {save_path}", flush=True)
        return {"picked": True, "save_path": save_path, "name": p.name}

    def _handle_save_issues_file(self, payload):
        """JS 侧调用：保存标注问题 JSON 到用户选择位置。

        入参 payload：
            content (str):  JSON 字符串（必填）
            defaultName (str):  建议文件名，默认 scai-issues-<ts>.json
        返回：
            {saved: True, file_path, size_bytes}
            {saved: False, reason: 'canceled' / 'no_content' / 'write_error'}
        """
        from PyQt6.QtWidgets import QFileDialog
        import time

        content = payload.get("content") if isinstance(payload, dict) else None
        if not content or not isinstance(content, str):
            return {"saved": False, "reason": "no_content"}
        default_name = payload.get("defaultName") if isinstance(payload, dict) else None
        default_name = default_name or f"scai-issues-{int(time.time()*1000)}.json"

        file_path, _ = QFileDialog.getSaveFileName(
            self._parent_window,
            "导出标注问题为 JSON",
            default_name,
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not file_path:
            return {"saved": False, "reason": "canceled"}
        p = Path(file_path)
        if not p.suffix:
            p = p.with_suffix(".json")
            file_path = str(p)
        try:
            p.write_text(content, encoding="utf-8")
            size = p.stat().st_size
        except OSError as e:
            return {"saved": False, "reason": "write_error", "detail": str(e)}
        return {"saved": True, "file_path": file_path, "size_bytes": size}

    def _handle_load_issues_file(self, payload):
        """JS 侧调用：从用户选择的 JSON 导入标注问题。

        返回：
            {loaded: True, content: str(原始内容), file_path, issues: [...]}
            {loaded: False, reason: 'canceled' / 'parse_error' / 'read_error'}
        """
        from PyQt6.QtWidgets import QFileDialog
        import json

        file_path, _ = QFileDialog.getOpenFileName(
            self._parent_window,
            "导入标注问题 JSON",
            "",
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not file_path:
            return {"loaded": False, "reason": "canceled"}
        p = Path(file_path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            return {"loaded": False, "reason": "read_error", "detail": str(e)}
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            return {"loaded": False, "reason": "parse_error", "detail": str(e)}
        # 兼容直接是 issues 数组，或对象 {issues: [...]}
        issues = obj["issues"] if isinstance(obj, dict) and "issues" in obj and isinstance(obj["issues"], list) else (
            obj if isinstance(obj, list) else []
        )
        return {"loaded": True, "content": text, "file_path": str(p), "issues": issues}

    # ---------- 渠道连接 ----------
    def _handle_get_channel_status(self, payload):
        statuses = channels_dao.get_all_status()
        # 动态把 WCF 的实际运行态覆盖（只读探活，不影响用户运行的 WCF）
        for s in statuses:
            if s.get("channel") == "wcf":
                s["connected"] = 1 if self.wcf_client.connected else 0
        return {"channels": statuses}

    def _handle_get_wcf_status(self, payload):
        info = self.wcf_client.health_check()
        return {
            "connected": info.get("connected", False),
            "port_10086": info.get("port_10086", False),
            "port_10087": info.get("port_10087", False),
            "is_login": info.get("is_login", False),
            "self_wxid": info.get("self_wxid", ""),
            "version": info.get("version", ""),
        }

    # ---------- 风控配置（账号级） ----------

    def _handle_get_risk_settings(self, payload):
        """获取账号级风控配置（所有智能体共用）。"""
        cfg = risk_config_dao.get()
        return {
            "level": cfg.get("level", "conservative"),
            "auto_adjust": cfg.get("auto_adjust", True),
            "busy_prob": cfg.get("busy_prob", True),
            "leak_back": cfg.get("leak_back", True),
            "health_score": cfg.get("health_score", 100),
        }

    def _handle_set_risk_settings(self, payload):
        """保存账号级风控配置。

        payload 字段：
          level: ultra_safe / conservative / balanced / aggressive
          auto_adjust / busy_prob / leak_back: bool
        """
        valid_levels = {"ultra_safe", "conservative", "balanced", "aggressive"}
        fields = {}
        level = payload.get("level")
        if level and level in valid_levels:
            fields["level"] = level
        for k in ("auto_adjust", "busy_prob", "leak_back"):
            if k in payload:
                fields[k] = bool(payload[k])
        cfg = risk_config_dao.update(**fields)
        return {
            "level": cfg.get("level"),
            "auto_adjust": cfg.get("auto_adjust"),
            "busy_prob": cfg.get("busy_prob"),
            "leak_back": cfg.get("leak_back"),
            "health_score": cfg.get("health_score"),
        }

    # ---------- 公众号（OA）多渠道支持 ----------

    def _handle_oa_env_check(self, payload):
        """环境预检。

        步骤1（不传 port）：只验微信 API 凭据（AppID/AppSecret + IP白名单）
        步骤2（传 port）：额外验本地端口可用性
        """
        import socket
        result = {"checks": []}
        port_val = payload.get("port")
        check_port = bool(port_val)  # 没传端口就不测
        try:
            # 1. 本地端口（只有步骤2才测）
            if check_port:
                port = int(port_val)
                port_ok = True
                port_msg = "端口可用"
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(1)
                    s.bind(("0.0.0.0", port))
                    s.close()
                    port_msg = "端口空闲可监听"
                except OSError:
                    try:
                        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s2.settimeout(1)
                        s2.connect(("127.0.0.1", port))
                        s2.close()
                        if self.oa_client and getattr(self.oa_client, "_flask_thread", None) and self.oa_client._flask_thread.is_alive():
                            port_msg = f"Flask 已在端口 {port} 监听（正常）"
                        else:
                            port_ok = False
                            port_msg = f"端口 {port} 被其他进程占用，请换一个端口"
                    except OSError:
                        port_ok = False
                        port_msg = f"端口 {port} 被占用且无法连接，请换一个端口"
                result["checks"].append({"name": "本地端口", "ok": port_ok, "msg": port_msg})

            # 2. 公网 IP（便利项，方便用户复制去微信后台更新白名单）
            ip_ok = True
            ip_msg = ""
            try:
                import urllib.request, urllib.error
                ip_sources = ["https://api.ipify.org", "https://ifconfig.me/ip"]
                found_ip = ""
                for src in ip_sources:
                    try:
                        req = urllib.request.Request(src, headers={"User-Agent": "MVP-IP-Check"})
                        resp = urllib.request.urlopen(req, timeout=3)
                        found_ip = resp.read().decode().strip()
                        if found_ip:
                            break
                    except Exception:
                        continue
                if found_ip:
                    ip_msg = f"公网 IP: {found_ip}（已自动检测）"
                else:
                    ip_ok = False
                    ip_msg = "公网 IP 自动检测失败，请手动在「本机公网 IP」框获取"
            except Exception as e:
                ip_ok = False
                ip_msg = f"公网 IP 检测异常: {e}"
            result["checks"].append({"name": "公网 IP", "ok": ip_ok, "msg": ip_msg})

            # 3. 服务号凭据（AppID/AppSecret + IP白名单）——这是核心检测
            api_ok = False
            api_msg = ""
            app_id = getattr(self.oa_client, "app_id", "")
            app_secret = getattr(self.oa_client, "app_secret", "")
            if app_id and app_secret:
                try:
                    self.oa_client._init_wx_client()
                    if self.oa_client._wx_client:
                        token = self.oa_client._wx_client.fetch_access_token()
                        if token:
                            api_ok = True
                            api_msg = "凭据有效，IP已在白名单"
                        else:
                            api_msg = "access_token 返回为空"
                    else:
                        api_msg = "wechatpy 客户端初始化失败"
                except Exception as e:
                    api_msg = str(e)
            else:
                api_msg = "请先填写 AppID 和 AppSecret"
            result["checks"].append({"name": "服务号凭据", "ok": api_ok, "msg": api_msg})
        except Exception as e:
            result["checks"].append({"name": "检测异常", "ok": False, "msg": str(e)})

        result["ok"] = all(c["ok"] for c in result["checks"])
        return result

    def _handle_oa_push_check(self, payload):
        """第二步验证：按 phase 区分 URL 检测 / Token 验签 / 全部。"""
        import socket
        import urllib.request
        phase = payload.get("phase", "")  # 'url' | 'token' | ''(全部)
        result = {"checks": [], "phase": phase}
        try:
            port = int(payload.get("port") or getattr(self.oa_client, "callback_port", 9999) or 9999)
            url = (payload.get("url") or "").strip()
            token = (payload.get("token") or "").strip()

            flask_ok = False
            flask_msg = ""

            # A. 启动/探测 Flask（所有阶段都需要）
            flask_ok = False
            flask_msg = ""
            try:
                # 快速探测：TCP 端口连上就算 Flask 在监听
                # （发假签名 probe 会被 Flask 返回 403，这是正常的——只要 TCP 能通就 OK）
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        flask_ok = True
                        flask_msg = f"Flask 已在端口 {port} 监听"
                except Exception:
                    pass  # 端口没东西，需要重启

                if not flask_ok:
                    # 停旧的 → 启新的
                    if self.oa_client and getattr(self.oa_client, "_flask_thread", None):
                        try:
                            self.oa_client.stop()
                        except Exception:
                            pass
                    if self.oa_client:
                        self.oa_client.callback_port = port
                    self.oa_client.start()  # start() 内部会等最多 5 秒
                    flask_ok = getattr(self.oa_client, "_flask_running", False)
                    flask_msg = f"Flask 已启动，端口 {port}" if flask_ok else f"Flask 启动后端口 {port} 未监听"
            except Exception as e:
                flask_msg = f"Flask 启动失败：{e}"

            # phase='url' 或 ''：返回 Flask + 穿透
            if phase in ("", "url"):
                result["checks"].append({"name": "Flask 本地服务", "ok": flask_ok, "msg": flask_msg})
                if url:
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        probe_url = f"{parsed.scheme}://{parsed.netloc}/wechat"
                        req = urllib.request.Request(probe_url, method='GET', headers={'User-Agent': 'MVP-Probe'})
                        urllib.request.urlopen(req, timeout=6)
                        result["checks"].append({"name": "回调 URL", "ok": True, "msg": f"可达（{parsed.netloc}）"})
                    except urllib.error.HTTPError as e:
                        if e.code in (403, 401, 405):
                            result["checks"].append({"name": "回调 URL", "ok": True, "msg": f"可达（HTTP {e.code}，Flask 正常拒绝非服务号请求）"})
                        else:
                            result["checks"].append({"name": "回调 URL", "ok": False, "msg": f"HTTP {e.code}，可能不可达"})
                    except Exception as e:
                        result["checks"].append({"name": "回调 URL", "ok": False, "msg": f"无法连通：{e}"})
                else:
                    result["checks"].append({"name": "回调 URL", "ok": False, "msg": "请先填写 URL"})

            # phase='token' 或 ''：返回 Token 自验签
            if phase in ("", "token"):
                if not token:
                    result["checks"].append({"name": "Token 验签", "ok": False, "msg": "Token 不能为空"})
                elif not flask_ok:
                    result["checks"].append({"name": "Token 验签", "ok": False, "msg": "Flask 未启动"})
                else:
                    try:
                        import hashlib, random
                        timestamp = str(int(__import__("time").time()))
                        nonce = str(random.randint(100000, 999999))
                        echostr = "mvp_test_verify_ok"
                        sort_list = [token, timestamp, nonce]
                        sort_list.sort()
                        signature = hashlib.sha1("".join(sort_list).encode()).hexdigest()
                        from urllib.parse import urlencode
                        params = urlencode({"signature": signature, "timestamp": timestamp, "nonce": nonce, "echostr": echostr})
                        local_url = f"http://127.0.0.1:{port}/wechat?{params}"
                        req = urllib.request.Request(local_url, method='GET', headers={'User-Agent': 'MVP-SelfTest'})
                        resp = urllib.request.urlopen(req, timeout=3)
                        body = resp.read().decode("utf-8", errors="replace")
                        if body.strip() == echostr:
                            result["checks"].append({"name": "Token 验签", "ok": True, "msg": "验签通过"})
                        else:
                            result["checks"].append({"name": "Token 验签", "ok": False, "msg": f"验签响应异常：{body[:50]}"})
                    except Exception as e:
                        result["checks"].append({"name": "Token 验签", "ok": False, "msg": f"验签失败：{e}"})

        except Exception as e:
            result["checks"].append({"name": "检测异常", "ok": False, "msg": str(e)})

        result["ok"] = all(c["ok"] for c in result["checks"])
        return result

    def _handle_get_public_ip(self, payload):
        """获取本机公网出口 IP（用于配置微信 API IP 白名单）。"""
        import urllib.request
        try:
            req = urllib.request.Request('https://api.ipify.org?format=json', headers={'User-Agent': 'MVP'})
            resp = urllib.request.urlopen(req, timeout=8)
            import json
            data = json.loads(resp.read())
            return {"ok": True, "ip": data.get("ip", "")}
        except Exception:
            try:
                req = urllib.request.Request('https://ifconfig.me/ip', headers={'User-Agent': 'MVP'})
                resp = urllib.request.urlopen(req, timeout=8)
                return {"ok": True, "ip": resp.read().decode().strip()}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def _handle_configure_oa(self, payload):
        """配置公众号参数（内存 + 持久化到 SQLite）。

        payload 字段：
          app_id, app_secret, token, encoding_aes_key, callback_port, url

        持久化策略：和已有配置合并，空字段不覆盖已有值。
          这样步骤1只传 AppID/Secret 时，不会清掉之前存的 token/url/port。

        last_verify_time 策略：
          - URL 没变 → 保留 last_verify_time（配置没变，验签还有效）
          - URL 变了 → 清掉 last_verify_time（微信那边要重新配置 URL，需重新验签）
          - 前端 bootstrap 自动恢复配置时 URL 不变，不会误清
        """
        self.oa_client.configure(
            app_id=payload.get("app_id", ""),
            app_secret=payload.get("app_secret", ""),
            token=payload.get("token", ""),
            encoding_aes_key=payload.get("encoding_aes_key", ""),
        )
        if payload.get("callback_port") or payload.get("port"):
            self.oa_client.callback_port = int(payload.get("callback_port") or payload.get("port"))

        # 持久化：和已有配置合并，空字段不覆盖
        try:
            import json as _json
            existing = {}
            try:
                row = channels_dao.get("oa")
                if row and row.get("config_json"):
                    existing = _json.loads(row["config_json"])
            except Exception:
                pass

            cfg = {}
            for key in ("app_id", "app_secret", "token", "encoding_aes_key", "url"):
                new_val = payload.get(key, "")
                old_val = existing.get(key, "")
                cfg[key] = new_val if new_val else old_val

            # callback_port 特殊：用 oa_client 当前值（可能从 payload 来也可能是之前设的）
            cfg["callback_port"] = self.oa_client.callback_port or existing.get("callback_port", 0)

            # last_verify_time：URL 变了才清，否则保留
            old_url = existing.get("url", "") or ""
            new_url = cfg.get("url", "") or ""
            url_changed = bool(new_url) and new_url != old_url
            if url_changed:
                cfg["last_verify_time"] = 0
                self.oa_client._last_verify_time = 0
                print(f"[Bridge] OA URL 变更，重置 last_verify_time: {old_url} -> {new_url}", flush=True)
            else:
                cfg["last_verify_time"] = float(existing.get("last_verify_time", 0) or 0)

            channels_dao.upsert("oa", connected=0, config=cfg, error="")
            safe = {k: v for k, v in cfg.items() if k != "app_secret"}
            print(f"[Bridge] OA 配置已持久化: {safe}", flush=True)
        except Exception as e:
            print(f"[Bridge] OA 配置持久化失败: {e}", flush=True)

        return {"ok": True}

    def _handle_start_oa(self, payload):
        """启动服务号连接：Flask + 微信API凭据 + 穿透URL主动探测。

        三项全过 = 已连接，不需要用户再去做额外操作。
        """
        if not self.oa_client.app_id or not self.oa_client.app_secret or not self.oa_client.token:
            return {"ok": False, "error": "请先配置服务号参数"}
        # 创建专属 pipeline
        self.oa_pipeline = MessagePipeline(
            channel_client=self.oa_client,
            agents_dao=agents_dao,
            channels_dao=channels_dao,
            conv_dao=conv_dao,
            msg_dao=msg_dao,
            llm_dao=llm_dao,
            send_message_fn=self._handle_send_message,
            risk_config_dao=risk_config_dao,
            quick_llm_fn=self.quick_llm_call,
        )
        # 1. 启动 Flask + 验证微信 API 凭据
        status = self.oa_client.start()
        flask_ok = self.oa_client.connected
        probe_ok = False
        probe_msg = ""

        # 2. 主动探测穿透 URL 是否通到本地 Flask
        url = (payload.get("url") or "").strip()
        if flask_ok and url:
            probe_ok, probe_msg = self.oa_client.probe_callback_url(url)
        elif flask_ok and not url:
            probe_msg = "未填 URL，跳过穿透探测"
        elif not flask_ok:
            probe_msg = "Flask/API 未通过，跳过穿透探测"

        if flask_ok and not probe_ok and url:
            print(f"[Bridge] 穿透探测失败: {probe_msg}", flush=True)

        # 真正的"已连接"= Flask + 穿透都通 + 微信真的验签过
        wx_verified = getattr(self.oa_client, "_last_verify_time", 0) > 0
        truly_connected = flask_ok and probe_ok and wx_verified

        return {
            "ok": flask_ok,
            "connected": truly_connected,
            "flask_running": status.get("flask_running", False),
            "api_verified": status.get("api_verified", False),
            "probe_ok": probe_ok,
            "probe_msg": probe_msg,
            "wx_verified": wx_verified,
            "last_verify_time": getattr(self.oa_client, "_last_verify_time", 0),
            "error": status.get("error", ""),
        }

    def _handle_get_oa_verify_status(self, payload):
        """查询服务号配置状态。"""
        import json as _json
        saved_url = ""

        try:
            row = channels_dao.get("oa")
            if row and row.get("config_json"):
                cfg = _json.loads(row["config_json"])
                saved_url = cfg.get("url", "")
        except Exception as e:
            print(f"[Bridge] 配置读取失败: {e}", flush=True)

        # 回调 URL 可达性：使用缓存值（探针异步执行，不阻塞 UI）
        flask_running = getattr(self.oa_client, "_flask_running", False)
        url_reachable = bool(getattr(self.oa_client, "_url_reachable_cache", False))

        return {
            "last_verify_time": getattr(self.oa_client, "_last_verify_time", 0),
            "flask_running": flask_running,
            "api_verified": getattr(self.oa_client, "_api_verified", False),
            "url_reachable": url_reachable,
            "saved_url": saved_url,
        }

    def _handle_get_oa_saved_config(self, payload):
        """读取保存的公众号配置（启动时自动加载用）。"""
        import json as _json
        try:
            row = channels_dao.get("oa")
            if row and row.get("config_json"):
                cfg = _json.loads(row["config_json"])
                # 同时把配置灌回 oa_client 内存
                self.oa_client.configure(
                    app_id=cfg.get("app_id", ""),
                    app_secret=cfg.get("app_secret", ""),
                    token=cfg.get("token", ""),
                    encoding_aes_key=cfg.get("encoding_aes_key", ""),
                )
                if cfg.get("callback_port"):
                    self.oa_client.callback_port = int(cfg["callback_port"])
                safe_cfg = {k: v for k, v in cfg.items() if k not in ('app_secret', 'encoding_aes_key')}
                safe_cfg['has_app_secret'] = bool(cfg.get('app_secret'))
                safe_cfg['has_encoding_aes_key'] = bool(cfg.get('encoding_aes_key'))
                return {"ok": True, "config": safe_cfg}
        except Exception as e:
            print(f"[Bridge] 读取 OA 保存配置失败: {e}", flush=True)
        return {"ok": False, "config": {}}

    def _handle_stop_oa(self, payload):
        """停止服务号连接：Flask + pipeline。"""
        if self.oa_pipeline:
            self.oa_pipeline.shutdown(wait=False)
            self.oa_pipeline = None
        self.oa_client.stop()
        return {"ok": True}

    def _handle_get_oa_status(self, payload):
        """获取公众号连接状态——诚实分层：

          - 未连接: Flask 没跑 / API 无效
          - 配置就绪: Flask 跑 + API 有效 + URL 可达，但从未验签（last_verify_time=0）
          - 已连接: last_verify_time > 0 且 Flask + URL + API 全正常
          - 已断开: last_verify_time > 0 但 Flask 挂了 / URL 不可达 / API 失效

        last_verify_time 持久化到 SQLite，重启后恢复，避免每次重启都退回配置就绪。

        性能优化：url_reachable 使用缓存值，探针在后台线程异步执行（15秒节流），
        避免同步 HTTP 请求阻塞 PyQt UI 主线程导致卡顿。
        """
        health = self.oa_client.health_check()
        flask_running = getattr(self.oa_client, "_flask_running", False)
        flask_port = getattr(self.oa_client, "callback_port", None)

        # 从保存的配置里拿 URL（config_json 是 JSON 字符串）
        import json as _json
        cfg = {}
        try:
            row = channels_dao.get("oa")
            if row and row.get("config_json"):
                cfg = _json.loads(row["config_json"])
        except Exception as e:
            print(f"[Bridge] get_oa_status read cfg exception: {type(e).__name__}: {e}", flush=True)
        url = cfg.get("url", "") or ""

        # last_verify_time 同步逻辑：内存 > 0 时写入 SQLite；内存 = 0 时从 SQLite 读回
        mem_verify_time = getattr(self.oa_client, "_last_verify_time", 0)
        saved_verify_time = float(cfg.get("last_verify_time", 0) or 0)
        if mem_verify_time > 0 and mem_verify_time != saved_verify_time:
            # 内存有新值，同步到 SQLite
            try:
                cfg["last_verify_time"] = mem_verify_time
                channels_dao.upsert("oa", connected=0, config=cfg, error="")
                saved_verify_time = mem_verify_time
            except Exception as e:
                print(f"[Bridge] save last_verify_time failed: {e}", flush=True)
        elif mem_verify_time == 0 and saved_verify_time > 0:
            # 重启后内存清零，从 SQLite 恢复
            self.oa_client._last_verify_time = saved_verify_time
            mem_verify_time = saved_verify_time
        last_verify_time = max(mem_verify_time, saved_verify_time)

        # URL 可达性：返回缓存值，后台线程异步刷新（15秒节流，避免阻塞 UI）
        # force_probe=True 时同步探测（用户主动点"重新检测"，期望立即反馈）
        force_probe = bool(payload.get("force_probe", False))
        url_reachable = bool(getattr(self.oa_client, "_url_reachable_cache", False))
        now = time.time()
        last_probe = getattr(self.oa_client, "_last_url_probe_time", 0.0)
        if url and flask_running and (force_probe or (now - last_probe) > 15):
            self.oa_client._last_url_probe_time = now
            if force_probe:
                try:
                    ok, _ = self.oa_client.probe_callback_url(url)
                    url_reachable = bool(ok)
                    self.oa_client._url_reachable_cache = url_reachable
                except Exception:
                    url_reachable = False
                    self.oa_client._url_reachable_cache = False
            else:
                import threading as _threading
                def _probe():
                    try:
                        ok, _ = self.oa_client.probe_callback_url(url)
                        self.oa_client._url_reachable_cache = bool(ok)
                    except Exception:
                        self.oa_client._url_reachable_cache = False
                _threading.Thread(target=_probe, daemon=True).start()

        api_verified = getattr(self.oa_client, "_api_verified", False)

        return {
            "connected": self.oa_client.connected,        # 只有真微信验签过才 True
            "configured": self.oa_client.configured,      # Flask + API + token
            "flask_running": flask_running,
            "flask_port": flask_port,
            "api_verified": api_verified,
            "url_reachable": url_reachable,
            "last_verify_time": last_verify_time,
            "health": health,
        }

    # ═══════════════════════════════════════════════════════════
    # 【CLI 渠道后端模板 - 企微 WeCom】
    #
    # 飞书/Lark 复制指南（共 5 处 ✏️）：
    #
    #  需要改的（企微特化）：
    #   ① _xxx_cli_path()           → 换 CLI 命令名 + fallback 路径
    #   ② _handle_generate_xxx_qr   → init 命令（扫码流程）
    #   ③ _handle_fetch_xxx_contacts → 通讯录子命令 + 群聊列表子命令
    #   ④ _handle_save_xxx_agent_contacts → 绑定保存（用通用 channels_dao 不变，但 CLI 子命令名改）
    #   ⑤ _handle_unbind_xxx        → 删凭证文件路径
    #
    #  不需要改的（模板骨架）：
    #   - Bridge 初始化时创建 pipeline（if wecom_client.connected → 创建 pipeline → start）
    #   - Bridge.shutdown 停 pipeline + client.stop()
    #   - dispatch 注册（"generate_wecom_qr"/"fetch_wecom_contacts" 等）
    #   - channels_dao / conv_dao / msg_dao（数据库层零硬编码，全靠 channel 字段过滤）
    #   - _wecom_cli_run（统一 JSON-RPC 解析，企微和飞书 CLI 返回结构应该相同）
    #
    #  前端配合：企微 HTML tab + JS 函数全部复制改名（见 index.html 注释）
    # ═══════════════════════════════════════════════════════════

    # 后台 CLI init 进程（扫码模式）
    _wecom_qr_proc = None

    @staticmethod
    def _wecom_config_dir() -> Path:
        """企微 CLI 凭证存储目录。✏️ 飞书改成 ~/.config/lark/"""
        return Path.home() / ".config" / "wecom"

    @staticmethod
    def _wecom_enc_path() -> Path:
        """扫码绑定成功后 wecom-cli 生成的凭据文件。

        v1.2.1+ 文件名从 mcp_config.enc 改为 credentials.enc
        """
        return Path.home() / ".config" / "wecom" / "credentials.enc"

    @staticmethod
    def _wecom_cli_path() -> str | None:
        """定位 wecom-cli 可执行文件的完整路径。

        优先级：PyInstaller 内置 → PATH → npm 全局路径。
        wecom-cli.exe 是 @wecom/cli platform-specific 包预编译的 9.6MB 自包含 PE32，
        spec 里已硬打进 EXE 到 sys._MEIPASS/channels/wecom/wecom-cli.exe。
        """
        import shutil
        import sys
        import os
        # 1. PyInstaller 内置（打包时硬打到 channels/wecom/wecom-cli.exe）
        if getattr(sys, "frozen", False):
            bundled = os.path.join(sys._MEIPASS, "channels", "wecom", "wecom-cli.exe")
            if os.path.isfile(bundled):
                return bundled
        # 2. shutil.which（会自动处理 .exe/.cmd/.ps1 后缀）
        found = shutil.which("wecom-cli") or shutil.which("wecom-cli.cmd")
        if found:
            return found
        # 3. 兜底：npm 全局安装的常见路径
        candidates = [
            os.path.expandvars(r"%APPDATA%\npm\node_modules\@wecom\cli\node_modules\@wecom\cli-win32-x64\bin\wecom-cli.exe"),
            os.path.expandvars(r"%APPDATA%\npm\wecom-cli.cmd"),
            os.path.expandvars(r"%ProgramFiles%\nodejs\wecom-cli.cmd"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Roaming\npm\wecom-cli.cmd"),
            "/usr/local/bin/wecom-cli",
            "/opt/homebrew/bin/wecom-cli",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    # MVP 验证过的企微 CLI 版本（冒烟测试通过的版本）
    WECOM_VERIFIED_VERSION = "1.2.1"
    # 已知不兼容的版本黑名单
    WECOM_INCOMPATIBLE_VERSIONS = []

    @staticmethod
    def _wecom_cli_version() -> str | None:
        """获取 wecom-cli 版本号。返回如 '1.2.1'，失败返回 None。"""
        import subprocess
        cli = BridgeServer._wecom_cli_path()
        if not cli:
            return None
        try:
            proc = subprocess.run(
                [cli, "--version"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            out = (proc.stdout or "").strip()
            # 输出可能是 "wecom-cli/1.2.1" 或 "1.2.1"
            import re
            m = re.search(r'(\d+\.\d+\.\d+)', out)
            return m.group(1) if m else None
        except Exception:
            return None

    @staticmethod
    def _check_cli_compat(version: str | None, verified_version: str, incompatible_versions: list[str] | None = None) -> str:
        """通用 CLI 版本兼容性判断，返回 'compatible' | 'unknown' | 'incompatible'。

        规则：
          - version 为空 → unknown
          - version 在不兼容黑名单 → incompatible
          - version 完全等于已验证版本 → compatible
          - 大版本号大于已验证版本 → incompatible
          - 小版本/补丁升级 → unknown（需冒烟测试）
        """
        if not version:
            return "unknown"
        if incompatible_versions and version in incompatible_versions:
            return "incompatible"
        if version == verified_version:
            return "compatible"
        def parse(v):
            parts = v.split(".")
            return tuple(int(p) for p in parts[:3]) if len(parts) >= 3 else (0, 0, 0)
        try:
            cur = parse(version)
            ver = parse(verified_version)
        except Exception:
            return "unknown"
        if cur[0] > ver[0]:
            return "incompatible"
        return "unknown"

    @staticmethod
    def _wecom_check_compat(version: str | None) -> str:
        """判断企微 CLI 版本兼容性。"""
        return BridgeServer._check_cli_compat(
            version,
            BridgeServer.WECOM_VERIFIED_VERSION,
            BridgeServer.WECOM_INCOMPATIBLE_VERSIONS,
        )

    @staticmethod
    def _wecom_extract_auth_url(gen_url: str) -> str | None:
        """从 wecom-cli 输出的 /ai/qc/gen?... 中间页提取真正的 auth_url。

        wecom-cli init 输出的 URL 是一个 PC 端跳转页，页面里 window.settings.auth_url
        才是编码了 &for_native=true 的企微 App 直接授权链接。如果提取失败，返回 None。
        """
        import urllib.request
        try:
            req = urllib.request.Request(gen_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp = urllib.request.urlopen(req, timeout=8)
            html = resp.read().decode("utf-8", errors="replace")
            # 匹配 window.settings = {... "auth_url":"..." ...}
            m = re.search(r'auth_url["\s:=]+["\']([^"\']+)["\']', html)
            if m:
                auth_url = m.group(1)
                # 确保是 for_native 版本
                if "for_native" not in auth_url:
                    auth_url += "&for_native=true"
                return auth_url
        except Exception as e:
            print(f"[Bridge] _wecom_extract_auth_url 失败: {e}", flush=True)
        return None

    def _handle_get_wecom_status(self, payload):
        """获取企业微信连接状态 + CLI 版本兼容信息。

        连接判定统一走 wecom_client.health_check()（三态：unbound/connected/auth_expired），
        该判定由轮询线程实际跑 CLI 调用维护，比单看 enc 文件可靠。
        """
        health = self.wecom_client.health_check()
        cli_version = self._wecom_cli_version()
        compat = self._wecom_check_compat(cli_version)
        return {
            "ok": True,
            "state": health.get("state", "unbound"),
            "connected": bool(health.get("connected")),
            "enc_exists": self._wecom_enc_path().exists(),
            "cli_version": cli_version,
            "cli_compat": compat,
            "verified_version": self.WECOM_VERIFIED_VERSION,
            "error": health.get("error", ""),
            "last_success_ts": health.get("last_success_ts", 0),
            "consecutive_failures": health.get("consecutive_failures", 0),
        }

    def _handle_generate_wecom_qr(self, payload):
        """生成企业微信授权二维码（扫码模式）。

        流程：
          1. 杀掉残留的旧扫码进程（如果有）
          2. Popen 起 wecom-cli auth init --noninteractive --no-browser
             （v1.2.1：init → auth init，--no-open → --no-browser）
          3. 实时读 stdout，提取二维码 URL
          4. 用 qrcode 生成 PNG base64 返回
          5. 进程留在后台等扫码（最多 5 分钟）
        """
        import subprocess
        import base64
        import io
        import threading

        # 1. 先杀掉残留进程
        self._wecom_kill_qr_proc()

        # 如果已经绑定了，不需要再生成
        if self._wecom_enc_path().exists():
            return {"ok": False, "error": "已绑定企业微信机器人，先解绑才能重新生成二维码"}

        # 2. 定位 wecom-cli 并启动（不阻塞，读 stdout 到拿到 URL 就行）
        cli_path = self._wecom_cli_path()
        if not cli_path:
            return {"ok": False, "error": "未找到 wecom-cli，请先运行 npm install -g @wecom/cli"}
        try:
            # v1.2.1：wecom-cli init → wecom-cli auth init，--no-open → --no-browser
            proc = subprocess.Popen(
                [cli_path, "auth", "init", "--noninteractive", "--no-browser"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            return {"ok": False, "error": f"启动 wecom-cli 失败: {e}"}

        # 3. 读 stdout 拿中间页 URL（最多等 15 秒）
        gen_url = None
        output_lines = []
        import time
        start = time.time()
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    output_lines.append(line)
                    if not gen_url and line.startswith("https://") and ("weixin.qq.com" in line or "wecom" in line or "weixin" in line):
                        gen_url = line
                    if time.time() - start > 15:
                        break
                    if gen_url and "等待扫码" in line:
                        break
        except Exception:
            pass

        if not gen_url:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
            full_output = "\n".join(output_lines)
            return {"ok": False, "error": "未能从 wecom-cli 输出中提取二维码链接", "raw": full_output[-500:]}

        # 3.5 访问 gen_url 提取真正的 auth_url
        # wecom-cli 输出的 /ai/qc/gen?... 是中间跳转页，页面里 window.settings.auth_url
        # 才是能被企微 App 直接扫码授权的 /ai/qc/c?...&for_native=true 链接
        qr_url = self._wecom_extract_auth_url(gen_url) or gen_url
        print(f"[Bridge] WeCom gen_url={gen_url[:80]}... → auth_url={qr_url[:80]}...", flush=True)

        # 4. 生成 QR 图片（用 auth_url 而非 gen_url）
        try:
            import qrcode
            qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            proc.terminate()
            return {"ok": False, "error": f"二维码生成失败: {e}", "qr_url": qr_url}

        # 5. 保存进程引用，前端轮询状态时检查 mcp_config.enc 是否生成
        self._wecom_qr_proc = proc
        print(f"[Bridge] WeCom 二维码已生成，URL={qr_url[:80]}...，进程 PID={proc.pid}，等待扫码", flush=True)

        return {
            "ok": True,
            "qr_url": qr_url,
            "qr_image": f"data:image/png;base64,{qr_b64}",
        }

    def _wecom_kill_qr_proc(self):
        """杀掉后台残留的 wecom-cli init 进程"""
        proc = getattr(self, "_wecom_qr_proc", None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                print(f"[Bridge] 已杀掉残留 wecom-cli init 进程 PID={proc.pid}", flush=True)
            except Exception:
                pass
        self._wecom_qr_proc = None

    def _handle_unbind_wecom(self, payload):
        """解绑企业微信机器人：杀掉后台进程 + 删除凭据文件。"""
        import shutil

        # 1. 杀掉扫码进程
        self._wecom_kill_qr_proc()

        # 2. 删除凭据文件
        removed = False
        enc_dir = self._wecom_config_dir()
        enc_file = self._wecom_enc_path()
        key_file = enc_dir / ".encryption_key"
        bot_enc = enc_dir / "bot.enc"

        for f in [enc_file, key_file, bot_enc]:
            if f.exists():
                try:
                    f.unlink()
                    removed = True
                    print(f"[Bridge] WeCom 已删除凭据: {f}", flush=True)
                except Exception as e:
                    return {"ok": False, "error": f"删除凭据文件失败: {e}"}

        # 3. 清理缓存
        cache_dir = enc_dir / "cache"
        if cache_dir.exists():
            try:
                shutil.rmtree(cache_dir)
            except Exception:
                pass

        # 4. 清理 DB 绑定记录
        try:
            from storage.db import get_conn
            conn = get_conn()
            n1 = conn.execute('DELETE FROM channel_binding WHERE channel=?', ('wecom',)).rowcount
            n2 = conn.execute('DELETE FROM peer_profile WHERE channel=?', ('wecom',)).rowcount
            conn.commit()
            print(f"[Bridge] WeCom 解绑清理: binding={n1} peer_profile={n2}", flush=True)
        except Exception as e:
            print(f"[Bridge] WeCom 解绑清理失败: {e}", flush=True)

        # 5. 更新渠道状态
        try:
            channels_dao.upsert("wecom", connected=0, config={}, error="")
        except Exception:
            pass

        try:
            self.wecom_client.reset_state()
        except Exception:
            pass

        return {"ok": True, "removed": removed}

    def _wecom_cli_run(self, *args, timeout=30):
        """统一封装：调 wecom-cli 子命令并解析 JSON 输出。

        返回 (success: bool, data: dict|list|None, error: str)
        """
        import subprocess
        import json as _json

        cli_path = self._wecom_cli_path()
        if not cli_path:
            return False, None, "未找到 wecom-cli"
        try:
            proc = subprocess.run(
                [cli_path, *args],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, None, f"wecom-cli 超时（{timeout}s）"
        except Exception as e:
            return False, None, f"wecom-cli 调用失败: {e}"

        raw = (proc.stdout or "").strip()
        if proc.returncode != 0:
            return False, None, (proc.stderr or raw or "wecom-cli 返回非零状态").strip()[:200]

        # 输出是 JSON-RPC 格式，里面 content[0].text 才是业务 JSON
        try:
            envelope = _json.loads(raw)
            inner = envelope.get("result", {}).get("content", [{}])
            if inner and isinstance(inner, list):
                text = inner[0].get("text", "")
                return True, _json.loads(text), ""
        except Exception:
            pass
        # 兜底：直接当 JSON 解析
        try:
            return True, _json.loads(raw), ""
        except Exception:
            return False, None, f"wecom-cli 输出解析失败: {raw[:100]}"

    def _handle_fetch_wecom_contacts(self, payload):
        """拉取企微通讯录成员 + 群聊会话列表，合并成统一格式返回。

        返回结构与 WCF fetch_wcf_contacts 对齐：
          [{"peer_type":"friend"|"group",
            "peer_id": "userid 或 chat_id",
            "peer_name": "姓名或群名",
            "member_count": 群聊成员数(可选)}]

        数据源（wecom-cli v1.2.1+）：
          单聊成员 → wecom-cli contact users search --search-mode list --keywords "."
          群聊     → wecom-cli chat groups list --set begin_time=... --set end_time=...
        """
        import time

        # 1. 检查是否已绑定
        if not self._wecom_enc_path().exists():
            return {"ok": True, "contacts": [], "source": "empty",
                    "note": "企微未绑定，请先在连接管理扫码绑定"}

        contacts = []
        errors = []

        # 2. 拉通讯录成员
        # wecom-cli v1.2.1 关键变化：
        #   - keywords 是 array（不是字符串），必须用 --json 传参
        #   - open cli 权限下搜 "." 不再返回全量，需要多关键词"穷尽"搜
        #   - 能搜到的范围 = 和机器人有过会话的联系人 + 授权真人关系链
        import json as _json
        ok, data, err = self._wecom_cli_run(
            "contact", "users", "search",
            "--json", _json.dumps({
                "search_mode": "list",
                "keywords": ["@", "_", ".", "-", "a", "e", "i", "o", "u"],
            }, ensure_ascii=False),
        )
        users = []
        if ok and data and not data.get("error"):
            users = data.get("users", []) or []
            for u in users:
                contacts.append({
                    "peer_type": "friend",
                    "peer_id": u.get("userid", ""),
                    "peer_name": u.get("name", ""),
                    "alias": u.get("alias", ""),
                })
            print(f"[Bridge] fetch_wecom_contacts: 通讯录 {len(users)} 人", flush=True)
        else:
            errors.append(f"通讯录: {err or (data.get('error',{}).get('message','') if data else '')}")
            print(f"[Bridge] fetch_wecom_contacts 通讯录失败: {err}", flush=True)

        # 3. 拉群聊（企微 API 硬限制：begin_time 不能早于 7 天前，用 6 天留余量）
        today = time.strftime("%Y-%m-%d 23:59:59")
        week_ago = time.strftime("%Y-%m-%d 00:00:00",
                                  time.localtime(time.time() - 6 * 86400))
        ok2, data2, err2 = self._wecom_cli_run(
            "chat", "groups", "list",
            "--set", f"begin_time={week_ago}",
            "--set", f"end_time={today}",
        )
        group_n = 0
        if ok2 and data2 and not data2.get("error"):
            for c in data2.get("chats", []):
                contacts.append({
                    "peer_type": "group",
                    "peer_id": c.get("chat_id", ""),
                    "peer_name": c.get("chat_name", ""),
                    "member_count": c.get("msg_count", 0),
                    "last_msg_time": c.get("last_msg_time", ""),
                })
                group_n += 1
            print(f"[Bridge] fetch_wecom_contacts: 群聊 {group_n} 个", flush=True)
        else:
            err2_msg = err2 or (data2.get("error",{}).get("message","") if data2 else "")
            errors.append(f"群聊: {err2_msg}")
            print(f"[Bridge] fetch_wecom_contacts 群聊失败: {err2_msg}", flush=True)

        friend_n = sum(1 for c in contacts if c["peer_type"] == "friend")
        note = f"企微 {friend_n} 成员 / {group_n} 群聊"
        if errors:
            note += f"（部分失败: {'; '.join(errors)}）"

        # 缓存通讯录供 save 时取 peer_name
        self._wecom_cache = contacts
        return {"ok": True, "contacts": contacts, "source": "wecom_cli", "note": note}

    def _handle_save_wecom_agent_contacts(self, payload):
        """保存/更新某个智能体在企微渠道的启用 peer 列表（用 channel_binding 表，和微信/服务号对齐）。

        payload: {"agent_id": str, "peers": [{"peer_type":"friend"|"group", "peer_id": str}]}
        """
        agent_id = (payload or {}).get("agent_id")
        peers = (payload or {}).get("peers") or []
        if not agent_id:
            return {"ok": False, "error": "缺少 agent_id"}

        # 1. 先把当前 agent 的所有 wecom 绑定全部置为 disabled
        existing = channels_dao.list_bindings(agent_id, "wecom")
        for b in existing:
            channels_dao.set_binding(
                agent_id=agent_id, channel="wecom",
                peer_id=b["peer_id"], peer_name=b.get("peer_name", ""),
                peer_type=b.get("peer_type", "friend"), enabled=False,
            )

        # 2. 把新勾选的 peers 设为 enabled
        #    先拿到 peer_name（set_binding 需要）
        #    优先用 _wecom_cache（来自 fetch_wecom_contacts），避免每次保存都跑 CLI
        peer_name_map = {}
        cache = getattr(self, '_wecom_cache', None)
        if cache:
            for c in cache:
                pid = c.get("peer_id") or c.get("userid")
                if pid:
                    peer_name_map[pid] = c.get("peer_name") or c.get("name", pid)
        else:
            # cache 没有才 CLI 拉（兜底，用新版本命令 + array keywords）
            try:
                import json as _json
                ok, data, _ = self._wecom_cli_run(
                    "contact", "users", "search",
                    "--json", _json.dumps({
                        "search_mode": "list",
                        "keywords": ["@", "_", ".", "-", "a", "e", "i", "o", "u"],
                    }, ensure_ascii=False),
                )
                if ok and data and not data.get("error"):
                    for item in data.get("users", []) or []:
                        pid = item.get("userid") or item.get("peer_id")
                        if pid:
                            peer_name_map[pid] = item.get("name", pid)
            except Exception:
                pass

        saved = 0
        for p in peers:
            pid = p.get("peer_id", "")
            if not pid:
                continue
            ptype = p.get("peer_type", "friend")
            pname = peer_name_map.get(pid, pid)
            channels_dao.set_binding(
                agent_id=agent_id, channel="wecom",
                peer_id=pid, peer_name=pname,
                peer_type=ptype, enabled=True,
            )
            saved += 1

        return {"ok": True, "count": saved}

    def _handle_get_wecom_agent_contacts(self, payload):
        """读取某个智能体在企微渠道已启用的 peer 列表（用 channel_binding 表）。"""
        agent_id = (payload or {}).get("agent_id")
        if not agent_id:
            return {"ok": False, "error": "缺少 agent_id"}
        try:
            bindings = channels_dao.list_bindings(agent_id, "wecom")
            peers = [
                {
                    "peer_type": b.get("peer_type", "friend"),
                    "peer_id": b["peer_id"],
                    "peer_name": b.get("peer_name", b["peer_id"]),
                }
                for b in bindings
                if b.get("enabled")
            ]
        except Exception as e:
            return {"ok": False, "error": f"读取失败: {e}"}
        return {"ok": True, "peers": peers}

    # ═══════════════════════════════════════════════════════════
    # 飞书（Feishu）渠道 handler — 基于 lark-cli
    # ═══════════════════════════════════════════════════════════

    _feishu_qr_proc = None

    @staticmethod
    def _feishu_config_dir() -> Path:
        return Path.home() / ".lark-cli"

    @staticmethod
    def _feishu_cli_path() -> str | None:
        import shutil
        import sys
        import os
        # 1. PyInstaller 内置（打包时硬打到 channels/feishu/lark-cli.exe）
        if getattr(sys, "frozen", False):
            bundled = os.path.join(sys._MEIPASS, "channels", "feishu", "lark-cli.exe")
            if os.path.isfile(bundled):
                return bundled
        # 2. shutil.which
        found = shutil.which("lark-cli")
        if found:
            return found
        # 3. 兜底：环境变量路径
        candidates = [
            os.path.expandvars(r"%USERPROFILE%\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\lark-cli\lark-cli.exe"),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return None

    # MVP 验证过的飞书 CLI 版本
    FEISHU_VERIFIED_VERSION = "1.0.94"
    FEISHU_INCOMPATIBLE_VERSIONS: list[str] = []

    def _lark_cli_version(self) -> str | None:
        """获取 lark-cli 版本号。返回如 '1.0.94'，失败返回 None。"""
        import subprocess
        import re
        cli = self._feishu_cli_path()
        if not cli:
            return None
        try:
            proc = subprocess.run(
                [cli, "--version"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            out = (proc.stdout or "").strip()
            m = re.search(r'(\d+\.\d+\.\d+)', out)
            return m.group(1) if m else None
        except Exception:
            return None

    @staticmethod
    def _lark_check_compat(version: str | None) -> str:
        """判断飞书 CLI 版本兼容性。"""
        return BridgeServer._check_cli_compat(
            version,
            BridgeServer.FEISHU_VERIFIED_VERSION,
            BridgeServer.FEISHU_INCOMPATIBLE_VERSIONS,
        )

    def _handle_get_feishu_status(self, payload):
        """获取飞书连接状态 + CLI 版本兼容信息。

        连接判定统一走 feishu_client.health_check()，避免 bridge 与客户端各写一套判定。
        """
        health = self.feishu_client.health_check()
        cli_version = self._lark_cli_version()
        compat = self._lark_check_compat(cli_version)
        return {
            "ok": True,
            "connected": bool(health.get("connected")),
            "cli_version": cli_version,
            "cli_compat": compat,
            "verified_version": self.FEISHU_VERIFIED_VERSION,
            "error": health.get("error", ""),
        }

    def _ensure_feishu_pipeline(self):
        """确保飞书 pipeline 已创建 + 轮询线程已启动。

        MVP 启动时若 user 未授权，feishu_client.connected=False，pipeline 不会创建。
        用户在 UI 完成授权后，需补建 pipeline 并启动轮询。
        """
        if self.feishu_pipeline is None and self.feishu_client.connected:
            self.feishu_pipeline = MessagePipeline(
                channel_client=self.feishu_client,
                agents_dao=agents_dao,
                channels_dao=channels_dao,
                conv_dao=conv_dao,
                msg_dao=msg_dao,
                llm_dao=llm_dao,
                send_message_fn=self._handle_send_message,
                risk_config_dao=risk_config_dao,
            quick_llm_fn=self.quick_llm_call,
            )
            print("[Bridge] 飞书 pipeline 已创建（授权后补建）", flush=True)
        if self.feishu_pipeline is not None:
            # 启动轮询线程（start 内部有幂等判断，重复调用安全）
            self.feishu_client.start()

    def _handle_generate_feishu_qr(self, payload):
        """生成飞书授权二维码（lark-cli config init --new）。

        流程：Popen 起 lark-cli config init --new → 读 stdout 提取 URL → 生成二维码。
        """
        import subprocess
        import base64
        import io

        self._feishu_kill_qr_proc()

        if self.feishu_client.connected:
            return {"ok": False, "error": "已绑定飞书机器人，先解绑才能重新生成二维码"}

        cli_path = self._feishu_cli_path()
        if not cli_path:
            return {"ok": False, "error": "未找到 lark-cli"}

        try:
            proc = subprocess.Popen(
                [cli_path, "config", "init", "--new"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            return {"ok": False, "error": f"启动 lark-cli 失败: {e}"}

        # 读 stdout 拿 URL（lark-cli 输出二维码 + URL）
        qr_url = None
        output_lines = []
        import time
        start = time.time()
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    output_lines.append(line)
                    if not qr_url and line.startswith("https://") and "feishu.cn" in line:
                        qr_url = line
                    if time.time() - start > 15:
                        break
                    if qr_url and "等待" in line:
                        break
        except Exception:
            pass

        if not qr_url:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
            full_output = "\n".join(output_lines)
            return {"ok": False, "error": "未能从 lark-cli 输出中提取授权链接", "raw": full_output[-500:]}

        # 生成 QR 图片
        try:
            import qrcode
            qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            proc.terminate()
            return {"ok": False, "error": f"二维码生成失败: {e}", "qr_url": qr_url}

        self._feishu_qr_proc = proc
        print(f"[Bridge] Feishu 二维码已生成，URL={qr_url[:80]}...，进程 PID={proc.pid}", flush=True)

        return {
            "ok": True,
            "qr_url": qr_url,
            "qr_image": f"data:image/png;base64,{qr_b64}",
        }

    def _feishu_kill_qr_proc(self):
        proc = getattr(self, "_feishu_qr_proc", None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
            except Exception:
                pass
        self._feishu_qr_proc = None

    def _handle_unbind_feishu(self, payload):
        """解绑飞书机器人：杀掉后台进程 + 清理配置。"""
        import shutil

        self._feishu_kill_qr_proc()

        # 停止 event consume
        self.feishu_client.stop()

        # 删除配置目录（保留 cache 以外的需要谨慎，这里只删 profile 相关）
        removed = False
        cfg_dir = self._feishu_config_dir()
        if cfg_dir.exists():
            try:
                # 删除配置文件，保留 cache
                for f in cfg_dir.iterdir():
                    if f.name != "cache":
                        if f.is_file():
                            f.unlink()
                            removed = True
                        elif f.is_dir():
                            shutil.rmtree(f)
                            removed = True
                print(f"[Bridge] Feishu 已清理配置目录: {cfg_dir}", flush=True)
            except Exception as e:
                return {"ok": False, "error": f"清理配置失败: {e}"}

        # 清理 channel_binding 里飞书的绑定记录
        try:
            from storage.db import get_conn
            conn = get_conn()
            n = conn.execute('DELETE FROM channel_binding WHERE channel=?', ('feishu',)).rowcount
            conn.commit()
            print(f"[Bridge] Feishu 解绑清理: channel_binding={n}", flush=True)
        except Exception as e:
            print(f"[Bridge] Feishu 解绑清理失败: {e}", flush=True)

        try:
            channels_dao.upsert("feishu", connected=0, config={}, error="")
        except Exception:
            pass

        return {"ok": True, "removed": removed}

    # ============================================================
    # 钉钉（DWS）渠道 handlers
    # ============================================================

    @staticmethod
    def _dingtalk_config_dir() -> Path:
        return Path.home() / ".dws"

    @staticmethod
    def _dingtalk_identity_path() -> Path:
        return Path.home() / ".dws" / "identity.json"

    @staticmethod
    def _dingtalk_cli_path() -> str | None:
        import shutil
        import sys
        import os
        # 1. PyInstaller 内置（打包时硬打到 channels/dingtalk/dws.exe）
        if getattr(sys, "frozen", False):
            bundled = os.path.join(sys._MEIPASS, "channels", "dingtalk", "dws.exe")
            if os.path.isfile(bundled):
                return bundled
        # 2. shutil.which
        found = shutil.which("dws") or shutil.which("dws.exe")
        if found:
            return found
        candidates = [
            os.path.expandvars(r"%USERPROFILE%\.local\bin\dws.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Microsoft\WindowsApps\dws.exe"),
            "/usr/local/bin/dws",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    # MVP 验证过的钉钉 DWS 版本
    DINGTALK_VERIFIED_VERSION = "1.0.61"
    DINGTALK_INCOMPATIBLE_VERSIONS: list[str] = []

    @staticmethod
    def _dws_cli_version() -> str | None:
        """获取 dws 版本号。返回如 '1.0.61'，失败返回 None。"""
        import subprocess
        import re
        cli = BridgeServer._dingtalk_cli_path()
        if not cli:
            return None
        try:
            proc = subprocess.run(
                [cli, "--version"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            out = (proc.stdout or "").strip()
            m = re.search(r'(\d+\.\d+\.\d+)', out)
            return m.group(1) if m else None
        except Exception:
            return None

    @staticmethod
    def _dws_check_compat(version: str | None) -> str:
        """判断钉钉 DWS 版本兼容性。"""
        return BridgeServer._check_cli_compat(
            version,
            BridgeServer.DINGTALK_VERIFIED_VERSION,
            BridgeServer.DINGTALK_INCOMPATIBLE_VERSIONS,
        )

    def _handle_get_dingtalk_status(self, payload):
        """获取钉钉连接状态 + CLI 版本兼容信息。

        connected 沿用 dingtalk_client.connected（CLI 探测不出结论时回退为“已绑定即连接”，
        避免网络抖动误判离线）；用户名/错误信息取自 health_check()，不在此重复实现健康判定。
        """
        health = self.dingtalk_client.health_check()
        cli_version = self._dws_cli_version()
        return {
            "ok": True,
            "connected": self.dingtalk_client.connected,
            "username": health.get("user_name", ""),
            "corp_name": health.get("corp_name", ""),
            "cli_version": cli_version,
            "cli_compat": self._dws_check_compat(cli_version),
            "verified_version": self.DINGTALK_VERIFIED_VERSION,
            "error": health.get("error", ""),
        }

    def _handle_generate_dingtalk_qr(self, payload):
        """生成钉钉授权二维码（device code 模式）。

        流程：
          1. Popen 起 dws auth login --device
          2. 实时读 stdout，提取 user_code + verify_url
          3. 拼接完整 URL（带 user_code），用 qrcode 生成 PNG base64 返回
          4. 进程留在后台轮询等授权（最多 15 分钟）
        """
        import subprocess
        import base64
        import io

        # 如果已经绑定了，不需要再生成
        if self._dingtalk_identity_path().exists():
            return {"ok": False, "error": "已绑定钉钉账号，先解绑才能重新生成二维码"}

        # 1. 定位 CLI
        cli_path = self._dingtalk_cli_path()
        if not cli_path:
            return {"ok": False, "error": "未找到 dws CLI，请先安装：npm install -g @alicloud/dws-cli"}

        # 2. 启动 dws auth login --device（不阻塞）
        try:
            proc = subprocess.Popen(
                [cli_path, "auth", "login", "--device", "--no-browser"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            return {"ok": False, "error": f"启动 dws auth login 失败: {e}"}

        # 3. 读 stdout 拿 URL + user_code（最多等 10 秒）
        import re
        import time
        import threading

        verify_url = None
        user_code = None
        full_url = None
        output_lines = []
        start = time.time()

        def _read_output():
            try:
                for line in proc.stdout:
                    output_lines.append(line.strip())
            except Exception:
                pass

        reader_thread = threading.Thread(target=_read_output, daemon=True)
        reader_thread.start()

        while time.time() - start < 25:
            if verify_url and user_code:
                break
            # 扫描已有的输出行
            for line in output_lines:
                low = line.lower()
                if not verify_url and "login.dingtalk.com" in low and "verify" in low:
                    # 提取 URL：可能是 "链接: https://..."
                    m = re.search(r'https://[^\s)]+verify[^\s)]*', line)
                    if m:
                        verify_url = m.group(0).strip('.:')
                if not user_code:
                    m = re.search(r'(?:授权码|user[_\s-]*code|code)[::]\s*([A-Z0-9-]+)', line, re.IGNORECASE)
                    if m:
                        user_code = m.group(1)
                if not full_url and "user_code=" in low:
                    m = re.search(r'https://[^\s)]+?user_code=[A-Z0-9-]+', line)
                    if m:
                        full_url = m.group(0).strip('.:')
            time.sleep(0.3)

        if not verify_url or not user_code:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
            raw = "\n".join(output_lines[-20:])
            print(f"[Bridge] Dingtalk QR 解析失败！raw output ({len(output_lines)} lines):\n{raw}", flush=True)
            return {"ok": False, "error": "未能从 dws 输出中提取二维码信息", "raw": raw[:500]}

        # 优先用带 user_code 的完整 URL，否则拼接
        qr_url = full_url or f"{verify_url}?user_code={user_code}"
        print(f"[Bridge] Dingtalk device_code={user_code}, url={qr_url[:80]}...", flush=True)

        # 4. 生成 QR 图片
        try:
            import qrcode
            qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            proc.terminate()
            return {"ok": False, "error": f"二维码生成失败: {e}", "qr_url": qr_url}

        # 5. 保存进程引用，前端轮询检查 identity.json 是否生成
        self._dingtalk_qr_proc = proc
        print(f"[Bridge] Dingtalk 二维码已生成，code={user_code}, PID={proc.pid}，等待用户扫码", flush=True)

        return {
            "ok": True,
            "qr_url": qr_url,
            "qr_image": f"data:image/png;base64,{qr_b64}",
            "user_code": user_code,
            "expires_in": 900,
        }

    def _dingtalk_kill_qr_proc(self):
        proc = getattr(self, "_dingtalk_qr_proc", None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                print(f"[Bridge] 已杀掉残留 dws auth login 进程 PID={proc.pid}", flush=True)
            except Exception:
                pass
        self._dingtalk_qr_proc = None

    def _handle_unbind_dingtalk(self, payload):
        """解绑钉钉：杀掉后台扫码进程 + 删除 ~/.dws 凭据。"""
        import shutil

        self._dingtalk_kill_qr_proc()

        removed = False
        ident = self._dingtalk_identity_path()
        if ident.exists():
            try:
                # 优先用 dws auth logout 安全登出
                cli_path = self._dingtalk_cli_path()
                if cli_path:
                    try:
                        import subprocess
                        result = subprocess.run(
                            [cli_path, "auth", "logout"],
                            capture_output=True, text=True, timeout=10,
                        )
                        print(f"[Bridge] Dingtalk logout: {result.stdout.strip()[:100]} {result.stderr.strip()[:100]}", flush=True)
                    except Exception as e:
                        print(f"[Bridge] Dingtalk logout 失败: {e}，直接删文件", flush=True)
                # 安全起见手动也删一下关键凭据
                for fname in ("identity.json", "token.json", "profiles.json"):
                    f = self._dingtalk_config_dir() / fname
                    if f.exists():
                        f.unlink(missing_ok=True)
                        removed = True
            except Exception as e:
                print(f"[Bridge] Dingtalk 解绑异常: {e}", flush=True)

        # 清理 channel_binding 里钉钉的绑定记录
        try:
            from storage.db import get_conn
            conn = get_conn()
            n = conn.execute('DELETE FROM channel_binding WHERE channel=?', ('dingtalk',)).rowcount
            conn.commit()
            print(f"[Bridge] Dingtalk 解绑清理: channel_binding={n}", flush=True)
        except Exception as e:
            print(f"[Bridge] Dingtalk 解绑清理失败: {e}", flush=True)

        print(f"[Bridge] Dingtalk 解绑完成，removed={removed}", flush=True)
        return {"ok": True, "removed": removed}

    # ==================== 钉钉通讯录（连接配置用） ====================

    def _dingtalk_cli_run(self, *args, timeout=15):
        """执行 dws CLI 命令，返回 (ok: bool, data_or_text, error_or_empty)."""
        import subprocess, json as _json
        cli = self._dingtalk_cli_path()
        if not cli:
            return False, None, "dws CLI 未找到，请先安装并配置 PATH"
        try:
            result = subprocess.run(
                [cli] + list(args),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout,
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            if result.returncode != 0:
                return False, None, err or out or f"退出码 {result.returncode}"
            # 尝试解析 JSON
            try:
                return True, _json.loads(out), ""
            except Exception:
                return True, out, ""
        except subprocess.TimeoutExpired:
            return False, None, f"命令超时（{timeout}s）"
        except Exception as e:
            return False, None, str(e)

    def _handle_fetch_dingtalk_contacts(self, payload):
        """拉取钉钉联系人：会话列表（私聊+群聊）+ 通讯录补充。

        策略（兼顾完整性和可操作性）：
          1. conversation-list → 所有已有会话（私聊和群聊），peer_id=conversationId
             → dingtalk_client send/pull 都用 conversationId，必须有
          2. +my-groups → 群聊 member_count 补充
          3. contact dept + members → 全企业通讯录名字补充，以及没聊过的同事展示
             （没 conversationId 的成员暂无法直接发/拉消息，留作二期）
        """
        # 1. 检查是否已绑定
        if not self._dingtalk_identity_path().exists():
            return {"ok": False, "error": "钉钉未绑定，请先在连接管理扫码绑定",
                    "contacts": []}

        # 2. 拉全量会话（私聊+群聊）
        conv_map = {}
        ok_cl, data_cl, err_cl = self._dingtalk_cli_run(
            "chat", "+conversation-list", "--page-all", "--limit", "100",
            "--format", "json"
        )
        if ok_cl and isinstance(data_cl, dict):
            for c in data_cl.get("conversations", []):
                cid = c.get("openConversationId", "")
                cname = c.get("conversationName", "")
                if not cid or cname.startswith("工作通知") or cname.startswith("主页通知"):
                    continue
                conv_map[cid] = {"conversationId": cid, "name": cname, "peer_type": None}
            print(f"[Bridge] Dingtalk conversation-list: {len(conv_map)} 个会话", flush=True)
        else:
            print(f"[Bridge] Dingtalk conversation-list 失败: {err_cl}", flush=True)

        # 3. 拉群聊补充 memberCount（+my-groups 比 conversation-list 多 memberCount）
        ok_g, data_g, err_g = self._dingtalk_cli_run(
            "chat", "+my-groups", "--page-all", "--limit", "100",
            "--format", "json"
        )
        group_ids = set()
        if ok_g and isinstance(data_g, dict):
            for g in data_g.get("groups", []):
                cid = g.get("conversationId", "")
                group_ids.add(cid)
                if cid in conv_map:
                    conv_map[cid]["peer_type"] = "group"
                    conv_map[cid]["member_count"] = g.get("memberCount", 0)
                else:
                    cname = g.get("name", "")
                    if cname.startswith("工作通知"):
                        continue
                    conv_map[cid] = {
                        "conversationId": cid,
                        "name": cname or cid[:20],
                        "peer_type": "group",
                        "member_count": g.get("memberCount", 0),
                    }
            print(f"[Bridge] Dingtalk my-groups: {len(group_ids)} 个群聊", flush=True)
        else:
            print(f"[Bridge] Dingtalk my-groups 失败: {err_g}", flush=True)

        # 4. 通讯录补充：全企业成员名字
        contact_name_map = {}
        contact_user_ids = set()
        ok_d, data_d, err_d = self._dingtalk_cli_run(
            "contact", "dept", "list-children", "--dept", "1",
            "--format", "json"
        )
        dept_ids = ["1"]
        if ok_d and isinstance(data_d, dict):
            for d in data_d.get("result", []):
                did = d.get("deptId")
                if not did:
                    continue
                dept_ids.append(str(did))
        for did in dept_ids:
            ok_m, data_m, _ = self._dingtalk_cli_run(
                "contact", "+list-dept-members", "--depts", did,
                "--format", "json"
            )
            if not ok_m or not isinstance(data_m, dict):
                continue
            for m in data_m.get("data", {}).get("members", []):
                uid = m.get("userId", "")
                if not uid:
                    continue
                contact_user_ids.add(uid)
                contact_name_map[uid] = m.get("name", "") or uid
        print(f"[Bridge] Dingtalk contact 通讯录: {len(contact_user_ids)} 个成员", flush=True)

        # 5. 组装联系人列表
        contacts = []
        conv_user_names = set()
        friend_n = group_n = 0
        for cid, conv in conv_map.items():
            ptype = conv.get("peer_type")
            if ptype is None:
                ptype = "friend"
            entry = {
                "peer_type": ptype,
                "peer_id": cid,
                "peer_name": conv.get("name", "") or cid[:20],
            }
            if ptype == "group":
                entry["member_count"] = conv.get("member_count", 0)
                group_n += 1
            else:
                friend_n += 1
                conv_user_names.add(conv.get("name", ""))
            contacts.append(entry)

        # 6. 通讯录里没聊过的同事，作为可展示的成员补充
        for uid, uname in contact_name_map.items():
            if uname in conv_user_names or uid in conv_user_names:
                continue
            already = any(c.get("peer_type") == "friend" and c.get("peer_id") == uid for c in contacts)
            if already:
                continue
            contacts.append({
                "peer_type": "friend",
                "peer_id": uid,
                "peer_name": uname,
                "from_contact": True,
            })
            friend_n += 1

        contacts.sort(key=lambda c: (c.get("peer_type", ""), c.get("peer_name", "")))

        # 缓存供 save 时补 peer_name
        self._dingtalk_cache = contacts
        extra_n = friend_n - (friend_n if friend_n <= len(conv_map) else len(conv_map))
        note = f"钉钉 {friend_n} 成员 / {group_n} 群聊"
        print(f"[Bridge] fetch_dingtalk_contacts: {note}", flush=True)
        return {"ok": True, "contacts": contacts, "source": "dws", "note": note}

    def _handle_save_dingtalk_agent_contacts(self, payload):
        """保存智能体在钉钉渠道的启用 peer 列表（复用 feishu 模板）。"""
        from storage import channels_dao
        agent_id = (payload or {}).get("agent_id")
        peers = (payload or {}).get("peers") or []
        if not agent_id:
            return {"ok": False, "error": "缺少 agent_id"}
        try:
            existing = channels_dao.list_bindings(agent_id, "dingtalk")
            for b in existing:
                channels_dao.set_binding(
                    agent_id=agent_id, channel="dingtalk",
                    peer_id=b["peer_id"], peer_name=b.get("peer_name", ""),
                    peer_type=b.get("peer_type", "group"), enabled=False,
                )
            cache = getattr(self, '_dingtalk_cache', None) or []
            cache_map = {(c.get("peer_type"), c.get("peer_id")): c.get("peer_name", "")
                         for c in cache if c.get("peer_id")}
            for p in peers:
                pid = p.get("peer_id", "")
                ptype = p.get("peer_type", "group")
                pname = p.get("peer_name", "") or cache_map.get((ptype, pid), "")
                channels_dao.set_binding(
                    agent_id=agent_id, channel="dingtalk",
                    peer_id=pid, peer_name=pname,
                    peer_type=ptype, enabled=True,
                )
        except Exception as e:
            return {"ok": False, "error": f"保存失败: {e}"}
        return {"ok": True}

    def _handle_get_dingtalk_agent_contacts(self, payload):
        """读取某个智能体在钉钉渠道已启用的 peer 列表。"""
        from storage import channels_dao
        agent_id = (payload or {}).get("agent_id")
        if not agent_id:
            return {"ok": False, "error": "缺少 agent_id"}
        try:
            bindings = channels_dao.list_bindings(agent_id, "dingtalk")
            peers = [
                {
                    "peer_type": b.get("peer_type", "group"),
                    "peer_id": b["peer_id"],
                    "peer_name": b.get("peer_name", b["peer_id"]),
                }
                for b in bindings if b.get("enabled")
            ]
            return {"ok": True, "peers": peers}
        except Exception as e:
            return {"ok": False, "error": f"读取失败: {e}"}

    def _handle_fetch_feishu_contacts(self, payload):
        """获取飞书通讯录 + 群聊列表（优先 user 身份）。"""
        # 先查身份模式
        auth_mode = "bot"
        try:
            ok, out, _ = self._feishu_run(["auth", "status", "--json"], timeout=10)
            if ok:
                import json as _json
                data = _json.loads(out)
                identities = data.get("identities", {}) or {}
                user_ident = identities.get("user", {}) or {}
                bot_ident = identities.get("bot", {}) or {}
                if user_ident.get("status") == "ready" or user_ident.get("available"):
                    auth_mode = "user"
                elif bot_ident.get("status") == "ready" or bot_ident.get("available"):
                    auth_mode = "bot"
        except Exception:
            pass

        contacts = self.feishu_client.get_contacts()
        # 缓存通讯录供 save 时取 peer_name（与企微 _wecom_cache 对齐）
        self._feishu_cache = contacts
        return {"ok": True, "contacts": contacts, "auth_mode": auth_mode}

    def _handle_save_feishu_agent_contacts(self, payload):
        """保存智能体在飞书渠道的启用 peer 列表。"""
        agent_id = (payload or {}).get("agent_id")
        peers = (payload or {}).get("peers") or []
        if not agent_id:
            return {"ok": False, "error": "缺少 agent_id"}
        try:
            # 先把当前 agent 的所有 feishu 绑定全部置为 disabled
            existing = channels_dao.list_bindings(agent_id, "feishu")
            for b in existing:
                channels_dao.set_binding(
                    agent_id=agent_id, channel="feishu",
                    peer_id=b["peer_id"], peer_name=b.get("peer_name", ""),
                    peer_type=b.get("peer_type", "friend"), enabled=False,
                )
            # 把新勾选的 peers 设为 enabled（或创建新绑定）
            # peer_name 兜底：前端未传时从 _feishu_cache 补全，避免历史对话显示 oc_xxx
            cache = getattr(self, '_feishu_cache', None) or []
            cache_map = {(c.get("peer_type"), c.get("peer_id")): c.get("peer_name", "")
                         for c in cache if c.get("peer_id")}
            for p in peers:
                pid = p.get("peer_id", "")
                ptype = p.get("peer_type", "group")
                pname = p.get("peer_name", "") or cache_map.get((ptype, pid), "")
                channels_dao.set_binding(
                    agent_id=agent_id,
                    channel="feishu",
                    peer_id=pid,
                    peer_name=pname,
                    peer_type=ptype,
                    enabled=True,
                )
        except Exception as e:
            return {"ok": False, "error": f"保存失败: {e}"}
        return {"ok": True}

    def _handle_get_feishu_agent_contacts(self, payload):
        """读取某个智能体在飞书渠道已启用的 peer 列表。"""
        agent_id = (payload or {}).get("agent_id")
        if not agent_id:
            return {"ok": False, "error": "缺少 agent_id"}
        try:
            bindings = channels_dao.list_bindings(agent_id, "feishu")
            peers = [
                {
                    "peer_type": b.get("peer_type", "group"),
                    "peer_id": b["peer_id"],
                    "peer_name": b.get("peer_name", b["peer_id"]),
                }
                for b in bindings
                if b.get("enabled")
            ]
        except Exception as e:
            return {"ok": False, "error": f"读取失败: {e}"}
        return {"ok": True, "peers": peers}

    # ================ 飞书 User OAuth ================

    def _feishu_cli_path(self) -> str | None:
        """定位 lark-cli.exe —— 与静态方法 BridgeServer._feishu_cli_path 完全相同的查找逻辑。

        历史：bridge.py 里曾有两个同名方法（L2793 静态 + L3585 实例），Python 后定义的覆盖前定义的，
        导致静态方法里写的 sys._MEIPASS 查找完全被跳过！所有 self._feishu_cli_path() 调用
        都走的是没 MEIPASS 的硬编码版本 —— 开发机能跑只是因为刚好有 .trae-cn/plugins/... 路径。
        现在统一走完整查找链：MEIPASS → PATH → 环境变量路径 → fallback。
        """
        import shutil
        import sys
        import os
        # 1. PyInstaller 内置
        if getattr(sys, "frozen", False):
            bundled = os.path.join(sys._MEIPASS, "channels", "feishu", "lark-cli.exe")
            if os.path.isfile(bundled):
                return bundled
        # 2. shutil.which
        found = shutil.which("lark-cli")
        if found:
            return found
        # 3. 兜底：环境变量路径
        candidates = [
            os.path.expandvars(r"%USERPROFILE%\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe"),
            os.path.expandvars(r"%USERPROFILE%\.trae\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\lark-cli\lark-cli.exe"),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return None

    def _feishu_run(self, args, timeout=15):
        """运行 lark-cli 命令，返回 (ok, stdout, stderr)。"""
        import subprocess
        cli = self._feishu_cli_path()
        if not cli:
            return False, "", "lark-cli not found"
        try:
            proc = subprocess.run(
                [cli] + args,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout,
            )
            return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "timeout"
        except Exception as e:
            return False, "", str(e)

    def _handle_generate_feishu_user_auth(self, payload):
        """生成飞书 user OAuth device code + 二维码，并启动后台线程等待授权完成。"""
        import json as _json
        import base64
        import io
        import threading
        import subprocess

        print(f"[Bridge][FeishuUserAuth] === generate 被调用 ===", flush=True)

        if not self.feishu_client.connected:
            print(f"[Bridge][FeishuUserAuth] ❌ bot 未绑定", flush=True)
            return {"ok": False, "error": "请先完成应用凭证绑定（第一步）"}

        cli = self._feishu_cli_path()
        if not cli:
            return {"ok": False, "error": "未找到 lark-cli"}

        # MVP 完整业务域：消息 + 通讯录 + 文档 + 云空间 + 日历 + 任务 + 多维表格 + 电子表格 + 知识库 + 审批 + 邮件 + 妙记
        domain = "im,contact,docs,drive,calendar,task,base,sheets,wiki,approval,mail,minutes"
        # --domain im 不包含 im:message.send_as_user，需显式追加（AI 代用户发消息必需）
        extra_scope = "im:message.send_as_user"
        print(f"[Bridge][FeishuUserAuth] 请求 domain={domain} scope={extra_scope}", flush=True)
        ok, out, err = self._feishu_run(
            ["auth", "login", "--domain", domain, "--scope", extra_scope, "--no-wait", "--json"],
            timeout=30,
        )
        print(f"[Bridge][FeishuUserAuth] CLI结果 ok={ok} err={(err or '')[:150]}", flush=True)
        if not ok:
            return {"ok": False, "error": f"生成授权失败: {err or out}"}

        try:
            data = _json.loads(out)
        except Exception:
            return {"ok": False, "error": f"解析输出失败: {out[:200]}"}

        device_code = data.get("device_code")
        verification_url = data.get("verification_url")
        user_code = data.get("user_code")
        expires_in = data.get("expires_in", 600)

        print(f"[Bridge][FeishuUserAuth] ✅ device_code={device_code[:40] if device_code else 'None'}... user_code={user_code} expires={expires_in}s", flush=True)

        if not verification_url:
            return {"ok": False, "error": "未获取到授权链接", "raw": out[:300]}

        # 用 lark-cli 自己生成 QR
        import tempfile
        import os
        tmp_dir = tempfile.gettempdir()
        qr_path = os.path.join(tmp_dir, f"feishu_user_auth_qr_{os.getpid()}.png")

        ok2, out2, err2 = self._feishu_run(
            ["auth", "qrcode", verification_url, "--output", qr_path],
            timeout=15,
        )

        if ok2 and os.path.exists(qr_path):
            with open(qr_path, "rb") as f:
                qr_b64 = base64.b64encode(f.read()).decode("ascii")
            try:
                os.unlink(qr_path)
            except Exception:
                pass
        else:
            # fallback: qrcode 库
            try:
                import qrcode
                qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
                qr.add_data(verification_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            except Exception as e:
                return {"ok": False, "error": f"二维码生成失败: {e}"}

        # 清理旧的 device_code 和后台线程状态（刷新 QR 场景）
        self._feishu_user_auth_device_code = None
        self._feishu_user_auth_poll_done = False
        self._feishu_user_auth_poll_error = None

        # 保存新 device_code + 启动后台线程阻塞等待授权完成
        self._feishu_user_auth_device_code = device_code

        def _poll_worker():
            """后台线程：阻塞执行 auth login --device-code，等用户授权完成后 user 身份自动写入本地凭证。"""
            print(f"[Bridge][FeishuUserAuth] 🧵 后台线程启动，阻塞等待 device_code 授权...", flush=True)
            try:
                proc = subprocess.run(
                    [cli, "auth", "login", "--device-code", device_code],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=expires_in + 30,  # device_code 有效期 + 缓冲
                )
                print(f"[Bridge][FeishuUserAuth] 🧵 后台线程结束 rc={proc.returncode} err={(proc.stderr or '')[:200]}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"[Bridge][FeishuUserAuth] 🧵 后台线程超时（device_code 过期）", flush=True)
                self._feishu_user_auth_poll_error = "expired"
            except Exception as e:
                print(f"[Bridge][FeishuUserAuth] 🧵 后台线程异常: {e}", flush=True)
                self._feishu_user_auth_poll_error = str(e)
            finally:
                self._feishu_user_auth_poll_done = True
                self._feishu_user_auth_device_code = None  # device_code 已消费

        t = threading.Thread(target=_poll_worker, daemon=True, name="feishu_user_auth_poll")
        t.start()

        print(f"[Bridge][FeishuUserAuth] ✅ QR 已生成 + 后台轮询线程已启动, user_code={user_code}", flush=True)

        return {
            "ok": True,
            "qr_image": f"data:image/png;base64,{qr_b64}",
            "user_code": user_code,
            "verification_url": verification_url,
        }

    def _handle_poll_feishu_user_auth(self, payload):
        """轮询 user 授权状态 — 有 device_code pending 时不查 auth status（旧 token 会误报）。"""
        import json as _json
        import subprocess

        # 快速路径：如果后台线程已经标记了错误
        if getattr(self, "_feishu_user_auth_poll_error", None):
            err = self._feishu_user_auth_poll_error
            self._feishu_user_auth_poll_error = None
            print(f"[Bridge][FeishuUserAuth] ⚠️ poll 返回错误: {err}", flush=True)
            return {"ok": True, "authorized": False, "expired": True}

        # device_code 还在轮询中 → 直接返回 pending，不跑 auth status（避免旧 token 误报）
        if getattr(self, "_feishu_user_auth_device_code", None) and not getattr(self, "_feishu_user_auth_poll_done", False):
            return {"ok": True, "authorized": False, "pending": True}

        # 轻量检查：auth status --json 立即返回
        cli = self._feishu_cli_path()
        if not cli:
            return {"ok": True, "authorized": False, "pending": True}

        try:
            proc = subprocess.run(
                [cli, "auth", "status", "--json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=5,
            )
            if proc.returncode == 0:
                data = _json.loads(proc.stdout)
                identities = data.get("identities", {}) or {}
                user_ident = identities.get("user", {}) or {}
                user_ready = user_ident.get("status") == "ready"
                if user_ready:
                    username = user_ident.get("name", "") or user_ident.get("open_id", "")
                    print(f"[Bridge][FeishuUserAuth] 🎉 授权检测到! username={username}", flush=True)
                    self._feishu_user_auth_device_code = None
                    self._feishu_user_auth_poll_done = True
                    # 授权成功后确保 pipeline 已创建 + 轮询已启动
                    # （MVP 启动时若未授权，pipeline 不会创建，需在此补建）
                    self._ensure_feishu_pipeline()
                    scope_result = self.feishu_client.check_required_scopes()
                    if scope_result.get("scope_ok"):
                        print(f"[Bridge][FeishuUserAuth] ✅ scope 完整，共 {len(scope_result.get('granted', []))} 个必要 scope", flush=True)
                        return {
                            "ok": True,
                            "authorized": True,
                            "username": username,
                            "scope_ok": True,
                        }
                    missing = scope_result.get("missing", [])
                    hint = scope_result.get("hint", "")
                    print(f"[Bridge][FeishuUserAuth] ⚠️ scope 不完整! missing={missing}", flush=True)
                    return {
                        "ok": True,
                        "authorized": True,
                        "scope_ok": False,
                        "username": username,
                        "missing_scopes": missing,
                        "hint": hint,
                    }
        except Exception:
            pass

        # 如果 device_code 已经没了且后台线程也结束了但 user 还没 ready → device_code 过期
        if not getattr(self, "_feishu_user_auth_device_code", None) and getattr(self, "_feishu_user_auth_poll_done", False):
            print(f"[Bridge][FeishuUserAuth] ⚠️ device_code 已过期", flush=True)
            return {"ok": True, "authorized": False, "expired": True}

        return {"ok": True, "authorized": False, "pending": True}

    def _feishu_get_username(self):
        """获取当前 user 身份的用户名。"""
        import json as _json
        ok, out, err = self._feishu_run(
            ["im", "+get-user", "me", "--as", "user", "--json"],
            timeout=10,
        )
        if ok:
            try:
                data = _json.loads(out)
                u = data.get("data", {})
                return u.get("name") or u.get("user_name") or ""
            except Exception:
                pass
        # fallback: 从 auth status 读
        ok2, out2, err2 = self._feishu_run(["auth", "status", "--json"], timeout=10)
        if ok2:
            try:
                data = _json.loads(out2)
                identities = data.get("identities", {}) or {}
                user_ident = identities.get("user", {}) or {}
                return user_ident.get("name", "")
            except Exception:
                pass
        return ""

    def _handle_get_feishu_user_auth_status(self, payload):
        """查询 user 身份授权状态（含 scope 完整性检测）。"""
        import json as _json
        import subprocess

        cli = self._feishu_cli_path()
        if not cli:
            return {"ok": True, "authorized": False}

        # 跑一个轻量命令验证 user 身份是否可用
        try:
            proc = subprocess.run(
                [cli, "auth", "status", "--json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10,
            )
            if proc.returncode == 0:
                data = _json.loads(proc.stdout)
                identities = data.get("identities", {}) or {}
                user_ident = identities.get("user", {}) or {}
                bot_ident = identities.get("bot", {}) or {}
                user_ready = user_ident.get("status") == "ready"
                username = user_ident.get("name", "") or user_ident.get("open_id", "")
                if user_ready:
                    scope_result = self.feishu_client.check_required_scopes()
                    if scope_result.get("scope_ok"):
                        return {
                            "ok": True,
                            "authorized": True,
                            "username": username,
                            "scope_ok": True,
                        }
                    return {
                        "ok": True,
                        "authorized": True,
                        "username": username,
                        "scope_ok": False,
                        "missing_scopes": scope_result.get("missing", []),
                        "hint": scope_result.get("hint", ""),
                    }
                return {"ok": True, "authorized": False}
        except Exception:
            pass

        return {"ok": True, "authorized": False}

    def _handle_get_oa_contacts(self, payload):
        """获取公众号关注者列表（受 500 次/日限制，默认返回缓存）。"""
        refresh = bool(payload.get("refresh", False))
        if refresh:
            contacts = self.oa_client.refresh_followers()
        else:
            contacts = self.oa_client.get_contacts()
        return {"contacts": contacts}

    def _handle_test_wcf(self, payload):
        """WCF 通道健康检查。对齐新的三步引导语义。

        用户目标：确认底座正不正常 + 微信是否联通 + MVP 是否接入。
        检查项（与三步引导一致，避免混淆 is_login 含义）：
          1. 底座端口    —— 端口 10086 是否在监听（DLL 注入结果）
          2. 底座就绪    —— 微信本身已登录（窗口标题/类名判断 wechat_logged_in）
          3. MVP 接入    —— MVP 已作为客户端接入 WCF（self._connected）
        """
        health = self.wcf_client.health_check()

        port_ok = health.get("port_10086", False)
        wechat_logged_in = bool(health.get("wechat_logged_in", False))
        mvp_connected = bool(health.get("is_login", False))  # self._connected && _wcf_real
        hint = health.get("hint", "")

        steps = []
        # 1. 底座端口
        if port_ok:
            steps.append({"name": "底座端口", "status": "pass", "info": "端口 10086 正常（DLL 已注入）"})
        else:
            steps.append({"name": "底座端口", "status": "fail",
                          "info": "端口 10086 未监听，请先通过开关「连接」注入 WCF"})

        # 2. 底座就绪（微信登录状态，独立判断）
        if wechat_logged_in:
            nick = health.get("wechat_nickname", "") or "微信用户"
            steps.append({"name": "底座就绪", "status": "pass", "info": f"微信已登录（{nick}）"})
        else:
            if port_ok:
                steps.append({"name": "底座就绪", "status": "fail",
                              "info": "端口已监听但微信未登录，请先在微信客户端扫码登录"})
            else:
                steps.append({"name": "底座就绪", "status": "skip", "info": "端口未就绪，跳过检查"})

        # 3. MVP 接入
        if mvp_connected:
            wxid = health.get("self_wxid", "") or ""
            info = "MVP 已接入 WCF"
            if wxid:
                info += f"（wxid={wxid}）"
            steps.append({"name": "MVP 接入", "status": "pass", "info": info})
        else:
            if port_ok and wechat_logged_in:
                steps.append({"name": "MVP 接入", "status": "fail",
                              "info": "底座就绪但 MVP 尚未接入，请点击上方开关「连接」"})
            else:
                steps.append({"name": "MVP 接入", "status": "skip",
                              "info": "前序未通过，跳过检查"})

        ok = mvp_connected

        # 写入渠道状态
        try:
            channels_dao.upsert("wcf", connected=1 if ok else 0,
                                config_json="{}", error="" if ok else hint)
        except Exception:
            pass

        return {"steps": steps, "connected": ok, "health": health}

    def _handle_get_wcf_health(self, payload):
        """获取 WCF 底座健康状态（只读）。

        注意：通用路由已经在外层包了一层 {ok: True, action: 'get_wcf_health', data: <本函数返回值>}，
        前端读取 data.data 拿到真实 health 对象。因此本函数**绝不能再包一层 {ok:true, data:...}**，
        否则会变成 data.data.data.health，前端所有字段全部变成 undefined，
        导致 wechat_logged_in=false 显示「等待登录」、好友/群聊数量显示「—」等连锁Bug。
        """
        try:
            health = self.wcf_client.health_check()
        except Exception as e:
            print(f"[Bridge] get_wcf_health 异常: {type(e).__name__}: {e}", flush=True)
            return {
                "port_10086": False,
                "port_10087": False,
                "connected": False,
                "is_login": False,
                "self_wxid": "",
                "wechat_version": "",
                "version": "",
                "friend_count": 0,
                "group_count": 0,
                "wechat_logged_in": False,
                "wechat_nickname": "",
                "hint": f"health_check异常: {type(e).__name__}",
            }
        # 后端是否真的接入了（_connected 为真）= backendConnected，供前端兜底
        backend_connected = bool(health.get("connected") or health.get("is_login"))
        health.setdefault("backendConnected", backend_connected)
        health.setdefault("version", health.get("wechat_version", ""))
        return health

    def _handle_env_diagnose(self, payload):
        """环境预检：逐项检查微信 + wcferry 环境。"""
        try:
            from channel.wcf_client import WcfClient
            return WcfClient.env_diagnose()
        except Exception as e:
            print(f"[Bridge] env_diagnose 异常: {type(e).__name__}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return {"ok": False, "summary": f"诊断异常: {e}", "checks": []}

    def _handle_get_learning_status(self, payload):
        """返回某个 agent 的学习状态：已积累记忆数、上次提炼时间、当前会话消息数、是否正在提炼等。
        前端「智能学习」Tab 的状态卡用这个接口填数据。

        Payload: { agent_id: str }
        返回: {
            profile_len, episodic_len,
            last_refine_at (unix秒),
            msg_count (所有会话该 agent 的总消息数),
            refine_interval (每 N 条提炼一次),
            refining (bool, 当前是否有提炼任务跑在 executor),
            just_refreshed (bool, 前端不需要可以忽略),
            profile_added / episodic_added (int, just_refreshed 时有效),
          }
        """
        agent_id = payload.get("agent_id") if isinstance(payload, dict) else None
        if not agent_id:
            return {
                "profile_len": 0, "episodic_len": 0,
                "last_refine_at": 0, "msg_count": 0,
                "refine_interval": MEMORY_REFINE_THRESHOLD,
                "refining": False,
            }
        agent = agents_dao.get(agent_id)
        mem = self._parse_memory_json_safe(agent.get("memories") if agent else "")
        # 计数：该 agent 所有 conversation 下的 messages 总数（提炼触发按单会话 conv.message_count，但给用户看整体更直观）
        try:
            from storage import db as _db
            import sqlite3 as _sq
            total = 0
            last_ref = int(mem.get("last_refine_at") or 0)
            with _sq.connect(_db.DB_PATH) as conn:
                cur = conn.execute(
                    "SELECT COALESCE(SUM(message_count),0) FROM conversations WHERE agent_id = ?",
                    (str(agent_id),),
                )
                row = cur.fetchone()
                if row: total = int(row[0] or 0)
        except Exception:
            total = 0
            last_ref = 0
        # 判断是否正在提炼：executor 队列里还有未完成任务（粗略估算）
        refining = False
        try:
            if hasattr(self, "_memory_executor") and self._memory_executor is not None:
                pending = getattr(self._memory_executor, "_work_queue", None)
                refining = bool(pending and not pending.empty())
        except Exception:
            pass
        return {
            "profile_len":   len(mem.get("user_profile") or []),
            "episodic_len":  len(mem.get("episodic") or []),
            "last_refine_at": last_ref,
            "msg_count":     total,
            "refine_interval": MEMORY_REFINE_THRESHOLD,
            "refining":      refining,
        }

    def _handle_start_wcf(self, payload):
        """一键接入 WCF。异步执行，不阻塞主线程。
        进度和结果通过 send_to_js 推送到前端。
        """
        import threading as _thr

        def _on_progress(step, detail):
            self.send_to_js("start_wcf_progress", {
                "step": step, "detail": detail
            })

        def _do_connect():
            try:
                r = self.wcf_client.start_wcf(progress_cb=_on_progress)
                ok = r.get("ok", False)
                mode = r.get("mode", "none")
                err = r.get("error", "")
                contacts = r.get("contacts", 0)
                wxid = r.get("wxid", "")

                print(f"[Bridge start_wcf] 完成: ok={ok} mode={mode} wxid={wxid!r} contacts={contacts} error={err!r}",
                      flush=True)

                if ok:
                    try:
                        channels_dao.upsert("wcf", connected=1, config_json="{}", error="")
                    except Exception:
                        pass
                else:
                    try:
                        channels_dao.upsert("wcf", connected=0, config_json="{}", error=err or "start_wcf失败")
                    except Exception:
                        pass

                # 推送最终结果
                self.send_to_js("start_wcf", {
                    "ok": ok, "error": err, "wxid": wxid,
                    "contacts": contacts, "mode": mode
                })
            except Exception as e:
                print(f"[Bridge start_wcf] 异常: {e}", flush=True)
                self.send_to_js("start_wcf", {
                    "ok": False, "error": str(e), "wxid": "",
                    "contacts": 0, "mode": "none"
                })

        # 异步启动，立即返回
        t = _thr.Thread(target=_do_connect, daemon=True)
        t.start()

        # 立即返回，告诉前端已开始连接
        return {"ok": True, "error": "", "wxid": "", "contacts": 0, "mode": "connecting", "async": True}

    def _handle_stop_wcf(self, payload):
        """停止 WCF 底座连接。"""
        self.wcf_client.stop_wcf()
        try:
            channels_dao.upsert("wcf", connected=0, config_json="{}", error="手动停止")
        except Exception:
            pass
        return {"ok": True, "error": ""}

    def _handle_test_oa(self, payload):
        return {"steps": [
            {"name": "网络连通性", "status": "skip", "info": "未实现，留待公众号云端模块"},
        ], "connected": False}

    def _handle_save_channel_config(self, payload):
        """保存渠道配置（WCF / 公众号云端）。配置写入 SQLite channel_connection.config_json。"""
        ch_type = (payload.get("type") or "").strip().lower()
        if not ch_type:
            raise ValueError("缺少 type 字段")
        # 类型映射：JS 里用 mp/wcf，数据库里存 oa_cloud/wcf
        channel_map = {
            "mp": "oa_cloud",
            "oa": "oa_cloud",
            "oa_cloud": "oa_cloud",
            "wcf": "wcf",
        }
        channel = channel_map.get(ch_type, ch_type)
        # 去掉内部字段，其余全部当作 config 保存
        config = {k: v for k, v in payload.items() if k not in ("type",)}
        # 原有的连接状态（不覆盖 connected）
        existing = channels_dao.get(channel)
        connected = bool(existing.get("connected")) if existing else False
        error = existing.get("error", "") if existing else ""
        saved = channels_dao.upsert(channel, connected, config, error)
        # 保存后刷新前端状态
        self.send_to_js("channel_status_changed", {
            "channels": channels_dao.get_all_status()
        })
        return {"saved": saved, "channel": channel}

    def _handle_list_channel_bindings(self, payload):
        """返回当前 agent 的绑定 + 同渠道其他 agent 的占用清单。

        前端用 occupants 来标记「哪些 peer 被别人占了」。
        """
        aid = payload.get("agent_id")
        ch  = payload.get("channel", "wcf")
        if ch in ("wcf", "oa"):
            self._require_perm("wechat", msg="微信渠道绑定需要特殊版解锁")
        if not aid:
            raise ValueError("缺少 agent_id")
        my_bindings = channels_dao.list_bindings(aid, ch)
        all_occupants = channels_dao.list_all_enabled_peer_occupants(ch)
        # 过滤掉自己的，只给前端"别人占的"
        others = [o for o in all_occupants if o.get("agent_id") != aid]
        return {"channel": ch, "bindings": my_bindings, "occupants": others}

    def _handle_set_channel_binding(self, payload):
        required = ["agent_id", "channel", "peer_id"]
        for k in required:
            if not payload.get(k):
                raise ValueError(f"缺少 {k}")
        aid = payload["agent_id"]
        ch  = payload["channel"]
        pid = payload["peer_id"]
        if ch in ("wcf", "oa"):
            self._require_perm("wechat", msg="微信渠道绑定需要特殊版解锁")
        enabled = payload.get("enabled", True)
        force_replace = bool(payload.get("force_replace", False))

        # === 排他校验 ===
        if enabled:
            conflict = channels_dao.find_conflict(ch, pid, aid)
            if conflict:
                if force_replace:
                    # 事务化抢占替换：关对方 + 绑自己 原子执行
                    b = channels_dao.replace_binding(
                        new_agent_id=aid,
                        channel=ch,
                        peer_id=pid,
                        peer_name=payload.get("peer_name", ""),
                        peer_type=payload.get("peer_type", "friend"),
                    )
                    occupant_name = conflict.get("agent_name") or "其他智能体"
                    print(f"[Bridge] 抢占替换: {occupant_name} → {pid} → agent_id={aid} (事务化)", flush=True)
                    return {"saved": True, "binding": b, "replaced_from": conflict.get("agent_id")}
                else:
                    # 非抢占：返回冲突错误让前端弹确认
                    occupant_name = conflict.get("agent_name") or conflict.get("agent_id") or "其他智能体"
                    peer_disp = conflict.get("peer_name") or pid
                    return {
                        "saved": False,
                        "conflict": True,
                        "error": f"「{peer_disp}」已被智能体「{occupant_name}」绑定",
                        "occupant": {
                            "agent_id": conflict.get("agent_id"),
                            "agent_name": conflict.get("agent_name"),
                            "peer_name": conflict.get("peer_name"),
                            "peer_type": conflict.get("peer_type"),
                        },
                    }

        b = channels_dao.set_binding(
            agent_id=aid,
            channel=ch,
            peer_id=pid,
            peer_name=payload.get("peer_name", ""),
            peer_type=payload.get("peer_type", "friend"),
            enabled=enabled,
        )
        return {"saved": True, "binding": b}

    def _handle_save_agent_managers(self, payload):
        """保存某 agent 在某渠道上的管理者名单（全量覆盖语义）。

        payload:
          agent_id:  str
          channel:   str
          managers:  [{peer_id, peer_name?, peer_type?}] 或 ["peer_id", ...]

        先把该 agent×渠道下的 is_manager 全部清零，再逐个重新标记。
        被标记为管理者的 peer 会自动 enabled=1（管理者必须有可路由的落点）。
        """
        aid = payload.get("agent_id")
        ch  = payload.get("channel", "wcf")
        if ch in ("wcf", "oa"):
            self._require_perm("wechat", msg="微信渠道管理者设置需要特殊版解锁")
        if not aid:
            raise ValueError("缺少 agent_id")

        raw = payload.get("managers") or []
        managers: list[dict] = []
        seen: set[str] = set()
        for m in raw:
            if isinstance(m, str):
                m = {"peer_id": m}
            if not isinstance(m, dict):
                continue
            pid = m.get("peer_id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            managers.append(m)

        cleared = channels_dao.clear_managers(aid, ch)
        saved = []
        # ★ 管理者绑定不做排他检查——管理者本来就允许绑多个 agent
        # （我们今天做的整个聚合路由就是这个前提）
        for m in managers:
            pid = m["peer_id"]
            rec = channels_dao.set_manager(
                agent_id=aid,
                channel=ch,
                peer_id=pid,
                peer_name=m.get("peer_name", ""),
                peer_type=m.get("peer_type", "friend"),
                is_manager=True,
            )
            if rec:
                saved.append(rec)
        print(f"[Bridge] save_agent_managers: agent={aid} channel={ch} "
              f"cleared={cleared} managers={[m['peer_id'] for m in managers]}", flush=True)
        return {"saved": True, "cleared": cleared, "managers": saved, "conflicts": []}

    def _handle_fetch_wcf_contacts(self, payload):
        """返回微信同步的好友/群聊候选列表。

        规则（与设置页状态严格对齐）：
        1. 已连接微信 → 从 wcferry.get_contacts() 读真实联系人；经过滤：去系统号、去自己、
           好友在前、群聊在后，组内按名称排序，群聊附 member_count
        2. 未连接微信 → 返回 contacts=[]，让前端显示"请先在设置→渠道连接开启微信连接"
           （不再塞入 Mock 假人，避免给用户"这些是我微信好友"的误导）
        """
        contacts = []
        source = "empty"
        note = "微信未连接，真实联系人需先开启连接"
        try:
            real = self.wcf_client.get_contacts()
            if real:
                contacts = real
                source = "wcf_real"
                note = f"真实微信联系人 {len(contacts)} 个"
        except Exception as e:
            print(f"[Bridge] fetch_wcf_contacts 读取失败: {e}", flush=True)
        friend_n = sum(1 for c in contacts if c.get("peer_type") == "friend")
        group_n  = sum(1 for c in contacts if c.get("peer_type") == "group")
        for i, c in enumerate(contacts[:8]):
            print(f"  → 样本[{i}] peer_id={c.get('peer_id')!r} peer_name={c.get('peer_name')!r} type={c.get('peer_type')} members={c.get('member_count',0)}", flush=True)
        return {"contacts": contacts, "source": source, "note": note}

    def _handle_fetch_wcf_avatar(self, payload):
        """拉取单个微信联系人的头像（用于前端替换首字母占位符）。

        payload 参数：
          - wxid / peer_id：联系人 wxid（二选一，peer_id 优先，与 fetch_wcf_contacts 返回保持一致）

        返回结构：{type, value, mime?}
          - type="url"   : value 是 http(s) 头像直链，前端直接 <img src="value">
          - type="base64": value 是纯 base64 字节串（不含 data: 前缀），mime 默认 image/jpeg 兼容
          - type="none"  : 拿不到头像，前端继续显示首字母
        """
        wxid = (payload or {}).get("peer_id") or (payload or {}).get("wxid") or ""
        base = {"peer_id": wxid, "wxid": wxid}
        if not wxid:
            return {**base, "type": "none", "value": "", "note": "missing wxid/peer_id"}
        try:
            raw = self.wcf_client.get_avatar_base64(wxid)
        except Exception as e:
            print(f"[Bridge] fetch_wcf_avatar({wxid!r}) 异常: {type(e).__name__}: {e}", flush=True)
            return {**base, "type": "none", "value": "", "note": f"error: {type(e).__name__}"}
        if not raw:
            print(f"[Bridge] fetch_wcf_avatar({wxid!r}) → 无头像", flush=True)
            return {**base, "type": "none", "value": ""}
        if isinstance(raw, str) and raw.startswith("__URL__:"):
            url = raw[len("__URL__:"):]
            print(f"[Bridge] fetch_wcf_avatar({wxid!r}) → URL 长度 {len(url)}", flush=True)
            return {**base, "type": "url", "value": url}
        # 其余作为 base64 返回（jpeg/png 兼容）
        print(f"[Bridge] fetch_wcf_avatar({wxid!r}) → base64 长度 {len(str(raw))}", flush=True)
        return {**base, "type": "base64", "value": str(raw), "mime": "image/jpeg"}

    def _handle_fetch_oa_contacts(self, payload):
        """返回服务号渠道的关注用户候选列表（真实调用微信 API）。

        返回 error 字段，前端可区分"拉取失败"和"真的没关注用户"。
        拉取失败时（如 API 配额用尽），不应该把已绑定用户标为"未在公众号拉取列表中"。
        """
        refresh = bool(payload.get("refresh", False))
        if refresh:
            contacts = self.oa_client.refresh_followers()
        else:
            contacts = self.oa_client.get_contacts()
        # 判断是否拉取失败（contacts 为空且微信客户端存在时，大概率是 API 错误）
        error = ""
        if not contacts and getattr(self.oa_client, "_wx_client", None):
            error = getattr(self.oa_client, "_last_followers_error", "") or "拉取关注列表失败（可能是微信 API 配额用尽）"
        return {"contacts": contacts, "source": "wechat_api",
                "note": f"共 {len(contacts)} 位关注用户", "error": error}

    # ---------- 激活 / 试用 ----------
    def _handle_get_activation_status(self, payload):
        """返回当前生效的授权状态。优先云端 JWT，fallback 本地。
        payload.force=True 时跳过缓存同步查云端。
        """
        force = bool(payload.get("force", False))
        return self._get_effective_activation(force)

    def _handle_increment_trial(self, payload):
        n = int(payload.get("n", 1))
        return activation_dao.increment_trial_used(n)

    def _handle_activate(self, payload):
        """激活本机。

        前端只需传 license_key；machine_code 由 Bridge 自动取本机机器码，
        不信任前端传入（防止伪造）。
        """
        from storage.machine import get_machine_code
        license_key = (payload.get("license_key") or "").strip()
        if not license_key:
            raise ValueError("缺少激活码")
        # 自动取本机机器码，忽略前端传的 machine_code（即使传了也以本机为准）
        machine_code = get_machine_code()
        return activation_dao.activate(license_key, machine_code)

    def _handle_can_use_trial(self, payload):
        return {"ok": activation_dao.can_use_trial()}

    def _get_effective_activation(self, force_refresh=False):
        """获取当前生效的授权状态。优先 poll_license（云端 JWT），
        超时/离线 fallback 本地 activation_dao。
        每次调用都会对比上次快照，状态变化时自动推送给前端权益卡片。"""
        from storage.machine import get_machine_code
        result = None
        try:
            cloud = poll_license(get_machine_code(), force_refresh=force_refresh)
            if cloud and cloud.get('active'):
                result = cloud
        except Exception:
            pass
        if result is None:
            local = activation_dao.get_status() or {}
            active = bool(local.get('activated'))
            tier = local.get('tier') or ('pro' if active else 'free')
            result = {
                'tier': tier,
                'active': active,
                'activated': active,
                'agent_cap': local.get('agent_cap', 2),
                'kb': bool(local.get('kb', False)),
                'memory': bool(local.get('memory', False)),
                'wechat_unlocked': bool(local.get('wechat_unlocked', False)),
                'tier_name': local.get('tier_name') or tier,
                'expires_at': local.get('expires_at', 0),
                'source': 'local',
            }
        sig = (
            result.get('tier'),
            result.get('active'),
            result.get('wechat_unlocked'),
            result.get('expires_at'),
            result.get('source'),
        )
        import datetime as _dt
        if sig != self._last_act_sig:
            print(f'[Bridge] activation CHANGED: {self._last_act_sig} → {sig}', flush=True)
            self._last_act_sig = sig
            try:
                self.send_to_js('activation_status_changed', result)
                print(f"[Bridge] send_to_js('activation_status_changed') OK, tier={result.get('tier')}", flush=True)
            except Exception as e:
                print(f'[Bridge] send_to_js FAILED: {e}', flush=True)
        return result

    def _check_perm(self, perm):
        """和 _require_perm 一样，但返回 bool 而不是 raise。用于'不跑'场景。"""
        act = self._get_effective_activation()
        if perm == 'active':
            return bool(act.get('active'))
        elif perm == 'memory':
            return bool(act.get('memory'))
        elif perm == 'kb':
            return bool(act.get('kb'))
        elif perm == 'agent':
            return len(agents_dao.list_all()) < act.get('agent_cap', 2)
        elif perm == 'wechat':
            return bool(act.get('wechat_unlocked'))
        else:
            return bool(act.get('active'))

    def _require_perm(self, perm, msg=None):
        """统一权限 gate：没权限直接 raise PermissionError。
        perm 取值: 'memory' | 'kb' | 'agent' | 'wechat' | 'active'
        """
        act = self._get_effective_activation()
        if perm == 'active':
            ok = bool(act.get('active'))
        elif perm == 'memory':
            ok = bool(act.get('memory'))
        elif perm == 'kb':
            ok = bool(act.get('kb'))
        elif perm == 'agent':
            cap = act.get('agent_cap', 2)
            ok = len(agents_dao.list_all()) < cap
        elif perm == 'wechat':
            ok = bool(act.get('wechat_unlocked'))
        else:
            ok = bool(act.get('active'))
        if not ok:
            raise PermissionError(msg or '需要升级才能使用此功能')

    # ---------- 支付 / 激活码（虎皮椒 V3） ----------
    def _handle_get_machine_code(self, payload):
        """返回本机机器码，前端激活 Modal Tab2 展示用。"""
        from storage.machine import get_machine_code
        return {"machine_code": get_machine_code()}

    def _handle_pay_create(self, payload):
        """创建支付订单 → 调云端 cloud_server 真虎皮椒下单。

        前端 payload：
            tier: str  (starter/standard/pro/special)  ← 推荐，档位定价走云端
            amount_yuan: float  (可选，老前端兼容)
        """
        import urllib.request as _ur
        import urllib.error as _ue
        from storage.machine import get_machine_code
        from storage.cloud_license import CLOUD_BASE

        machine_code = get_machine_code()
        tier = (payload.get("tier") or "").strip()
        if not tier:
            # 老前端：按金额反推档位
            amount = float(payload.get("amount_yuan") or 299)
            _TIER_BY_AMT = {
                0.1: "starter", 0.2: "standard", 0.3: "pro", 0.4: "special",
                19.0: "starter", 39.0: "standard", 99.0: "pro", 199.0: "special",
            }
            tier = _TIER_BY_AMT.get(round(amount, 2), "starter")

        body = json.dumps({"machine_code": machine_code, "tier": tier}).encode("utf-8")
        req = _ur.Request(
            f"{CLOUD_BASE}/api/pay/create",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _ur.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
        except (_ue.URLError, _ue.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as e:
            if isinstance(e, _ue.HTTPError):
                try:
                    err_detail = e.read().decode("utf-8", errors="replace")
                    try:
                        err_json = json.loads(err_detail)
                        err_detail = err_json.get("error") or err_detail
                    except Exception:
                        pass
                except Exception:
                    err_detail = ""
                raise RuntimeError(err_detail or f"HTTP {e.code}")
            raise RuntimeError(f"云端下单失败：{e}")

        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "云端返回 ok=false")

        trade_order_id = result["trade_order_id"]
        qr_url = result.get("qr_url") or ""
        amount_cents = int(result.get("amount_cents") or 0)
        mode = result.get("mode") or "real"

        # 本地入库（幂等：同一 trade_order_id 不会重复插）
        expires_at = int(time.time()) + 900
        try:
            order = activation_orders_dao.create({
                "id": trade_order_id,
                "xunhu_order_id": result.get("xunhu_order_id") or "",
                "transaction_id": "",
                "machine_code": machine_code,
                "amount_cents": amount_cents,
                "amount_yuan": amount_cents / 100.0,
                "status": "created",
                "mode": mode,
                "goods_name": f"阿维达AI · {tier} 档",
                "attach_json": {
                    "notify_url": f"{CLOUD_BASE}/api/pay/xunhu_notify",
                    "source": "bridge._handle_pay_create → cloud",
                    "tier": tier,
                },
                "qr_url": qr_url,
                "license_key": "",
                "created_at": int(time.time()),
                "expires_at": expires_at,
            })
        except Exception as e:  # noqa: BLE001
            print(f"[PAY] 本地入库失败（仍然返回二维码）：{e}", flush=True)
            order = None

        # 从云端拿到的是虎皮椒 PNG 图片 URL → 下载转 base64（前端直接 <img src=...>）
        qr_base64 = ""
        if qr_url:
            try:
                req2 = _ur.Request(qr_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with _ur.urlopen(req2, timeout=10) as img_resp:
                    png_bytes = img_resp.read()
                import base64 as _b64
                qr_base64 = "data:image/png;base64," + _b64.b64encode(png_bytes).decode("ascii")
            except Exception as e:  # noqa: BLE001
                print(f"[PAY] 下载虎皮椒 PNG 失败（前端会尝试直接 URL）: {e}", flush=True)

        return {
            "ok": True,
            "mode": mode,
            "tier": tier,
            "trade_order_id": trade_order_id,
            "xunhu_order_id": result.get("xunhu_order_id") or "",
            "qr_url": qr_url,
            "qr_base64": qr_base64,
            "amount": result.get("amount") or f"¥{amount_cents / 100:.2f}",
            "amount_yuan": amount_cents / 100.0,
            "amount_cents": amount_cents,
            "expires_at": expires_at,
            "machine_code": machine_code,
            "notify_url": f"{CLOUD_BASE}/api/pay/xunhu_notify",
            "order": order,
        }

    def _handle_pay_poll(self, payload):
        """前端轮询云端订单状态。paid=True 后：云端已自动激活 license → 本机只刷新 JWT。

        payload: { trade_order_id: str }
        """
        import urllib.request as _ur
        import urllib.error as _ue
        from storage.machine import get_machine_code
        from storage.cloud_license import CLOUD_BASE

        order_id = (payload.get("trade_order_id") or payload.get("order_id") or "").strip()
        if not order_id:
            raise ValueError("缺少 trade_order_id")

        machine_code = get_machine_code()
        activation_orders_dao.mark_expired_if_needed(order_id)

        body = json.dumps({"trade_order_id": order_id}).encode("utf-8")
        req = _ur.Request(f"{CLOUD_BASE}/api/pay/poll",
                          data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with _ur.urlopen(req, timeout=10) as resp:
                polled = json.loads(resp.read())
        except (_ue.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            return {"ok": False, "paid": False, "error": f"云端查单失败：{e}"}

        if not polled.get("ok"):
            return {"ok": False, "paid": False, "error": polled.get("error") or "云端查单 ok=false"}

        paid = bool(polled.get("paid"))
        activated = False
        activation_result = None
        order_snap = activation_orders_dao.get(order_id)

        if paid:
            if order_snap:
                order_snap, _ = activation_orders_dao.mark_paid(
                    order_id,
                    paid_at=polled.get("paid_at") or None,
                    attach_json={"paid_via": "cloud_callback → local_poll"},
                )
            try:
                activation_result = self._get_effective_activation(force_refresh=True)
                activated = bool(activation_result and activation_result.get("active"))
            except Exception as e:  # noqa: BLE001
                print(f"[PAY] 云端 JWT 刷新失败: {e}", flush=True)
                activation_result = {"error": str(e)}
            if activated:
                act = activation_result if isinstance(activation_result, dict) else {}
                self.send_to_js("activation_status_changed", {"activated": True, "trigger": "poll", **act})

        return {
            "ok": True,
            "paid": paid,
            "status": polled.get("status"),
            "tier": polled.get("tier"),
            "activated": activated,
            "paid_at": polled.get("paid_at"),
            "machine_code": polled.get("machine_code") or machine_code,
            "activation": activation_result,
        }

    def _handle_activate_with_license(self, payload):
        """Tab2「输入激活码激活」。别名：兼容前端不同命名，走同一套验证。"""
        return self._handle_activate(payload)

    def _handle_admin_gen_license(self, payload):
        """【管理员用】根据机器码生成激活码（人工兜底 SOP）。

        预留密码：admin_seed，避免普通用户看到就能瞎生成；MVP 阶段先明文比对，
        正式版要替换成更强的管理员认证。
        """
        ADMIN_SEED = "avatar-admin-2025"  # 与 tests 约定好的种子，方便脚本联调
        seed = (payload.get("admin_seed") or payload.get("secret") or "").strip()
        if seed != ADMIN_SEED:
            raise PermissionError("管理员密钥错误，禁止生成激活码")
        target_mc = (payload.get("machine_code") or "").strip()
        if not target_mc:
            raise ValueError("machine_code 不能为空")
        license_key = activation_dao.admin_generate_license(target_mc)
        return {
            "machine_code": target_mc,
            "license_key": license_key,
            "format": "AVTR-XXXX-XXXX-XXXX（绑定机器码，一码一机）",
        }

    def _handle_pay_notify(self, payload):
        """JS 其实不会直接调这个；留作调试/手动把回调 body 塞进来触发。
        真正的异步回调走本地 HTTP 服务 /pay/xunhupay/notify（见 _ensure_notify_server_running）。
        """
        raw = payload.get("raw_body") or payload.get("body") or ""
        content_type = payload.get("content_type") or ""
        return self._process_notify_payload(raw, content_type, source="bridge_call")

    # ---- .lic 文件 / 机器码文件 导入导出（人工兜底用户侧 UI） ----
    def _handle_export_machine_code(self, payload):
        """Tab2「导出我的机器码」：把本机 machine_code 写成一个 .mc 的 json 小文件。

        payload：
          target_dir: str | None  可选，指定保存目录；不传则保存到用户桌面 / 下载文件夹之一（第一个存在的）
        返回：{ saved_path: str, machine_code: str, filename: str }

        用途：
          1) 用户嫌复制粘贴容易漏字符时 → 直接把 .mc 文件发给管理员
          2) 管理员收到 .mc 文件后，admin_console 未来可加"导入 .mc → 直接读取机器码"按钮（本期先不做，
             管理员记事本打开就能看到 machine_code 字段）
        """
        import json as _j
        from storage.machine import get_machine_code

        mc = get_machine_code()
        ts = int(__import__("time").time())
        day = datetime.fromtimestamp(ts).strftime("%Y%m%d")
        content = _j.dumps({
            "schema": "v1",
            "machine_code": mc,
            "tool": "AVATAR AI MVP",
            "exported_at": ts,
            "tip": "把这个文件发给管理员，或直接记事本打开→复制 machine_code 粘贴即可",
        }, ensure_ascii=False, indent=2)

        target = None
        preferred = (payload or {}).get("target_dir")
        if preferred:
            p = _Path(str(preferred))
            if p.is_dir():
                target = p
        if target is None:
            for cand in (_Path.home() / "Desktop", _Path.home() / "Downloads",
                         _Path.home() / "Documents", _Path.home()):
                if cand.exists() and cand.is_dir():
                    target = cand
                    break
        if target is None:
            raise RuntimeError("找不到合适的保存目录，请手动选一个")
        target.mkdir(parents=True, exist_ok=True)

        suffix = mc.replace("-", "").replace(" ", "")[-6:] or "MCXXXX"
        filename = f"avatar_machine_code_{day}_{suffix}.mc"
        out = target / filename
        out.write_text(content, encoding="utf-8")
        return {"saved_path": str(out), "machine_code": mc, "filename": filename, "size": len(content)}

    def _handle_import_license_file(self, payload):
        """Tab2「导入授权文件」：用户在前端选了一个 .lic 文件，把文本内容传过来。

        payload：
          file_text : str   .lic 文件里的完整文本（UTF-8 JSON）
          file_path : str | None  本地路径（可选，只用于日志）

        校验顺序：
          1) JSON 能解析，schema=v1；
          2) 里面的 license_key + machine_code HMAC 验通过（签名算法与 generate 对齐）；
          3) machine_code == 本机机器码  → 保证是管理员给他这台电脑专属发的，防止倒卖；
          4) 走 activation_dao.activate(license_key, machine_code) → 写入 activation 表 + 推送 activation_status_changed。

        返回：{ activated: bool, license_key: str, machine_code_checked: bool, activation: {...} }
        """
        import json as _j
        from storage.license import verify_license_key
        from storage.machine import get_machine_code

        text = (payload or {}).get("file_text") or ""
        text = text.lstrip("\ufeff").strip()  # BOM 兼容
        if not text:
            raise ValueError("授权文件内容为空，是不是选到错文件了？正确的是 xxx.lic，大小约 300 字节")
        try:
            data = _j.loads(text)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"授权文件格式不对（读 JSON 失败: {e!r}）。正确 .lic 文件是一个 UTF-8 JSON；别把压缩包/图片发过来了哦") from e
        if not isinstance(data, dict):
            raise ValueError("授权文件内容不是 JSON 对象，损坏或被篡改")

        # 1) schema 兼容（v1 都能认；未来 v2 再提）
        if str(data.get("schema") or "v1") != "v1":
            raise ValueError(f"授权文件版本 {data.get('schema')!r} 不兼容，请用最新版管理员工具重新生成一份 .lic 再发用户")

        lic_key = (data.get("license_key") or "").strip()
        file_mc = (data.get("machine_code") or "").strip().upper()
        if not lic_key or not file_mc:
            raise ValueError("授权文件缺少必要字段 license_key/machine_code，可能不是管理员发的那份")

        # 2) HMAC 验签：文件未被篡改
        if not verify_license_key(lic_key, file_mc):
            raise ValueError("授权文件被篡改过（签名对不上）。请重新向管理员要一份新的 .lic，不要随便改文件内容哦")

        # 3) 机器码必须与本机一致（一码一机硬约束）
        local_mc = get_machine_code().strip().upper()
        if file_mc != local_mc:
            raise ValueError(
                f"这份授权文件不是你的电脑用的哦（一码一机）。\n"
                f"  你的机器码：…{local_mc[-8:]}\n"
                f"  文件绑定的：…{file_mc[-8:]}\n"
                f"请把【本机】机器码（激活弹窗 Tab2 顶部显示，或导出 .mc 文件）发给管理员重新生成。"
            )

        # 4) 写入 activation 表（幂等）+ 推送 activation_status_changed 信号
        activation_result = activation_dao.activate(lic_key, local_mc)
        if activation_result.get("activated"):
            self.send_to_js("activation_status_changed", {
                "activated": True,
                "trigger": "import_license_file",
                "status": activation_dao.get_status(),
            })
        return {
            "activated": bool(activation_result.get("activated")),
            "license_key": lic_key,
            "machine_code_checked": True,
            "edition": activation_result.get("edition"),
            "activation": activation_result,
            "already_activated_before": bool(activation_result.get("already_activated")),
        }

    # ---- 支付回调处理核心（HTTP 服务 与 JS 调试 共用） ----
    def _process_notify_payload(self, raw_body: str, content_type: str = "",
                                source: str = "http") -> dict:
        """解析回调 → 验签 → mark_paid → （本机）激活 → 返回给虎皮椒的响应字符串。

        返回 dict：{
            "response_text": str,     # 要回给虎皮椒 HTTP 客户端的 body，官方要求 "success"
            "processed": bool,
            "paid": bool,
            "verified": bool,
            "activated": bool,
            "order_id": str,
            "error": str | None
        }
        """
        from storage.machine import get_machine_code
        from storage import payment as pay_mod

        parsed = pay_mod.parse_notify(raw_body, content_type or "")
        order_id = parsed.get("out_trade_no") or ""
        verified = bool(parsed.get("verified"))
        paid = bool(parsed.get("paid"))
        error = parsed.get("error")
        activated = False

        # 回调留痕（无论验签是否通过，都记一笔，方便排查）
        if order_id:
            try:
                activation_orders_dao.record_notify(
                    order_id,
                    raw_body=parsed.get("raw") or raw_body or "",
                    verified=verified,
                    attempts_increment=1,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[PAY] 回调留痕失败 order={order_id}: {e}", flush=True)

        if not verified:
            print(f"[PAY] {source} 回调验签不通过: {parsed}", flush=True)
            return {
                "response_text": "fail",
                "processed": False,
                "paid": False,
                "verified": False,
                "activated": False,
                "order_id": order_id,
                "error": error or "验签失败",
            }

        if order_id and paid:
            # 1) mark_paid 幂等流转
            attach_mc = parsed.get("attach") or ""
            order = activation_orders_dao.get(order_id)
            machine_code = (order or {}).get("machine_code") or attach_mc
            license_key = ""
            if machine_code:
                try:
                    license_key = pay_mod.generate_license_for_machine(machine_code)
                except Exception as e:  # noqa: BLE001
                    print(f"[PAY] 激活码生成失败: {e}", flush=True)
            updated, first_time = activation_orders_dao.mark_paid(
                order_id,
                transaction_id=parsed.get("transaction_id") or "",
                paid_at=now_ts(),
                license_key=license_key,
                attach_json={
                    "paid_via": source,
                    "notify_parsed": parsed.get("parsed") or {},
                },
            )

            # 2) 如果命中本机 → 直接激活 & 推 JS
            local_mc = get_machine_code()
            if machine_code and machine_code == local_mc and license_key:
                try:
                    act_res = activation_dao.activate(license_key, local_mc)
                    activated = bool(act_res and act_res.get("activated"))
                    if activated:
                        self.send_to_js("activation_status_changed", {
                            "activated": True,
                            "trigger": source,
                            "status": activation_dao.get_status(),
                        })
                except Exception as e:  # noqa: BLE001
                    print(f"[PAY] 回调激活本机失败: {e}", flush=True)

        # 虎皮椒要求：收到回调且成功处理，必须返回 ASCII "success"，否则它会一直重试
        #   参考：https://www.xunhupay.com/doc/api/pay.html 末尾「异步通知」章节
        return {
            "response_text": "success",
            "processed": True,
            "paid": paid,
            "verified": True,
            "activated": activated,
            "order_id": order_id,
            "error": None,
        }

    # ---- 本地回调 HTTP 服务（仅监听 127.0.0.1，防止其他机器乱打） ----
    _notify_server_state = {"server": None, "thread": None, "port": None}  # 类级单例，避免重复启动

    def _ensure_notify_server_running(self) -> dict:
        """启动本地 HTTP 服务监听虎皮椒回调。多次调用安全（幂等）。"""
        state = BridgeServer._notify_server_state
        if state["server"] is not None:
            return {"started": True, "host": state["server"].server_name,
                    "port": state["server"].server_port, "note": "already running"}
        try:
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
            from urllib.parse import urlparse
            from storage.payment import LOCAL_NOTIFY_HOST, LOCAL_NOTIFY_PORT, LOCAL_NOTIFY_PATH

            bridge_self = self  # 闭包捕获

            class _NotifyHandler(BaseHTTPRequestHandler):
                server_version = "AVATAR-AI-PayNotify/1.0"

                def log_message(self, fmt, *args):  # 安静点，别刷屏
                    print(f"[PAY-notify] {args[0] if args else fmt}", flush=True)

                def do_GET(self):
                    parsed = urlparse(self.path or "")
                    # 健康检查：浏览器打开 /ping 返回 pong，方便快速确认服务活着
                    if parsed.path == "/ping":
                        body = b"pong"
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    if parsed.path == LOCAL_NOTIFY_PATH:
                        # 不接受 GET 回调
                        self._write(405, b"Method Not Allowed")
                        return
                    self._write(404, b"Not Found")

                def do_POST(self):
                    parsed = urlparse(self.path or "")
                    if parsed.path != LOCAL_NOTIFY_PATH:
                        self._write(404, b"Not Found")
                        return
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = ""
                    if length > 0:
                        raw_bytes = self.rfile.read(length)
                        raw = raw_bytes.decode("utf-8", errors="replace")
                    content_type = self.headers.get("Content-Type") or ""
                    result = bridge_self._process_notify_payload(
                        raw, content_type=content_type, source="http"
                    )
                    resp_bytes = (result.get("response_text") or "success").encode("utf-8")
                    # 回调验签不过 → 仍然返回 200 但 body=fail（虎皮椒官方：非 success 就会重试）
                    status = 200
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(resp_bytes)))
                    self.end_headers()
                    self.wfile.write(resp_bytes)
                    print(
                        f"[PAY-notify] verified={result.get('verified')} paid={result.get('paid')} "
                        f"activated={result.get('activated')} order={result.get('order_id')}",
                        flush=True,
                    )

                def _write(self, status: int, body: bytes):
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            server = ThreadingHTTPServer((LOCAL_NOTIFY_HOST, LOCAL_NOTIFY_PORT), _NotifyHandler)
            server.daemon_threads = True

            def _serve_forever():
                try:
                    server.serve_forever(poll_interval=0.5)
                except Exception as e:  # noqa: BLE001
                    print(f"[PAY-notify] server exit: {e!r}", flush=True)

            import threading
            t = threading.Thread(target=_serve_forever, name="pay-notify-http", daemon=True)
            t.start()
            state["server"] = server
            state["thread"] = t
            state["port"] = LOCAL_NOTIFY_PORT
            print(f"[PAY-notify] listening on http://{LOCAL_NOTIFY_HOST}:{LOCAL_NOTIFY_PORT}{LOCAL_NOTIFY_PATH}", flush=True)
            return {"started": True, "host": LOCAL_NOTIFY_HOST, "port": LOCAL_NOTIFY_PORT,
                    "path": LOCAL_NOTIFY_PATH, "note": "newly started"}
        except Exception as e:  # noqa: BLE001
            # 端口占用 / 没权限：不影响「轮询」主路径，打印一下即可
            print(f"[PAY-notify] 启动失败（可忽略，轮询仍可用）：{e!r}", flush=True)
            state["server"] = None
            return {"started": False, "error": str(e)}

    # ---------- 通用配置（键值对，后续可迁移到 kv 表） ----------
    def _handle_save_config(self, payload):
        """MVP：无单独 kv 表，仅打印占位。"""
        print(f"[Bridge] 保存配置(暂不落地): {payload}", flush=True)
        return {"saved": True, "note": "MVP 占位，未单独持久化"}

    def _handle_get_config(self, payload):
        """MVP 占位。"""
        return {}

    # ---------- 对话（Agent Chat） ----------
    def _handle_create_conversation(self, payload):
        agent_id = payload.get("agent_id")
        if not agent_id:
            raise ValueError("缺少 agent_id")
        title = payload.get("title", "")
        conv = conv_dao.create(agent_id, title)
        return {"conversation": conv}

    def _handle_get_conversations(self, payload):
        agent_id = payload.get("agent_id")
        if not agent_id:
            raise ValueError("缺少 agent_id")
        return {"conversations": conv_dao.list_by_agent(agent_id)}

    def _handle_delete_conversation(self, payload):
        conv_id = payload.get("id")
        if not conv_id:
            raise ValueError("缺少 id")
        msg_dao.delete_by_conversation(conv_id)
        ok = conv_dao.delete(conv_id)
        return {"deleted": ok, "id": conv_id}

    def _handle_get_conversation_messages(self, payload):
        conv_id = payload.get("conversation_id")
        if not conv_id:
            raise ValueError("缺少 conversation_id")
        return {"messages": msg_dao.list_by_conversation(conv_id)}

    # ---------- 智能记忆：prompt 注入辅助 ----------
    def _format_memory_for_prompt(self, memories_raw):
        """把 agents.memories 里存的 JSON 字符串，格式化成 LLM 可读的一段文本。

        JSON 结构（与前端 parseMemoryJSON / collectMemoryEntries 对齐）：
            { enabled: bool,
              user_profile: [{title, content, ...}],
              episodic:     [{title, content, ...}] }

        返回：
            - enabled=False 或解析失败或两条都为空 → 返回 ""（不注入）
            - 免费版 → 强制返回 ""（闸门 C：记忆注入需正式版解锁）
            - 否则返回类似「关于当前用户你需要记住以下信息：
                  【长期画像】
                  · 学习目标：高二在读…
                  【近期重点】
                  · 物理进度：已学习牛顿第二定律…」这样的块
        """
        # —— 闸门 C：免费版完全不注入记忆（哪怕 DB 里存了也白存）——
        if not self._check_perm("memory"):
            return ""
        if not memories_raw or not isinstance(memories_raw, str):
            return ""
        try:
            import json as _json
            data = _json.loads(memories_raw)
        except Exception:
            return ""
        if not isinstance(data, dict):
            return ""
        if data.get("enabled") is False:
            return ""

        def _fmt_entries(entries):
            if not isinstance(entries, list):
                return []
            lines = []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                # 兼容两种条目格式：
                #   LLM提炼/后端sanitize → {title, content}
                #   前端v2手工/直接存 → {category, content} （没有 title 字段）
                title_raw = (e.get("title") or "").strip()
                content = (e.get("content") or "").strip()
                if not content:
                    # content 也可能塞在 title 字段里（纯文本迁移来的老数据）
                    content = title_raw
                    title_raw = ""
                if not content:
                    continue
                # 没 title 时，用 content 前 12 字当短标题
                if not title_raw:
                    title_raw = content[:12] + ("…" if len(content) > 12 else "")
                content_display = content if len(content) <= 200 else content[:197] + "…"
                lines.append(f"· {title_raw}：{content_display}")
            return lines

        profile_lines = _fmt_entries(data.get("user_profile"))
        episodic_lines = _fmt_entries(data.get("episodic"))

        if not profile_lines and not episodic_lines:
            return ""

        block_lines = ["【关于当前对话对象，你需要记住以下信息（跨会话持续生效）】"]
        if profile_lines:
            block_lines.append("长期画像（稳定特征：身份/偏好/目标）：")
            block_lines.extend(profile_lines)
        if episodic_lines:
            if profile_lines:
                block_lines.append("")
            block_lines.append("近期重点（最近聊过的内容/待跟进事项）：")
            block_lines.extend(episodic_lines)
        return "\n".join(block_lines)

    # ---------- 智能记忆：自动提炼（对齐小智 AI） ----------
    def _parse_memory_json_safe(self, memories_raw):
        """把任意 memories 输入安全解析成合法内存结构。

        永远返回 dict：
            {"enabled": bool, "user_profile": list, "episodic": list,
             "pending": dict|None, "history": list, "last_confirm_at": int|None}
        即使输入为空/非法也返回带空数组的默认值，方便下游直接 merge。
        """
        default = {
            "enabled": True, "user_profile": [], "episodic": [],
            "pending": None, "history": [], "last_confirm_at": None,
        }
        if not memories_raw:
            return default
        try:
            if isinstance(memories_raw, str):
                data = json.loads(memories_raw)
            else:
                data = memories_raw
            if not isinstance(data, dict):
                return default
        except Exception:
            return default
        # 字段规范化：缺什么补什么，类型错了兜底
        result = {}
        enabled_val = data.get("enabled")
        if isinstance(enabled_val, bool):
            result["enabled"] = enabled_val
        elif enabled_val is None:
            result["enabled"] = True
        else:
            # 兼容 truthy / falsy（比如前端偶尔传 0/1 字符串）
            try:
                result["enabled"] = bool(enabled_val)
            except Exception:
                result["enabled"] = True
        for k in ("user_profile", "episodic", "history"):
            v = data.get(k)
            result[k] = v if isinstance(v, list) else []
        # pending：要么是dict（暂存的三维建议），要么是None
        pending_val = data.get("pending")
        result["pending"] = pending_val if isinstance(pending_val, dict) else None
        # last_confirm_at：unix时间戳int，None表示从未确认过
        lca = data.get("last_confirm_at")
        result["last_confirm_at"] = int(lca) if (isinstance(lca, (int, float)) and lca > 0) else None
        return result

    @staticmethod
    def _extract_memory_json_from_llm_text(text: str):
        """从 LLM 返回文本中安全抽取 JSON（经验 1044370 兜底：空/坏响应一律返回 None，不抛异常）。

        策略顺序：
        1. 找 ```json ... ``` 代码块
        2. 找最外层的 { ... } 配对大括号
        3. 尝试直接 json.loads(text)
        4. 最后做结构校验：必须有 enabled + user_profile(list) + episodic(list)
        全部失败 → 返回 None（调用方要记得跳过写回，不能覆盖好的旧记忆）
        """
        if not text or not isinstance(text, str):
            return None
        raw = text.strip()
        if not raw:
            return None

        json_str = ""
        # ① 代码块包裹
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        if m:
            json_str = m.group(1).strip()
        else:
            # ② 最外层 {} 配对
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                json_str = raw[start:end + 1]
            else:
                json_str = raw

        try:
            data = json.loads(json_str)
        except Exception:
            return None

        # 结构校验 + 规范化
        if not isinstance(data, dict):
            return None
        for k in ("user_profile", "episodic"):
            if not isinstance(data.get(k), list):
                return None
        if "enabled" not in data:
            data["enabled"] = True
        elif not isinstance(data.get("enabled"), bool):
            try:
                data["enabled"] = bool(data["enabled"])
            except Exception:
                data["enabled"] = True
        return data

    @staticmethod
    def _sanitize_memory_entry_list(entries):
        """把 LLM 返回的 user_profile / episodic 条目洗成统一结构：

        必须是 {title, content}；其他字段一律丢弃；title/content 做长度截断。
        过滤空条目，去重（同 title 合并 content）。
        """
        if not isinstance(entries, list):
            return []
        # title -> content 字典（顺序保留最后一条）
        cleaned: dict[str, str] = {}
        order: list[str] = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            title_raw = (e.get("title") or "").strip()
            content_raw = (e.get("content") or "").strip()
            if not content_raw:
                continue
            title = title_raw[:16] if title_raw else content_raw[:12]
            content = content_raw[:300] if len(content_raw) > 300 else content_raw
            if title in cleaned:
                # 同 title 合并：如果新内容信息更多就覆盖，否则追加
                prev = cleaned[title]
                if content not in prev and prev not in content:
                    cleaned[title] = f"{prev}；{content}"[:300]
            else:
                cleaned[title] = content
                order.append(title)
        return [{"title": t, "content": cleaned[t]} for t in order]

    def _extract_and_save_memory(self, agent_id: str, conv_id: str, llm_cfg: dict):
        """【核心】从近期对话中用 LLM 提炼记忆，并写回 agents.memories。

        完全对齐小智 mem_local_short.save_memory 的流程：
            新消息 + 旧记忆 → 喂给 LLM → LLM 自己 merge → 写回。
        失败时只打日志，**绝不覆盖旧 memories**（安全第一）。
        """
        t0 = now_ts()
        tag = f"[记忆提炼][agent={agent_id[:8]}][conv={conv_id[:8]}]"
        try:
            # 1) 取会话 & 智能体
            agent = agents_dao.get(agent_id)
            if not agent:
                print(f"{tag} 跳过：智能体不存在", flush=True)
                return
            conv = conv_dao.get(conv_id)
            if not conv:
                print(f"{tag} 跳过：会话不存在", flush=True)
                return

            # 2) 解析旧记忆；如果 enabled=false，说明用户关了 → 也跑一次但保持 enabled=false
            old_mem = self._parse_memory_json_safe(agent.get("memories") or "")

            # 3) 拉会话全部消息（没多少条，总量 ≤ 几百的量级），最多取最近 80 条
            all_msgs = msg_dao.list_by_conversation(conv_id)
            if not all_msgs:
                print(f"{tag} 跳过：会话无消息", flush=True)
                return
            recent = all_msgs[-80:] if len(all_msgs) > 80 else all_msgs

            # 4) 组装 LLM user 消息：旧记忆 JSON + 本轮对话
            old_mem_dump = json.dumps(old_mem, ensure_ascii=False, indent=2)
            conv_lines = []
            for m in recent:
                role = m.get("role") or "user"
                c = (m.get("content") or "").strip()
                if not c:
                    continue
                tag_cn = "用户" if role == "user" else ("AI" if role == "assistant" else role)
                # 单条截断 400 字，防止某条超长消息爆 LLM 上下文
                if len(c) > 400:
                    c = c[:397] + "…"
                conv_lines.append(f"{tag_cn}：{c}")
            conv_text = "\n".join(conv_lines)
            now_s = str(t0)
            user_prompt = (
                "以下是用户提供的两部分数据，请按 system 指令提炼并输出 JSON。\n\n"
                f"【当前时间戳】{now_s}\n\n"
                f"【旧记忆（如果和新对话冲突，以新对话为准；如果新对话没提到，保留旧记忆）】\n"
                f"{old_mem_dump}\n\n"
                f"【本轮近期对话历史（按时间顺序）】\n"
                f"{conv_text}\n"
            )

            # 5) 调 LLM（低温度 0.15 → 稳定输出合法 JSON；2k max_tokens 足够装 30 条记忆）
            if not llm_cfg:
                # 兜底：如果传进来是空，走智能体自己的默认配置
                llm_id = agent.get("llm_config_id") or ""
                llm_cfg = (llm_dao.get(llm_id) if llm_id else None) or llm_dao.get_default()
            if not llm_cfg:
                print(f"{tag} 跳过：无可用 LLM 配置", flush=True)
                return

            try:
                provider = LLMProvider.from_config(llm_cfg)
                result = provider.chat(
                    messages=[
                        {"role": "system", "content": MEMORY_REFINE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.15,
                    max_tokens=2000,
                )
            except Exception as e:
                print(f"{tag} LLM 调用异常: {e}", flush=True)
                return

            # 6) 安全解析（经验 1044370 兜底：空/坏 → 不动旧记忆）
            if result.get("error"):
                print(f"{tag} LLM 错误: {result['error']}", flush=True)
                return
            llm_text = result.get("text") or ""
            if not llm_text.strip():
                print(f"{tag} LLM 返回空，跳过写回", flush=True)
                return
            new_mem = self._extract_memory_json_from_llm_text(llm_text)
            if new_mem is None:
                print(f"{tag} LLM 返回 JSON 解析失败，跳过写回。原始内容前 200 字：{llm_text[:200]!r}", flush=True)
                return

            # 7) 结构清洗：标题/长度/去重，防止 LLM 生成垃圾字段爆 DB
            new_profile = self._sanitize_memory_entry_list(new_mem.get("user_profile") or [])
            new_episodic = self._sanitize_memory_entry_list(new_mem.get("episodic") or [])
            # ============================================================
            # 迭代系统改造：不再直接覆盖正式的 user_profile/episodic
            # 而是写入 old_mem["pending"] 暂存区，等用户点「确认应用」才正式生效
            # prompt_suggestions / kb_suggestions MVP阶段先返回空列表（占位），
            # 后续补：①Prompt优化基于用户反馈/纠正史生成 ②KB优化基于RAG未命中统计
            # ============================================================
            pending_payload = {
                "prompt_suggestions": [],   # 占位：后续补真实逻辑
                "kb_suggestions": [],       # 占位：后续补真实逻辑
                "user_profile": new_profile,
                "episodic": new_episodic,
                "created_at": now_ts(),
            }
            final_mem = {
                "enabled": old_mem["enabled"] if old_mem.get("enabled") is not None else True,
                # 正式内容：保持原样（绝不偷偷改）
                "user_profile": old_mem.get("user_profile") or [],
                "episodic":     old_mem.get("episodic") or [],
                # 暂存区：写入本次 LLM 提炼结果
                "pending": pending_payload,
                # 历史 & 确认时间：保留原值
                "history": old_mem.get("history") or [],
                "last_confirm_at": old_mem.get("last_confirm_at"),
            }
            # 如果 enabled 原始是 False，就保持 False（用户主动关的，我们别改）
            if old_mem.get("enabled") is False:
                final_mem["enabled"] = False

            # 8) 写回 agents.memories（只改 memories 字段，不碰其他）
            final_mem_str = json.dumps(final_mem, ensure_ascii=False)
            agents_dao.update(agent_id, {"memories": final_mem_str})
            profile_cnt = len(new_profile)
            episodic_cnt = len(new_episodic)
            usage = result.get("usage") or {}
            tokens = usage.get("total_tokens") or 0
            cost_ms = max(0, (now_ts() - t0))
            print(
                f"{tag} 已生成优化方案并暂存（等待用户确认）。"
                f"长期画像={profile_cnt} 条，近期重点={episodic_cnt} 条，"
                f"LLM tokens={tokens}，耗时={cost_ms}s",
                flush=True,
            )
        except Exception as e:
            # 任何异常都要兜底：绝不影响主流程
            cost_ms = max(0, (now_ts() - t0))
            print(f"{tag} 顶层异常（耗时 {cost_ms}s）: {e}", flush=True)

    def _maybe_trigger_memory_refine(self, agent_id: str, conv_id: str, llm_cfg):
        """检查是否达到提炼阈值，是则提交到后台线程池异步执行。

        返回
        ----
        Future | None : 如果确实提交了任务 → 返回 concurrent.futures.Future；否则 None。
            调用方可以 fut.result(timeout=120) 同步等待任务完成，做测试/调试用。

        必须满足的 4 个前提：
          ① 正式版（闸门 B：未激活完全不提炼）
          ② 该智能体的「智能记忆开关」是 enabled=true
          ③ 当前会话总消息数 % MEMORY_REFINE_THRESHOLD == 0（每满 10 条触发一次）
          ④ 有可用的 LLM 配置
        """
        fut = None
        try:
            if not agent_id or not conv_id:
                return None
            # —— 闸门 B：未激活完全不提炼，避免浪费 LLM token ——
            if not self._check_perm("memory"):
                return None
            # 开关 & 阈值检查（查一次 agent + 一次 conv，SQLite 本地很快）
            agent = agents_dao.get(agent_id)
            if not agent:
                return None
            mem_cfg = self._parse_memory_json_safe(agent.get("memories") or "")
            if not mem_cfg["enabled"]:
                return None
            conv = conv_dao.get(conv_id)
            if not conv:
                return None
            cnt = int(conv.get("message_count") or 0)
            if cnt <= 0 or (cnt % MEMORY_REFINE_THRESHOLD) != 0:
                return None

            # 确认 llm_cfg 可用：优先用 _handle_send_message 传进来的那份（避免重复查）
            cfg = llm_cfg if (llm_cfg and isinstance(llm_cfg, dict)) else None
            if not cfg:
                llm_id = agent.get("llm_config_id") or ""
                cfg = (llm_dao.get(llm_id) if llm_id else None) or llm_dao.get_default()
            if not cfg:
                print(f"[记忆提炼] conv={conv_id[:8]} 触发但无可用 LLM，已跳过", flush=True)
                return None

            print(f"[记忆提炼] 触发：会话 {conv_id[:8]} 消息数={cnt}，已提交到后台线程池。", flush=True)
            # 用 submit + 回调 swallow 异常，保证任何情况下不阻塞发送消息的主线
            fut = self._memory_executor.submit(
                self._extract_and_save_memory, agent_id, conv_id, cfg,
            )

            def _on_done(f):
                try:
                    _ = f.result()  # 触发可能潜伏的异常，打到日志里
                except Exception as e:
                    print(f"[记忆提炼] 后台任务异常: {e}", flush=True)

            fut.add_done_callback(_on_done)
            return fut
        except Exception as e:
            print(f"[记忆提炼] 触发检查异常: {e}", flush=True)
            return fut  # 哪怕异常也返回 None 或 前面已经提交的 Future（虽然后者基本不可能发生）

    # ============================================================
    # 迭代系统：3 个 IPC Handler（预览 / 确认应用 / 回滚）
    # 自动调度规则：action=xxx → 自动匹配 self._handle_xxx
    # ============================================================

    def _do_memory_extract_pure(self, agent_id: str, conv_id: str = None, llm_cfg=None,
                                conv_ids: list[str] | None = None):
        """【纯提炼】只跑 LLM 提炼 + 返回三维结果，不写任何 DB。

        用于前端「刷新」按钮的手动预览调用。
        提炼范围：该智能体下**所有**非空会话（而不是只取最近一个），
                 每个会话取最近 40 条，合并后喂给 LLM。
        如果传了 conv_ids，则只从这些指定会话提炼（用于「导入」功能）。

        返回：{"prompt_suggestions": list, "kb_suggestions": list, "user_profile": list, "episodic": list}
        失败时返回空结构（保证不抛异常）。
        """
        empty = {"prompt_suggestions": [], "kb_suggestions": [], "user_profile": [], "episodic": []}
        t0 = now_ts()
        try:
            agent = agents_dao.get(agent_id)
            if not agent:
                return empty
            old_mem = self._parse_memory_json_safe(agent.get("memories") or "")

            # —— 确定要提炼的会话列表 ——
            if conv_ids:
                # 导入模式：只从指定会话提炼
                target_convs = [conv_dao.get(cid) for cid in conv_ids]
                target_convs = [c for c in target_convs if c]
            else:
                # 刷新模式：该智能体所有非空会话（双层 profile 架构后不再过滤 manager，per-agent 是 agent 级通用知识）
                sessions_list = conv_dao.list_by_agent(agent_id) or []
                target_convs = [
                    s for s in sessions_list
                    if (s.get("message_count") or 0) > 0
                    # 🆕 双层 profile 架构后，per-agent 是 agent 级通用知识，包含所有人对话
                    # 管理者/用户的专属画像由 per-peer profile 处理，per-agent 不再过滤 manager
                ]

            if not target_convs:
                return empty

            # —— 从每个会话取最近 40 条，合并 ——
            all_conv_lines = []
            for conv in target_convs:
                cid = conv["id"]
                peer = conv.get("peer_name") or "未知"
                msgs = msg_dao.list_by_conversation(cid) or []
                recent = msgs[-40:] if len(msgs) > 40 else msgs
                if not recent:
                    continue
                all_conv_lines.append(f"── 【{peer}】的对话 ──")
                for m in recent:
                    role = m.get("role") or "user"
                    c = (m.get("content") or "").strip()
                    if not c:
                        continue
                    tag_cn = "用户" if role == "user" else ("AI" if role == "assistant" else role)
                    if len(c) > 400:
                        c = c[:397] + "…"
                    all_conv_lines.append(f"{tag_cn}：{c}")
            conv_text = "\n".join(all_conv_lines)
            if not conv_text.strip():
                return empty

            # —— 组装 prompt ——
            old_mem_dump = json.dumps(
                {"enabled": old_mem.get("enabled", True),
                 "user_profile": old_mem.get("user_profile") or [],
                 "episodic": old_mem.get("episodic") or []},
                ensure_ascii=False, indent=2
            )
            user_prompt = (
                "以下是用户提供的两部分数据，请按 system 指令提炼并输出 JSON。\n\n"
                f"【当前时间戳】{str(t0)}\n\n"
                f"【旧记忆（和新对话冲突以新对话为准；新对话没提到就保留旧记忆）】\n"
                f"{old_mem_dump}\n\n"
                f"【近期对话历史（可能包含多个联系人，按联系人分组）】\n{conv_text}\n"
            )

            if not llm_cfg:
                llm_id = agent.get("llm_config_id") or ""
                llm_cfg = (llm_dao.get(llm_id) if llm_id else None) or llm_dao.get_default()
            if not llm_cfg:
                return empty
            try:
                provider = LLMProvider.from_config(llm_cfg)
                result = provider.chat(
                    messages=[
                        {"role": "system", "content": MEMORY_REFINE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.15,
                    max_tokens=4000,
                )
            except Exception as e:
                print(f"[纯提炼预览] LLM异常: {e}", flush=True)
                return empty
            if result.get("error") or not (result.get("text") or "").strip():
                return empty
            new_mem = self._extract_memory_json_from_llm_text(result["text"])
            if new_mem is None:
                return empty
            return {
                "prompt_suggestions": [],  # 占位：后续补
                "kb_suggestions": [],      # 占位：后续补
                "user_profile": self._sanitize_memory_entry_list(new_mem.get("user_profile") or []),
                "episodic":     self._sanitize_memory_entry_list(new_mem.get("episodic") or []),
            }
        except Exception as e:
            print(f"[纯提炼预览] 顶层异常: {e}", flush=True)
            return empty

    # ================================================================
    # 双层 profile 架构：per-peer 分组提炼
    # ================================================================
    def _extract_peer_profiles_for_agent(self, agent_id: str):
        """按 peer 分组提炼 per-peer profile，并写入 peer_profile 表。

        流程：
        1. conv_dao.list_by_agent(agent_id) 查出该 agent 下所有会话
        2. 按 (channel, peer_id) 分组（不过滤管理者——per-peer 就是要提炼所有人）
        3. 每组单独跑一次提炼（复用 MEMORY_REFINE_SYSTEM_PROMPT + 现有 LLM 逻辑）
        4. 写入 peer_profile 表（upsert，UNIQUE 保证幂等）

        返回：提炼了几个 peer。
        """
        agent = agents_dao.get(agent_id)
        if not agent:
            return 0
        # 闸门：未激活跳过
        if not self._check_perm("memory"):
            return 0
        # 拿 LLM 配置
        llm_id = agent.get("llm_config_id") or ""
        llm_cfg = (llm_dao.get(llm_id) if llm_id else None) or llm_dao.get_default()
        if not llm_cfg:
            return 0

        sessions_list = conv_dao.list_by_agent(agent_id) or []
        # 按 (channel, peer_id) 分组，跳过空消息会话
        groups: dict[tuple, list] = {}
        for s in sessions_list:
            if (s.get("message_count") or 0) <= 0:
                continue
            key = (s.get("channel", ""), s.get("peer_id", ""))
            if key[1]:  # peer_id 非空
                groups.setdefault(key, []).append(s)

        count = 0
        for (channel, peer_id), convs in groups.items():
            # 拼该 peer 的对话文本
            all_lines = []
            peer_name = ""
            for conv in convs:
                peer_name = peer_name or conv.get("peer_name") or "未知"
                msgs = msg_dao.list_by_conversation(conv["id"]) or []
                recent = msgs[-40:] if len(msgs) > 40 else msgs
                if not recent:
                    continue
                all_lines.append(f"── 【{peer_name}】的对话 ──")
                for m in recent:
                    role = m.get("role") or "user"
                    c = (m.get("content") or "").strip()
                    if not c:
                        continue
                    tag_cn = "用户" if role == "user" else ("AI" if role == "assistant" else role)
                    if len(c) > 400:
                        c = c[:397] + "…"
                    all_lines.append(f"{tag_cn}：{c}")
            conv_text = "\n".join(all_lines)
            if not conv_text.strip():
                continue

            # 查 role（从 channel_binding 看是否管理者）
            role = "user"
            try:
                # 先看是否 is_manager_peer
                if channels_dao.is_manager_peer(agent_id, channel, peer_id):
                    role = "manager"
                else:
                    # 再看 binding 表里有没有 is_manager=1 的其他绑定（跨 agent 也查）
                    from storage.db import get_conn as _get_conn
                    _bind = _get_conn().execute(
                        "SELECT is_manager FROM channel_binding WHERE channel=? AND peer_id=? AND is_manager=1 AND enabled=1 LIMIT 1",
                        (channel, peer_id),
                    ).fetchone()
                    if _bind:
                        role = "manager"
            except Exception:
                pass

            # 取旧记忆（per-peer 级别的）
            import json as _json2
            old_peer = peer_profile_dao.get(channel, peer_id)
            old_mem_raw = old_peer.get("memories") if old_peer else "{}"
            old_mem = self._parse_memory_json_safe(old_mem_raw)
            old_mem_dump = _json2.dumps(
                {"enabled": old_mem.get("enabled", True),
                 "user_profile": old_mem.get("user_profile") or [],
                 "episodic": old_mem.get("episodic") or []},
                ensure_ascii=False, indent=2,
            )

            # 组装 prompt → 喂 LLM
            now = now_ts()
            user_prompt = (
                "以下是当前对话对象的两部分数据，请按 system 指令提炼并输出 JSON。\n\n"
                f"【当前时间戳】{str(now)}\n\n"
                f"【旧记忆（和新对话冲突以新对话为准；新对话没提到就保留旧记忆）】\n"
                f"{old_mem_dump}\n\n"
                f"【近期对话历史（仅该对话对象）】\n{conv_text}\n"
            )
            try:
                provider = LLMProvider.from_config(llm_cfg)
                result = provider.chat(
                    messages=[
                        {"role": "system", "content": MEMORY_REFINE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.15,
                    max_tokens=4000,
                )
            except Exception as e:
                print(f"[per-peer提炼] LLM异常 channel={channel} peer={peer_id[:16]}.. err={e}", flush=True)
                continue
            if result.get("error") or not (result.get("text") or "").strip():
                continue
            new_mem = self._extract_memory_json_from_llm_text(result["text"])
            if new_mem is None:
                continue

            # 写 peer_profile
            final_mem = {
                "enabled": True,
                "user_profile": self._sanitize_memory_entry_list(new_mem.get("user_profile") or []),
                "episodic":     self._sanitize_memory_entry_list(new_mem.get("episodic") or []),
                "last_confirm_at": old_mem.get("last_confirm_at"),
                "last_refine_at": now,
            }
            peer_profile_dao.upsert({
                "channel": channel,
                "peer_id": peer_id,
                "peer_name": peer_name,
                "role": role,
                "memories": json.dumps(final_mem, ensure_ascii=False),
                "last_refine_at": now,
            })
            count += 1
            print(f"[per-peer提炼] ✅ channel={channel} peer={peer_id[:16]}.. role={role} "
                  f"profile={len(final_mem['user_profile'])} episodic={len(final_mem['episodic'])}",
                  flush=True)

        return count

    def _handle_refine_memory_preview(self, payload):
        """【IPC】前端「刷新最新方案」按钮调用。
        优先级：① 如果DB里已经有pending暂存 → 直接返回（省LLM调用）
                ② 否则立即手动跑一次纯提炼，返回结果（不写DB任何东西）
        payload: {"agent_id": str, "conv_id": str可选, "force": bool可选}
                 force=true → 忽略pending，强制重新跑一次 LLM 预览
        """
        agent_id = (payload or {}).get("agent_id") or ""
        conv_id  = (payload or {}).get("conv_id") or None
        force    = bool((payload or {}).get("force"))
        agent = agents_dao.get(agent_id) if agent_id else None
        if not agent:
            raise ValueError("智能体不存在")
        # —— 闸门：未激活直接拒（和 create/update_agent 上的闸门 A 对齐）——
        self._require_perm("memory", msg="升级标准版解锁记忆与进化")
        mem = self._parse_memory_json_safe(agent.get("memories") or "")

        # 优先用 pending（除非 force=true）
        pending = mem.get("pending") if not force else None
        if pending and isinstance(pending, dict):
            result_payload = {
                "prompt_suggestions": pending.get("prompt_suggestions") or [],
                "kb_suggestions":     pending.get("kb_suggestions") or [],
                "user_profile":       pending.get("user_profile") or [],
                "episodic":           pending.get("episodic") or [],
                "created_at":         pending.get("created_at"),
            }
            source = "pending"
        else:
            # 手动预览：立即跑一次 LLM，不写 DB
            result_payload = self._do_memory_extract_pure(agent_id, conv_id)
            result_payload["created_at"] = now_ts()
            source = "live_preview"

        # 返回完整上下文给前端：（不包 ok —— 全项目 handler 统一风格，Bridge.call 包 ok）
        suggest_p = result_payload.get("user_profile") or []
        suggest_e = result_payload.get("episodic") or []
        print(
            f"[记忆预览] agent={agent_id[:8]} source={source} "
            f"suggest({len(suggest_p)}画像/{len(suggest_e)}重点) "
            f"formal({len(mem.get('user_profile') or [])}画像/{len(mem.get('episodic') or [])}重点) "
            f"history={len(mem.get('history') or [])}条",
            flush=True,
        )
        return {
            "suggest": result_payload,
            "source": source,                             # "pending" 或 "live_preview"
            "has_pending": mem.get("pending") is not None,
            "formal": {
                "user_profile": mem.get("user_profile") or [],
                "episodic":     mem.get("episodic") or [],
            },
            "last_confirm_at": mem.get("last_confirm_at"),
            "history": (mem.get("history") or [])[-10:],
        }

    def _handle_confirm_apply_optimize(self, payload):
        """【IPC】前端点「确认并应用到智能体」调用。
        做 4 件事：① 做 before/after 版本快照 ② 把用户编辑后的画像/重点写入正式 memories
                   ③ 追加一条 history 记录（限最近 10 条） ④ 清 pending + 更新 last_confirm_at
        人设/知识库建议前端自行处理，这里只持久化 Context 记忆部分。
        payload: {"agent_id": str,
                  "edited": {"user_profile":[{title,content}], "episodic":[{title,content}]},
                  "summary": str可选  // 改动摘要，显示在优化历史里
                  "custom_change_count": int可选 // 前端算的用户手动修改了几处}
        """
        p = payload or {}
        agent_id = p.get("agent_id") or ""
        edited = p.get("edited") or {}
        summary_user = p.get("summary") or ""
        custom_cnt = int(p.get("custom_change_count") or 0)
        agent = agents_dao.get(agent_id) if agent_id else None
        if not agent:
            raise ValueError("智能体不存在")
        self._require_perm("memory", msg="升级标准版解锁记忆与进化")
        old_mem = self._parse_memory_json_safe(agent.get("memories") or "")
        before_profile = list(old_mem.get("user_profile") or [])
        before_episodic = list(old_mem.get("episodic") or [])
        after_profile = self._sanitize_memory_entry_list(edited.get("user_profile") or [])
        after_episodic = self._sanitize_memory_entry_list(edited.get("episodic") or [])

        # 算改动摘要（给优化历史用）
        added_p = max(0, len(after_profile) - len(before_profile))
        added_e = max(0, len(after_episodic) - len(before_episodic))
        summary_parts = [f"画像+{added_p}" if added_p > 0 else f"画像{len(after_profile)}",
                         f"重点+{added_e}" if added_e > 0 else f"重点{len(after_episodic)}"]
        if custom_cnt > 0:
            summary_parts.append(f"用户手动修改{custom_cnt}处")
        if summary_user:
            summary_parts.append(summary_user)
        final_summary = " / ".join(summary_parts)
        now = now_ts()

        # —— 写快照到 history：最多保留最近 10 条 ——
        snapshot = {
            "time": now,
            "before": {"user_profile": before_profile, "episodic": before_episodic},
            "after":  {"user_profile": after_profile,  "episodic": after_episodic},
            "summary": final_summary,
        }
        old_history = list(old_mem.get("history") or [])
        old_history.append(snapshot)
        if len(old_history) > 10:
            old_history = old_history[-10:]

        # —— 合并最终 memories：pending 清掉，正式内容更新，last_confirm_at=now，history 替换 ——
        final_mem = {
            "enabled": old_mem.get("enabled") if isinstance(old_mem.get("enabled"), bool) else True,
            "user_profile": after_profile,
            "episodic":     after_episodic,
            "pending": None,   # 清掉：已经确认应用了
            "history": old_history,
            "last_confirm_at": now,
        }
        agents_dao.update(agent_id, {"memories": json.dumps(final_mem, ensure_ascii=False)})
        print(
            f"[优化确认应用] agent={agent_id[:8]} "
            f"BEFORE({len(before_profile)}画像/{len(before_episodic)}重点) → "
            f"AFTER({len(after_profile)}画像/{len(after_episodic)}重点) "
            f"history={len(old_history)}条 summary={final_summary}",
            flush=True,
        )
        return {
            "last_confirm_at": now,
            "history": old_history[-10:],
            "counts": {
                "profile_cnt": len(after_profile),
                "episodic_cnt": len(after_episodic),
            },
            "full_mem": final_mem,
        }

    # ============================================================
    # 记忆与进化 v2：刷新 / 导入（对齐 Workbody 交互）
    # ============================================================

    def _maybe_daily_memory_refine(self):
        """【24小时机制】启动时检查所有智能体，距上次整理 >24h 的后台静默跑一次全量提炼。

        对齐 Workbody「每晚自动整理」：实际是每 24 小时一次，软件启动时触发检查。
        """
        try:
            if not self._check_perm("memory"):
                return  # 未激活不跑
            now = now_ts()
            day_seconds = 24 * 3600
            agents = agents_dao.list_all()
            for ag in agents:
                mem = self._parse_memory_json_safe(ag.get("memories") or "")
                if not mem.get("enabled", True):
                    continue  # 用户关了记忆开关
                last = int(ag.get("last_memory_refine_at") or 0)
                if last > 0 and (now - last) < day_seconds:
                    continue  # 24 小时内整理过，跳过
                # 后台提交
                self._memory_executor.submit(self._daily_refine_one, ag["id"])
        except Exception as e:
            print(f"[24h记忆整理] 检查异常: {e}", flush=True)

    def _daily_refine_one(self, agent_id: str):
        """后台线程：对单个智能体做一次全量记忆整理。"""
        try:
            result = self._do_memory_extract_pure(agent_id)
            if result.get("user_profile") or result.get("episodic"):
                self._save_memory_result(agent_id, result)
                print(f"[24h记忆整理] agent={agent_id[:8]} 完成 per-agent 提炼", flush=True)
            # 🆕 per-peer 分组提炼（双层 profile 架构）
            n = self._extract_peer_profiles_for_agent(agent_id)
            if n > 0:
                print(f"[24h记忆整理] agent={agent_id[:8]} 完成 per-peer 提炼，{n} 个 peer", flush=True)
        except Exception as e:
            print(f"[24h记忆整理] agent={agent_id[:8]} 异常: {e}", flush=True)

    def _save_memory_result(self, agent_id: str, result: dict) -> dict:
        """将提炼结果直接写入 ai_agent.memories（覆盖 user_profile/episodic）。

        result 格式：{"user_profile": [...], "episodic": [...]}
        返回写入后的完整 memories dict。
        """
        agent = agents_dao.get(agent_id)
        if not agent:
            raise ValueError("智能体不存在")
        old_mem = self._parse_memory_json_safe(agent.get("memories") or "")
        now = now_ts()
        final_mem = {
            "enabled": old_mem.get("enabled") if isinstance(old_mem.get("enabled"), bool) else True,
            "user_profile": self._sanitize_memory_entry_list(result.get("user_profile") or []),
            "episodic":     self._sanitize_memory_entry_list(result.get("episodic") or []),
            "pending": None,
            "history": old_mem.get("history") or [],
            "last_confirm_at": old_mem.get("last_confirm_at"),
            "last_refine_at": now,
        }
        agents_dao.update(agent_id, {
            "memories": json.dumps(final_mem, ensure_ascii=False),
            "last_memory_refine_at": now,
        })
        return final_mem

    def _handle_refresh_memory(self, payload):
        """【IPC】前端「刷新」按钮：从该智能体所有非空会话提炼记忆，直接写入 DB。

        payload: {"agent_id": str}
        返回：{"user_profile": [...], "episodic": [...], "last_refine_at": ts}
        """
        agent_id = (payload or {}).get("agent_id") or ""
        if not agent_id:
            raise ValueError("缺少 agent_id")
        agent = agents_dao.get(agent_id)
        if not agent:
            raise ValueError("智能体不存在")
        self._require_perm("memory", msg="升级标准版解锁记忆与进化")

        result = self._do_memory_extract_pure(agent_id)
        has_result = (result.get("user_profile") or []) or (result.get("episodic") or [])
        if has_result:
            final_mem = self._save_memory_result(agent_id, result)
        else:
            # LLM 未返回有效记忆时，不覆盖 DB，返回当前已有记忆
            old_mem = self._parse_memory_json_safe(agent.get("memories") or "")
            final_mem = {
                "user_profile": old_mem.get("user_profile") or [],
                "episodic": old_mem.get("episodic") or [],
            }
            print(f"[记忆刷新] LLM 未返回有效记忆，保留原有 {len(final_mem['user_profile'])} 画像 / {len(final_mem['episodic'])} 重点", flush=True)
        print(f"[记忆刷新] agent={agent_id[:8]} 画像={len(final_mem['user_profile'])} 重点={len(final_mem['episodic'])}", flush=True)
        # 🆕 per-peer 分组提炼（双层 profile 架构）
        n = self._extract_peer_profiles_for_agent(agent_id)
        if n > 0:
            print(f"[记忆刷新] agent={agent_id[:8]} per-peer 提炼完成，{n} 个 peer", flush=True)
        return {
            "user_profile": final_mem["user_profile"],
            "episodic": final_mem["episodic"],
            "last_refine_at": now_ts(),
        }

    def _handle_list_migrated(self, payload):
        """【IPC】前端「导入」弹窗：列出从别处搬迁过来、尚未导入记忆的会话。

        payload: {"agent_id": str}
        返回：[{"id", "peer_name", "peer_type", "message_count", "from_agent_name", "updated_at"}, ...]
        """
        agent_id = (payload or {}).get("agent_id") or ""
        if not agent_id:
            raise ValueError("缺少 agent_id")
        rows = conv_dao.list_migrated_by_agent(agent_id)
        return [{
            "id": r["id"],
            "peer_name": r.get("peer_name") or "",
            "peer_type": r.get("peer_type") or "friend",
            "message_count": r.get("message_count") or 0,
            "from_agent_name": r.get("from_agent_name") or "未知智能体",
            "updated_at": r.get("updated_at") or 0,
        } for r in rows]

    def _handle_import_memory(self, payload):
        """【IPC】前端「导入」确认：异步从选中的搬迁会话提炼记忆，合并进当前记忆。

        对齐 WorkBuddy 交互：导入是后台耗时操作，用户可关闭弹窗，完成后自动录入记忆。
        payload: {"agent_id": str, "conv_ids": [str]}
        立即返回：{"started": True}
        完成后推送：memory_imported {agent_id, user_profile, episodic, imported_count}
        """
        p = payload or {}
        agent_id = p.get("agent_id") or ""
        conv_ids = p.get("conv_ids") or []
        if not agent_id:
            raise ValueError("缺少 agent_id")
        if not conv_ids:
            raise ValueError("请至少选择一个会话")
        agent = agents_dao.get(agent_id)
        if not agent:
            raise ValueError("智能体不存在")
        self._require_perm("memory", msg="升级标准版解锁记忆与进化")

        # 立即返回，后台异步执行
        self._memory_executor.submit(self._do_import_memory_async, agent_id, conv_ids)
        return {"started": True}

    def _do_import_memory_async(self, agent_id: str, conv_ids: list[str]):
        """后台线程：执行实际的记忆导入，完成后推送到前端。"""
        try:
            result = self._do_memory_extract_pure(agent_id, conv_ids=conv_ids)
            final_mem = self._save_memory_result(agent_id, result)
            conv_dao.clear_migrated(conv_ids)
            print(f"[记忆导入] agent={agent_id[:8]} 导入会话={len(conv_ids)} 画像={len(final_mem['user_profile'])} 重点={len(final_mem['episodic'])}", flush=True)
            # 🆕 per-peer 分组提炼（双层 profile 架构）
            n = self._extract_peer_profiles_for_agent(agent_id)
            if n > 0:
                print(f"[记忆导入] agent={agent_id[:8]} per-peer 提炼完成，{n} 个 peer", flush=True)
            self.send_to_js("memory_imported", {
                "agent_id": agent_id,
                "user_profile": final_mem["user_profile"],
                "episodic": final_mem["episodic"],
                "imported_count": len(conv_ids),
            })
        except Exception as e:
            print(f"[记忆导入] agent={agent_id[:8]} 异常: {e}", flush=True)
            self.send_to_js("memory_imported", {
                "agent_id": agent_id,
                "error": str(e),
            })

    def _handle_rollback_optimize(self, payload):
        """【IPC】一键回滚到上一个历史版本（优化历史里的「回滚」按钮）。
        语义：撤销最近一次「确认更新」或「回滚」操作，回到 history[-1].before。
        history 数组里每条快照的 before 字段永远是「写快照之前的正式内容」，
        所以 rollback 就是把 history[-1].before 当作新的正式 memories。
        每次 rollback 自身也会追加一条 history 快照（方便"后悔了再 rollback 回去"）。
        payload: {"agent_id": str, "history_index": int可选  // 忽略，始终回滚一个版本}
        """
        p = payload or {}
        agent_id = p.get("agent_id") or ""
        agent = agents_dao.get(agent_id) if agent_id else None
        if not agent:
            raise ValueError("智能体不存在")
        self._require_perm("memory", msg="升级标准版解锁记忆与进化")
        old_mem = self._parse_memory_json_safe(agent.get("memories") or "")
        history = list(old_mem.get("history") or [])
        if not history:
            raise ValueError("暂无历史版本可回滚（确认更新后才会生成快照）")

        # ★ 关键：回滚目标 = 最新快照的 before 字段
        # 因为每次写 history（confirm / rollback），before 都是写快照之前的正式内容
        # 所以 history[-1].before = 上一个版本
        latest_snap = history[-1]
        target_before = latest_snap.get("before") or {}
        if not isinstance(target_before, dict):
            raise ValueError("历史快照损坏")
        target_profile = self._sanitize_memory_entry_list(target_before.get("user_profile") or [])
        target_episodic = self._sanitize_memory_entry_list(target_before.get("episodic") or [])

        now = now_ts()
        before_profile = list(old_mem.get("user_profile") or [])
        before_episodic = list(old_mem.get("episodic") or [])
        snap_time = latest_snap.get("time") or 0
        # 把当前 before → target 也存一条新历史（方便"后悔回滚了，再回滚"）
        rollback_snap = {
            "time": now,
            "before": {"user_profile": before_profile, "episodic": before_episodic},
            "after":  {"user_profile": target_profile, "episodic": target_episodic},
            "summary": f"一键回滚到 {fmt_date_short(snap_time) if snap_time else '旧版本'}（原摘要：{latest_snap.get('summary') or '-'}）",
        }
        new_history = list(history)
        new_history.append(rollback_snap)
        if len(new_history) > 10:
            new_history = new_history[-10:]

        final_mem = {
            "enabled": old_mem.get("enabled") if isinstance(old_mem.get("enabled"), bool) else True,
            "user_profile": target_profile,
            "episodic":     target_episodic,
            "pending": old_mem.get("pending"),   # 回滚不影响 pending
            "history": new_history,
            "last_confirm_at": now,              # 回滚也相当于一次"确认应用"
        }
        agents_dao.update(agent_id, {"memories": json.dumps(final_mem, ensure_ascii=False)})
        print(f"[优化回滚] agent={agent_id[:8]}，回滚到 history[-1].before（{len(target_profile)}画像/{len(target_episodic)}重点）。", flush=True)
        return {
            "last_confirm_at": now,
            "history": new_history[-10:],
            "counts": {
                "profile_cnt": len(target_profile),
                "episodic_cnt": len(target_episodic),
            },
            "rolled_back_to": snap_time,
            "full_mem": final_mem,
        }

    # -------- 两阶段：轻量 LLM 调用（生成占位回复） --------
    def quick_llm_call(
        self,
        agent_id: str,
        reason: str,
        channel: str = "",
        file_size_mb: float = 0,
        risk_delay: float = 0,
        rate_level: str = "normal",
        is_manager: bool = False,
        hour: int = -1,
        msg_type: str = "text",
    ) -> str:
        """
        轻量 LLM 调用：生成自然的占位回复文案。
        - 不走完整翻译层 + RAG + 历史
        - 只给极简 system prompt + 一句话 user prompt
        - 10s 超时兜底（返回硬编码文案）
        - 不入库（占位回复不需要存）
        - risk_delay: 风控模拟打字等待秒数（0=无）
        """
        FALLBACKS = {
            "file_large": "收到啦～文件有点大，稍等我一下哦～",
            "llm_busy": "我这边现在有点忙，稍等哦～",
            "queue_full": "前面还有几条消息在处理，稍等我哦～",
            "timeout": "网络好像有点慢，要不你稍后再试？",
            "risk_delay_long": "收到啦～正在整理你的消息，稍等我一下哦～",
        }

        try:
            agent = agents_dao.get(agent_id)
            if not agent:
                return FALLBACKS.get(reason, "稍等哦～")

            llm_id = agent.get("llm_config_id") or ""
            llm_cfg = llm_dao.get(llm_id) if llm_id else llm_dao.get_default()
            if not llm_cfg:
                return FALLBACKS.get(reason, "稍等哦～")

            agent_name = agent.get("name", "AI")
            reason_cn = {
                "file_large": f"用户发了一个 {file_size_mb:.1f}MB 的大文件",
                "llm_busy": "大模型现在比较忙",
                "queue_full": "前面还有消息在排队处理",
                "risk_delay_long": "消息正在整理中",
            }.get(reason, reason)

            # 🆕 融合版：从 agent 的 system_prompt 里抽 persona 锚点（不让 LLM 瞎发挥）
            sys_prompt = (agent.get("system_prompt") or "").strip()
            if sys_prompt:
                persona_hint = sys_prompt[:150].replace("\n", " ")
            else:
                persona_hint = "自然、口语化、像正常人说话"

            # 🆕 融合版：收集事实描述（不硬给要说的具体词汇）
            facts_parts = []
            type_cn = {
                "file": "文件",
                "image": "图片",
                "voice": "语音",
                "video": "视频",
                "text": "消息",
                "link": "链接",
            }.get(msg_type, "消息")
            if reason == "file_large" and file_size_mb > 0:
                facts_parts.append(f"对方发了一个 {file_size_mb:.1f}MB 的{type_cn}")
            elif reason == "risk_delay_long":
                if file_size_mb > 0:
                    facts_parts.append(f"对方发了一个 {file_size_mb:.1f}MB 的{type_cn}")
                else:
                    facts_parts.append("对方发了一条消息")
            elif reason == "queue_full":
                facts_parts.append("你手上还有几条消息在处理")

            rate_cn = {
                "aggressive": "激进（风控松）",
                "normal": "正常",
                "conservative": "保守（风控严）",
            }.get(rate_level, rate_level)
            if channel == "wcf":
                facts_parts.append(f"渠道是微信，风控档位{rate_cn}")

            if hour >= 0:
                is_night = hour < 6 or hour >= 23
                if is_night and channel == "wcf":
                    facts_parts.append(f"现在是凌晨/深夜（{hour}点），微信风控保守")
                elif hour >= 11 and hour <= 13:
                    facts_parts.append(f"现在是中午休息时间（{hour}点）")
                elif hour >= 22 or hour < 7:
                    facts_parts.append(f"现在是晚上/凌晨（{hour}点）")

            if is_manager:
                facts_parts.append("对面是老板/管理者，语气可以自然随意")
            if risk_delay and risk_delay > 5:
                if risk_delay > 120:
                    facts_parts.append("你可能要等好几分钟才发正式回复")
                elif risk_delay > 60:
                    facts_parts.append("你大概要等一两分钟才发正式回复")
                else:
                    facts_parts.append(f"你大概要等 {risk_delay:.0f} 秒才发正式回复")
            facts_str = "；".join(facts_parts) if facts_parts else "你需要一点时间"

            messages = [
                {"role": "system",
                 "content": f"你是{agent_name}的AI分身。你的性格参考：{persona_hint}。\n"
                            f"说话自然、口语化、简短。不要超过20字。\n"
                            f"不要用'系统''后台''处理中''排队'这些词。"},
                {"role": "user",
                 "content": f"情境：{facts_str}。说一句话告诉对方你稍等，自然就行。"},
            ]

            provider = LLMProvider.from_config(llm_cfg)
            result = provider.chat(messages, temperature=0.7)

            text = (result.get("text") or "").strip()
            if text and len(text) >= 2:
                text = text.strip('"').strip('\n').strip('`')
                return text[:80]

        except Exception as e:
            print(f"[Bridge] quick_llm_call 异常（用兜底）: {type(e).__name__}: {e}", flush=True)

        return FALLBACKS.get(reason, "稍等哦～")

    def _build_runtime_context(
        self,
        agent: dict,
        llm_cfg: dict,
        channel: str,
        peer_id: str,
        peer_name: str,
        is_manager_peer: bool,
        media_list: list = None,
        msg_facts: dict = None,
    ) -> str:
        """【翻译层】把 MVP 的运行时配置翻译成 LLM 能读懂的入场简报 Prompt。

        融合后：代码负责采集事实，LLM 负责决策。
        - msg_facts: Pipeline 采集的当前消息事实（file_size/risk_delay/queue_depth 等）
        - 不做任何"要不要说话""说什么"的硬编码决策，只给事实 + 参考
        """
        try:
            import json as _json
            # 使用 bridge.py 顶部已导入的模块级变量（不重新 import）
            # channels_dao, agents_dao, peer_profile_dao, kb_dao 都在模块作用域

            lines = [f"【系统简报 · 你当前的运行环境】"]

            # ▎产品名（硬编码）
            lines.append(f"\n▎系统平台\n你运行在「{PRODUCT_NAME}」— 一个让你成为具体某个人的数字分身的平台。")

            # ▎当前智能体
            agent_name = agent.get("name", "未命名")
            lines.append(f"\n▎当前会话")
            lines.append(f"- 智能体：{agent_name}")

            # ▎渠道
            ch_label = _CHANNEL_LABELS.get(channel, channel)
            lines.append(f"- 渠道：{ch_label}（{channel}）")

            # ▎渠道 ASR 能力（从 dao.py 已有表查）
            try:
                from storage.dao import _CHANNEL_CF_DEFAULTS
                channel_has_asr = _CHANNEL_CF_DEFAULTS.get(channel, {}).get("voice", False)
            except Exception:
                channel_has_asr = False

            # ▎当前对话对象
            role_label = "管理者（主人）" if is_manager_peer else "普通用户"
            lines.append(f"- 对话对象：{peer_name or '未知'} — {role_label}")

            # ▎本渠道绑定了多少管理者/普通用户
            try:
                all_bindings = channels_dao.list_bindings(channel) if hasattr(channels_dao, 'list_bindings') else []
                mgr_count = sum(1 for b in all_bindings if b.get("is_manager"))
                user_count = sum(1 for b in all_bindings if b.get("enabled", 1) and not b.get("is_manager"))
                lines.append(f"- 本渠道已绑定：{mgr_count} 个管理者，{user_count} 个普通用户")
            except Exception:
                pass

            # ▎内容形式配置 + 渠道能力交叉
            cf_raw = agent.get("content_formats") or "{}"
            cf = _json.loads(cf_raw) if isinstance(cf_raw, str) else (cf_raw or {})

            fmt_labels = {
                "text": "文本",
                "voice": "语音",
                "image": "图片",
                "video": "视频",
                "file": "文件",
            }
            lines.append(f"\n▎渠道内容能力")
            fmt_parts = []
            for key, label in fmt_labels.items():
                enabled = cf.get(key, False)
                if not enabled:
                    continue
                # 交叉渠道能力
                channel_block = False
                if key == "voice" and not channel_has_asr:
                    channel_block = True
                fmt_parts.append(f"✅ {label}" + ("（但当前渠道无自动转写）" if channel_block else ""))

            # 补充未开启的
            disabled_labels = [label for key, label in fmt_labels.items() if not cf.get(key, False)]
            if disabled_labels:
                fmt_parts.append(f"❌ {'/'.join(disabled_labels)}（未开启）")

            lines.append("  ".join(fmt_parts))

            # ▎知识库
            kb_ids_raw = agent.get("kb_ids") or "[]"
            kb_ids = _json.loads(kb_ids_raw) if isinstance(kb_ids_raw, str) else (kb_ids_raw or [])
            if kb_ids:
                kb_names = []
                for kid in kb_ids:
                    try:
                        kb = kb_dao.get(kid)
                        if kb:
                            kb_names.append(f"{kb.get('name', kid)}（{kb.get('doc_count', '?')} 篇）")
                    except Exception:
                        pass
                if kb_names:
                    lines.append(f"\n▎知识库\n已绑定：{'，'.join(kb_names)}，RAG 检索{'开启' if agent.get('kb_enabled') else '关闭'}")
                else:
                    lines.append(f"\n▎知识库\n已绑定但无法获取详情，RAG 检索{'开启' if agent.get('kb_enabled') else '关闭'}")
            else:
                lines.append(f"\n▎知识库\n（未绑定）")

            # ▎运营设置
            aigc = agent.get("aigc_enabled", False)
            emoji = agent.get("emoji_enabled", False)
            rate_raw = agent.get("rate_profile") or "{}"
            try:
                rate = _json.loads(rate_raw) if isinstance(rate_raw, str) else (rate_raw or {})
            except Exception:
                rate = {}
            rate_level = rate.get("level", "保守")

            lines.append(f"\n▎运营设置")
            lines.append(f"- AI 生成内容标识：{'开启' if aigc else '关闭'}")
            lines.append(f"- 表情：{'开启' if emoji else '关闭'}")
            lines.append(f"- 风控档位：{rate_level}")

            # 🆕 ▎当前消息事实（代码采集的客观数据，你作为人来解读）
            if msg_facts:
                lines.append(f"\n▎当前消息事实（客观数据，你作为人来解读）")
                for k, v in msg_facts.items():
                    lines.append(f"  · {k}: {v}")

            # 🆕 ▎Persona 锚点（从 agent prompt 里抽你的性格关键词）
            sys_prompt = (agent.get("system_prompt") or "").strip()
            if sys_prompt:
                # 取前 200 字（通常就是 persona 描述），避免太长
                persona_hint = sys_prompt[:200].replace("\n", " ")
                lines.append(f"\n▎你的性格参考（从你自己的设定里抽的）")
                lines.append(f"  {persona_hint}...")
                lines.append(f"  → 用这个性格说话，不要变成客服机器人。")

            # 🆕 ▎说话参考（给你参考，不是硬指令）
            lines.append(f"\n▎说话参考（参考，不是硬指令，你自己判断）")
            lines.append(f"  设想你是一个正常人，对方给你发了点东西，你会怎么反应：")
            lines.append(f"  · 如果是一两页纸的小文件 → 直接说正事就行，不用特意打招呼")
            lines.append(f"  · 如果是几十页的文件 → 可以开头说一句'好的，我看看这个'再讲正事")
            lines.append(f"  · 如果是上百页 → 可以说'内容不少，我仔细看看'")
            if is_manager_peer:
                lines.append(f"  · 对方是管理者/老板，他给你发东西可能等着要结果")
            lines.append(f"  · 不用刻意强调'正在处理'——正常人不会说这种话")
            lines.append(f"  · 不要用'系统''后台''处理中''排队'这些技术词")
            lines.append(f"  · 要不要打招呼、怎么打招呼——全由你根据自己的性格和上面的事实决定")
            lines.append(f"  · 如果看到 [非文本消息: xxx] 开头的内容——这是系统无法自动解析的消息类型（如日程/位置/名片/红包/会议等）——如实告诉对方你看到了什么，但不要承诺去执行你做不到的动作（如改日历、发红包、导航等）")

            # ▎全系统概览（只给管理者）
            if is_manager_peer:
                try:
                    total_agents = len(agents_dao.list_all()) if hasattr(agents_dao, 'count') else 0
                    all_channels = set()
                    total_mgr = 0
                    total_user = 0
                    try:
                        all_agents = agents_dao.list_all() if hasattr(agents_dao, 'list') else []
                        for ag in all_agents:
                            ch = ag.get("channel", "")
                            if ch:
                                all_channels.add(ch)
                    except Exception:
                        pass
                    try:
                        from storage import channels_dao as _cd
                        all_bindings = channels_dao.list_bindings('') if hasattr(channels_dao, 'list_bindings') else []
                        for b in all_bindings:
                            if b.get("is_manager"):
                                total_mgr += 1
                            elif b.get("enabled", 1):
                                total_user += 1
                    except Exception:
                        pass

                    ch_labels = [_CHANNEL_LABELS.get(c, c) for c in all_channels]
                    lines.append(f"\n▎全系统概览（管理者专属）")
                    lines.append(f"- 智能体：{total_agents} 个，覆盖 {', '.join(ch_labels) if ch_labels else '(无)'}")
                    lines.append(f"- 已识别管理者 {total_mgr} 人，普通用户 {total_user} 人")
                except Exception:
                    pass

            try:
                from storage import agent_app_dao, app_credential_dao
                from app_registry import APPS
                agent_id = agent.get("id", "")
                app_lines_ok = []
                app_lines_missing = []
                _bindings = agent_app_dao.list_by_agent(agent_id)
                _bound_ids = {b["app_id"] for b in _bindings if b.get("enabled")}
                for _aid in _bound_ids:
                    _meta = APPS.get(_aid)
                    if not _meta:
                        continue
                    _aud = _meta.get("audience", "both")
                    if _aud == "manager" and not is_manager_peer:
                        continue
                    if _aud == "customer" and is_manager_peer:
                        continue
                    _creds_schema = _meta.get("credential_schema") or {}
                    _required_keys = [f["key"] for f in _creds_schema.get("fields", []) if f.get("required")]
                    _missing = []
                    if _required_keys:
                        for _ck in _required_keys:
                            _cv = app_credential_dao.get(_ck)
                            if not (_cv and _cv.get("value")):
                                _missing.append(_ck)
                    _label = _meta.get("name", _aid)
                    _desc = (_meta.get("description") or "").strip()
                    _usage = (_meta.get("usage") or "").strip().split("\n")[0] if _meta.get("usage") else ""
                    _one_line = _desc or _usage
                    if _missing:
                        app_lines_missing.append(f"⚠️ {_label}（{', '.join(_missing)} 未填，别向用户承诺能用）")
                    else:
                        app_lines_ok.append(f"✅ {_label} —— {_one_line[:80]}")
                if app_lines_ok or app_lines_missing:
                    lines.append(f"\n▎可用工具（应用市场）")
                    for _l in app_lines_ok:
                        lines.append(f"  {_l}")
                    for _l in app_lines_missing:
                        lines.append(f"  {_l}")
                else:
                    lines.append(f"\n▎可用工具（应用市场）\n  （未启用任何应用）")
            except Exception as _ae:
                print(f"[Bridge] 翻译层 · 应用列表构建异常: {_ae}", flush=True)

            # ▎角色说明（帮助 LLM 区分说话方式）
            lines.append(f"\n▎角色说明")
            lines.append("- 管理者：本智能体的所有者。他们关心配置、运营、数据，会问规模、配置、知识库相关问题。")
            lines.append("- 普通用户：面向外部的客户。他们不知道你是 AI，不需要技术细节，保持友好自然。")

            return "\n".join(lines)

        except Exception as e:
            print(f"[Bridge] 翻译层构建异常: {e}", flush=True)
            return None

    def _user_has_any_channel_binding(self, channels):
        """用户是否绑定了 channels 列表里的至少一个渠道（channel_binding 表）。"""
        try:
            from storage.db import get_conn
            conn = get_conn()
            rows = conn.execute('SELECT DISTINCT channel FROM channel_binding WHERE is_bound=1').fetchall()
            bound = {r['channel'] for r in rows}
            return bool(bound & set(channels))
        except Exception:
            return True

    def _dispatch_tool_call(self, tc, agent_id, is_manager_mode):
        """根据 tool_call 的 name 找到对应的 tool_fn 并执行，返回 JSON string。

        args 自动注入：
          __tool_name    —— tool 名称（同一个 tool_fn 内部分发多个工具名）
          __agent_id     —— 智能体 ID
          __is_manager   —— 当前是否管理者模式
          __credentials  —— 这个应用的凭据（从 app_credential 表按 credential_schema 过滤）
          __app_config   —— agent_app 表里的 config_json（应用运行时配置）
        """
        import json as _json
        import importlib
        from app_registry import APPS
        from storage import agent_app_dao, app_credential_dao
        name = tc.get('name', '')
        try:
            args_str = tc.get('arguments', '{}')
            args = _json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
        except Exception:
            args = {}
        for app_id, meta in APPS.items():
            fn_ref = meta.get('tool_fn')
            if not fn_ref:
                continue
            fn_name = ''
            def_ref = meta.get('tool_def')
            def_json = meta.get('tool_def_json')
            if isinstance(def_json, dict):
                fn_name = (def_json.get('function') or {}).get('name', '')
            elif isinstance(def_ref, str):
                try:
                    mod_path, attr = def_ref.rsplit(':', 1)
                    mod = importlib.import_module(mod_path)
                    real_def = getattr(mod, attr, None)
                    fn_name = (real_def or {}).get('function', {}).get('name', '') if isinstance(real_def, dict) else ''
                except Exception:
                    pass
            if fn_name != name:
                continue
            try:
                args['__tool_name'] = tc.get('name', '')
                args['__agent_id'] = agent_id
                args['__is_manager'] = is_manager_mode
                cred_schema = meta.get('credential_schema') or {}
                allowed_keys = {f['key'] for f in cred_schema.get('fields', [])}
                creds = {}
                if allowed_keys:
                    for cred in app_credential_dao.list_all():
                        if cred['credential_key'] not in allowed_keys:
                            continue
                        creds[cred['credential_key']] = cred.get('value', '')
                args['__credentials'] = creds
                try:
                    cfg_row = agent_app_dao.get_config(agent_id, app_id)
                    args['__app_config'] = cfg_row if isinstance(cfg_row, dict) else {}
                except Exception:
                    args['__app_config'] = {}
                mod_path2, fn_name = fn_ref.rsplit(':', 1)
                mod2 = importlib.import_module(mod_path2)
                call_fn = getattr(mod2, fn_name)
                return call_fn(args)
            except Exception as _te:
                import traceback as _tb
                return _json.dumps({
                    'ok': False,
                    'error': f'tool 执行异常: {_te}',
                    'traceback': _tb.format_exc()[:500],
                }, ensure_ascii=False)
        return _json.dumps({'ok': False, 'error': f'未知工具: {name}'}, ensure_ascii=False)

    def _handle_send_message(self, payload):
        """发送消息到 LLM，返回完整回复（非流式）。

        链路：
        1. 获取智能体（persona / system_prompt / 绑定的知识库）
        2. 构建 system prompt（persona + 风格 + AIGC 标识）
        3. 检索知识库（如有绑定）
        4. 拼接历史消息（最近 N 轮）
        5. 调用 LLM（非流式）
        6. 保存消息到数据库（带 channel / model 维度）
        7. 返回完整回复

        可选入参：
          channel : wcf / wecom / oa / feishu / dingtalk，默认 wcf
          peer_id / peer_name : 渠道联系人标识（未传则不写入 conversation）
        """
        agent_id = payload.get("agent_id")
        user_input = (payload.get("content") or "").strip()
        conv_id = payload.get("conversation_id") or ""
        use_kb = bool(payload.get("use_kb", True))
        channel = (payload.get("channel") or "wcf").strip().lower() or "wcf"
        peer_id = (payload.get("peer_id") or "").strip()
        peer_name = (payload.get("peer_name") or "").strip()
        peer_type = (payload.get("peer_type") or "friend").strip()

        # ★ 多模态：图片/视频 base64 data URL 列表，格式 [{"type":"image","url":"data:...","name":"xxx"}]
        media_list = payload.get("media") or []

        # ★ 管理者聚合模式：pipeline 传的标记
        is_manager_mode = bool(payload.get("is_manager_mode", False))
        bound_agent_ids = payload.get("bound_agent_ids") or []

        if not agent_id:
            raise ValueError("缺少 agent_id")
        # 有 media（图片/视频）就算 user_input 为空也允许，LLM 会处理
        if not user_input and not media_list:
            raise ValueError("消息不能为空")

        agent = agents_dao.get(agent_id)
        if not agent:
            raise ValueError(f"智能体不存在: {agent_id}")

        # —— 管理者模式：聚合所有 bound agents 的 kb_ids，各自尊重 kb_enabled 开关 ——
        all_kb_ids = []
        if is_manager_mode and bound_agent_ids:
            import json as _json2
            all_kb_ids_set = set()
            for aid in bound_agent_ids:
                try:
                    ba = agents_dao.get(aid)
                    if not ba:
                        continue
                    # 尊重该 agent 的 kb_enabled 开关
                    if ba.get("kb_enabled") == 0:
                        continue
                    raw = ba.get("kb_ids") or "[]"
                    ids = _json2.loads(raw) if isinstance(raw, str) else (raw or [])
                    all_kb_ids_set.update(ids)
                except Exception as _e:
                    print(f"[Bridge] 管理者聚合跳过 agent_id={aid}: {_e}", flush=True)
            all_kb_ids = list(all_kb_ids_set)
            print(f"[Bridge] ★ 管理者模式：聚合 {len(bound_agent_ids)} 个 agent 的 kb_ids → {len(all_kb_ids)} 个唯一 ID", flush=True)
            if not all_kb_ids:
                use_kb = False
        else:
            # 普通用户模式：尊重当前 agent 的 kb_enabled 开关
            if use_kb and agent.get("kb_enabled") == 0:
                use_kb = False

        # 1. 获取 LLM 配置
        llm_id = agent.get("llm_config_id") or ""
        if llm_id:
            llm_cfg = llm_dao.get(llm_id)
        else:
            llm_cfg = llm_dao.get_default()

        if not llm_cfg:
            return {
                "error": "未配置 LLM。请到「设置 → LLM 管理」添加配置。",
                "conversation_id": conv_id,
                "user_message": None,
                "assistant_message": None,
            }

        # 2. 创建会话（如果没有）——带上渠道/联系人维度
        if not conv_id:
            conv = conv_dao.create(agent_id, title=user_input[:30],
                                   channel=channel, peer_id=peer_id,
                                   peer_name=peer_name, peer_type=peer_type)
            conv_id = conv["id"]
        else:
            conv_dao.touch(conv_id)

        # 3. 保存用户消息
        user_msg = msg_dao.create(conv_id, "user", user_input, channel=channel)

        # 4. 构建 system prompt
        # ⚠️ 合并版（2025-09 起）：「性格/说话风格」作为「## 说话风格」Markdown 分段写在 persona（system_prompt）里，
        #    不再单独注入一行 "回复风格：xxx"（之前的方式容易被长 persona 淹没导致 Compliance Drift，被模型忽略）。
        #    参考 Prompt Engineering 业界共识：System Prompt 6 元素结构 → 风格属于 ③ Behavioural Guidelines，
        #    必须是带小标题的 section，而不是夹在尾部的 1 行短句。
        persona = agent.get("system_prompt") or ""
        style = agent.get("style") or ""
        aigc_enabled = bool(agent.get("aigc_enabled", 1))

        # 兼容旧 DB 数据（2025-09 之前产生）：如果 persona 里完全没有「说话风格/回复风格」小标题，
        # 且旧 style 字段是有效长文本（不是 4 字模板名），自动以小标题段合并到 persona
        if style and len(style) > 12:
            _has_style_hdr = ("说话风格" in persona) or ("回复风格" in persona)
            _is_tpl_name = style in (
                "数字分身", "专属客服", "销售顾问", "学习搭档",
                "情感陪聊", "优惠推荐官", "天才同桌", "自定义",
                "default",
            )
            if not _has_style_hdr and not _is_tpl_name:
                persona = (persona.rstrip() + "\n\n" if persona.strip() else "") + \
                          f"## 回复风格\n{style}\n"

        system_parts = [
            persona or f"你是「{agent.get('name', '未命名')}」，一个 AI 数字分身。",
            "请用中文回复，自然、口语化。",
        ]

        # 4a. 管理者（主人）模式：当前 peer 若被标记为该 agent 的管理者，
        #     用全局唯一的「主人模式」预设替换 persona（屏蔽各智能体自定义角色/风格，
        #     对管理者一视同仁）；记忆 / 通用系统规则 / 知识库仍照常注入。
        _is_manager_peer = False
        try:
            if channel and peer_id:
                _is_manager_peer = channels_dao.is_manager_peer(agent_id, channel, peer_id)
        except Exception as _mgr_e:
            print(f"[Bridge] 管理者判定异常: {_mgr_e}", flush=True)

        if _is_manager_peer:
            print(f"[Bridge] 主人模式生效: agent_id={agent_id} channel={channel} peer_id={peer_id}", flush=True)
            system_parts[0] = MANAGER_PROMPT

        # 4b. 注入「智能记忆」：从 agent.memories JSON 读用户画像 + 情景记忆
        # enabled=false / 字段为空 / 解析失败 都跳过；注入顺序放在 persona 之后，确保模型"先理解角色、再了解这个人"
        # ★ 管理者聚合模式跳过：memories 是 agent 级的用户画像，管理者不需要看任何单个 agent 的用户画像
        if not is_manager_mode:
            memories_text = self._format_memory_for_prompt(agent.get("memories") or "")
            if memories_text:
                system_parts.append(memories_text)

        # 4c. 🆕 注入 per-peer profile（双层 profile 架构）
        # 每个人专属画像，不管普通用户还是管理者都注入；per-peer 是默认功能，无独立开关
        if channel and peer_id:
            try:
                peer_prof = peer_profile_dao.get(channel, peer_id)
                if peer_prof and peer_prof.get("memories"):
                    peer_mem_text = self._format_memory_for_prompt(peer_prof["memories"])
                    if peer_mem_text:
                        system_parts.append(
                            "【以下是当前对话对象的专属画像（跨会话持续生效）】\n" +
                            peer_mem_text
                        )
                        print(f"[Bridge] 🆕 注入 per-peer profile: channel={channel} peer={peer_id[:16]}..", flush=True)
            except Exception as _e:
                print(f"[Bridge] per-peer profile 注入异常: {_e}", flush=True)

        # 注入通用系统规则（所有智能体共享的底线规则）
        if ANCHOR_RULES:
            system_parts.append(ANCHOR_RULES)

        # 4d. ★ 翻译层：把 MVP 运行时配置翻译成 LLM 能读懂的入场简报
        # 位置在 ANCHOR_RULES 之后、RAG 之前——先定规则，再给环境上下文，最后给知识
        try:
            rt_ctx = self._build_runtime_context(
                agent=agent,
                llm_cfg=llm_cfg,
                channel=channel,
                peer_id=peer_id,
                peer_name=peer_name,
                is_manager_peer=_is_manager_peer,
                media_list=media_list,
                msg_facts=payload.get("msg_facts"),
            )
            if rt_ctx:
                system_parts.append(rt_ctx)
                print(f"[Bridge] ★ 翻译层已注入：agent={agent.get('name','?')} channel={channel} model={(llm_cfg or {}).get('model','?')}", flush=True)
        except Exception as _rt_e:
            print(f"[Bridge] 翻译层注入异常: {_rt_e}", flush=True)

        # 5. RAG 检索（如果智能体绑定了知识库且启用了 RAG）
        kb_context = ""
        # 免费版闸门 B：未激活的话，即便是改 DB 方式硬塞了 kb_ids 也不会走检索
        _activated = False
        try:
            _activated = self._check_perm("kb")
        except Exception:
            _activated = False
        if use_kb and not _activated:
            use_kb = False
            print(
                f"[Gate] 免费版跳过 RAG 检索：agent_id={agent_id} "
                f"kb_ids_raw={agent.get('kb_ids') or '[]'}",
                flush=True,
            )
        if use_kb:
            try:
                import json as _json
                # ★ 管理者模式用聚合后的 kb_ids，普通用户用 agent 自己的
                if is_manager_mode and all_kb_ids:
                    kb_ids = all_kb_ids
                else:
                    kb_ids_raw = agent.get("kb_ids") or "[]"
                    kb_ids = _json.loads(kb_ids_raw) if isinstance(kb_ids_raw, str) else (kb_ids_raw or [])
                if kb_ids:
                    results = self._retriever.search(user_input, top_k=3, kb_ids=kb_ids)
                    if results:
                        passages = []
                        for r in results:
                            passages.append(f"[{r.get('source', '未知')}]: {r.get('content', '')[:200]}")
                        kb_context = "\n\n参考资料：\n" + "\n".join(passages)
            except Exception as e:
                print(f"[Bridge] RAG 检索异常: {e}", flush=True)

        if kb_context:
            system_parts.append(kb_context)

        system_prompt = "\n".join(system_parts)

        # 6. 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]

        # 拼接最近 10 轮历史
        history = msg_dao.list_by_conversation(conv_id)
        # 过滤掉刚插入的用户消息（避免重复），取最近的
        history_msgs = [m for m in history if m["id"] != user_msg["id"]]
        recent = history_msgs[-10:] if len(history_msgs) > 10 else history_msgs
        for m in recent:
            messages.append({"role": m["role"], "content": m["content"]})

        # 加入当前用户消息
        if media_list:
            # ★ 多模态：content 用 array 格式（text + image_url blocks）
            # 历史消息永远是纯 str（L5939），只有当前用户消息可能带 media
            user_content = []
            if user_input:
                user_content.append({"type": "text", "text": user_input})
            for item in media_list:
                mtype = (item.get("type") or "image").lower()
                murl = item.get("url", "")
                if mtype == "image" and murl:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": murl},
                    })
                elif mtype == "video" and murl:
                    # video：OpenAI 兼容协议用 video_url block
                    user_content.append({
                        "type": "video_url",
                        "video_url": {"url": murl},
                    })
            messages.append({"role": "user", "content": user_content})
            print(f"[Bridge] ★ 多模态: content array 组装完成 ({len(media_list)} 个媒体块, text={len(user_input)}字)", flush=True)
        else:
            # 纯文本：维持原逻辑
            messages.append({"role": "user", "content": user_input})

        # 7. 调用 LLM（支持 function calling）
        tool_defs = []
        try:
            from storage import agent_app_dao, app_credential_dao
            from app_registry import APPS
            import importlib
            import json as _json
            bindings = agent_app_dao.list_by_agent(agent_id)
            bound_app_ids = {b["app_id"] for b in bindings if b.get("enabled")}
            for app_id in bound_app_ids:
                global_row = app_credential_dao.get(f"app_enabled_{app_id}")
                global_ok = bool(global_row and global_row.get("value") == "1")
                if not global_ok:
                    continue
                app_meta = APPS.get(app_id)
                if not app_meta:
                    continue
                audience = app_meta.get("audience", "both")
                if audience == "manager" and not is_manager_mode:
                    continue
                if audience == "customer" and is_manager_mode:
                    continue
                if len(tool_defs) >= 20:
                    print(f"[Bridge] ⚠️ FC 护栏：tool 数量已达上限 20，跳过 app={app_id}", flush=True)
                    continue
                app_channels = app_meta.get("channels") or []
                if app_channels and not _user_has_any_channel_binding(app_channels):
                    print(f"[Bridge] ⚠️ FC 护栏：用户未绑定 app={app_id} 所需的任何渠道，跳过", flush=True)
                    continue
                tool_def_ref = app_meta.get("tool_def")
                tool_def_json = app_meta.get("tool_def_json")
                if isinstance(tool_def_json, dict):
                    td_chars = len(json.dumps(tool_def_json, ensure_ascii=False))
                    if td_chars > 2000:
                        print(f"[Bridge] ⚠️ FC 护栏：app={app_id} tool_def 过大 ({td_chars} chars)，跳过", flush=True)
                        continue
                    tool_defs.append(tool_def_json)
                elif isinstance(tool_def_json, list):
                    for td in tool_def_json:
                        if len(json.dumps(td, ensure_ascii=False)) > 2000:
                            print(f"[Bridge] ⚠️ FC 护栏：app={app_id} 某个 tool_def 过大，跳过", flush=True)
                            continue
                        tool_defs.append(td)
                elif isinstance(tool_def_ref, str):
                    try:
                        mod_path, fn = tool_def_ref.rsplit(":", 1)
                        mod = importlib.import_module(mod_path)
                        obj = getattr(mod, fn)
                        if isinstance(obj, (list, tuple)):
                            tool_defs.extend(obj)
                        else:
                            tool_defs.append(obj)
                    except Exception as _te:
                        print(f"[Bridge] tool_def 加载失败 app={app_id}: {_te}", flush=True)
            if tool_defs:
                print(f"[Bridge] 注入 {len(tool_defs)} 个 tools: {[t.get('function', {}).get('name', '?') for t in tool_defs]} agent={agent.get('name', '?')}", flush=True)
        except Exception as _e:
            print(f"[Bridge] tool 收集异常: {_e}", flush=True)

        try:
            import time as _time
            provider = LLMProvider.from_config(llm_cfg)
            max_tool_loops = 3 if tool_defs else 0
            _fc_deadline = _time.time() + 60
            _used_tools = set()
            loop = 0
            result = None
            final_text = ""
            while loop <= max_tool_loops:
                if _time.time() > _fc_deadline:
                    print(f"[Bridge] ⚠️ FC 循环超时（60s），强制 break，当前 loop={loop}", flush=True)
                    result = {"error": "AI 处理超时，请稍后重试（或换个更短的问题）"}
                    break
                result = provider.chat(messages, temperature=0.7,
                                       tools=tool_defs if loop == 0 else None)
                if result.get("error"):
                    break
                tcs = result.get("tool_calls") or []
                if not tcs:
                    final_text = (result.get("text") or "").strip()
                    break
                loop += 1
                for tc in tcs:
                    _used_tools.add(tc.get("name", ""))
                assistant_msg = {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                        for tc in tcs
                    ],
                }
                messages.append(assistant_msg)
                for tc in tcs:
                    tool_result = self._dispatch_tool_call(tc, agent_id, is_manager_mode)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc["name"],
                        "content": tool_result,
                    })
                    print(f"[Bridge] tool_call: {tc['name']} → {tool_result[:120]}", flush=True)
                if loop > max_tool_loops:
                    result = {"error": "function calling 达到最大循环次数"}
                    break
            loop = 0

            if result.get("error"):
                friendly_err = result["error"]
                # LLM 调用失败，保存错误消息
                err_msg = f"[错误] {friendly_err}"
                assistant_msg = msg_dao.create(
                    conv_id, "assistant", err_msg,
                    aigc_marked=0, channel=channel,
                    model=llm_cfg.get("model", ""),
                )
                # 【智能记忆】v2：不再每 10 条自动提炼，改为每 24 小时全量整理
                # self._maybe_trigger_memory_refine(agent_id, conv_id, llm_cfg)
                return {
                    "error": friendly_err,
                    "conversation_id": conv_id,
                    "user_message": user_msg,
                    "assistant_message": assistant_msg,
                }

            reply_text = final_text or "（空回复）"

            # AIGC 标识：末尾追加纯中文括号文本「（AI 生成内容）」
            # 微信只支持纯文本，不能带 HTML 图标或彩色标记
            if aigc_enabled and reply_text:
                aigc_suffix = "（AI 生成内容）"
                # 防重复：已经以该后缀结尾就不再加
                if not reply_text.endswith(aigc_suffix):
                    reply_text = reply_text.rstrip() + aigc_suffix

            usage = result.get("usage", {})
            tokens_used = int((usage.get("total_tokens") or 0))
            _source_tag = ""
            if _used_tools:
                _source_tag = "tool:" + ",".join(sorted(_used_tools))

            # 保存 AI 回复
            assistant_msg = msg_dao.create(
                conv_id, "assistant", reply_text,
                tokens=tokens_used,
                aigc_marked=1 if aigc_enabled else 0,
                channel=channel,
                model=llm_cfg.get("model", ""),
                source_tag=_source_tag,
            )

            # 更新会话标题（如果还是空的）
            conv = conv_dao.get(conv_id)
            if conv and not conv.get("title"):
                conv_dao.update_title(conv_id, user_input[:30])

            # 【智能记忆】v2：不再每 10 条自动提炼，改为每 24 小时全量整理
            # self._maybe_trigger_memory_refine(agent_id, conv_id, llm_cfg)

            return {
                "error": "",
                "conversation_id": conv_id,
                "user_message": user_msg,
                "assistant_message": assistant_msg,
                "usage": usage,
            }

        except Exception as e:
            err_msg = f"[异常] {str(e)}"
            assistant_msg = msg_dao.create(
                conv_id, "assistant", err_msg,
                aigc_marked=0, channel=channel,
                model=llm_cfg.get("model", "") if llm_cfg else "",
            )
            # 【智能记忆】v2：不再每 10 条自动提炼，改为每 24 小时全量整理
            # self._maybe_trigger_memory_refine(agent_id, conv_id, llm_cfg)
            return {
                "error": str(e),
                "conversation_id": conv_id,
                "user_message": user_msg,
                "assistant_message": assistant_msg,
            }

    # ---------- 历史对话（全局"历史"Tab + 单智能体历史Modal） ----------
    def _handle_get_all_history(self, payload):
        """全局历史会话列表（对应「历史」Tab左栏）。

        入参过滤：
          agent_id : 仅看某智能体（单智能体卡片历史按钮用）
          channel  : wcf / wecom / oa / feishu / dingtalk 渠道筛选
          keyword  : 标题/用户名模糊搜索
          with_messages : 是否附带最近 10 条消息（空或false则不带，省流量）
          limit    : 最多返回多少条会话（默认 200，上限 5000；前端拉全渠道时应显式放大）
        返回格式对齐旧 MOCK_HISTORY_SESSIONS：
          [{id, title, agent_id, agent_name, agent_avatar, channel, user_name,
            peer_id, message_count, updated_at, messages?}]
        """
        agent_id = payload.get("agent_id") or None
        ch_filter = payload.get("channel") or None
        keyword = (payload.get("keyword") or "").strip() or None
        with_msgs = bool(payload.get("with_messages"))
        # 前端一次拉全渠道、在本地按 tab 过滤，故 limit 不能沿用 200 默认值，
        # 否则后落库的渠道（如钉钉）会被 list_all 的 LIMIT 整段截掉；上限 5000 兜底防止一次拉爆。
        try:
            limit = int(payload.get("limit") or 200)
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(limit, 5000))

        print(f"[History] get_all_history 请求 agent_id={agent_id!r}, channel={ch_filter!r}, limit={limit}", flush=True)

        # 1. 拉会话
        rows = conv_dao.list_all(agent_id=agent_id, channel=ch_filter,
                                 keyword=keyword, limit=limit)
        print(f"[History] 返回 {len(rows)} 条会话: agent_ids={set(r.get('agent_id') for r in rows)}", flush=True)

        # 2. 拼装智能体信息（agent_name/avatar 缓存避免重复查）
        agent_cache: dict = {}
        for r in rows:
            aid = r.get("agent_id")
            if aid and aid not in agent_cache:
                a = agents_dao.get(aid) or {}
                agent_cache[aid] = {
                    "name": a.get("name", ""),
                    "avatar": a.get("avatar", ""),
                }

        # 3. 组装结果
        sessions = []
        for r in rows:
            aid = r.get("agent_id")
            agent_info = agent_cache.get(aid, {})
            s = {
                "id": r["id"],
                "title": r.get("title") or "（无标题）",
                "agent_id": aid,
                "agent_name": agent_info.get("name", "未知智能体"),
                "agent_avatar": agent_info.get("avatar", ""),
                "channel": r.get("channel", "wcf"),
                "peer_id": r.get("peer_id", ""),
                "user_name": r.get("peer_name") or (r.get("peer_id") or "匿名用户"),
                "peer_type": r.get("peer_type", "friend"),
                "message_count": int(r.get("message_count", 0)),
                "created_at_ts": r.get("created_at", 0),
                "updated_at_ts": r.get("updated_at", 0),
                # 兼容字符串日期格式，前端可直接显示
                "created_at": self._ts_iso(r.get("created_at", 0)),
                "updated_at": self._ts_iso(r.get("updated_at", 0)),
            }
            if with_msgs:
                msgs_raw = msg_dao.list_by_conversation(r["id"])
                s["messages"] = self._fmt_history_messages(msgs_raw)
            sessions.append(s)
        return {"sessions": sessions,
                "filters": {"agent_id": agent_id, "channel": ch_filter,
                            "keyword": keyword, "with_messages": with_msgs}}

    def _handle_get_history_session(self, payload):
        """返回单个会话的完整消息流（前端点击左侧会话后加载右侧消息）。

        入参：conversation_id 或 session_id（二选一）
        返回：{session, messages} 结构，messages 对齐前端消息气泡格式。
        """
        cid = (payload.get("conversation_id") or
               payload.get("session_id") or "")
        if not cid:
            print("[History][get_history_session] 缺少 conversation_id/session_id，前端可能传空", flush=True)
            return {"session": None, "messages": [], "ok": False, "error": "缺少 conversation_id"}
        conv = conv_dao.get(cid)
        if not conv:
            return {"session": None, "messages": [], "ok": False, "error": "会话不存在"}
        msgs_raw = msg_dao.list_by_conversation(cid)
        messages = self._fmt_history_messages(msgs_raw)
        # 同样附带智能体名称等信息，方便右侧头部渲染
        agent = agents_dao.get(conv["agent_id"]) or {}
        session = {
            "id": conv["id"],
            "title": conv.get("title") or "（无标题）",
            "agent_id": conv["agent_id"],
            "agent_name": agent.get("name", "未知智能体"),
            "agent_avatar": agent.get("avatar", ""),
            "channel": conv.get("channel", "wcf"),
            "peer_id": conv.get("peer_id", ""),
            "user_name": conv.get("peer_name") or "匿名用户",
            "peer_type": conv.get("peer_type", "friend"),
            "message_count": len(messages),
            "updated_at": self._ts_iso(conv.get("updated_at", 0)),
        }
        return {"session": session, "messages": messages}

    # ---- 历史对话内部辅助 ----
    @staticmethod
    def _ts_iso(ts: int | None) -> str:
        """Unix 时间戳 → ISO 字符串（本地时区），前端可直接渲染。"""
        if not ts:
            return ""
        try:
            return datetime.datetime.fromtimestamp(int(ts)).isoformat()
        except (ValueError, OSError):
            return ""

    @staticmethod
    def _fmt_time(ts: int | None) -> str:
        """Unix 时间戳 → HH:MM。"""
        if not ts:
            return ""
        try:
            return datetime.datetime.fromtimestamp(int(ts)).strftime("%H:%M")
        except (ValueError, OSError):
            return ""

    def _fmt_history_messages(self, msgs_raw):
        """SQLite chat_message 行 → 前端消息气泡格式（按 created_at 升序）。"""
        out = []
        for m in msgs_raw:
            out.append({
                "id": m["id"],
                "role": m["role"],
                "content": m.get("content", ""),
                "tokens": int(m.get("tokens", 0)),
                "aigc_marked": bool(m.get("aigc_marked", 0)),
                "channel": m.get("channel", "wcf"),
                "model": m.get("model", ""),
                "time": self._fmt_time(m.get("created_at", 0)),
                "created_at_ts": m.get("created_at", 0),
            })
        # ★ 保证时间正序：SQLite 返回依赖 rowid 不一定严格按时间戳
        out.sort(key=lambda x: int(x.get("created_at_ts", 0) or 0))
        return out
    # ---------- 导出单个联系人的全部对话为 Markdown（两段式：pick 路径已由 pick_history_export_path 完成） ----------
    def _handle_export_history_contact(self, payload):
        """（第 2 段）写入：把某联系人的全部对话写成 Markdown，存到前端 pick 好的路径里。

        对应 KB 导出的 _handle_export_kb（第 1 段是 pick_export_path）。
        第 1 段的 pick_history_export_path 已经把 QFileDialog 对话框、cancel、fallback 都处理完了，
        所以本函数只负责：
          1) 按 agent_id + channel + peer_id 拉该联系人的所有 conversation
          2) 逐段拉消息，按时间正序拼 Markdown
          3) 直接写到 payload.save_path（用户已经 pick 过并确认的路径）
          4) 返回结果

        入参 payload：
          agent_id  (str): 智能体 ID（必填）
          peer_id   (str): 联系人/群的 peer_id（必填）
          channel   (str): 渠道 'wcf' / 'wecom' / 'oa' / 'feishu' / 'dingtalk'，默认 'wcf'
          peer_name (str): 联系人/群显示名，用于 md 标题，默认 peer_id
          agent_name(str): 智能体显示名，用于 md 标题，默认 '智能体'
          save_path (str): 完整保存路径（**必填**，由 pick_history_export_path 返回）
        返回：
          {saved: True, file_path, size_bytes, session_count, total_messages, peer_name, agent_name}
          {saved: False, reason: 'no_save_path' | 'no_contact' | 'write_error', detail?}
        """

        agent_id = payload.get("agent_id") or ""
        peer_id = payload.get("peer_id") or ""
        channel = payload.get("channel") or "wcf"
        peer_name = (payload.get("peer_name") or "").strip() or peer_id or "联系人"
        agent_name = (payload.get("agent_name") or "").strip() or "智能体"
        save_path = payload.get("save_path") or ""

        if not save_path:
            return {"saved": False, "reason": "no_save_path",
                    "detail": "缺少 save_path，先调用 pick_history_export_path"}
        if not agent_id or not peer_id:
            return {"saved": False, "reason": "no_contact",
                    "detail": "缺少 agent_id 或 peer_id"}

        # 1) 该智能体+渠道下所有 conversation（limit 放 10000 兜底）
        all_convs = conv_dao.list_all(agent_id=agent_id, channel=channel, limit=10000)
        convs = [c for c in all_convs if str(c.get("peer_id") or "") == str(peer_id)]
        convs.sort(key=lambda c: int(c.get("created_at", 0) or 0))

        channel_label = _CHANNEL_LABELS.get(channel, channel)

        # 2) 拼 Markdown
        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_messages = 0
        sessions_block = []
        for idx, conv in enumerate(convs, 1):
            msgs_raw = msg_dao.list_by_conversation(conv["id"]) or []
            msgs_fmt = self._fmt_history_messages(msgs_raw)
            msgs_fmt.sort(key=lambda m: int(m.get("created_at_ts", 0) or 0))
            total_messages += len(msgs_fmt)
            title_line = conv.get("title") or (peer_name + " 的对话")
            first_ts = msgs_fmt[0].get("time", "") if msgs_fmt else ""
            last_ts = msgs_fmt[-1].get("time", "") if msgs_fmt else ""
            period = ""
            if first_ts and last_ts:
                period = f"  ({first_ts} — {last_ts})"
            elif conv.get("updated_at"):
                period = f"  (最近活跃 {self._ts_iso(conv.get('updated_at',0))})"
            sessions_block.append(
                f"\n\n## 会话 {idx}：{title_line}{period}\n\n"
                f"> 会话 ID：{conv.get('id','')}\n"
                f"> 消息数：{len(msgs_fmt)} 条\n"
                f"> 创建时间：{self._ts_iso(conv.get('created_at',0)) or '—'}\n"
                f"> 最近活跃：{self._ts_iso(conv.get('updated_at',0)) or '—'}\n"
            )
            if not msgs_fmt:
                sessions_block.append("\n_（无消息）_\n")
                continue
            for m in msgs_fmt:
                role_label = "用户" if m.get("role") == "user" else agent_name
                aigc_mark = "  `AIGC`" if bool(m.get("aigc_marked")) else ""
                tm = m.get("time") or ""
                head = f"### {role_label}  {tm}{aigc_mark}\n\n"
                content = (m.get("content") or "").replace("\r", "").strip()
                if not content:
                    continue
                sessions_block.append(head + content + "\n")

        if not convs:
            sessions_block.append("\n\n> ℹ️ 尚未找到该联系人在本智能体下的对话记录（可能数据还未同步，尝试右上角「刷新」后再导出）。\n")

        header = (
            f"# {peer_name} · 对话导出\n\n"
            f"> 来源：阿维达AI · 智能体「{agent_name}」\n"
            f"> 联系人/群：{peer_name}  渠道：{channel_label}\n"
            f"> 导出时间：{now_iso}\n"
            f"> 会话数：{len(convs)} 段  |  总消息数：{total_messages} 条\n"
        )
        md_text = header + "".join(sessions_block) + "\n"

        # 3) 写到 save_path（第 1 段 pick 好的路径）
        p = Path(save_path)
        if not p.suffix:
            p = p.with_suffix(".md")
            save_path = str(p)
        try:
            os.makedirs(str(p.parent or "."), exist_ok=True)
            p.write_text(md_text, encoding="utf-8")
            size_bytes = p.stat().st_size
        except OSError as e:
            return {"saved": False, "reason": "write_error", "detail": str(e)}
        print(f"[Bridge][export_history_contact] 已写入 {save_path} ({size_bytes}B) "
              f"sessions={len(convs)} msgs={total_messages}", flush=True)
        return {
            "saved": True,
            "file_path": save_path,
            "size_bytes": size_bytes,
            "session_count": len(convs),
            "total_messages": total_messages,
            "peer_name": peer_name,
            "agent_name": agent_name,
        }

    def _handle_prepare_feedback_package(self, payload):
        """打包 zip（日志 + 系统信息 + 用户表单 + 截图），返回 zip 路径 + mailto URL。"""
        import zipfile
        import io
        import platform
        import base64
        from pathlib import Path
        from datetime import datetime

        APP_VERSION = "1.0.0"
        FEEDBACK_EMAIL = "14584407@qq.com"

        try:
            from logger import get_log_dir
            log_dir = Path(get_log_dir())
        except Exception:
            log_dir = Path.home() / ".appdata" / "SCAI" / "logs"

        system_info = {
            "app_version": APP_VERSION,
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "feedback_time": datetime.now().isoformat(),
        }

        channels_status = {}
        try:
            channels_status["wecom"] = bool(self.wecom_client and self.wecom_client.connected)
        except Exception:
            pass
        try:
            channels_status["feishu"] = bool(self.feishu_client and self.feishu_client.connected)
        except Exception:
            pass
        try:
            channels_status["dingtalk"] = bool(self.dingtalk_client and self.dingtalk_client.connected)
        except Exception:
            pass
        try:
            channels_status["wcf"] = bool(self.wcf_client and self.wcf_client.connected)
        except Exception:
            pass
        try:
            channels_status["oa"] = bool(self.oa_client and self.oa_client.connected)
        except Exception:
            pass

        feedback_data = {
            "type": payload.get("type", "other"),
            "subject": payload.get("subject", "(无主题)"),
            "description": payload.get("description", ""),
            "contact": payload.get("contact", ""),
            "channels": channels_status,
            "screenshots_count": len(payload.get("screenshots") or []),
        }

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path.home() / "Desktop"
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / f"SCAI_feedback_{timestamp}.zip"

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:

                zf.writestr("system_info.json", json.dumps(system_info, ensure_ascii=False, indent=2))

                zf.writestr("feedback.json", json.dumps(feedback_data, ensure_ascii=False, indent=2))

                if log_dir.exists():
                    for log_file in sorted(log_dir.glob("scai_*.log")):
                        try:
                            zf.write(log_file, f"logs/{log_file.name}")
                        except Exception:
                            pass

                screenshots = payload.get("screenshots") or []
                for idx, shot in enumerate(screenshots):
                    try:
                        name = shot.get("name", f"screenshot_{idx}.png")
                        data_url = shot.get("data", "")
                        if data_url.startswith("data:"):
                            b64 = data_url.split(",", 1)[1]
                        else:
                            b64 = data_url
                        img_bytes = base64.b64decode(b64)
                        zf.writestr(f"screenshots/{idx}_{name}", img_bytes)
                    except Exception:
                        pass
        except Exception as e:
            raise RuntimeError(f"打包日志失败: {e}")

        try:
            subject_line = f"[SCAI反馈] {feedback_data['subject']}"
            body_lines = [
                f"问题类型：{payload.get('type', 'other')}",
                f"主题：{feedback_data['subject']}",
                f"联系方式：{feedback_data['contact'] or '未填写'}",
                f"截图：{feedback_data['screenshots_count']} 张（在 zip 里）",
                "",
                "--- 详细描述 ---",
                feedback_data["description"],
                "",
                "--- 系统信息 ---",
                f"App: {APP_VERSION}  OS: {platform.system()} {platform.version()[:30]}",
                f"渠道: {channels_status}",
                "",
                f"📎 诊断日志已打包在：{zip_path}",
                "请将此 zip 文件作为附件添加到邮件中发送。",
            ]
            body_text = "\r\n".join(body_lines)

            import urllib.parse
            mailto_url = (
                f"mailto:{FEEDBACK_EMAIL}?subject={urllib.parse.quote(subject_line)}"
                f"&body={urllib.parse.quote(body_text)}"
            )
        except Exception:
            mailto_url = f"mailto:{FEEDBACK_EMAIL}"

        print(f"[Bridge][prepare_feedback_package] zip={zip_path}", flush=True)
        return {
            "ok": True,
            "zip_path": str(zip_path),
            "mailto_url": mailto_url,
        }

    # ---------- 导出知识库（OKF / LLM Wiki 格式 zip） ----------
    def _handle_export_kb(self, payload):
        import zipfile, os, re
        from tempfile import TemporaryDirectory

        kb_id = payload.get("id")
        if not kb_id:
            raise ValueError("缺少知识库 ID")

        kb = kb_dao.get(kb_id)
        if not kb:
            raise ValueError("知识库不存在")

        docs = docs_dao.list_by_kb(kb_id)
        if not docs:
            raise ValueError("知识库还没有文档，无法导出")

        # 1. 复用图谱节点/边
        graph = self._handle_build_kb_graph({"id": kb_id})
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        # 2. 连边数 + 邻接表
        node_deg = {}
        for e in edges:
            node_deg[e["source"]] = node_deg.get(e["source"], 0) + 1
            node_deg[e["target"]] = node_deg.get(e["target"], 0) + 1

        neighbors = {n["id"]: [] for n in nodes}
        id_to_label = {n["id"]: n.get("label", n["id"]) for n in nodes}
        for e in edges:
            s, t = e["source"], e["target"]
            if s in neighbors and t in id_to_label and id_to_label[t] not in neighbors[s]:
                neighbors[s].append(id_to_label[t])
            if t in neighbors and s in id_to_label and id_to_label[s] not in neighbors[t]:
                neighbors[t].append(id_to_label[s])

        # 3. 节点分类（先过 stopwords 过滤掉高频无意义词）
        STOPWORDS = {
            "对方", "关键词", "拳详解", "round", "然后", "其实", "自己", "这个", "那个",
            "时候", "可能", "一般", "一下", "现在", "就是", "什么", "怎么", "为什么",
            "所以", "因为", "如果", "但是", "而且", "或者", "以及", "还有", "可以",
            "需要", "应该", "例如", "比如", "内容", "文档", "信息", "步骤", "要点",
            "说明", "情况", "问题", "方法", "方式", "方面", "其中", "之后", "之前",
            "sop", "step", "note", "tips", "tip", "example", "section", "chapter",
        }
        cat_nodes = {"concept": [], "entity": [], "source-summary": []}
        for n in nodes:
            cat = n.get("category", "")
            label_clean = (n.get("label", "") or "").strip()
            # 过滤规则: stopwords / 纯数字 / <2字符 / 全标点
            normed = label_clean.lower()
            if normed in STOPWORDS:
                continue
            if len(label_clean) < 2:
                continue
            if re.fullmatch(r"[\d\W_]+", label_clean or ""):
                continue
            if cat == "keyword":
                cat_nodes["concept"].append(n)
            elif cat == "entity":
                cat_nodes["entity"].append(n)
            elif cat in ("chapter", "section"):
                cat_nodes["source-summary"].append(n)

        # 4. 工具函数
        def _slug(text, maxlen=40):
            s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text or "", flags=re.UNICODE).strip("-")
            s = s.lower().replace(" ", "-")
            return (s[:maxlen] or "page")

        def _safe(text):
            return (text or "").replace("\n", " ").replace("\r", " ").strip()

        def _fm(node_type, title, sources_list):
            d = datetime.datetime.now().strftime("%Y-%m-%d")
            src_str = "\n".join("  - " + s for s in sources_list) if sources_list else "  - (synthetic)"
            return (
                "---\n"
                "type: " + node_type + "\n"
                "title: " + _safe(title) + "\n"
                "sources:\n" + src_str + "\n"
                "tags: " + node_type + "\n"
                "created: " + d + "\n"
                "updated: " + d + "\n"
                "status: draft\n"
                "---\n\n"
            )

        # 5. 先把 kb 下所有 chunk 读一次，用来给 wiki 页补「来源原文摘录」正文
        chunks_rows = docs_dao.list_chunks_by_kb(kb_id) or []
        chunk_texts = []
        for cr in chunks_rows:
            cr_d = cr if isinstance(cr, dict) else getattr(cr, '_asdict', lambda: {})()
            content = str(cr_d.get("content") or "")
            if len(content) < 8:
                continue
            # 按句拆分（中文句号/问号/感叹号/换行），得到句子池
            sents = re.split(r"(?<=[。？！\n])\s*", content)
            for st in sents:
                st = st.strip()
                if 10 <= len(st) <= 220:
                    chunk_texts.append(st)

        doc_ids_to_names = {str(d.get("id") or ""): str(d.get("name") or "文档") for d in docs}

        def _extract_quote(label, top=2, extra_keywords=None):
            """从 chunk 句子池中挑 top 条包含 label（或任一 extra_keywords）的句子，作为正文摘录。"""
            if not chunk_texts or not label:
                return ""
            keys = [label]
            if extra_keywords:
                keys.extend([k for k in extra_keywords if k])
            # 去重小写
            norm = list(dict.fromkeys(k.lower() for k in keys if k and len(k) >= 1))
            hits = []
            for s in chunk_texts:
                s_low = s.lower()
                score = 0
                for k in norm:
                    if k in s_low:
                        # 长 key 匹配优先
                        score += 10 + len(k)
                if score > 0:
                    hits.append((score, s))
            hits.sort(key=lambda x: -x[0])
            picked = []
            seen = set()
            for _, s in hits:
                if s in seen:
                    continue
                seen.add(s)
                picked.append(s)
                if len(picked) >= top:
                    break
            return "\n\n".join("> " + s for s in picked) if picked else ""

        # 6. 组装 wiki 页面
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        wiki_pages = {}

        for n in cat_nodes["concept"]:
            nid, label = n["id"], n["label"]
            slug = _slug(label)
            sources = ["raw/" + today + "-" + _slug(d["name"], 30) + ".md" for d in docs]
            links = neighbors.get(nid, [])[:8]
            hint = (n.get("hint", "") or "").strip()
            quote = _extract_quote(label, top=2, extra_keywords=links)
            body = "# " + label + "\n\n"
            # 摘要段：有 hint 用 hint；否则用 neighbors 生成一句话描述
            if hint and len(hint) >= 4:
                body += hint + "\n\n"
            else:
                desc_parts = []
                if links:
                    desc_parts.append("与「" + "、".join(links[:4]) + "」等概念相关")
                if len(desc_parts) == 0:
                    desc_parts.append("从知识库文档中抽取的核心概念")
                body += label + "是本知识库中的" + ("关键字段" if n.get("category") == "keyword" else "知识点") + \
                        "，" + "，".join(desc_parts) + "。\n\n"
            if quote:
                body += "## 来源原文摘录\n\n" + quote + "\n\n"
            if links:
                body += "## 相关概念\n\n" + ", ".join(
                    "[[" + _slug(l) + "|" + l + "]]" for l in links
                ) + "\n"
            wiki_pages["wiki/concepts/" + slug + ".md"] = _fm("concept", label, sources) + body

        for n in cat_nodes["entity"]:
            nid, label = n["id"], n["label"]
            slug = _slug(label)
            links = neighbors.get(nid, [])[:5]
            quote = _extract_quote(label, top=2, extra_keywords=links)
            hint = (n.get("hint", "") or "").strip()
            body = "# " + label + "\n\n"
            if hint and len(hint) >= 4:
                body += hint + "\n\n"
            else:
                body += label + "是本知识库中抽取到的命名实体"
                if links:
                    body += "，与「" + "、".join(links[:3]) + "」等节点关联"
                body += "。\n\n"
            if quote:
                body += "## 来源原文摘录\n\n" + quote + "\n\n"
            if links:
                body += "## 关联\n\n" + ", ".join(
                    "[[" + _slug(l) + "|" + l + "]]" for l in links
                ) + "\n"
            wiki_pages["wiki/entities/" + slug + ".md"] = _fm("entity", label, []) + body

        for n in cat_nodes["source-summary"]:
            nid, label = n["id"], n["label"]
            slug = _slug(label)
            links = neighbors.get(nid, [])[:6]
            quote = _extract_quote(label, top=2, extra_keywords=links)
            hint = (n.get("hint", "") or "").strip()
            body = "# " + label + "\n\n"
            if hint and len(hint) >= 4:
                body += hint + "\n\n"
            else:
                body += label + "是本知识库里的一个" + ("章节" if n.get("category") in ("chapter", "section") else "文档/摘要") + "节点"
                if links:
                    body += "，涵盖「" + "、".join(links[:4]) + "」等内容"
                body += "。\n\n"
            if quote:
                body += "## 来源原文摘录\n\n" + quote + "\n\n"
            if links:
                body += "## 涉及\n\n" + ", ".join(
                    "[[" + _slug(l) + "|" + l + "]]" for l in links
                ) + "\n"
            wiki_pages["wiki/source-summary/" + slug + ".md"] = (
                _fm("source-summary", label, []) + body
            )

        for n in nodes:
            if n.get("category") == "chapter":
                dl = n["label"]
                slug = _slug(dl, 30)
                links = neighbors.get(n["id"], [])[:6]
                quote = _extract_quote(dl, top=2, extra_keywords=links)
                hint = (n.get("hint", "") or "").strip()
                body = "# " + dl + "\n\n"
                if hint and len(hint) >= 4:
                    body += hint + "\n\n"
                else:
                    body += dl + "章节节选自源文档，提炼了该段的关键信息"
                    if links:
                        body += "，涉及「" + "、".join(links[:4]) + "」"
                    body += "。\n\n"
                if quote:
                    body += "## 来源原文摘录\n\n" + quote + "\n\n"
                if links:
                    body += "## 涵盖\n\n" + ", ".join(
                        "[[" + _slug(l) + "|" + l + "]]" for l in links
                    ) + "\n"
                wiki_pages["wiki/source-summary/" + slug + ".md"] = _fm(
                    "source-summary", dl, ["raw/" + today + "-" + slug + ".md"]
                ) + body

        # index.md（补 YAML frontmatter，符合 LLM Wiki schema 对 index 页的要求）
        kb_name = kb.get("name", "")
        index_fm = (
            "---\n"
            "type: index\n"
            "title: " + _safe(kb_name + " · 知识目录") + "\n"
            "sources:\n  - (compiled)\n"
            "tags: index, " + _safe(kb_name) + "\n"
            "created: " + today + "\n"
            "updated: " + today + "\n"
            "status: compiled\n"
            "---\n\n"
        )
        idx = [
            index_fm,
            "# 知识目录\n\n",
            "> 知识库：" + kb_name + "\n",
            "> 导出时间：" + datetime.datetime.now().isoformat() + "\n",
            "> 文档数：" + str(len(docs)) + " | 节点：" + str(len(nodes)) + " | 连边：" + str(len(edges)) + "\n\n",
        ]
        for cat_label, cat_key, folder in [
            ("概念 concepts", "concept", "concepts"),
            ("命名实体 entities", "entity", "entities"),
            ("章节 / 文档", "source-summary", "source-summary"),
        ]:
            idx.append("## " + cat_label + "\n\n")
            pool = cat_nodes.get(cat_key, [])
            if not pool:
                idx.append("_（自动编译，暂无）_\n\n")
                continue
            for n in sorted(pool, key=lambda x: -node_deg.get(x["id"], 0))[:30]:
                slug = _slug(n["label"])
                deg = node_deg.get(n["id"], 0)
                idx.append(
                    "- [[" + folder + "/" + slug + "|" + n["label"] + "]] （" + str(deg) + " 条关联）\n"
                )
            idx.append("\n")
        wiki_pages["wiki/index.md"] = "".join(idx)

        wiki_pages["wiki/log.md"] = (
            "# 操作日志\n\n"
            "- " + today + " Ingest：" + str(len(docs)) + " 文档 → " +
            str(len(nodes)) + " 节点 / " + str(len(edges)) + " 连边\n"
        )

        wiki_pages["schema.md"] = (
            "# Knowledge Base Schema\n\n"
            "导出知识库的目录结构与格式规范，对齐 Karpathy LLM Wiki / OKF v0.1 / Obsidian。\n"
        )

        # 6. 组装 zip（优先按用户选的 save_path 写，不指定则 fallback 到桌面）
        save_path = payload.get("save_path") if isinstance(payload, dict) else None
        if save_path:
            zip_path = str(save_path)
            os.makedirs(os.path.dirname(zip_path) or ".", exist_ok=True)
        else:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            kb_name_clean = _slug(kb.get("name", "knowledge-base"), 40)
            fname = (
                kb_name_clean + "_KB_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"
            )
            zip_path = os.path.join(desktop, fname)

        with TemporaryDirectory() as tmpdir:
            raw_dir = os.path.join(tmpdir, "raw")
            os.makedirs(raw_dir, exist_ok=True)
            for d in docs:
                dn = d.get("name", "unknown")
                slug_dn = _slug(dn, 30)
                raw_path = os.path.join(raw_dir, today + "-" + slug_dn + ".md")
                content = "# " + dn + "\n\n"
                if d.get("description"):
                    content += d["description"] + "\n\n"
                fp = d.get("file_path") or ""
                if fp and os.path.isfile(fp):
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as rf:
                            content += rf.read()[:50000]
                    except Exception:
                        content += "_原文读取失败：" + fp + "_\n"
                else:
                    content += "_原文已不在磁盘上。原始路径：" + fp + "_\n"
                with open(raw_path, "w", encoding="utf-8") as wf:
                    wf.write(content)

            for rel, content in wiki_pages.items():
                full = os.path.join(tmpdir, rel)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as wf:
                    wf.write(content)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(tmpdir):
                    for fn in files:
                        full_path = os.path.join(root, fn)
                        arcname = os.path.relpath(full_path, tmpdir)
                        zf.write(full_path, arcname)

        print(
            "[Bridge][export_kb] " + kb.get("name", "") + " -> " + zip_path,
            flush=True,
        )
        return {
            "path": zip_path,
            "kb_name": kb.get("name", ""),
            "docs": len(docs),
            "nodes": len(nodes),
            "edges": len(edges),
        }

    # ---------- 应用市场 ----------
    def _handle_list_apps(self, payload):
        import importlib, app_registry as _ar
        importlib.reload(_ar)
        from storage import app_credential_dao
        apps = []
        for app_meta in _ar.list_apps():
            app_id = app_meta['id']
            # 全局开关
            row = app_credential_dao.get(f'app_enabled_{app_id}')
            enabled = row and row.get('value') == '1'
            # 凭据是否已配置
            cred_fields = (app_meta.get('credential_schema') or {}).get('fields') or []
            configured = False
            for f in cred_fields:
                if app_credential_dao.get(f['key']):
                    configured = True
                    break
            apps.append({**app_meta, 'enabled': enabled, 'configured': configured})
        return {'ok': True, 'apps': apps}

    def _handle_toggle_agent_app(self, payload):
        import importlib
        from app.app_registry import app_registry as _ar
        importlib.reload(_ar)
        from storage import app_credential_dao, agent_app_dao
        agent_id = payload.get('agent_id')
        app_id = payload.get('app_id')
        enabled = bool(payload.get('enabled', True))
        if not app_id:
            raise ValueError('缺少 app_id')
        if app_id not in _ar.APPS:
            raise ValueError(f'未知应用: {app_id}')
        # agent_id == '__global__' 表示操作全局开关
        if not agent_id or agent_id == '__global__':
            app_credential_dao.save(f'app_enabled_{app_id}', '1' if enabled else '0')
            return {'ok': True, 'scope': 'global', 'app_id': app_id, 'enabled': enabled}
        agent_app_dao.toggle(agent_id, app_id, enabled)
        return {'ok': True, 'scope': 'agent', 'agent_id': agent_id, 'app_id': app_id, 'enabled': enabled}

    def _handle_save_app_credentials(self, payload):
        from storage import app_credential_dao
        app_id = payload.get('app_id')
        credentials = payload.get('credentials') or {}
        if not app_id:
            raise ValueError('缺少 app_id')
        if app_id not in APPS:
            raise ValueError(f'未知应用: {app_id}')
        saved = {}
        for key, value in credentials.items():
            app_credential_dao.save(key, value or '')
            saved[key] = True
        return {'ok': True, 'app_id': app_id, 'saved': list(saved.keys())}

    def _handle_get_app_credentials(self, payload):
        from storage import app_credential_dao
        app_id = payload.get('app_id')
        if not app_id:
            raise ValueError('缺少 app_id')
        app_meta = get_app(app_id)
        if not app_meta:
            raise ValueError(f'未知应用: {app_id}')
        allowed_keys = {f['key'] for f in app_meta.get('credential_schema', {}).get('fields', [])}
        result = {}
        for cred in app_credential_dao.list_all():
            if cred['credential_key'] not in allowed_keys:
                continue
            result[cred['credential_key']] = cred.get('value', '')
        return {'ok': True, 'app_id': app_id, 'credentials': result}

    def _handle_run_app_test(self, payload):
        import importlib
        app_id = payload.get('app_id')
        if not app_id:
            raise ValueError('缺少 app_id')
        app_meta = get_app(app_id)
        if not app_meta:
            raise ValueError(f'未知应用: {app_id}')
        test_fn_path = app_meta.get('test_fn')
        if not test_fn_path:
            return {'ok': True, 'app_id': app_id, 'tested': False, 'message': '此应用暂无连通性测试'}
        try:
            mod_path, fn_name = test_fn_path.rsplit(':', 1)
            mod = importlib.import_module(mod_path)
            test_fn = getattr(mod, fn_name)
            result = test_fn()
            return {'ok': True, 'app_id': app_id, 'result': result}
        except ImportError as e:
            return {'ok': False, 'app_id': app_id, 'error': f'测试模块未就绪: {e}'}
        except Exception as e:
            return {'ok': False, 'app_id': app_id, 'error': str(e)}

    def _handle_run_app_once(self, payload):
        import importlib
        app_id = payload.get('app_id')
        if not app_id:
            raise ValueError('缺少 app_id')
        app_meta = get_app(app_id)
        if not app_meta:
            raise ValueError(f'未知应用: {app_id}')
        runner_fn_path = app_meta.get('runner_fn')
        if not runner_fn_path:
            return {'ok': False, 'app_id': app_id, 'error': '此应用暂无 runner'}
        try:
            mod_path, fn_name = runner_fn_path.rsplit(':', 1)
            mod = importlib.import_module(mod_path)
            runner_fn = getattr(mod, fn_name)
            context = payload.get('context') or {}
            keywords = payload.get('keywords') or context.get('keywords') or []
            result = runner_fn(context)
            items = []
            if isinstance(result, dict):
                items = result.get('items') or []
            brief = []
            for it in items:
                brief.append({
                    'title': it.get('title', ''),
                    'platform': it.get('platform', ''),
                    'price': it.get('price'),
                    'commission_rate': it.get('commission_rate'),
                    'score': it.get('score'),
                })
            return {
                'ok': True,
                'app_id': app_id,
                'count': len(items),
                'total_searched': result.get('total_searched', 0) if isinstance(result, dict) else 0,
                'note': result.get('note', '') if isinstance(result, dict) else '',
                'items': brief,
            }
        except ImportError as e:
            return {'ok': False, 'app_id': app_id, 'error': f'runner 模块未就绪: {e}'}
        except Exception as e:
            import traceback
            return {'ok': False, 'app_id': app_id, 'error': f'{type(e).__name__}: {e}'}

    def _handle_get_mcp_config(self, payload):
        from mcp_manager import get_mcp_manager
        return get_mcp_manager().get_config()

    def _handle_set_mcp_config(self, payload):
        from mcp_manager import get_mcp_manager
        mgr = get_mcp_manager()
        enabled = bool(payload.get('enabled', False))
        mgr.set_enabled(enabled)
        if enabled:
            mgr.get_or_generate_token()
            self._ensure_mcp_thread_running()
        else:
            self._stop_mcp_thread()
        return mgr.get_config()

    def _ensure_mcp_thread_running(self):
        """启动 MCP server 子进程（stdio 模式，供外部 Trae 连接）。"""
        import os as _os
        import subprocess
        from mcp_manager import get_mcp_manager
        mgr = get_mcp_manager()
        if not mgr.is_enabled():
            return
        # frozen（PyInstaller）模式下无独立 python 解释器可用，禁用 MCP server
        if getattr(sys, "frozen", False):
            print("[MCP] frozen 模式禁用 MCP server（开发版功能）", flush=True)
            self._mcp_process = None
            return
        token = mgr.get_or_generate_token()
        # 已启动则跳过
        if getattr(self, "_mcp_process", None) is not None:
            return
        env = _os.environ.copy()
        env["MCP_TOKEN"] = token
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "app.mcp_server"],
                env=env,
                cwd=str(Path(__file__).parent.parent),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._mcp_process = proc
            print(f"[MCP] server 已启动 PID={proc.pid}, token={token[:8]}...", flush=True)
        except Exception as e:
            print(f"[MCP] 启动失败: {e}", flush=True)
            self._mcp_process = None

    def _stop_mcp_thread(self):
        if getattr(self, "_mcp_process", None) is not None:
            try:
                self._mcp_process.terminate()
                self._mcp_process.wait(timeout=2)
            except Exception:
                try:
                    self._mcp_process.kill()
                except Exception:
                    pass
            self._mcp_process = None
            print("[MCP] server 已停止", flush=True)

    def _handle_get_agent_apps(self, payload):
        import json as _json
        from storage import agent_app_dao, app_credential_dao
        from app_registry import APPS
        agent_id = payload.get('agent_id')
        if not agent_id:
            raise ValueError('缺少 agent_id')
        bindings = {b['app_id']: b for b in agent_app_dao.list_by_agent(agent_id)}
        result = []
        for app_id, app_meta in APPS.items():
            # 全局开关：必须全局启用才对智能体可见
            global_row = app_credential_dao.get(f'app_enabled_{app_id}')
            global_enabled = bool(global_row and global_row.get('value') == '1')
            if not global_enabled:
                continue
            b = bindings.get(app_id)
            agent_enabled = bool(b.get('enabled', 0)) if b else False
            config_json = b.get('config_json') or '{}' if b else '{}'
            try:
                runtime_config = _json.loads(config_json)
            except Exception:
                runtime_config = {}
            result.append({
                'app_id': app_id,
                'name': app_meta['name'],
                'icon': app_meta.get('icon', '📦'),
                'description': app_meta.get('description', ''),
                'version': app_meta.get('version', '1.0.0'),
                'enabled': agent_enabled,
                'credential_schema': app_meta.get('credential_schema', {}),
                'runtime_schema': app_meta.get('runtime_schema', {}),
                'runtime_config': runtime_config,
            })
        return {'ok': True, 'agent_id': agent_id, 'apps': result}

    def _handle_save_agent_app_config(self, payload):
        import json as _json
        from storage import agent_app_dao
        agent_id = payload.get('agent_id')
        app_id = payload.get('app_id')
        config = payload.get('config') or {}
        if not agent_id or not app_id:
            raise ValueError('缺少 agent_id 或 app_id')
        config_json = _json.dumps(config, ensure_ascii=False)
        agent_app_dao.upsert(agent_id, app_id, enabled=True, config_json=config_json)
        return {'ok': True, 'agent_id': agent_id, 'app_id': app_id}

