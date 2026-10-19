"""消息处理流水线（多渠道通用）：

任意渠道收到一条消息
  -> BindingRouter 查有没有绑定的智能体（没绑就丢）
  -> ConversationDAO.get_or_create_by_peer 找/建会话
  -> Bridge._handle_send_message 调 LLM 拿回复 + 入库
  -> ChannelClient.send_reply 发回对应渠道（未连接就跳过，日志留痕）

风控策略：仅微信（wcf）走完整风控（防封号），其他渠道直接发送。

整个流程在后台线程池里串行化跑（单 worker，顺序不重要但不要并发改同一会话）。
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

from storage.dao import (
    AgentsDAO, ChannelsDAO, ConversationDAO, ChatMessageDAO, LLMConfigDAO,
    RiskConfigDAO,
)
from storage.db import get_conn, now_ts

from .base import ChannelClient, ChannelMessage
from .binding_router import BindingRouter
from .risk_engine import RiskEngine


@dataclass
class PipelineResult:
    handled: bool
    reason: str = ""
    conversation_id: str = ""
    assistant_text: str = ""
    sent_to_wcf: bool = False  # 保留字段名向后兼容，实际表示"是否已发送到渠道"


class MessagePipeline:
    def __init__(self,
                 channel_client: ChannelClient,
                 agents_dao: AgentsDAO,
                 channels_dao: ChannelsDAO,
                 conv_dao: ConversationDAO,
                 msg_dao: ChatMessageDAO,
                 llm_dao: LLMConfigDAO,
                 send_message_fn: Callable[[dict], dict],
                 risk_config_dao: Optional[RiskConfigDAO] = None,
                 quick_llm_fn: Optional[Callable[..., str]] = None,   # 🆕 Bridge.quick_llm_call
                 ):
        self.channel_client = channel_client
        self.router = BindingRouter(channels_dao)
        self.agents_dao = agents_dao
        self.channels_dao = channels_dao
        self.conv_dao = conv_dao
        self.msg_dao = msg_dao
        self.llm_dao = llm_dao
        # Bridge._handle_send_message，由外层注入避免循环 import
        self._send_message_fn = send_message_fn
        # 🆕 Bridge.quick_llm_call（两阶段占位文案生成，默认 None 则不触发两阶段）
        self._quick_llm_fn = quick_llm_fn
        # 风控引擎（速率控制 + 行为模拟 + 漏回）—— 仅微信渠道使用
        self.risk_engine = RiskEngine()
        # 账号级风控配置（所有智能体共用）
        self.risk_config_dao = risk_config_dao

        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ChannelPipeline")
        self._lock = threading.RLock()

        # 🆕 两阶段后台任务队列深度跟踪
        self._bg_lock = threading.Lock()
        self._bg_queue_depth = 0

        # 注册渠道消息回调
        channel_client.set_message_handler(self._on_message)

        # 服务号新关注用户回调（自动托管）
        if hasattr(channel_client, "set_subscribe_handler"):
            channel_client.set_subscribe_handler(self._on_subscribe)

    # -------- 对外：注入消息（真实或模拟都走这里） --------
    def handle_wcf_message(self, msg: ChannelMessage) -> Optional[PipelineResult]:
        """同步处理一条消息（供测试调用）。异步回调用 _on_message。"""
        return self._process_one(msg)

    # 通用别名（多渠道场景用这个）
    handle_message = handle_wcf_message

    def shutdown(self, wait: bool = True):
        self._pool.shutdown(wait=wait)

    # -------- 文件预处理：file_path → parse_document → 塞进 msg.content --------
    def _preprocess_file(self, msg: ChannelMessage) -> None:
        """把 ChannelMessage 的 file_path 解析成文本，塞回 content。

        - 有 file_path 且文件存在 → 调 doc_parser.parse_document
        - 解析成功 → content 改成 "用户发了文件 [xxx.ext]，内容如下：\\n{text}"
        - 解析失败 → content 改成 "[文件解析失败：xxx]"，走 LLM 让它回复"抱歉这个文件我看不懂"
        - 没有 file_path 也没有 media_id → content 改成 "[文件暂无法下载，请稍后再试]"
        """
        import os
        from storage.doc_parser import parse_document

        fpath = getattr(msg, "file_path", "") or ""
        fname = getattr(msg, "file_name", "") or ""
        mid = getattr(msg, "media_id", "") or ""

        # --- 没有本地路径但有 media_id：调 media_downloader 下载 ---
        if (not fpath or not os.path.isfile(fpath)) and mid:
            try:
                from channel.media_downloader import download_file

                print(
                    f"[Pipeline]   → 无本地路径，尝试 media_downloader 下载 "
                    f"(channel={msg.channel}, media_id={mid[:40]}…)…",
                    flush=True,
                )
                downloaded = download_file(msg.channel, msg)
                if downloaded and os.path.isfile(downloaded):
                    fpath = downloaded
                    fname = fname or os.path.basename(fpath)
                    msg.file_path = fpath
                    msg.file_name = fname
                    print(f"[Pipeline]   → 下载成功: {fpath} ({os.path.getsize(fpath)} bytes)", flush=True)
                else:
                    msg.content = (
                        f"[用户发了文件 {fname or '(未命名)'}(media_id={mid[:40]}…)，"
                        f"自动下载暂时未实现，请手动保存后再发给 AI]"
                    )
                    print(f"[Pipeline]   → media_downloader 返回 None，占位提示", flush=True)
                    return
            except ImportError:
                msg.content = f"[media_downloader 未安装，文件 {fname} 无法下载]"
                print(f"[Pipeline]   → ImportError，占位提示", flush=True)
                return
            except Exception as e:
                msg.content = f"[用户发了文件 {fname or '(未命名)'}，下载异常：{e}]"
                print(f"[Pipeline]   → 下载异常: {e}", flush=True)
                return

        # --- 彻底没路径：但如果 file_path 有值只是还没落盘，再等一轮 ---
        if (not fpath or not os.path.isfile(fpath)) and msg_type == "file":
            import time
            for _retry in range(10):
                if fpath and os.path.isfile(fpath):
                    print(f"[Pipeline]   → file_path 等落盘成功 ({_retry*0.3}s)", flush=True)
                    break
                time.sleep(0.3)

        if not fpath or not os.path.isfile(fpath):
            msg.content = f"[用户发了文件 {fname or '(未命名)'}，但无法获取本地路径]"
            print(f"[Pipeline]   → file 无任何路径，占位", flush=True)
            return

        # 有本地路径 → 解析
        fname = fname or os.path.basename(fpath)
        print(f"[Pipeline]   → file_path={fpath}，开始 parse_document…", flush=True)
        try:
            result = parse_document(fpath)
            if result.get("error"):
                msg.content = (
                    f"[用户发了文件 {fname}，但解析失败：{result['error']}]"
                )
                print(f"[Pipeline]   → 解析失败: {result['error']}", flush=True)
                return

            text = result.get("text", "") or ""
            # 大文件截断：超过 20000 字（约 4-6 页 A4）时截断
            MAX_CHARS = 20000
            truncated = len(text) > MAX_CHARS
            if truncated:
                text = text[:MAX_CHARS] + "\n\n（文件较大，已截断前 20000 字）"

            msg.content = (
                f"用户发了一个文件：{fname}\n"
                f"文件路径：{fpath}\n"
                f"文件大小：{result.get('file_size', 0)} 字节\n"
                f"解析到 {result.get('chunk_count', 0)} 个切片\n"
                f"--- 文件内容 ---\\n{text}"
            )
            print(
                f"[Pipeline]   → 解析成功: {fname} "
                f"({len(text)}字, {result.get('chunk_count',0)}切片"
                f"{'，已截断' if truncated else ''})",
                flush=True,
            )
        except Exception as e:
            msg.content = f"[用户发了文件 {fname}，解析异常：{e}]"
            print(f"[Pipeline]   → 解析异常: {e}", flush=True)

    # -------- 语音预处理：三级回退 --------
    def _preprocess_voice(self, msg: ChannelMessage, asr_cfg: Optional[dict] = None) -> None:
        """语音消息处理 — 三级回退：

        L1: msg.content 已有转写（企微/飞书/钉钉 payload 自带 ASR）→ 直接用
        L2: file_path 存在 + ASR 已配置 → 调 asr_client.transcribe()
        L3: 都没有 → 塞占位文本，让 LLM 知道"用户发了语音但没转写"

        Args:
            msg:     ChannelMessage，voice 类型
            asr_cfg: ASR 配置 dict，格式 {provider, api_key, endpoint, model}
                     传 None 或空 dict 时跳过 L2
        """
        transcript = (getattr(msg, "content", "") or "").strip()
        fpath = getattr(msg, "file_path", "") or ""

        # --- L1: 已有转写字段 ---
        if transcript and not transcript.startswith("[用户发了语音"):
            print(f"[Pipeline]   → voice L1 已有转写: {transcript[:60]}…", flush=True)
            return

        # --- L2: file_path 存在 + ASR 配置 ---
        if fpath and os.path.isfile(fpath):
            cfg = asr_cfg or {}
            provider = cfg.get("provider", "none")
            api_key = cfg.get("api_key", "")
            if provider and provider != "none" and api_key:
                try:
                    from asr_client import transcribe as asr_transcribe
                    result = asr_transcribe(
                        audio_path=fpath,
                        provider=provider,
                        api_key=api_key,
                        endpoint=cfg.get("endpoint", ""),
                        model=cfg.get("model", ""),
                    )
                    if result:
                        msg.content = result
                        print(f"[Pipeline]   → voice L2 ASR({provider}) 转写: {result[:60]}…", flush=True)
                        return
                    else:
                        print(f"[Pipeline]   → voice L2 ASR({provider}) 返回空，降级到占位", flush=True)
                except Exception as e:
                    print(f"[Pipeline]   → voice L2 ASR({provider}) 异常: {type(e).__name__}: {e}", flush=True)
            else:
                print(f"[Pipeline]   → voice L2 ASR 未配置 (provider={provider!r})，跳过", flush=True)
        elif transcript.startswith("[用户发了语音"):
            # 上游 Client 已经塞了占位（比如旧版微信），直接保留
            print(f"[Pipeline]   → voice 上游已占位: {transcript[:60]}…", flush=True)
            return

        # --- L3: 占位降级 ---
        msg.content = "[用户发了语音，但暂不支持自动转写，请手动转写后发文字消息]"
        print(f"[Pipeline]   → voice L3 占位降级", flush=True)

    # -------- 图片/视频预处理：下载 → base64 → 塞 media_url --------
    def _preprocess_media(self, msg: ChannelMessage) -> None:
        """图片/视频预处理：拿到本地文件路径 → 转 base64 data URL → 塞 msg.media_url。

        - 有 file_path → 直接用
        - 无 file_path 但有 media_id → media_downloader 下载
        - 转 base64 后存进 msg.media_url（格式 data:image/png;base64,xxx）
        - Bridge 收到 payload.media_url 后，会组装 image_url content block 发给 LLM
        """
        import base64
        import mimetypes
        import os

        fpath = getattr(msg, "file_path", "") or ""
        fname = getattr(msg, "file_name", "") or ""
        mid = getattr(msg, "media_id", "") or ""
        mtype = (getattr(msg, "msg_type", "") or "image").lower()

        # --- 无本地路径但有 media_id：调 media_downloader 下载 ---
        if (not fpath or not os.path.isfile(fpath)) and mid:
            try:
                from channel.media_downloader import download_file
                print(
                    f"[Pipeline]   → 无本地路径，尝试 media_downloader 下载 "
                    f"(channel={msg.channel}, media_id={mid[:40]}…)…",
                    flush=True,
                )
                downloaded = download_file(msg.channel, msg)
                if downloaded and os.path.isfile(downloaded):
                    fpath = downloaded
                    fname = fname or os.path.basename(fpath)
                    msg.file_path = fpath
                    msg.file_name = fname
                    print(f"[Pipeline]   → 下载成功: {fpath} ({os.path.getsize(fpath)} bytes)", flush=True)
                else:
                    # 下载失败 → 给 LLM 一个占位，让它回复友好提示
                    msg.content = f"[用户发了{mtype}，但暂时无法下载，请手动保存后描述内容，或等功能升级]"
                    print(f"[Pipeline]   → media_downloader 返回 None，占位", flush=True)
                    return
            except Exception as e:
                msg.content = f"[用户发了{mtype}，下载异常：{e}]"
                print(f"[Pipeline]   → 下载异常: {e}", flush=True)
                return

        # --- 彻底没路径：占位 ---
        if not fpath or not os.path.isfile(fpath):
            msg.content = f"[用户发了{mtype}，但无法获取本地路径]"
            print(f"[Pipeline]   → media 无任何路径，占位", flush=True)
            return

        # --- 转 base64 ---
        fname = fname or os.path.basename(fpath)
        # 推断 mime：文件名后缀优先，不行按 mtype 猜
        mime = mimetypes.guess_type(fname)[0] or ""
        if not mime:
            mime = {"image": "image/jpeg", "video": "video/mp4"}.get(mtype, "application/octet-stream")

        # 安全限制：图片 ≤ 10MB（base64 后 ≤ 13MB），视频 ≤ 50MB（base64 后 ≤ 67MB）
        size = os.path.getsize(fpath)
        MAX_IMG = 10 * 1024 * 1024   # 10MB
        MAX_VID = 50 * 1024 * 1024   # 50MB
        if mtype == "image" and size > MAX_IMG:
            msg.content = f"[用户发的图片 {fname} 超过 10MB，建议压缩后再发]"
            print(f"[Pipeline]   → image 超 10MB ({size} bytes)，占位", flush=True)
            return
        if mtype == "video" and size > MAX_VID:
            msg.content = f"[用户发的视频 {fname} 超过 50MB，建议压缩或截图后再发]"
            print(f"[Pipeline]   → video 超 50MB ({size} bytes)，占位", flush=True)
            return

        try:
            with open(fpath, "rb") as f:
                raw = f.read()
            b64 = base64.b64encode(raw).decode("ascii")
            msg.media_url = f"data:{mime};base64,{b64}"
            print(
                f"[Pipeline]   → base64 编码完成: {fname} "
                f"({size} bytes → {len(b64)} chars, mime={mime})",
                flush=True,
            )
            # 附加一个简短文本提示（可选，让 LLM 知道图片/视频是什么）
            if not msg.content.strip():
                msg.content = f"用户发了一个{mtype}：{fname}，请帮我分析一下。"
        except Exception as e:
            msg.content = f"[用户发了{mtype} {fname}，base64 编码异常：{e}]"
            print(f"[Pipeline]   → base64 异常: {e}", flush=True)

    # -------- 渠道回调：异步丢线程池 --------
    def _on_message(self, msg: ChannelMessage):
        try:
            self._pool.submit(self._process_one, msg)
        except RuntimeError as e:
            print(f"[Pipeline] 线程池已关闭或满溢，消息丢弃: peer={msg.peer_id} err={e}", flush=True)

    def _on_subscribe(self, openid: str):
        """服务号新关注用户回调：自动绑定到开启了「自动托管」的智能体。"""
        try:
            rows = get_conn().execute(
                "SELECT id, name FROM ai_agent WHERE oa_auto_enable = 1"
            ).fetchall()
            if not rows:
                return
            for row in rows:
                agent_id, agent_name = row["id"], row["name"]
                # 检查是否已绑定（避免重复）
                existing = get_conn().execute(
                    "SELECT id FROM channel_binding WHERE agent_id=? AND channel='oa' AND peer_id=?",
                    (agent_id, openid),
                ).fetchone()
                if existing:
                    # 已存在则确保 enabled
                    get_conn().execute(
                        "UPDATE channel_binding SET enabled=1, updated_at=? WHERE id=?",
                        (int(time.time()), existing["id"]),
                    )
                else:
                    import uuid as _uuid
                    bid = str(_uuid.uuid4())
                    ts = int(time.time())
                    get_conn().execute(
                        """INSERT INTO channel_binding
                           (id, agent_id, channel, peer_id, peer_name, peer_type, enabled, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (bid, agent_id, "oa", openid, openid[:12], "friend", 1, ts, ts),
                    )
                get_conn().commit()
                print(f"[Pipeline] 自动托管：新关注用户 {openid} 已绑定到智能体 {agent_name}({agent_id})", flush=True)
        except Exception as e:
            print(f"[Pipeline] 自动托管处理异常: {e}", flush=True)

    # 向后兼容别名
    _on_wcf_message = _on_message

    # -------- 两阶段触发判断 --------
    @staticmethod
    def _should_trigger_two_stage(msg: ChannelMessage, queue_depth: int) -> bool:
        """
        融合版：只判断"要不要后台线程处理"（不负责"要不要先发一句"）。
        - 文件/图片超过 500KB 就后台处理（给文件解析留时间）
        - 要不要在正式回复前先发一句 → LLM 通过翻译层事实自己判断
        """
        if msg.msg_type in ('file', 'image') and msg.file_size > 500 * 1024:
            _mb = msg.file_size / 1024 / 1024
            print(f"[Pipeline] 两阶段触发（后台处理）：{msg.msg_type} {_mb:.1f}MB", flush=True)
            return True

        return False

    # -------- 核心流程 --------
    def _process_one(self, msg: ChannelMessage) -> PipelineResult:
        try:
            return self.__process_one(msg)
        except Exception as e:
            print(f"[Pipeline] 处理异常 peer={msg.peer_id}: {e}", flush=True)
            return PipelineResult(handled=False, reason=f"exception:{e}")

    def __process_one(self, msg: WcfMessage) -> PipelineResult:
        print(f"[Pipeline] ===== 收到新消息 ===== channel={msg.channel!r} peer={msg.peer_id!r} is_self={msg.is_self}", flush=True)
        print(f"[Pipeline]   content= {(msg.content or '')[:100]!r}", flush=True)
        # 1) 空消息过滤
        if not msg.content or not msg.content.strip():
            print(f"[Pipeline]   → 空消息，丢弃", flush=True)
            return PipelineResult(False, "empty")
        if msg.is_self:
            print(f"[Pipeline]   → 自己发的消息，丢弃", flush=True)
            return PipelineResult(False, "self")

        channel = (msg.channel or "wcf").strip().lower() or "wcf"
        peer_id = msg.peer_id
        if not peer_id:
            print(f"[Pipeline]   → 无 peer_id，丢弃", flush=True)
            return PipelineResult(False, "no peer_id")

        # 2) ★ 管理者模式优先：先查 is_manager=1 的全部绑定
        #    命中 → 聚合路径（跨所有 bound agents 查 RAG，MANAGER_PROMPT，不注入 memories）
        #    未命中 → 走下面普通用户路径（单 agent + channel 锁过滤）
        manager_bounds = self.router.find_all_agents_for_manager(channel, peer_id)
        is_manager_mode = bool(manager_bounds)
        if is_manager_mode:
            print(f"[Pipeline]   → ★ 管理者模式命中，绑定 {len(manager_bounds)} 个 agent: "
                  f"{[b['agent_id'] for b in manager_bounds]}", flush=True)

        # —— 公共变量：管理者路径和普通用户路径都需要 ——
        if is_manager_mode:
            primary = manager_bounds[0]       # 第一个 = 最后更新的（ORDER BY updated_at DESC）
            agent_id = primary["agent_id"]
            bound_agent_ids = [b["agent_id"] for b in manager_bounds]
            peer_name = primary["peer_name"] or msg.peer_name or peer_id
            peer_type = "manager"              # ★ 标记为管理者会话
        else:
            # 普通用户路径：现有逻辑不动
            print(f"[Pipeline]   → 查绑定 router.find_agent_for_peer({channel!r}, {peer_id!r})", flush=True)
            bind = self.router.find_agent_for_peer(channel, peer_id)
            print(f"[Pipeline]   → 绑定结果: {bind!r}", flush=True)
            if not bind:
                # 未绑定：不回复、不入库，只打一条日志
                print(f"[Pipeline] 未绑定丢弃 channel={channel} peer={peer_id}", flush=True)
                return PipelineResult(False, "no binding")
            agent_id = bind["agent_id"]
            bound_agent_ids = []               # 普通用户没有聚合
            peer_name = bind["peer_name"] or msg.peer_name or peer_id
            peer_type = bind["peer_type"] or msg.peer_type or "friend"

        agent = self.agents_dao.get(agent_id)
        if not agent:
            print(f"[Pipeline]   → 智能体不存在 agent_id={agent_id}", flush=True)
            return PipelineResult(False, f"agent gone {agent_id}")
        mode_label = "管理者聚合" if is_manager_mode else "单 agent"
        print(f"[Pipeline]   → [{mode_label}] 主 agent: id={agent_id} name={agent.get('name')!r} "
              f"aigc_enabled={agent.get('aigc_enabled')}", flush=True)

        # 2.5) 非文本消息处理：按 content_formats 智能判断
        #   - 该类型已开启 → 放行（后续 pipeline 继续处理 ASR/下载/解析）
        #   - 该类型未开启 → 回复提示语，不调 LLM
        msg_type = (getattr(msg, "msg_type", "text") or "text").strip().lower()
        # msg_type → content_formats key 的映射
        _FMT_MAP = {
            "voice":   "voice",
            "image":   "image", "picture": "image",
            "video":   "video", "shortvideo": "video",
            "file":    "file", "app": "file", "filemessage": "file", "attachment": "file",
        }
        fmt_key = _FMT_MAP.get(msg_type)
        if fmt_key:
            # 该类型在 content_formats 里有对应开关
            raw_cf = agent.get("content_formats")
            try:
                cf = json.loads(raw_cf) if raw_cf else {}
            except Exception:
                cf = {}
            if cf.get(fmt_key, False):
                print(f"[Pipeline]   → 非文本消息({msg_type}/{fmt_key})已开启，放行处理", flush=True)
                # 放行后由后续链路（ASR/下载/解析）处理
            else:
                _type_cn = {"voice":"语音","image":"图片","video":"视频","file":"文件"}.get(fmt_key, fmt_key)
                # 动态计算：当前智能体开启了哪些内容形式（给普通用户的提示要精准）
                # NOTE video 1.0 不支持，永远从 _supported_hint 里排除
                _fmt_cn_all = {"text":"文字","voice":"语音","image":"图片","file":"文件"}
                _fmt_cn_list = [_fmt_cn_all[k] for k in ("text","voice","image","file") if cf.get(k, False)]
                _supported_hint = "、".join(_fmt_cn_list) if _fmt_cn_list else "文字"
                # voice 是真不支持（MVP 1.0 没 ASR），统一降级
                # video 是大模型普遍不支持，单独话术（甩锅给模型）
                # 其他类型是"能支持但开关没开"，区分 manager 给配置提示
                if fmt_key == "voice":
                    notice = f"目前暂不支持{_type_cn}消息，请发{_supported_hint}消息哦～"
                elif fmt_key == "video":
                    if is_manager_mode:
                        notice = f"主人，当前大部分大模型不支持视频处理，请让用户发{_supported_hint}吧～"
                    else:
                        notice = f"抱歉，目前还看不了视频哦～可以发{_supported_hint}告诉我～"
                elif is_manager_mode:
                    notice = f"主人，{_type_cn}能力没开启哦～在「内容管理」里打开{_type_cn}开关就行"
                else:
                    notice = f"抱歉，这个智能体暂时不支持{_type_cn}，请发{_supported_hint}消息～"
                print(f"[Pipeline]   → 非文本消息({msg_type}/{fmt_key})未开启，回复提示语({notice[:40]}...)", flush=True)
                at_id = msg.sender_id if peer_type == "group" else ""
                try:
                    self.channel_client.send_reply(peer_id, notice, peer_type=peer_type, at_sender_id=at_id)
                except Exception as e:
                    print(f"[Pipeline]   → 提示语发送失败: {e}", flush=True)
                return PipelineResult(True, f"non_text_blocked:{msg_type}")
        # 未识别的 msg_type 或 text → 继续走正常 LLM 链路

        # 2.6) 非文本消息预处理
        if msg_type == "file" and fmt_key and cf.get(fmt_key, False):
            self._preprocess_file(msg)
        elif msg_type == "voice" and fmt_key and cf.get(fmt_key, False):
            # 解析 ASR 配置（agent.asr_settings 可能是 JSON string 或 dict）
            raw_asr = agent.get("asr_settings")
            try:
                asr_cfg = json.loads(raw_asr) if isinstance(raw_asr, str) and raw_asr else (raw_asr or {})
            except Exception:
                asr_cfg = {}
            self._preprocess_voice(msg, asr_cfg=asr_cfg)
        elif msg_type in ("image", "video") and fmt_key and cf.get(fmt_key, False):
            self._preprocess_media(msg)

        # ========== 两阶段异步响应（占位 + 后台处理） ==========
        # 触发条件：有 quick_llm_fn 注入 + 满足任一触发条件
        if self._quick_llm_fn is not None:
            with self._bg_lock:
                _qd = self._bg_queue_depth
            if self._should_trigger_two_stage(msg, _qd):
                file_size_mb = msg.file_size / 1024 / 1024

                # --- 阶段 1：立即发占位回复 ---
                _placeholder_sent = False
                try:
                    placeholder = self._quick_llm_fn(
                        agent_id=agent_id, reason="file_large",
                        channel=channel, file_size_mb=file_size_mb,
                    )
                    at_id = msg.sender_id if peer_type == "group" else ""
                    _sent_ok = self.channel_client.send_reply(
                        peer_id, placeholder, peer_type=peer_type, at_sender_id=at_id,
                    )
                    if _sent_ok:
                        _placeholder_sent = True
                        print(f"[Pipeline] ★ 两阶段：占位已发送 ({placeholder[:40]}...)", flush=True)
                    else:
                        print(f"[Pipeline] ★ 两阶段：占位发送失败（send_reply 返回 False），降级同步", flush=True)
                except Exception as e:
                    print(f"[Pipeline] ★ 两阶段：占位发送异常（降级同步）: {e}", flush=True)

                if _placeholder_sent:
                    # --- 阶段 2：后台线程完整处理 ---
                    with self._bg_lock:
                        self._bg_queue_depth += 1

                    def _bg_process():
                        try:
                            import os as _os
                            import time as _t
                            from storage.dao import ChatMessageDAO as _CMDAO

                            # 2a. 等文件就绪（如果还没落盘）
                            if msg.msg_type in ('file', 'image') and not msg.is_ready:
                                for _ in range(10):
                                    if _os.path.isfile(msg.file_path):
                                        msg.is_ready = True
                                        break
                                    _t.sleep(0.3)

                            # 2b. 文件预处理（补齐 content 里的文本）
                            if msg.msg_type == "file":
                                self._preprocess_file(msg)
                            elif msg.msg_type in ("image", "video"):
                                self._preprocess_media(msg)

                            # 2c. 走完整 LLM 链路
                            conv_id = self._get_or_create_conversation(
                                agent_id=agent_id, channel=channel,
                                peer_id=peer_id, peer_name=peer_name,
                                peer_type=peer_type, first_msg=msg.content.strip(),
                            )
                            payload = {
                                "agent_id": agent_id,
                                "conversation_id": conv_id,
                                "content": msg.content.strip(),
                                "use_kb": True,
                                "channel": channel,
                                "peer_id": peer_id,
                                "peer_name": peer_name,
                                "peer_type": peer_type,
                            }
                            _media_url = getattr(msg, "media_url", "") or ""
                            if _media_url:
                                payload["media"] = [{"type": msg.msg_type, "url": _media_url,
                                                     "name": getattr(msg, "file_name", "") or ""}]
                            if is_manager_mode:
                                payload["is_manager_mode"] = True
                                payload["bound_agent_ids"] = bound_agent_ids

                            # 🆕 融合版：两阶段后台线程也塞 msg_facts
                            _bg_facts = {
                                "消息类型": msg.msg_type,
                                "对话对象": "管理者" if is_manager_mode else "普通联系人",
                                "处理状态": "后台处理中（两阶段）",
                            }
                            if msg.file_size and msg.file_size > 0:
                                _mb2 = msg.file_size / 1024 / 1024
                                if _mb2 >= 1:
                                    _bg_facts["文件大小"] = f"{_mb2:.1f} MB"
                                else:
                                    _bg_facts["文件大小"] = f"{msg.file_size / 1024:.0f} KB"
                                if getattr(msg, "file_name", ""):
                                    _bg_facts["文件名"] = msg.file_name
                            payload["msg_facts"] = _bg_facts

                            result = self._send_message_fn(payload)
                            reply_text = ((result.get("assistant_message") or {}).get("content") or "").strip()

                            if not reply_text:
                                _err_hint = ((result.get("assistant_message") or {}).get("content") or "").strip()
                                reply_text = _err_hint
                            if reply_text.startswith("[错误]"):
                                reply_text = reply_text[len("[错误]"):].strip()

                            if reply_text:
                                send_text = self._strip_old_aigc_prefix(
                                    reply_text, agent.get("name", ""),
                                )
                                at_id2 = msg.sender_id if peer_type == "group" else ""
                                if channel == "wcf":
                                    self.risk_engine.acquire_send_lock(min_gap=2.0)
                                    try:
                                        self.channel_client.send_reply(
                                            peer_id, send_text, peer_type=peer_type, at_sender_id=at_id2,
                                        )
                                    finally:
                                        self.risk_engine.release_send_lock()
                                else:
                                    self.channel_client.send_reply(
                                        peer_id, send_text, peer_type=peer_type, at_sender_id=at_id2,
                                    )
                                print(f"[Pipeline] ★ 两阶段：完整回复已发送 ({len(send_text)}字)", flush=True)
                            else:
                                print(f"[Pipeline] ★ 两阶段：LLM 返回空回复，不发第二条", flush=True)

                        except Exception as e:
                            print(f"[Pipeline] ★ 两阶段后台异常: {type(e).__name__}: {e}", flush=True)
                            try:
                                self.channel_client.send_reply(
                                    peer_id, "抱歉，处理中出了点问题，要不你稍后再发一次？",
                                    peer_type=peer_type,
                                )
                            except Exception:
                                pass
                        finally:
                            with self._bg_lock:
                                self._bg_queue_depth -= 1

                    self._pool.submit(_bg_process)
                    print(f"[Pipeline] ★ 两阶段：后台任务已提交，主线程返回", flush=True)
                    return PipelineResult(True, "two_stage_started")

                # 占位没发出去 → 降级走下面的同步流程（一行不跳过）

        # 3) 找/建会话（同一智能体 × 渠道 × peer 共用一个会话，跨消息历史连续）
        print(f"[Pipeline]   → 3. 找/建会话 agent={agent_id} peer={peer_id}", flush=True)
        conv_id = self._get_or_create_conversation(
            agent_id=agent_id, channel=channel,
            peer_id=peer_id, peer_name=peer_name, peer_type=peer_type,
            first_msg=msg.content.strip(),
        )
        print(f"[Pipeline]   →    会话ID: {conv_id}", flush=True)

        # 4) 调 Bridge.send_message：它会自己存 user 消息、调 LLM、存 assistant 消息、加 AIGC 标识
        payload = {
            "agent_id": agent_id,
            "conversation_id": conv_id,
            "content": msg.content.strip(),
            "use_kb": True,
            "channel": channel,
            "peer_id": peer_id,
            "peer_name": peer_name,
            "peer_type": peer_type,
        }
        # ★ 可选：图片/视频 base64 data URL → Bridge 组装 image_url content block
        media_url = getattr(msg, "media_url", "") or ""
        if media_url:
            media_cn = {"image": "图片", "video": "视频"}.get(msg_type, msg_type)
            fname = getattr(msg, "file_name", "") or ""
            payload["media"] = [{"type": msg_type, "url": media_url, "name": fname}]
            print(f"[Pipeline]   → payload.media 已注入 ({media_cn}, base64={len(media_url)}chars)", flush=True)
        # ★ 管理者模式额外字段：bridge 读这个做聚合 RAG
        if is_manager_mode:
            payload["is_manager_mode"] = True
            payload["bound_agent_ids"] = bound_agent_ids

        # 🆕 融合版：采集当前消息事实 → 喂给翻译层
        with self._bg_lock:
            _qd = self._bg_queue_depth
        _facts = {
            "消息类型": msg_type,
            "对话对象": "管理者" if is_manager_mode else "普通联系人",
        }
        if msg.file_size and msg.file_size > 0:
            _mb = msg.file_size / 1024 / 1024
            if _mb >= 1:
                _facts["文件大小"] = f"{_mb:.1f} MB"
            else:
                _facts["文件大小"] = f"{msg.file_size / 1024:.0f} KB"
            if getattr(msg, "file_name", ""):
                _facts["文件名"] = msg.file_name
        if _qd > 0:
            _facts["后台队列"] = f"还有 {_qd} 条在排队"
        payload["msg_facts"] = _facts
        print(f"[Pipeline]   → 4. 调 LLM (send_message_fn) ...", flush=True)
        result = self._send_message_fn(payload)
        print(f"[Pipeline]   →    LLM result keys={list(result.keys())} error={result.get('error')!r}", flush=True)

        # ★ error 也可能带降级提示（如模型不支持视频时 Bridge 存了友好提示）
        # 不能直接 return，要看看 assistant_message.content 里有没有东西可以发
        _err_hint = ""
        if result.get("error"):
            _am = result.get("assistant_message") or {}
            _err_hint = (_am.get("content") or "").strip()

        if result.get("error") and not _err_hint:
            # 真正的致命错误（连降级提示都没有）
            print(f"[Pipeline]   →    LLM 错误（无降级提示）: {result.get('error')}", flush=True)
            return PipelineResult(
                True, f"llm_error:{result['error']}",
                conversation_id=conv_id,
            )

        # 有降级提示 or 正常回复：统一取 assistant_message.content
        assistant_msg = result.get("assistant_message") or {}
        reply_text = assistant_msg.get("content", "") or ""
        # 去掉 Bridge 可能加的 [错误] 前缀，让用户看到干净的提示
        if reply_text.startswith("[错误]"):
            reply_text = reply_text[len("[错误]"):].strip()
        print(f"[Pipeline]   →    回复内容长度: {len(reply_text)} (error_hint={bool(_err_hint)})", flush=True)

        if not reply_text:
            print(f"[Pipeline]   →    空回复，结束", flush=True)
            return PipelineResult(True, "no_reply", conversation_id=conv_id)

        # 4.5) 风控决策：仅微信渠道（wcf）走完整风控（防封号）
        #      其他渠道（企微/飞书/钉钉/公众号）组织内通信，无封号风险，直接发送
        is_wcf = (channel == "wcf")
        if is_wcf:
            # 风控档位从账号级配置读取（所有智能体共用一套策略）
            if self.risk_config_dao:
                try:
                    risk_cfg = self.risk_config_dao.get()
                    rate_profile = {"level": risk_cfg.get("level", "conservative")}
                except Exception:
                    rate_profile = {"level": "conservative"}
            else:
                rate_profile = agent.get("rate_profile") or {}
            decision = self.risk_engine.decide(agent_id, rate_profile, len(reply_text))

            if not decision.should_send:
                print(f"[Pipeline]   → 风控决定跳过发送: {decision.reason}（消息已入库，不丢失）", flush=True)
                return PipelineResult(
                    True, f"skipped_by_risk:{decision.reason}",
                    conversation_id=conv_id, assistant_text=reply_text, sent_to_wcf=False,
                )

            if decision.delay_seconds > 0:
                # 🆕 融合版：风控 delay > 5s 就先发 quick_llm_call（低门槛，让 LLM 自然说）
                # 只有当 delay > 5s 且 quick_llm_fn 存在时才触发
                if decision.delay_seconds > 5 and self._quick_llm_fn is not None:
                    _risk_mb = msg.file_size / 1024 / 1024 if msg.file_size else 0
                    try:
                        _placeholder2 = self._quick_llm_fn(
                            agent_id=agent_id, reason="risk_delay_long",
                            channel=channel, file_size_mb=_risk_mb,
                        )
                        at_id_b = msg.sender_id if peer_type == "group" else ""
                        # 占位不走风控（短消息天然安全），直接发
                        self.channel_client.send_reply(
                            peer_id, _placeholder2, peer_type=peer_type, at_sender_id=at_id_b,
                        )
                        print(f"[Pipeline] ★ 风控长 delay: 占位已发送（delay={decision.delay_seconds}s, placeholder={_placeholder2[:40]}...）", flush=True)
                    except Exception as _e2:
                        print(f"[Pipeline] ★ 风控长 delay: 占位发送失败（继续 sleep）: {_e2}", flush=True)

                print(f"[Pipeline]   → 行为模拟等待 {decision.delay_seconds}s ...", flush=True)
                time.sleep(decision.delay_seconds)

        # 5) 把回复通过对应渠道发出去（未连接就跳过，只留入库记录）
        sent = False
        if reply_text:
            # 群聊需要 @发消息的人
            at_id = msg.sender_id if peer_type == "group" else ""
            # 只清理旧格式 AIGC 前缀 [AIGC·智能体名]（历史数据兼容）
            # 新格式：末尾「（AI 生成内容）」不清理，用户要在渠道里也看到这个标识
            send_text = self._strip_old_aigc_prefix(reply_text, agent.get("name", ""))
            print(f"[Pipeline]   → 5. 通过{channel}发送给 peer={peer_id} send_text[:80]={send_text[:80]!r}", flush=True)

            if is_wcf:
                # 微信：加串行发送锁 + 最小发送间隔（防风控）
                from channel.risk_engine import RiskEngine
                parsed_profile = RiskEngine._parse_profile(rate_profile)
                min_gap = parsed_profile.get("min_send_gap", 2.0)
                self.risk_engine.acquire_send_lock(min_gap=min_gap)
                try:
                    sent = self.channel_client.send_reply(peer_id, send_text, peer_type=peer_type, at_sender_id=at_id)
                finally:
                    self.risk_engine.release_send_lock()
            else:
                # 其他渠道：直接发送
                sent = self.channel_client.send_reply(peer_id, send_text, peer_type=peer_type, at_sender_id=at_id)

            print(f"[Pipeline]   →    发送结果: sent={sent}", flush=True)
            if not sent:
                print(f"[Pipeline] {channel} 回复未发出（未连接或发送失败，内容已入库）peer={peer_id}", flush=True)

        print(f"[Pipeline] ===== 消息处理完成 ===== conv_id={conv_id} sent_to_wcf={sent}", flush=True)
        return PipelineResult(
            True, "ok", conversation_id=conv_id,
            assistant_text=reply_text, sent_to_wcf=sent,
        )

    # -------- helpers --------
    def _get_or_create_conversation(self, *, agent_id: str, channel: str,
                                    peer_id: str, peer_name: str,
                                    peer_type: str, first_msg: str) -> str:
        """同一 (agent, channel, peer) 用同一个会话，让跨消息的上下文连续。"""
        with self._lock:
            conn = get_conn()
            row = conn.execute(
                """SELECT id, peer_type FROM conversation
                   WHERE agent_id = ? AND channel = ? AND peer_id = ?
                   ORDER BY updated_at DESC LIMIT 1""",
                (agent_id, channel, peer_id),
            ).fetchone()
            if row:
                cid = row["id"]
                # 🆕 修复：如果本次走管理者路径（peer_type='manager'）但 DB 还是 'friend'，同步更新
                if peer_type == "manager" and row["peer_type"] != "manager":
                    conn.execute(
                        "UPDATE conversation SET peer_type='manager', updated_at=? WHERE id=?",
                        (now_ts(), cid),
                    )
                    print(f"[Pipeline] 🆕 同步 conversation peer_type → 'manager': conv={cid[:24]}..", flush=True)
                self.conv_dao.touch(cid)
                return cid
            conv = self.conv_dao.create(
                agent_id, title=first_msg[:30],
                channel=channel, peer_id=peer_id,
                peer_name=peer_name, peer_type=peer_type,
            )
            return conv["id"]

    @staticmethod
    def _strip_old_aigc_prefix(text: str, agent_name: str) -> str:
        """清理旧格式 AIGC 前缀 [AIGC·智能体名]（历史数据兼容）。
        新格式末尾「（AI 生成内容）」不处理，原样保留供用户查看。"""
        if not isinstance(text, str):
            return text
        prefix1 = f"[AIGC·{agent_name}] "
        if text.startswith(prefix1):
            return text[len(prefix1):]
        # 回退：AIGC·任意名字
        import re
        return re.sub(r"^\[AIGC·[^\]]+\]\s*", "", text)
