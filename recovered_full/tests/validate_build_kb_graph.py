# -*- coding: utf-8 -*-
"""
单独跑 _handle_build_kb_graph 端到端验证：
  - 传用户真实 KB 的 id（之前 audit 得到 kb_37b6a555db97 / test）
  - 输出返回的 nodes + edges 汇总表
  - 断言：
      1. nodes 数 > 0
      2. 所有 nodes 的 label 里没有 "智能家电/E1 传感器/三包政策"（证明已经和 mock 划清）
      3. 出现 "test" 核心节点（core）
      4. 至少 3 个 关键词节点 / 实体节点 命中以下任一特征词集合：
         {'三大支柱', '核心特色', '1999元/年', '1999元', 'VIP', '腾讯微信', '字节跳动', '阿里巴巴', '阿凡达AI', 'AI数字分身', '私域'}
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

# 注意：bridge.py import 会拉 PyQt6，会崩溃。所以我们**直接实例化 Bridge 类并传入 _retriever，然后只测 _handle_build_kb_graph 方法**
#      但 Bridge 类 import 的时候就需要 PyQt6，这里用 trick：给 PyQt6 打个 dummy stub 让 import 通过，然后再单独调用 build_kb_graph（其实只用到 dao/db/doc_parser，不依赖 Qt）

import types
_pyqt_mod = types.ModuleType("PyQt6")
_qtcore_mod = types.ModuleType("PyQt6.QtCore")

class DummySignal:
    def __init__(self, *a, **k):
        self._cbs = []
    def connect(self, cb): self._cbs.append(cb)
    def emit(self, *a, **k):
        # print(">>> QObject.emit dummy", a)
        pass

_qtcore_mod.pyqtSignal = DummySignal

def _pyqtSlot(*a, **k):
    def wrap(fn): return fn
    return wrap
_qtcore_mod.pyqtSlot = _pyqtSlot

class DummyQObject:
    def __init__(self, *a, **k): pass

_qtcore_mod.QObject = DummyQObject
_pyqt_mod.QtCore = _qtcore_mod
sys.modules["PyQt6"] = _pyqt_mod
sys.modules["PyQt6.QtCore"] = _qtcore_mod

# 现在 import bridge 就不会炸 PyQt6 了
from bridge import BridgeServer

# 给 BridgeServer 构造最小参数：parent=None（Dummy），但它里面会用到 parent.windowHandle() 的话 —
# _handle_build_kb_graph 不用 parent，所以构造 dummy 即可。
class DummyParent:
    def windowHandle(self): return None
    def close(self): return None

class DummyRetriever:
    def add_text(self, *a, **k): return {"added": True}
    def stats(self): return {}

class DummyPipeline:
    def shutdown(self, *a, **k): pass

class DummyWcf:
    def stop(self): pass

br = BridgeServer.__new__(BridgeServer)
br._retriever = DummyRetriever()
br.pipeline = DummyPipeline()
br.wcf_client = DummyWcf()
br._index_ready = False
br._conv_locks = {}

# --- 开始测 ---
KB_ID = "kb_37b6a555db97"  # 根据 audit_mvp_backend 的结果
result = br._handle_build_kb_graph({"kb_id": KB_ID})
nodes = result["nodes"]
edges = result["edges"]
meta = result["meta"]

print("=" * 80)
print("  🧠 build_kb_graph 真实数据验证")
print("=" * 80)
import json
print(json.dumps(meta, ensure_ascii=False, indent=2))
print()

# --- 按分类打印节点
from collections import defaultdict
by_cat = defaultdict(list)
for n in nodes:
    by_cat[n["category"]].append(n)
for cat in ("core", "chapter", "section", "keyword", "entity"):
    arr = by_cat.get(cat, [])
    print(f"  🏷 {cat:<8s}  × {len(arr):>3d}:  " + "  ".join(f"[{n['label']}]" for n in arr[:16]))
    if len(arr) > 16:
        print(f"                ... 还有 {len(arr)-16} 个")
print()
print(f"  🔗 edges 共 {len(edges)} 条")
print()

# --- 断言检查 ---
all_labels = [n["label"] for n in nodes]
all_text = " ".join(all_labels)

print("=" * 80)
print("  ✅/❌ 断言")
print("=" * 80)

def check(name, cond, fail_msg=""):
    print(f"  {'✅' if cond else '❌'}  {name}" + ("" if cond else f" → {fail_msg}"))
    return cond

ok = True
ok &= check("1. nodes != 0", len(nodes) > 0, f"实际 {len(nodes)} 个")
ok &= check("2. 不再使用前端硬编码的 Graph mock 数据",
            # 真正的"老家电 mock 特征"不是「家电这个词本身」（用户库里本来就有 1 份叫《智能家电客服知识手册》的文档），
            # 而是前端 generateMockGraphData() 里那几条硬编码的 mock label 字面量：
            #   • 「智能家电知识库」这 6 个字（注意是精确 label，不是文档名「智能家电客服知识手册」）
            #   • 「E1 传感器故障」 精确实体 label
            #   • 「开场话术」 精确 section label
            #   • 精确的「第一章 产品概述」「第二章 故障代码」「第三章 客服话术」「第四章 退换货流程」
            all(term not in all_text
                for term in ("智能家电知识库",
                             "E1 传感器故障", "E3 过热保护", "E5 通讯故障",
                             "F2 漏水警报", "H1 化霜保护",
                             "开场话术", "安抚话术",
                             "第一章 产品概述", "第二章 故障代码",
                             "第三章 客服话术", "第四章 退换货流程",
                             "2.1 空调故障", "2.2 洗衣机故障", "2.3 冰箱故障",
                             "1.1 产品线简介", "1.2 型号对照表",
                             "3.1 开场话术", "3.2 安抚话术",
                             "4.1 三包政策",
                             "售后服务 全国联保 24H 响应",
                             "保修期 整机 1 年 核心 3 年")),
            f"实际文本前300字: '{all_text[:300]}'"
            )
ok &= check("3. 存在 core 节点（知识库名）",
            any(n["category"] == "core" for n in nodes),
            "没有 category=core 的节点")

TARGET_WORDS = {"三大支柱", "核心特色", "1999元/年", "1999元", "VIP", "VIP专业版",
                "腾讯微信", "微信事业部", "字节跳动", "AI Lab", "阿里巴巴",
                "阿凡达AI", "AvatarAI", "AI数字分身", "私域", "CEO 林辰", "林辰",
                "苏雪", "陈默", "腾讯", "阿里", "END_MARKER"}
hits = sorted({w for w in TARGET_WORDS if w in all_text})
ok &= check("4. 真实知识内容特征词 ≥ 3 个", len(hits) >= 3,
            f"仅命中 {len(hits)} 个: {hits}")
print(f"     命中特征词列表（{len(hits)} 个）: {hits}")

ENTITY_COUNT = len([n for n in nodes if n["category"] == "entity"])
KEYWORD_COUNT = len([n for n in nodes if n["category"] == "keyword"])
ok &= check(f"5. 关键词+实体 ≥ 10（保证图够丰富）", ENTITY_COUNT + KEYWORD_COUNT >= 10,
            f"keyword={KEYWORD_COUNT} entity={ENTITY_COUNT} 合计 {ENTITY_COUNT+KEYWORD_COUNT}")
print(f"     keyword × {KEYWORD_COUNT}    entity × {ENTITY_COUNT}")

# 核心节点一定要叫 "test" 或知识库真实名
ok &= check("6. core 节点 label=test（用户当前真实 KB 名）",
            any(n["category"] == "core" and n["label"].startswith("test") for n in nodes))

print()
if ok:
    print("🎉 6/6 断言通过 → 后端 build_kb_graph 已与真实 kb_chunk 绑定，已彻底剔除 mock 数据！")
else:
    print("⚠ 有断言失败，请根据上面具体项目定位问题。")

print()
print("[edges 抽样 10 条]")
for e in edges[:10]:
    def _label(xid):
        for n in nodes:
            if n["id"] == xid:
                return n["label"] + f"({n['category']})"
        return xid
    print(f"    · {_label(e['source']):<28s}   ──   {_label(e['target'])}")
