#!/usr/bin/env python3
"""Deterministic source-role and seven-module candidate mapping helpers."""

from __future__ import annotations

import re
from pathlib import Path


MODULES = ("公司概述", "产品介绍", "解决方案", "合作案例", "行业知识与洞察", "FAQ", "其他")
MAPPABLE_ROLE = "客户事实资料"
ROLE_VALUES = (MAPPABLE_ROLE, "写作运营资料", "疑似文章或终稿", "待确认")
STATUS_VALUES = ("机器初判", "已核验", "待确认")
CONFIDENCE_VALUES = ("高", "中", "低")

ROLE_FILENAME_PATTERNS = (
    ("写作运营资料", re.compile(r"文章要求|写作要求|内容要求|content[ _-]*brief|writing[ _-]*brief|seo[ _-]*brief", re.I)),
)
ARTICLE_TITLE_RE = re.compile(r"^(?:how\s+to|what\s+is|why\s+|\d+\s+|best\s+|tips?\s+|guide\s+)", re.I)
ARTICLE_BODY_RE = re.compile(r"\b(?:faq|conclusion|practical takeaway|discuss your|call to action)\b", re.I)

MODULE_TERMS = {
    "公司概述": (
        "company profile", "about us", "established", "founded", "our mission", "our team",
        "公司概述", "公司介绍", "企业介绍", "成立于", "团队", "使命", "全球市场",
    ),
    "产品介绍": (
        "catalog", "product range", "products", "packaging box", "paper box", "gift box",
        "watch box", "jewelry packaging", "foldable box", "specification", "materials & finishes",
        "产品目录", "产品范围", "产品介绍", "包装盒", "规格", "型号", "材料", "工艺",
    ),
    "解决方案": (
        "solution", "custom service", "customization", "one-stop", "design team", "quality control",
        "production process", "sampling", "delivery", "定制服务", "一站式", "解决方案", "设计服务",
        "质量控制", "生产流程", "打样", "交付",
    ),
    "合作案例": (
        "case study", "track record", "successful collaboration", "partnership", "designated supplier",
        "合作案例", "客户案例", "成功案例", "合作经验", "指定供应商", "长期合作",
    ),
    "行业知识与洞察": (
        "industry knowledge", "technical guide", "method", "principle", "standard", "how to choose",
        "行业知识", "行业洞察", "技术说明", "方法", "原理", "标准", "选型",
    ),
    "FAQ": (
        "frequently asked questions", "faq", "q:", "question:", "常见问题", "问答", "问题与回答",
    ),
}


def _search_text(path: Path, chunks: list[tuple[str, str]]) -> tuple[str, str]:
    filename = path.stem.casefold()
    body = "\n".join(text for _, text in chunks[:80])[:50000].casefold()
    return filename, body


def classify_role(path: Path, chunks: list[tuple[str, str]], has_verified_claim: bool = False) -> dict[str, str]:
    if has_verified_claim:
        return {
            "role": MAPPABLE_ROLE,
            "basis": "已有正式Claim回链到该来源",
            "confidence": "高",
            "status": "已核验",
        }
    path_signal = "/".join(path.parts)
    for role, pattern in ROLE_FILENAME_PATTERNS:
        if pattern.search(path_signal):
            return {
                "role": role,
                "basis": "文件名明确表示文章或内容运营要求",
                "confidence": "高",
                "status": "机器初判",
            }
    filename, body = _search_text(path, chunks)
    if ARTICLE_TITLE_RE.search(filename) and len(body) >= 1200 and ARTICLE_BODY_RE.search(body):
        return {
            "role": "疑似文章或终稿",
            "basis": "文件名与正文结构呈现完整文章特征",
            "confidence": "中",
            "status": "待确认",
        }
    return {
        "role": MAPPABLE_ROLE,
        "basis": "位于已确认的客户源资料范围，未命中非事实资料信号",
        "confidence": "中",
        "status": "机器初判",
    }


def _topic(path: Path, module: str) -> str:
    stem = re.sub(r"(?i)\b(?:revised|final|copy|最新版|最终版|整理版)\b", "", path.stem)
    stem = re.sub(r"(?i)\b20\d{2}(?:[-_.]?\d{1,2}){0,2}\b", "", stem)
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" -_")
    if module == "公司概述":
        return "企业概况"
    if module == "解决方案":
        return "定制服务、协作与交付流程"
    if module == "合作案例":
        return "客户合作经验"
    if module == "FAQ":
        return "常见业务问答"
    if module == "行业知识与洞察":
        return f"{stem}相关行业方法与技术说明" if stem else "行业方法与技术说明"
    if module == "产品介绍":
        catalog_name = re.sub(r"(?i)^catalog\s+(?:for|of)\s+", "", stem)
        catalog_name = re.sub(r"(?i)\s+from\s+.+$", "", catalog_name).strip()
        return f"{catalog_name}产品资料" if catalog_name else "产品资料"
    return stem or "待确认主题"


def derive_mappings(
    path: Path,
    chunks: list[tuple[str, str]],
    role: dict[str, str],
    verified_modules: set[str] | None = None,
) -> list[dict[str, str]]:
    verified_modules = verified_modules or set()
    if role["role"] != MAPPABLE_ROLE:
        return []
    filename, body = _search_text(path, chunks)
    product_filename_hint = bool(re.search(r"catalog|product|watch box|jewelry packaging|foldable box|gift box|产品|包装盒", filename, re.I))
    mappings: list[dict[str, str]] = []
    for module, terms in MODULE_TERMS.items():
        filename_hits = [term for term in terms if term in filename]
        body_hits = [term for term in terms if term in body]
        verified = module in verified_modules
        if product_filename_hint and module != "产品介绍" and not verified:
            continue
        minimum_body_hits = 1 if module in {"产品介绍", "FAQ"} else (3 if module == "行业知识与洞察" else 2)
        if not verified and not filename_hits and len(set(body_hits)) < minimum_body_hits:
            continue
        signals: list[str] = []
        if filename_hits:
            signals.append("文件名")
        if body_hits:
            signals.append("已提取正文结构")
        if verified:
            signals.append("已有正式Claim")
        confidence = "高" if verified or (filename_hits and body_hits) else "中"
        mappings.append({
            "module": module,
            "topic": _topic(path, module),
            "basis": " + ".join(signals),
            "confidence": confidence,
            "status": "已核验" if verified else "机器初判",
        })
    if mappings:
        return mappings
    return [{
        "module": "待确认",
        "topic": _topic(path, "其他"),
        "basis": "路径、文件名和已提取正文不足以稳定对应七大模块",
        "confidence": "低",
        "status": "待确认",
    }]


def mapping_status_summary(mappings: list[dict[str, str]], role: dict[str, str]) -> str:
    if not mappings:
        return f"{role['status']}（{role['confidence']}）"
    statuses = {item["status"] for item in mappings}
    if statuses == {"已核验"}:
        return "已核验"
    if "已核验" in statuses:
        return "部分已核验"
    if statuses == {"待确认"}:
        return "待确认（低）"
    confidence = "高" if any(item["confidence"] == "高" for item in mappings) else "中"
    return f"机器初判（{confidence}）"
