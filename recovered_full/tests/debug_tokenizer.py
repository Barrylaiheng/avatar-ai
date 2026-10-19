# -*- coding: utf-8 -*-
"""
快速调试 tokenize + entity 抽取：直接读 sample.txt 跑一遍看输出。
"""
import re
from collections import Counter
from pathlib import Path

SAMPLE = Path(r"c:\Users\Administrator\Desktop\WeChatAI_Project\tests\data\kb_format_test\test_intro.txt").read_text(encoding="utf-8")
print("文本总字数：", len(SAMPLE))

_CN_STOPWORDS = set("""
的 了 和 是 在 也 就 都 而 及 与 或 一个 一些 一下 一样 一种 可以 已经 因为 但是 不过
如果 这样 那样 这个 那个 这些 那些 所有 我们 你们 他们 它们 自己 什么 怎么 为什么 因此
以及 对于 关于 然后 还有 同时 并且 不是 不会 不能 不要 没有 进行 通过 提供 包含 拥有
基于 根据 目前 现在 之前 之后 比如 例如 其中 以及 以及
""".split())
_EN_STOPWORDS = {"the", "and", "for", "with", "you", "that", "this", "from", "have", "are",
                 "was", "were", "been", "will", "would", "your", "our", "its", "they", "their"}

def _tokenize(text):
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
                    if all(ch in BAD_CN_CHARS for ch in ngram):
                        continue
                    if sum(1 for ch in ngram if ch in BAD_CN_CHARS) * 2 > len(ngram):
                        continue
                    if "\u4e00" <= ngram[0] <= "\u9fff":
                        toks.append(ngram)
    return toks

toks = _tokenize(SAMPLE)
print(f"token 数: {len(toks)}")
tf = Counter(toks)
print()
print("Top 50 tokens:")
for tok, cnt in tf.most_common(50):
    print(f"    {cnt:>3d}  {tok}")

print()
TARGETS = {"三大支柱", "核心特色", "1999元/年", "1999元", "VIP专业版", "腾讯微信事业部",
           "字节跳动", "阿里巴巴", "AI数字分身", "私域运营", "阿凡达AI", "AvatarAI"}
for t in TARGETS:
    hit = f"✅ tf={tf[t]}" if tf[t] > 0 else "❌"
    print(f"  {t:<20s}  {hit}")

print()
print("实体抽取")
text = SAMPLE
found = []
for m in re.finditer(r"¥?\s*\d+(?:\.\d+)?\s*元(?:/[年月天])?", text):
    found.append((m.group(0).replace(" ", ""), "price"))
for suffix in ("公司", "集团", "事业部", "实验室", "Lab", "LAB", "团队", "大学", "学院",
               "研究院", "中科院", "清华", "北大", "浙大"):
    p = re.compile(rf"[\u4e00-\u9fffA-Za-z]{{2,10}}?{re.escape(suffix)}")
    for m in p.finditer(text):
        found.append((m.group(0), "org_suffix"))
for m in re.finditer(r"(CEO|CTO|CPO|创始人|创始人之一|首席执行官|首席技术官|首席产品官)\s*([\u4e00-\u9fff]{2,4})", text):
    found.append((m.group(2), "person"))
for org in ("腾讯", "微信", "阿里", "阿里巴巴", "淘宝", "字节跳动", "抖音", "火山引擎",
            "快手", "百度", "京东", "小米", "华为", "美团", "拼多多", "滴滴", "网易",
            "蚂蚁金服", "蚂蚁集团", "微信事业部", "AI Lab", "用户增长团队"):
    if org in text:
        found.append((org, "org_whitelist"))
seen = set()
uniq = []
for label, cat in found:
    k = (label, cat)
    if len(label) < 2: continue
    if k in seen: continue
    seen.add(k)
    uniq.append(k)
    print(f"    [{cat:<14s}]  {label}")
print(f"共 {len(uniq)} 个实体")

sections = []
seen_sec = set()
pat_zh = re.compile(r"第[一二三四五六七八九十百]+[章节]\s*.{0,26}?")
for m in pat_zh.finditer(text):
    s = m.group(0).strip()
    for sep in "。，；;,.\n":
        if sep in s: s = s.split(sep)[0]
    s = re.sub(r"\s+", " ", s).strip()[:22]
    if len(s) >= 2 and s not in seen_sec:
        seen_sec.add(s)
        sections.append(s)
print()
print("章节标题 sections:")
for x in sections[:15]: print(f"   · {x}")
print(f"共 {len(sections)} 条")
