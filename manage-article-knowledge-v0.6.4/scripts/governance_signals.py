"""Which CUS/ANM categories this article's facts actually touch.

The merged 20 used to need one row for each of the 14 CUS/ANM categories, and
most rows only said "本篇不涉及X".  The gate could check that such a row was
non-empty, not whether the article really did not involve X.  Here the code
looks at what the article will state - the candidate facts, the outline it
covers and where the facts come from - and names the categories with a signal.
A category with a signal needs a real source-backed check row; a category
without one is recorded as not involved by the code itself.

Detection errs towards a signal: a false signal costs one check row, a missed
one lets an unchecked customer fact through.  English words are matched
between non-letters, never with ``\\b`` (Python treats Chinese as word
characters, see SK-V064 known limits).
"""
from __future__ import annotations

import re

CUS = "CUS候选检测"
ANM = "ANM异常检测"


def _words(*terms: str) -> str:
    return "|".join(rf"(?<![A-Za-z]){term}(?![A-Za-z])" for term in terms)


_UNIT = (r"(?:mm|cm|m|km|μm|um|kg|g|mg|t|ml|mL|l|L|℃|°C|°F|%|inch|in|ft|gsm|g/m2|g/m²|w|W|kW|v|V|"
         r"A|Hz|MPa|kPa|psi|pcs|PCS|天|日|周|月|年|小时|分钟|毫米|厘米|米|公斤|千克|克|吨|毫升|升|度|件|个|只|套|箱|托|片)")
NUMBER_RE = re.compile(rf"\d+(?:[.,]\d+)?\s*(?:[-~–至到x×*]\s*\d+(?:[.,]\d+)?\s*)?{_UNIT}(?![A-Za-z])")
DIGIT_RE = re.compile(r"\d")

TEXT_SIGNALS: dict[tuple[str, str], re.Pattern[str]] = {
    (CUS, "客户能力"): re.compile(
        "我们|我司|本公司|公司|工厂|厂家|产能|生产线|设备|团队|研发|定制|代工|提供|可以做|能够|"
        + _words("we", "our", "us", "factory", "capacity", "capabilit(?:y|ies)", "manufactur\\w*",
                 "produc(?:e|es|ed|tion)", "custom\\w*", "OEM", "ODM", "in-house", "offer\\w*", "provid\\w*"),
        re.I),
    (CUS, "规格"): re.compile(
        "规格|尺寸|材质|材料|厚度|重量|容量|承重|克重|型号|参数|"
        + _words("spec\\w*", "size\\w*", "dimension\\w*", "material\\w*", "thickness", "weight", "capacity",
                 "gsm", "model"),
        re.I),
    (CUS, "认证"): re.compile(
        "认证|证书|资质|标准|合规|检测报告|"
        + _words("ISO", "CE", "FDA", "UL", "RoHS", "REACH", "SGS", "BSCI", "FSC", "GRS", "GOTS", "BRC", "LFGB",
                 "certif\\w*", "complian\\w*", "accredit\\w*", "standard\\w*", "approved"),
        re.I),
    (CUS, "案例"): re.compile(
        "案例|合作过|服务过|为.{0,12}(?:提供|生产|定制)|客户包括|品牌客户|"
        + _words("case stud(?:y|ies)", "clients? include", "customers? include", "worked with", "trusted by",
                 "partnered with", "project for"),
        re.I),
    (CUS, "商业条件"): re.compile(
        "起订|起订量|最小订单|价格|报价|费用|成本|单价|交期|交货|货期|付款|账期|质保|保修|售后|运费|样品费|免费|折扣|"
        + _words("MOQ", "minimum order\\w*", "price\\w*", "pricing", "cost\\w*", "quot(?:e|es|ation)",
                 "lead time", "deliver\\w*", "payment", "warrant\\w*", "guarantee\\w*", "shipping", "freight",
                 "sample fee", "free", "discount\\w*", "refund\\w*"),
        re.I),
    (CUS, "公开授权"): re.compile(
        "授权|商标|专利|保密|未公开|独家|内部资料|"
        + _words("licen[cs]\\w*", "trademark\\w*", "patent\\w*", "confidential", "NDA", "exclusive\\w*",
                 "proprietary"),
        re.I),
    (ANM, "版本"): re.compile(
        "版本|新版|旧版|最新|年款|(?:19|20)\\d{2}年|"
        + _words("version\\w*", "v\\d+(?:\\.\\d+)*", "latest", "updated", "new model", "(?:19|20)\\d{2}"),
        re.I),
    (ANM, "残缺与外推"): re.compile(
        "所有|全部|一切|总是|始终|永远|最好|最佳|最强|领先|第一|唯一|保证|确保|完全|绝对|任何|"
        + _words("all", "every", "always", "never", "best", "leading", "only", "unique", "guarantee\\w*",
                 "ensure\\w*", "no\\.? ?1", "fully", "completely") + "|100%",
        re.I),
}


def _hits(pattern: re.Pattern[str], texts: list[str], limit: int = 3) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in pattern.finditer(text):
            word = match.group(0).strip()
            if word and word not in found:
                found.append(word)
            if len(found) >= limit:
                return found
    return found


def detect(fact_texts: list[str], *, sources: list[str], partial_sections: list[str],
           multi_source_sections: list[str], translated_claims: list[str]) -> dict[tuple[str, str], str]:
    """Signal description per (detector, category) that has one.

    ``fact_texts``: what the article will state - candidate fact summaries and the outline labels.
    ``sources``: the candidate source pointers.  ``partial_sections``: outline items marked 部分覆盖.
    ``multi_source_sections``: outline items backed by numeric facts from more than one source.
    ``translated_claims``: adopted Claims whose original evidence is not in the article's language.
    """
    signals: dict[tuple[str, str], str] = {}
    for key, pattern in TEXT_SIGNALS.items():
        found = _hits(pattern, fact_texts)
        if found:
            signals[key] = "命中：" + "、".join(found)
    numbers = _hits(NUMBER_RE, fact_texts)
    if numbers:
        signals[(ANM, "数值与单位")] = "命中：" + "、".join(numbers)
        signals.setdefault((CUS, "规格"), "命中：" + "、".join(numbers))
    elif _hits(DIGIT_RE, fact_texts, 1):
        signals[(ANM, "数值与单位")] = "候选事实或大纲含数字"
    files = sorted({p.split("@", 1)[0] for p in sources if p.startswith("SRC-")})
    visual = sorted({p.split("@", 1)[0] for p in sources if p.startswith("SRC-") and p.endswith("（视觉）")})
    if files:
        signals[(ANM, "提取")] = "来自客户原件：" + "、".join(files[:3])
        signals[(ANM, "定位")] = "来自客户原件：" + "、".join(files[:3])
    if visual:
        signals[(ANM, "OCR")] = "来自客户原件视觉内容：" + "、".join(visual[:3])
    if multi_source_sections:
        signals[(ANM, "来源冲突")] = "同一大纲问题有多个来源：" + "、".join(multi_source_sections[:3])
    if partial_sections:
        signals.setdefault((ANM, "残缺与外推"), "部分覆盖：" + "、".join(partial_sections[:3]))
    if translated_claims:
        signals[(ANM, "翻译与规范化")] = "Claim原文与文章语言不同：" + "、".join(translated_claims[:3])
    return signals


def not_involved_reason(category: str) -> str:
    return f"{category}：代码检测本篇候选事实、大纲和来源未出现该类信号"
