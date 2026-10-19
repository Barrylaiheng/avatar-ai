"""ASR（语音识别）客户端底座 — 可插拔 Provider 框架。

设计原则：
  - MVP 1.0 只留骨架，不实现具体 API 调用
  - Provider 可插拔：none / azure / aliyun / tencent / openai_whisper / custom
  - 未配置（provider=none）时 transcribe() 返回 ""，由 Pipeline 走占位降级
  - 各 Provider 的 API 调用模板写在注释里，未来开发时直接填

调用方式（Pipeline 侧）：
    from asr_client import transcribe
    text = transcribe(
        audio_path=msg.file_path,          # 本地音频文件路径（WCF 自动下载）
        provider=asr_cfg.get("provider", "none"),
        api_key=asr_cfg.get("api_key", ""),
        endpoint=asr_cfg.get("endpoint", ""),
        model=asr_cfg.get("model", ""),
    )
    if text:
        msg.content = text
    else:
        # 降级：占位提示
        msg.content = "[语音转写失败，请发文字消息]"

音频格式说明：
  - 微信 WCF type=34 语音：silk v3 格式（.silk 文件）
  - 微信 OA voice：silk v3 或 mp3
  - 企微/飞书/钉钉：官方 API 自带转写，不走这里
  - 多数 ASR API 支持 wav/pcm/mp3，silk 需要转码（pydub + ffmpeg）
  - MVP 底座先假设 file_path 可直接喂给 API，转码留给后续开发
"""

from __future__ import annotations

import os
from typing import Optional

# --- Provider 常量 ---
PROVIDER_NONE = "none"
PROVIDER_AZURE = "azure"
PROVIDER_ALIYUN = "aliyun"
PROVIDER_TENCENT = "tencent"
PROVIDER_OPENAI_WHISPER = "openai_whisper"
PROVIDER_CUSTOM = "custom"

SUPPORTED_PROVIDERS = {
    PROVIDER_NONE,
    PROVIDER_AZURE,
    PROVIDER_ALIYUN,
    PROVIDER_TENCENT,
    PROVIDER_OPENAI_WHISPER,
    PROVIDER_CUSTOM,
}


def transcribe(
    audio_path: str,
    provider: str = PROVIDER_NONE,
    api_key: str = "",
    endpoint: str = "",
    model: str = "",
    **kwargs,
) -> str:
    """语音转文字 — 统一入口。

    Args:
        audio_path: 本地音频文件路径（WCF/企微/飞书/钉钉下载到本地的文件）
        provider:   ASR 服务提供商（见 SUPPORTED_PROVIDERS）
        api_key:    API Key / Secret
        endpoint:   API Endpoint URL（部分 provider 需要）
        model:      模型名称（部分 provider 需要）
        **kwargs:   其他 provider 特定参数

    Returns:
        转写文本（成功） 或 空字符串（未配置 / 转写失败）
    """
    if not audio_path or not os.path.isfile(audio_path):
        print(f"[ASR] ⏭️ 跳过: audio_path 无效 ({audio_path})", flush=True)
        return ""

    provider = (provider or PROVIDER_NONE).strip().lower()

    if provider == PROVIDER_NONE or not api_key:
        print(f"[ASR] ⏭️ 跳过: provider=none 或 api_key 未配置", flush=True)
        return ""

    if provider not in SUPPORTED_PROVIDERS:
        print(f"[ASR] ⚠️ 未知 provider={provider}，跳过", flush=True)
        return ""

    # --- 分发到具体 Provider 实现 ---
    try:
        if provider == PROVIDER_AZURE:
            return _transcribe_azure(audio_path, api_key, endpoint, model, **kwargs)
        elif provider == PROVIDER_ALIYUN:
            return _transcribe_aliyun(audio_path, api_key, endpoint, model, **kwargs)
        elif provider == PROVIDER_TENCENT:
            return _transcribe_tencent(audio_path, api_key, endpoint, model, **kwargs)
        elif provider == PROVIDER_OPENAI_WHISPER:
            return _transcribe_openai_whisper(audio_path, api_key, endpoint, model, **kwargs)
        elif provider == PROVIDER_CUSTOM:
            return _transcribe_custom(audio_path, api_key, endpoint, model, **kwargs)
    except Exception as e:
        print(f"[ASR] ❌ provider={provider} 转写失败: {type(e).__name__}: {e}", flush=True)
        return ""

    return ""


# ================================================================
# 各 Provider 实现 — MVP 1.0 留空返回 ""，API 调用模板写在注释里
# ================================================================

def _transcribe_azure(audio_path: str, api_key: str, endpoint: str, model: str, **kwargs) -> str:
    """Azure Speech Service — 语音转文字。

    API 模板（未来开发）：
        import requests
        # 1. 读取音频文件
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        # 2. 调 Azure REST API
        # POST {endpoint}/speech/recognition/conversation/cognitiveservices/v1?language=zh-CN
        # Headers: Ocp-Apim-Subscription-Key: {api_key}, Content-Type: audio/wav
        resp = requests.post(url, headers=headers, data=audio_bytes, timeout=30)
        # 3. 解析 recognitionResult
        return resp.json().get("DisplayText", "")
    """
    print(f"[ASR] Azure 尚未实现（audio={os.path.basename(audio_path)}）", flush=True)
    return ""


def _transcribe_aliyun(audio_path: str, api_key: str, endpoint: str, model: str, **kwargs) -> str:
    """阿里云智能语音 — 一句话识别 / 实时语音识别。

    API 模板（未来开发）：
        # 一句话识别：https://nls-gateway.cn-shanghai.aliyuncs.com/stream/v1/asr
        # 需要 appkey + token（token 由 AccessKey ID/Secret 签名生成）
        # 或使用 DashScope 兼容模式：POST https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation
    """
    print(f"[ASR] 阿里云 尚未实现（audio={os.path.basename(audio_path)}）", flush=True)
    return ""


def _transcribe_tencent(audio_path: str, api_key: str, endpoint: str, model: str, **kwargs) -> str:
    """腾讯云 ASR — 一句话识别。

    API 模板（未来开发）：
        # POST https://asr.tencentcloudapi.com/
        # Action=SentenceRecognition, Version=2019-06-14
        # 需要 SecretId + SecretKey 签名
    """
    print(f"[ASR] 腾讯云 尚未实现（audio={os.path.basename(audio_path)}）", flush=True)
    return ""


def _transcribe_openai_whisper(audio_path: str, api_key: str, endpoint: str, model: str, **kwargs) -> str:
    """OpenAI Whisper / 兼容服务（如 Groq、本地 llama.cpp server）。

    API 模板（未来开发）：
        import requests
        # POST {endpoint}/v1/audio/transcriptions
        # model=whisper-1（或本地模型名）
        # file=@audio_path
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"{endpoint}/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data={"model": model or "whisper-1", "language": "zh"},
                files={"file": f},
                timeout=60,
            )
        return resp.json().get("text", "")
    """
    print(f"[ASR] Whisper 尚未实现（audio={os.path.basename(audio_path)}）", flush=True)
    return ""


def _transcribe_custom(audio_path: str, api_key: str, endpoint: str, model: str, **kwargs) -> str:
    """自定义 ASR endpoint — 用户自部署的模型服务。

    API 模板（未来开发）：
        import requests
        # 假设 endpoint 接受 multipart/form-data: file + model
        with open(audio_path, "rb") as f:
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                files={"file": f},
                data={"model": model} if model else {},
                timeout=60,
            )
        return resp.json().get("text", "") or resp.text.strip()
    """
    print(f"[ASR] Custom 尚未实现（audio={os.path.basename(audio_path)}）", flush=True)
    return ""


# --- 音频格式转换工具（MVP 底座预留，暂不实现） ---
# WCF 微信语音是 silk v3 格式，多数 ASR API 需要 wav/pcm/mp3
# 转码方案：pydub + ffmpeg 或 silk-python
# def convert_audio(src_path: str, dst_fmt: str = "wav") -> Optional[str]:
#     """把 silk/amr/mp3 转成 wav（16kHz mono），返回临时文件路径。"""
#     ...
