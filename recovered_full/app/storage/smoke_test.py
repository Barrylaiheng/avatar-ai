"""Smoke test：建表 -> DAO CRUD -> 关闭连接重开 -> 验证持久化。

测试用临时目录通过 SCAI_APP_DIR 环境变量隔离，不污染真实 APPDATA。
"""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent   # app/
sys.path.insert(0, str(APP_ROOT))

os.environ.setdefault("SCAI_APP_DIR", str(Path(tempfile.mkdtemp(prefix="scai_test_"))))
TEST_DIR = Path(os.environ["SCAI_APP_DIR"])
print(f"[TEST] 测试目录: {TEST_DIR}")

import storage
from storage import (
    get_conn, reset_db_for_tests,
    get_db_path, DB_FILENAME,
    agents_dao, kb_dao, docs_dao, channels_dao, llm_dao, activation_dao,
)


def step(msg):
    print(f"\n=== {msg} ===", flush=True)


def assert_eq(actual, expected, hint=""):
    if actual != expected:
        raise AssertionError(f"断言失败 {hint}: actual={actual!r}, expected={expected!r}")
    print(f"  OK {hint}")


# ---------- Step 1: 建表 ----------
step("Step1: 触发建表 (首次调用 get_conn)")
conn = get_conn()
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()
table_names = [r[0] for r in tables]
required = {
    "llm_config", "ai_agent", "knowledge_base", "kb_document",
    "channel_connection", "channel_binding", "activation",
}
missing = required - set(table_names)
assert not missing, f"缺少表: {missing}"
print(f"  已建表: {table_names}")

# ---------- Step 2: 激活计数 ----------
step("Step2: 激活 DAO")
s = activation_dao.get_status()
assert_eq(s["trial_used"], 0, "trial_used 初始 0")
assert_eq(s["trial_limit"], 50, "trial_limit 默认 50")
assert_eq(bool(s["activated"]), False, "初始未激活")
assert_eq(activation_dao.can_use_trial(), True, "可以试用")

s = activation_dao.increment_trial_used(3)
assert_eq(s["trial_used"], 3, "试用次数 +3")
s = activation_dao.increment_trial_used(47)
assert_eq(s["trial_used"], 50, "试用次数到 50")
assert_eq(activation_dao.can_use_trial(), False, "达到上限，不可试用")

# 激活流程：用真实本机机器码 + 合法签名（HMAC）
from storage.machine import get_machine_code
from storage.license import (
    generate_license_key, verify_license_key,
    write_license_file, read_license_file, verify_license_file,
)
mc = get_machine_code()
lk = generate_license_key(mc)
assert verify_license_key(lk, mc), "合法激活码校验通过"
assert not verify_license_key(lk, "0000-0000-0000-0000"), "错误机器码校验失败"
assert not verify_license_key("AAAA-BBBB-CCCC-DDDD", mc), "假激活码校验失败"

# 错误机器码应被拒绝
try:
    activation_dao.activate(lk, "0000-0000-0000-0000")
    raise AssertionError("错误机器码应被拒绝")
except ValueError:
    print("  OK 错误机器码被拒绝")

# 假激活码应被拒绝
try:
    activation_dao.activate("AAAA-BBBB-CCCC-DDDD", mc)
    raise AssertionError("假激活码应被拒绝")
except ValueError:
    print("  OK 假激活码被拒绝")

# 合法激活码 + 本机机器码：激活成功 + 写 license.dat
activation_dao.activate(lk, mc)
s = activation_dao.get_status()
assert_eq(bool(s["activated"]), True, "已激活")
assert_eq(s["license_key"], lk, "激活码明文回读")
assert_eq(s["machine_code"], mc, "机器码保存（本机）")
assert_eq(activation_dao.can_use_trial(), True, "激活后可使用")

# license.dat 离线持久化验证
lic = read_license_file()
assert lic is not None, "license.dat 已写入"
assert_eq(lic["machine_code"], mc, "license.dat 机器码一致")
assert_eq(lic["license_key"], lk, "license.dat 激活码一致")
assert verify_license_file(), "离线校验通过（机器码 + 签名匹配）"

# 撤销激活应同步删 license.dat
activation_dao.deactivate()
assert read_license_file() is None, "撤销后 license.dat 已删除"
assert not verify_license_file(), "撤销后离线校验失败"

# ---------- Step 3: LLM 配置（DPAPI 加密） ----------
step("Step3: LLM 配置 DAO")
cfg = llm_dao.upsert({
    "name": "测试配置·深度求索",
    "provider": "DeepSeek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-REAL-KEY-123456",
    "model": "deepseek-chat",
    "is_default": True,
})
# 明文
assert_eq(cfg["api_key"], "sk-REAL-KEY-123456", "DAO 返回 api_key 明文解密正确")

# 验证 DB 里存的是加密后格式（不以 sk- 开头、带 v1:）
row = get_conn().execute('SELECT api_key FROM llm_config WHERE id=?', (cfg["id"],)).fetchone()
assert row["api_key"].startswith("v1:"), f"数据库里未加密: {row['api_key'][:30]!r}..."
assert not row["api_key"].startswith("v1:sk-"), "密文不应是 v1: 拼接明文"

# 更新
cfg2 = llm_dao.upsert({
    "id": cfg["id"],
    "name": "测试配置·更新",
    "provider": "自定义",
    "base_url": "https://my.internal.api/v1",
    "api_key": "sk-NEW-KEY",
    "model": "my-best",
    "is_default": False,
})
assert_eq(cfg2["name"], "测试配置·更新", "配置名已更新")
assert_eq(cfg2["api_key"], "sk-NEW-KEY", "新 api_key 解密正确")

all_cfgs = llm_dao.list_all()
assert any(c["id"] == cfg["id"] for c in all_cfgs), "list_all 可见"

# ---------- Step 4: 智能体 ----------
step("Step4: 智能体 DAO")
ag = agents_dao.create({
    "name": "工作分身",
    "avatar": "💼",
    "description": "处理工作相关事务的数字分身",
    "system_prompt": "你是工作助手，风格专业简洁。",
    "aigc_enabled": 1,
    "kb_ids": ["kb_placeholder_1"],
})
assert ag["name"] == "工作分身" and ag["aigc_enabled"] == 1
ag2 = agents_dao.rename(ag["id"], "商务小助手")
assert_eq(ag2["name"], "商务小助手", "重命名成功")
agents_dao.update(ag["id"], {"aigc_enabled": 0, "kb_ids": []})
assert_eq(agents_dao.get(ag["id"])["aigc_enabled"], 0, "AIGC 开关更新")

# ---------- Step 5: 知识库 + 文档 ----------
step("Step5: 知识库 + 文档 DAO")
kb = kb_dao.create({"name": "工作知识库", "description": "工作相关文档", "icon": "📁"})
d1 = docs_dao.create({
    "kb_id": kb["id"], "name": "产品需求.docx",
    "file_path": "C:/temp/prd.docx", "size_bytes": 10240,
    "status": "pending",
})
d2 = docs_dao.create({
    "kb_id": kb["id"], "name": "会议纪要.pdf",
    "file_path": "C:/temp/mt.pdf", "size_bytes": 4096,
    "status": "pending",
})
docs_dao.update_status(d1["id"], "done", chunk_count=42, error="")
docs_dao.update_status(d2["id"], "failed", chunk_count=0, error="密码保护 PDF")
kb_after = kb_dao.get(kb["id"])
assert_eq(kb_after["doc_count"], 2, "知识库文档计数")
assert_eq(kb_after["chunk_count"], 42, "知识库切片计数（仅 done 的）")

doc_list = docs_dao.list_by_kb(kb["id"])
statuses = {d["name"]: d["status"] for d in doc_list}
assert_eq(statuses, {"产品需求.docx": "done", "会议纪要.pdf": "failed"}, "文档状态")

docs_dao.delete(d2["id"])
kb_after2 = kb_dao.get(kb["id"])
assert_eq(kb_after2["doc_count"], 1, "删除后 doc_count=1")

# 删除知识库应级联清理其下属文档
remaining_doc = docs_dao.get(d1["id"])
assert remaining_doc is not None, "删除知识库前文档仍存在"
ok = kb_dao.delete(kb["id"])
assert_eq(ok, True, "kb_dao.delete 返回 True")
assert kb_dao.get(kb["id"]) is None, "kb 已被删除"
orphan = docs_dao.get(d1["id"])
assert orphan is None, "删除知识库后下属文档被级联清理"

# 重建一个知识库供 Step7 持久化断言
kb = kb_dao.create({"name": "工作知识库", "description": "工作相关文档", "icon": "📁"})
docs_dao.create({
    "kb_id": kb["id"], "name": "产品需求.docx",
    "file_path": "C:/temp/prd.docx", "size_bytes": 10240,
    "status": "done", "chunk_count": 42,
})

# ---------- Step 6: 渠道连接 + 绑定 ----------
step("Step6: 渠道连接 & 绑定")
channels_dao.upsert("wcf", False, {"version": "3.9.8.25"}, error="未启动 WCF")
s = channels_dao.get("wcf")
assert not s["connected"], "WCF 初始未连接"
channels_dao.upsert("wcf", True, {"version": "3.9.8.25", "wxid": "wxid_abcd"})
assert channels_dao.get("wcf")["connected"] == 1

b1 = channels_dao.set_binding(
    agent_id=ag["id"], channel="wcf",
    peer_id="wxid_zhangsan", peer_name="张三", peer_type="friend", enabled=True,
)
b2 = channels_dao.set_binding(
    agent_id=ag["id"], channel="wcf",
    peer_id="wxid_lisi", peer_name="李四", peer_type="friend", enabled=False,
)
bindings = channels_dao.list_bindings(ag["id"], "wcf")
assert len(bindings) == 2, "绑定数量"
assert bindings[0]["peer_id"] == "wxid_zhangsan", "enabled 在前"

# ---------- Step 7: 关闭/重开，验证持久化 ----------
step("Step7: 关闭连接，重建，验证持久化")
reset_db_for_tests()

# 重建连接
conn2 = get_conn()
agents = agents_dao.list_all()
assert any(a["name"] == "商务小助手" for a in agents), "智能体重启后仍存在"

llm = llm_dao.list_all()
assert any(c["name"] == "测试配置·更新" for c in llm), "LLM 配置持久化"
# 再次验证 api_key 解密
saved_cfg = next(c for c in llm if c["name"] == "测试配置·更新")
assert_eq(saved_cfg["api_key"], "sk-NEW-KEY", "重启后 LLM api_key 解密正确")

act = activation_dao.get_status()
assert_eq(act["trial_used"], 50, "重启后试用次数不变")
assert_eq(bool(act["activated"]), False, "重启后激活状态 deactivate 生效")

kbs = kb_dao.list_all()
assert any(k["name"] == "工作知识库" for k in kbs), "知识库持久化"
kb_row = next(k for k in kbs if k["name"] == "工作知识库")
assert_eq(kb_row["doc_count"], 1, "重启后 doc_count=1")

print("\n=== 全部 smoke test 通过 ===\n", flush=True)
print(f"[TEST] 清理临时目录: {TEST_DIR}", flush=True)
# 尝试删除临时 db（Windows 上可能句柄未释放，忽略错误）
try:
    reset_db_for_tests()
    dbp = get_db_path()
    if dbp.exists():
        dbp.unlink(missing_ok=True)
    (TEST_DIR / DB_FILENAME).unlink(missing_ok=True)
except Exception as e:
    print(f"  清理忽略: {e}")
