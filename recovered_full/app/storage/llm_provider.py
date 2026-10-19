"""LLM 调用封装：OpenAI 兼容协议（DeepSeek/OpenAI/智谱/月之暗面/混元等）。

零依赖（仅用标准库 urllib + json），支持：
- 非流式 chat：返回完整文本 + usage
- SSE 流式 chat_stream：逐字 yield 增量文本（首字符 < 500ms 目标）
- test_connection：发 "ping" 消息测连通 + 延迟

协议：POST {base_url}/v1/chat/completions
- Headers: Authorization: Bearer {api_key}, Content-Type: application/json
- Body: {model, messages, temperature, stream}
- SSE 响应：data: {choices:[{delta:{content}}]}\n\n ... data: [DONE]

后续升级：
- 可选装 requests（更稳的连接池 + 重试），目前 urllib 够用
- 支持 function calling / tool use（MVP 不做）
- 支持图片输入（vision 模型，MVP 不做）
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Iterator


# 默认超时（秒）
DEFAULT_TIMEOUT = 30
TEST_TIMEOUT = 15


def _normalize_base_url(base_url: str) -> str:
    """规范化 base_url：去尾部 /，确保以 /v1 结尾（不重复加）。

    用户可能填：
        https://api.deepseek.com
        https://api.deepseek.com/
        https://api.deepseek.com/v1
        https://api.deepseek.com/v1/
    统一输出：https://api.deepseek.com/v1
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    # 已有 /v1 结尾，不再加
    if url.endswith("/v1"):
        return url
    # 已有 /v1/ 结尾（rstrip 后不会，但兜底）
    if url.endswith("/v1/"):
        return url.rstrip("/")
    return url + "/v1"


def _build_chat_url(base_url: str) -> str:
    """拼接 chat completions 端点。"""
    return _normalize_base_url(base_url) + "/chat/completions"


class LLMProvider:
    """OpenAI 兼容协议的 LLM 调用封装。

    用法：
        p = LLMProvider("https://api.deepseek.com", "sk-xxx", "deepseek-chat")
        r = p.test_connection()
        for chunk in p.chat_stream([{"role":"user","content":"你好"}]):
            print(chunk, end="", flush=True)
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.base_url = _normalize_base_url(base_url)
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout = timeout

    @classmethod
    def from_config(cls, cfg: dict) -> "LLMProvider":
        """从 LLM 配置 dict（DAO 返回的，api_key 已解密）构造。"""
        return cls(
            base_url=cfg.get("base_url", ""),
            api_key=cfg.get("api_key", ""),
            model=cfg.get("model", ""),
        )

    # ---------- 连接测试 ----------
    def test_connection(self) -> dict:
        """发一个最短消息测连通，返回 {connected, latency_ms, reason, model}。

        不流式，等完整响应。失败时 connected=False + reason。
        """
        if not self.base_url or not self.api_key or not self.model:
            return {
                "connected": False,
                "latency_ms": 0,
                "reason": "参数不完整（base_url / api_key / model）",
                "model": self.model,
            }
        url = _build_chat_url(self.base_url)
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=TEST_TIMEOUT) as resp:
                if resp.status != 200:
                    return {
                        "connected": False,
                        "latency_ms": int((time.time() - t0) * 1000),
                        "reason": f"HTTP {resp.status}",
                        "model": self.model,
                    }
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                # 检查 API 层错误（某些服务 HTTP 200 但 body 带 error）
                if "error" in data:
                    return {
                        "connected": False,
                        "latency_ms": int((time.time() - t0) * 1000),
                        "reason": data["error"].get("message", "未知 API 错误"),
                        "model": self.model,
                    }
                latency = int((time.time() - t0) * 1000)
                return {
                    "connected": True,
                    "latency_ms": latency,
                    "reason": "ok",
                    "model": self.model,
                }
        except urllib.error.HTTPError as e:
            # 提取 API 错误消息（401 鉴权失败 / 429 限流等）
            reason = f"HTTP {e.code}"
            try:
                err_body = e.read().decode("utf-8")
                err_json = json.loads(err_body)
                if "error" in err_json:
                    reason = err_json["error"].get("message", reason)
            except Exception:
                pass
            return {
                "connected": False,
                "latency_ms": int((time.time() - t0) * 1000),
                "reason": reason,
                "model": self.model,
            }
        except urllib.error.URLError as e:
            return {
                "connected": False,
                "latency_ms": int((time.time() - t0) * 1000),
                "reason": f"网络错误: {e.reason}",
                "model": self.model,
            }
        except Exception as e:
            return {
                "connected": False,
                "latency_ms": int((time.time() - t0) * 1000),
                "reason": f"异常: {e}",
                "model": self.model,
            }

    # ---------- 非流式 ----------
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> dict:
        """非流式对话，返回完整结果。

        返回 {text, finish_reason, usage, error}
        成功 error=""，失败 error 非空。
        """
        body_dict: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            body_dict["max_tokens"] = max_tokens
        body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            _build_chat_url(self.base_url),
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                if "error" in data:
                    return {"text": "", "finish_reason": "",
                            "usage": {}, "error": data["error"].get("message", "")}
                choice = (data.get("choices") or [{}])[0]
                return {
                    "text": choice.get("message", {}).get("content", ""),
                    "finish_reason": choice.get("finish_reason", ""),
                    "usage": data.get("usage", {}),
                    "error": "",
                }
        except urllib.error.HTTPError as e:
            reason = f"HTTP {e.code}"
            try:
                err_json = json.loads(e.read().decode("utf-8"))
                reason = err_json.get("error", {}).get("message", reason)
            except Exception:
                pass
            return {"text": "", "finish_reason": "", "usage": {}, "error": reason}
        except Exception as e:
            return {"text": "", "finish_reason": "", "usage": {}, "error": str(e)}

    # ---------- SSE 流式 ----------
    def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> Iterator[str]:
        """SSE 流式对话，逐字 yield 增量文本。

        失败时 yield 一个 JSON 字符串 {"error": "..."} 表示错误（调用方判断）。
        正常结束自然 return（迭代结束）。
        """
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            _build_chat_url(self.base_url),
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            reason = f"HTTP {e.code}"
            try:
                err_json = json.loads(e.read().decode("utf-8"))
                reason = err_json.get("error", {}).get("message", reason)
            except Exception:
                pass
            yield json.dumps({"error": reason}, ensure_ascii=False)
            return
        except Exception as e:
            yield json.dumps({"error": str(e)}, ensure_ascii=False)
            return

        # 逐行读 SSE
        with resp:
            buf = b""
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buf += chunk
                # SSE 事件以 \n\n 分隔
                while b"\n\n" in buf:
                    event_bytes, buf = buf.split(b"\n\n", 1)
                    for line in event_bytes.decode("utf-8", errors="replace").split("\n"):
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            return
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        # 检查 API 层错误
                        if "error" in data:
                            yield json.dumps(
                                {"error": data["error"].get("message", "")},
                                ensure_ascii=False,
                            )
                            return
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content


if __name__ == "__main__":
    # 自测：需要真实 API key（环境变量 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）
    import os
    base = os.environ.get("LLM_BASE_URL", "")
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if not base or not key or not model:
        print("跳过自测：未设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 环境变量")
        print("示例（DeepSeek）：")
        print("  $env:LLM_BASE_URL='https://api.deepseek.com'")
        print("  $env:LLM_API_KEY='sk-xxx'")
        print("  $env:LLM_MODEL='deepseek-chat'")
        raise SystemExit(0)

    p = LLMProvider(base, key, model)
    print(f"=== test_connection ===")
    r = p.test_connection()
    print(f"connected={r['connected']} latency={r['latency_ms']}ms reason={r['reason']}")

    print(f"\n=== chat_stream ===")
    messages = [
        {"role": "system", "content": "你是阿维达AI助手，回答简洁。"},
        {"role": "user", "content": "用一句话介绍你自己。"},
    ]
    full = ""
    t0 = time.time()
    first_char_ts = None
    for chunk in p.chat_stream(messages):
        if chunk.startswith('{"error"'):
            print(f"\n[错误] {chunk}")
            break
        if first_char_ts is None:
            first_char_ts = time.time()
        full += chunk
        print(chunk, end="", flush=True)
    print()
    print(f"\n首字符延迟: {(first_char_ts - t0)*1000:.0f}ms" if first_char_ts else "无输出")
    print(f"总耗时: {(time.time()-t0)*1000:.0f}ms")
    print(f"完整文本: {full}")
