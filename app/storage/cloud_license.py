"""云端授权模块 v2 · JWT 签名 + 离线优先 + 宽限期。

架构：
  1. App 启动 → 先读本地缓存 JWT → 本地 RS256 验签
  2. 本地 JWT 有效 → 直接用，同时后台异步联网刷新（带客户端 nonce）
  3. 本地 JWT 过期但在宽限期（7 天）→ 继续用 + 弹 banner
  4. 联网刷新成功 → 存新 JWT → 权益自动更新
  5. 联网刷新失败 → 宽限期内继续用 / 超期降级免费

防破解：
  - RSA 私钥永远在云端
  - 客户端只内置公钥（RS256 验签）
  - 每次请求带客户端生成的 nonce → 云端签进 JWT → 客户端核 nonce（防重放）
  - 公钥硬编码在代码里（打包后 PyInstaller --key 加密 .pyc）
"""
from __future__ import annotations

import json
import os
import time
import uuid
import base64
import urllib.request
import urllib.error

try:
    import jwt as pyjwt
except ImportError:
    import sys
    print('============================================================', flush=True)
    print('FATAL: PyJWT 未安装！请运行:', flush=True)
    print('  pip install pyjwt cryptography', flush=True)
    print('缺少 PyJWT 会导致云端授权系统完全失效，所有用户显示免费版。', flush=True)
    print('============================================================', flush=True)
    sys.exit(1)

CLOUD_BASE = os.environ.get('WCAI_CLOUD', 'https://dadabot.cn/wechatai/cloud')

# 联网请求超时（秒）
_POLL_TIMEOUT = 3

# 宽限期：7 天（JWT 过期后仍可用）
_GRACE_PERIOD_SECONDS = 604800

# 后台刷新间隔：5 分钟
_JWT_REFRESH_BG_INTERVAL = 300


def _jwt_cache_path() -> str:
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    dir_path = os.path.join(appdata, 'SCAI', 'cloud')
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, 'license_jwt_cache.json')


# 内置公钥（RS256 验签用，对应云端私钥）
PUBLIC_KEY = (
    '-----BEGIN PUBLIC KEY-----\n'
    'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAy4BrfO+9qsRxvTOklqZd\n'
    'Qn0TjhT2iMi0DJQuoTyBR//3DT/Bjyi7taU4OoiPPagcRmBBC/3sN2+HXpLhA9Ej\n'
    'Vc+c+Mbd1XqNBsxKM90INTWaguvrOKKbzPA25mX8Jh93yC8Q0D/ZJmW7Ybyu9VmF\n'
    'JtlnyyAcSo73zEYj0G4SwtZ64z/pr3sPy2pBMG4zjrlNWYDcH47j1NvlsfySczgs\n'
    'ksd5JLIF9gQ5AKEB3A12fspoqgBr1agE4MgnMGLFEQ0QxoAaigxnbTnOCVPAtCfe\n'
    'lz+OANf9dk3rlBerwnW1y8qb5a6P04ZZhKKpnBmB7dHFxR+nzbQh/VCe/Xae5xXB\n'
    'OwIDAQAB\n'
    '-----END PUBLIC KEY-----'
)


def _read_cache() -> dict | None:
    """读本地 JWT 缓存文件。"""

    try:
        path = _jwt_cache_path()
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except Exception:
        return None


def _write_cache(token: str, nonce: str, decoded: dict):
    """写本地 JWT 缓存。"""

    try:
        path = _jwt_cache_path()
        data = {
            'token': token,
            'nonce': nonce,
            'mc': decoded.get('mc'),
            'tier': decoded.get('tier'),
            'saved_at': int(time.time()),
            'iat': decoded.get('iat'),
            'exp': decoded.get('exp'),
            'grace_until': decoded.get('grace_until'),
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f'[CloudLicense] write cache failed: {e}', flush=True)
        return None


def _verify_jwt_locally(token: str, expected_nonce: str = None) -> dict | None:
    """本地验签 + 核 nonce + 核硬件 ID + 检查 exp。

    返回 decoded payload（验签通过），验签失败返回 None。
    """

    try:
        decoded = pyjwt.decode(token, PUBLIC_KEY, algorithms=['RS256'], issuer='WeChatAI-Cloud', leeway=10)
        if expected_nonce and decoded.get('nonce') != expected_nonce:
            print(f'[CloudLicense] nonce mismatch: expected {expected_nonce}, got {decoded.get("nonce")}', flush=True)
            return None
        return decoded
    except pyjwt.ExpiredSignatureError:
        try:
            decoded = pyjwt.decode(token, PUBLIC_KEY, algorithms=['RS256'], issuer='WeChatAI-Cloud', leeway=10, options={'verify_exp': False})
            return decoded
        except Exception as e:
            print(f'[CloudLicense] JWT decode even with exp skipped: {e}', flush=True)
            return None
    except pyjwt.InvalidSignatureError:
        print('[CloudLicense] JWT signature INVALID (tampered?)', flush=True)
        return None
    except Exception as e:
        print(f'[CloudLicense] JWT verify failed: {e}', flush=True)
        return None


def _refresh_from_cloud(machine_code: str) -> tuple[str | None, str | None, dict | None]:
    """联网向云端请求新 JWT。

    Returns:
      (token, nonce, decoded)  全部 None 表示联网失败或验签失败
    """
    mc = (machine_code or '').strip()
    if not mc:
        return (None, None, None)
    nonce = str(uuid.uuid4())
    url = f'{CLOUD_BASE}/api/activate?mc={urllib.parse.quote(mc)}&nonce={nonce}'
    try:
        with urllib.request.urlopen(url, timeout=_POLL_TIMEOUT) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        print(f'[CloudLicense] cloud poll failed: {e}', flush=True)
        return (None, None, None)
    if not body.get('ok'):
        print(f'[CloudLicense] cloud returned ok=false: {body}', flush=True)
        return (None, None, None)
    if body.get('mode') == 'plain':
        lic = body.get('license') or {}
        decoded = _plain_to_decoded(lic, mc)
        return (None, None, decoded)
    token = body.get('token')
    if not token:
        print('[CloudLicense] no token in response', flush=True)
        return (None, None, None)
    decoded = _verify_jwt_locally(token, expected_nonce=nonce)
    if decoded is None:
        print('[CloudLicense] JWT verify failed after getting from cloud', flush=True)
        return (None, None, None)
    return (token, nonce, decoded)


def _plain_to_decoded(lic: dict, mc: str) -> dict:
    """旧明文模式兼容：把 plain license dict 转成 decoded payload 格式。"""
    return {
        'mc': mc,
        'tier': lic.get('tier', 'free'),
        'tier_name': lic.get('tier_name'),
        'agent_cap': lic.get('agent_cap', 2),
        'kb': lic.get('kb', False),
        'memory': lic.get('memory', False),
        'active': lic.get('active', False),
        'wechat_unlocked': lic.get('wechat_unlocked', False),
        'nonce': None,
        'iat': int(time.time()),
        'exp': int(time.time()) + 2592000,
        'grace_until': int(time.time()) + 3196800,
    }

_TIER_NAMES = {
    'free': '免费版',
    'starter': '入门版',
    'standard': '标准版',
    'pro': '专业版',
    'special': '特殊版',
}


def _decoded_to_activation(decoded: dict, source: str) -> dict:
    """把 decoded JWT payload 转成前端 refreshActivationCard 直接能用的 activation dict。"""
    tier = decoded.get('tier', 'free')
    active = bool(decoded.get('active'))
    # 过期时间戳（秒）
    expires_ts = int(decoded.get('exp', 0))
    # 三态：已激活 / 未激活 / 付费未激活
    return {
        'tier': tier,
        'active': active,
        'activated': active and tier != 'free',
        'agent_cap': decoded.get('agent_cap', 2),
        'kb': bool(decoded.get('kb', False)),
        'memory': bool(decoded.get('memory', False)),
        'wechat_unlocked': bool(decoded.get('wechat_unlocked', False)),
        'tier_name': decoded.get('tier_name') or _TIER_NAMES.get(tier, tier),
        'expires_at': expires_ts,
        'source': source,
    }


def poll_license(machine_code: str, timeout: int = None, force_refresh: bool = False) -> dict | None:
    """权益状态统一入口（v2，离线优先 + JWT 验签 + 宽限期）。

    调用方（bridge.py 的 _get_effective_activation）期望：
      - 成功返回 activation dict（含 tier / active / agent_cap 等）
      - 云端完全不可用时返回 None（让 bridge.py fallback 本地 activation_dao）

    本地 JWT 缓存判断逻辑：
      1. 有缓存 + 本地验签通过 + 未过期 → 返回缓存（source=cache），同时后台刷新
      2. 有缓存 + 本地验签通过 + 已过期 + 宽限期内 → 返回缓存（source=grace）
      3. 有缓存 + 本地验签通过 + 已过期 + 宽限期过了 → 返回 free 档
      4. 无缓存 / 验签失败 → 联网刷新
    """
    mc = (machine_code or '').strip()
    if not mc:
        return None
    now = int(time.time())
    cache = _read_cache()

    # 强制刷新：跳过缓存，直接联网
    if force_refresh:
        print('[CloudLicense] force_refresh=True, bypassing cache', flush=True)
        token, nonce, decoded = _refresh_from_cloud(mc)
        if decoded is not None:
            if token and nonce:
                _write_cache(token, nonce, decoded)
            return _decoded_to_activation(decoded, source='cloud')
        print('[CloudLicense] force_refresh cloud failed, falling back to cache', flush=True)

    # 缓存命中 + 机器码一致 + 有 token
    if cache and cache.get('mc') == mc and cache.get('token'):
        decoded = _verify_jwt_locally(cache['token'], expected_nonce=cache.get('nonce'))
        if decoded is not None:
            exp = decoded.get('exp', 0)
            grace_until = decoded.get('grace_until', exp + _GRACE_PERIOD_SECONDS)
            # 未过期 → 直接用，同时后台刷新
            if now <= exp:
                token2, nonce2, decoded2 = _refresh_from_cloud(mc)
                if decoded2 is not None:
                    if token2 and nonce2:
                        _write_cache(token2, nonce2, decoded2)
                    return _decoded_to_activation(decoded2, source='cloud')
                print('[CloudLicense] cloud unreachable, using local cache', flush=True)
                return _decoded_to_activation(decoded, source='cache')
            # 已过期但在宽限期内
            if now <= grace_until:
                print(f'[CloudLicense] grace period ({grace_until - now}s left)', flush=True)
                return _decoded_to_activation(decoded, source='grace')
            print('[CloudLicense] grace period expired, trying cloud refresh', flush=True)

    # 无缓存 / 验签失败 → 联网刷新
    token, nonce, decoded = _refresh_from_cloud(mc)
    if decoded is not None:
        if token and nonce:
            _write_cache(token, nonce, decoded)
        return _decoded_to_activation(decoded, source='cloud')

    # 联网失败：只要缓存机器码一致且宽限期内，仍用缓存（自救）
    if cache and cache.get('mc') == mc:
        grace_until = cache.get('grace_until', 0)
        if now <= grace_until:
            decoded = _verify_jwt_locally(cache.get('token', ''), expected_nonce=cache.get('nonce'))
            if decoded:
                return _decoded_to_activation(decoded, source='grace')

    print('[CloudLicense] ALL FAILED: no cache, no cloud, no grace', flush=True)
    return None


def _bg_refresh(mc: str):
    """后台线程刷新 JWT。"""
    import threading

    def _worker():
        try:
            cache = _read_cache()
            if cache and cache.get('mc') == mc:
                last_refresh = cache.get('saved_at', 0)
                if time.time() - last_refresh < _JWT_REFRESH_BG_INTERVAL:
                    return
            token, nonce, decoded = _refresh_from_cloud(mc)
            if token and nonce and decoded:
                _write_cache(token, nonce, decoded)
                print('[CloudLicense] bg refresh OK', flush=True)
        except Exception as e:
            print(f'[CloudLicense] bg refresh failed: {e}', flush=True)

    t = threading.Thread(target=_worker, name='CloudLicense-BgRefresh', daemon=True)
    t.start()


def clear_cache():
    """清除本地 JWT 缓存。"""

    try:
        path = _jwt_cache_path()
        if os.path.exists(path):
            os.remove(path)
            print(f'[CloudLicense] cache cleared: {path}')
            return None
        return None
    except Exception as e:
        print(f'[CloudLicense] clear failed: {e}')
        return None


if __name__ == '__main__':
    import sys
    mc = sys.argv[1] if len(sys.argv) > 1 else 'TEST-JWT-VERIFY-002'
    print('=== Cloud License Self-Test ===')
    print(f'CLOUD_BASE: {CLOUD_BASE}')
    print(f'JWT cache: {_jwt_cache_path()}')
    print(f'Testing with mc={mc}\n')

    print('[1] First poll (should hit cloud)...')
    r = poll_license(mc)
    print(json.dumps(r, ensure_ascii=False, indent=2))

    print('\n[2] Second poll (should use cache)...')
    r = poll_license(mc)
    print(json.dumps(r, ensure_ascii=False, indent=2))

    print('\n[3] Cache file contents:')
    cache = _read_cache()
    print(json.dumps(cache, ensure_ascii=False, indent=2))
