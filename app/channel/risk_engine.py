"""风控保护引擎（MVP 版）—— RateController + BehaviorSimulator 合并。

设计对齐 docs/微信接入风控控制方案_v1.0.md 的 Step 1 + Step 2：
  - 速率控制：令牌桶（分钟）+ 滑动窗口（小时）+ 日配额
  - 行为模拟：对数正态延迟 + 时段因子 + 偶尔漏回
  - 发送间隔：串行锁 + 最小发送间隔，保证真人级别的发送时序

微信风控三维检测模型（来自社区逆向 + 实际封控案例）：
  ┌──────────────────────────────────────────────────────────┐
  │  行为特征（MVP 覆盖 ✓）                                    │
  │  发送频率 / 回复延迟 / 发送间隔 / 时段分布 / 并发度        │
  │  社区经验阈值：>20条/min 连续30分钟触发临时限制             │
  ├──────────────────────────────────────────────────────────┤
  │  内容特征（由 SafetyShield v2 负责 ✗）                     │
  │  敏感词 / 营销话术 / 重复度 / 举报率 / AI内容标识          │
  ├──────────────────────────────────────────────────────────┤
  │  环境特征（MVP 不负责 ✗）                                  │
  │  IP 变动 / 设备指纹 / 多开检测 / 地理位置突变             │
  ├──────────────────────────────────────────────────────────┤
  │  社交特征（慢变量，无法技术模拟 ✗）                         │
  │  好友质量 / 互动率 / 关系网络密度                          │
  └──────────────────────────────────────────────────────────┘

插入位置：MessagePipeline.__process_one() 的 step 4 (LLM 返回) 和 step 5 (send_reply) 之间。
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ============================================================
# 预设档位（前端和后端统一参数源）
# ============================================================

# 档位数据（和前端 RISK_LEVELS 一一对应，参数值完全一致）
# 档位含义参考 docs/微信接入风控控制方案_v1.0.md §2.2
RATE_PROFILES: dict[str, dict] = {
    "ultra_safe": {
        "label": "极保守",
        "per_min": 10,
        "per_hour": 30,
        "per_day": 50,
        "base_delay": 45.0,        # 秒，对数正态中位数
        "night_slowdown": 15.0,    # 深夜倍率（预留）
        "drop_pct_day": 15.0,      # 白天漏回概率 %
        "drop_pct_night": 90.0,    # 深夜漏回概率 %
        "min_send_gap": 5.0,       # 最小发送间隔（秒）
    },
    "conservative": {
        "label": "保守",
        "per_min": 25,
        "per_hour": 100,
        "per_day": 200,
        "base_delay": 25.0,
        "night_slowdown": 10.0,
        "drop_pct_day": 10.0,
        "drop_pct_night": 80.0,
        "min_send_gap": 3.0,
    },
    "balanced": {
        "label": "平衡",
        "per_min": 40,
        "per_hour": 200,
        "per_day": 350,
        "base_delay": 15.0,
        "night_slowdown": 6.0,
        "drop_pct_day": 5.0,
        "drop_pct_night": 50.0,
        "min_send_gap": 2.0,
    },
    "aggressive": {
        "label": "激进",
        "per_min": 60,
        "per_hour": 350,
        "per_day": 500,
        "base_delay": 8.0,
        "night_slowdown": 3.0,
        "drop_pct_day": 2.0,
        "drop_pct_night": 30.0,
        "min_send_gap": 1.5,
    },
    "fast": {
        "label": "快速",
        "per_min": None,           # None = 不限
        "per_hour": None,
        "per_day": None,
        "base_delay": 5.0,
        "night_slowdown": 2.0,
        "drop_pct_day": 0.0,
        "drop_pct_night": 20.0,
        "min_send_gap": 1.0,
    },
}

# 默认档位（当传入无效 level 时回退到此）
_DEFAULT_LEVEL = "conservative"

# 时段因子（24 小时，0-23 各一个倍率）
# 对齐风控方案 §3.2 + 社区行为心理学数据
_HOUR_FACTORS: dict[int, float] = {
    0: 9.0, 1: 11.0, 2: 12.0, 3: 10.0, 4: 8.0, 5: 5.0,     # 深夜 6-12x
    6: 3.0, 7: 2.5, 8: 2.0,                                # 起床 2-3x
    9: 1.0, 10: 0.9, 11: 1.0,                               # 上午工作 0.9-1.0x
    12: 1.4, 13: 1.3,                                       # 午饭 1.3-1.5x
    14: 0.9, 15: 1.0, 16: 0.9, 17: 1.0,                     # 下午工作 0.9-1.0x
    18: 1.2, 19: 1.1,                                       # 下班 1.1-1.2x
    20: 0.7, 21: 0.8, 22: 0.8,                              # 晚间高峰 0.7-0.8x
    23: 1.5,                                                 # 准备睡觉 1.5x
}

# 硬上限参数
MAX_TOTAL_DELAY = 300.0       # 任何情况下总延迟不超过 5 分钟（防止深夜夸张到 10+ 分钟）
MAX_LENGTH_DELAY = 45.0       # 长消息打字模拟封顶 45 秒


# ============================================================
# 数据类
# ============================================================

@dataclass
class _AgentQuota:
    """单个 agent 的速率追踪（内存态，App 重启就重置——可接受）。"""
    # 令牌桶：按分钟速率补充
    tokens: float = 0.0           # 当前可用令牌数（初始按档位 per_min 填充）
    last_refill_ts: float = 0.0   # 上次补充令牌的时间戳
    per_min_cap: float = 25.0     # 记录创建时的 per_min，用于桶容量计算
    # 小时滑动窗口
    hour_timestamps: deque = field(default_factory=deque)  # 近 1 小时内发送的时间戳
    # 日配额
    day_count: int = 0
    day_date: str = ""            # YYYY-MM-DD


@dataclass
class RiskDecision:
    """风控决策结果。"""
    should_send: bool         # False = 漏回（跳过发送，但消息已入库）
    delay_seconds: float     # 应该等多久再发（0 = 立即发）
    reason: str               # 决策原因（日志用）


# ============================================================
# 风控引擎
# ============================================================

class RiskEngine:
    """合并版风控引擎：速率控制 + 行为模拟 + 串行发送 + 最小发送间隔。

    线程安全：所有状态操作都用 self._lock 保护。
    内存态：速率计数在内存里，App 重启归零——MVP 阶段完全够用，
            因为微信风控对 "每天换 IP / 重启后速率重置" 其实是更宽松的信号。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._quotas: dict[str, _AgentQuota] = {}  # agent_id -> quota
        # 串行发送锁：同一时刻只有一个线程在真正调用 send_reply
        self._send_lock = threading.Lock()
        # 上一条发送完成的时间戳（用于保证发送间隔）
        self._last_send_ts: float = 0.0

    # -------- 档位解析 --------

    @staticmethod
    def _parse_profile(profile_raw) -> dict:
        """把前端传来的 rate_profile（可能是 dict 或 JSON str）解析成档位数据。

        优先级：dict > JSON str > 空/非法值 → fallback 到 conservative。
        额外做字段补齐：确保档位里包含 min_send_gap 字段（老数据可能没有）。
        """
        level = _DEFAULT_LEVEL
        if isinstance(profile_raw, str) and profile_raw:
            try:
                import json as _json
                p = _json.loads(profile_raw)
                level = (p or {}).get("level", _DEFAULT_LEVEL)
            except Exception:
                level = _DEFAULT_LEVEL
        elif isinstance(profile_raw, dict):
            level = profile_raw.get("level", _DEFAULT_LEVEL)
        # 非法 level 也回退
        if level not in RATE_PROFILES:
            level = _DEFAULT_LEVEL
        return RATE_PROFILES[level]

    # -------- 速率控制 --------

    def _get_or_create_quota(self, agent_id: str, profile: dict) -> _AgentQuota:
        """获取或创建 agent 的配额追踪，按当前档位初始化。

        修复：之前硬编码 tokens=25.0，现在按档位 per_min 初始化，
        确保不同档位的初始可用令牌数正确。
        """
        q = self._quotas.get(agent_id)
        if q is None:
            per_min = profile.get("per_min")
            initial_tokens = per_min if per_min is not None else 40.0  # None=不限,给个中间值
            q = _AgentQuota(
                tokens=float(initial_tokens),
                last_refill_ts=time.time(),
                per_min_cap=float(initial_tokens),
            )
            self._quotas[agent_id] = q
        # 每天重置
        today = datetime.now().strftime("%Y-%m-%d")
        if q.day_date != today:
            q.day_date = today
            q.day_count = 0
        return q

    @staticmethod
    def _bucket_cap(per_min) -> float:
        """令牌桶容量 = per_min + per_min * 0.5（允许 0.5 分钟速率的突发缓冲）。

        设计参考 docs/微信接入风控控制方案_v1.0.md §2.3：
        "令牌桶允许一定突发"——桶不是严格卡速率，而是允许短时间集中爆发。
        conservative 档：25 * 1.5 = 37.5 条容量
        balanced 档：40 * 1.5 = 60 条容量
        fast 档：per_min=None 时不走令牌桶，不调这个函数
        """
        if per_min is None:
            return float("inf")
        return per_min + per_min * 0.5

    def _refill_tokens(self, q: _AgentQuota, profile: dict):
        """令牌桶补充：按 per_min 速率线性补充。"""
        per_min = profile.get("per_min")
        if per_min is None:
            return  # 不限速率
        now = time.time()
        elapsed = now - q.last_refill_ts
        if elapsed <= 0:
            return
        # 补充量 = 速率 × 经过秒数 / 60
        new_tokens = q.tokens + (per_min * elapsed / 60.0)
        cap = self._bucket_cap(per_min)
        q.tokens = min(new_tokens, cap)
        q.last_refill_ts = now

    def _check_and_consume_rate(self, agent_id: str, profile: dict) -> tuple[bool, str]:
        """三重速率检查。

        返回 (ok, reason)：
          - ok=True 表示可以发送，配额已扣
          - ok=False 表示超限，reason 说明是哪个维度超了
        """
        per_min = profile.get("per_min")
        per_hour = profile.get("per_hour")
        per_day = profile.get("per_day")

        # 全不限 = 直接通过
        if per_min is None and per_hour is None and per_day is None:
            return True, "fast-unlimited"

        with self._lock:
            q = self._get_or_create_quota(agent_id, profile)
            self._refill_tokens(q, profile)

            # 日配额检查
            if per_day is not None and q.day_count >= per_day:
                return False, f"day_quota({per_day})"

            # 小时窗口检查
            if per_hour is not None:
                now = time.time()
                cutoff = now - 3600
                # 淘汰过期时间戳
                while q.hour_timestamps and q.hour_timestamps[0] < cutoff:
                    q.hour_timestamps.popleft()
                if len(q.hour_timestamps) >= per_hour:
                    return False, f"hour_quota({per_hour})"

            # 令牌桶检查（分钟级）
            if per_min is not None:
                if q.tokens < 1.0:
                    return False, f"min_quota({per_min})"
                q.tokens -= 1.0

            # 扣配额
            q.day_count += 1
            now = time.time()
            q.hour_timestamps.append(now)

            return True, "ok"

    # -------- 行为模拟 --------

    @staticmethod
    def _lognormal_delay(mu: float, sigma: float = 0.5) -> float:
        """生成对数正态分布的延迟秒数。

        mu 是中位数（期望延迟），sigma 控制右尾厚度。
        真实人类行为的等待时间普遍符合对数正态分布。
        sigma=0.5 让分布更集中在中位数附近（90% 的样本在 mu*0.4 ~ mu*2.5 之间），
        比 sigma=0.6 更贴近真实人类行为（不会有太多极端长尾）。
        """
        if mu <= 0:
            return 0.0
        # lognormal 参数：中位数 = exp(mu_param)，所以 mu_param = ln(mu)
        mu_param = math.log(mu)
        val = random.lognormvariate(mu_param, sigma)
        # 限制在 [mu * 0.3, mu * 5] 之间，避免极端值
        return max(mu * 0.3, min(val, mu * 5))

    @staticmethod
    def _hour_factor() -> float:
        """当前时段的活跃因子倍率。"""
        hour = datetime.now().hour
        return _HOUR_FACTORS.get(hour, 1.0)

    @staticmethod
    def _is_night() -> bool:
        """深夜：23:00 - 次日 5:59。"""
        h = datetime.now().hour
        return h >= 23 or h < 6

    @staticmethod
    def _should_drop(profile: dict) -> bool:
        """偶尔漏回：按概率决定是否跳过发送。

        漏回发生时，速率配额不扣——因为消息根本没发出去。
        """
        is_night = RiskEngine._is_night()
        pct = profile["drop_pct_night"] if is_night else profile["drop_pct_day"]
        if pct <= 0:
            return False
        return random.random() * 100 < pct

    # -------- 主入口 --------

    def decide(self, agent_id: str, profile_raw, reply_text_len: int = 0) -> RiskDecision:
        """风控决策主入口。

        在 MessagePipeline.__process_one() 的 step 4 和 step 5 之间调用。
        返回一个 RiskDecision，告诉调用者要不要发、等多久发。
        """
        profile = self._parse_profile(profile_raw)

        # 1) 偶尔漏回（先于速率检查——如果决定漏回，速率配额不扣）
        if self._should_drop(profile):
            reason = "drop_" + ("night" if self._is_night() else "day")
            print(f"[Risk] agent={agent_id} 漏回（{reason}，档位={profile['label']}）", flush=True)
            return RiskDecision(should_send=False, delay_seconds=0.0, reason=reason)

        # 2) 速率控制
        ok, rate_reason = self._check_and_consume_rate(agent_id, profile)
        if not ok:
            # 超限：等待后再试（最多等 60 秒，超过就放弃这次发送）
            print(f"[Risk] agent={agent_id} 速率超限: {rate_reason}，等待 5s 后再试", flush=True)
            time.sleep(5)
            ok2, reason2 = self._check_and_consume_rate(agent_id, profile)
            if not ok2:
                print(f"[Risk] agent={agent_id} 二次检查仍超限，放弃本次发送", flush=True)
                return RiskDecision(should_send=False, delay_seconds=0.0, reason=f"rate_limited:{rate_reason}")
            rate_reason = reason2

        # 3) 行为模拟延迟
        # 基础延迟 × 时段因子
        base = profile["base_delay"]
        hour_factor = self._hour_factor()
        delay = self._lognormal_delay(base) * hour_factor

        # 消息越长，打字越久（简单线性叠加）
        # 修正：之前封顶 15s 太短，500 字消息模拟不足；提升到 45s
        if reply_text_len > 0:
            delay += min(reply_text_len * 0.02, MAX_LENGTH_DELAY)

        # 偶尔"在忙"，延迟翻倍（15% 概率）
        if random.random() < 0.15:
            delay *= 2.5
            print(f"[Risk] agent={agent_id} 触发'在忙'模式，延迟 ×2.5", flush=True)

        # 硬上限：任何情况下总延迟不超过 5 分钟
        delay = min(delay, MAX_TOTAL_DELAY)
        delay = round(delay, 1)
        print(f"[Risk] agent={agent_id} 决策: should_send=True delay={delay}s reason={rate_reason} hour={datetime.now().hour} factor={hour_factor}x", flush=True)

        return RiskDecision(should_send=True, delay_seconds=delay, reason=rate_reason)

    # -------- 串行发送 + 最小发送间隔 --------

    def acquire_send_lock(self, min_gap: float = 2.0):
        """获取串行发送锁 + 确保与上一条发送的间隔。

        修复：之前只有一把全局锁保证单线程 send，
        但如果两条消息同时到达、各自决策完延迟后，
        可能在毫秒级间隙内连续调用 send_reply——
        这正是微信风控行为时序层（LSTM）能识别的机器特征。

        现在：在拿到锁之后，检查与 _last_send_ts 的间隔，
        如果不够 min_gap 秒，再 sleep 补满。
        这样即使 Pipeline 单 worker，也保证发送间隔是真人级别的。
        """
        self._send_lock.acquire()

        # 检查与上一条的间隔
        gap = max(min_gap, 2.0)  # 硬保底 2 秒，不管什么档位
        with self._lock:
            now = time.time()
            since_last = now - self._last_send_ts
        if since_last < gap:
            wait = gap - since_last
            print(f"[Risk] 串行发送: 距上次仅 {since_last:.1f}s, 补等 {wait:.1f}s (min_gap={gap}s)", flush=True)
            time.sleep(wait)

    def release_send_lock(self):
        """释放串行发送锁，同时更新 _last_send_ts。"""
        with self._lock:
            self._last_send_ts = time.time()
        self._send_lock.release()


# ============================================================
# 单例
# ============================================================

_DEFAULT_RISK = RiskEngine()


def get_risk_engine() -> RiskEngine:
    """全进程共享的 RiskEngine 单例。schedule_message / MCP 生成应用的 send_reply 都用它。"""
    return _DEFAULT_RISK
