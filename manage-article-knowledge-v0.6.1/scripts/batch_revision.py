"""Retire article-scoped checkpoints when a committed batch run changes.

History is audit data only. Neither the synchronizer nor the material renderer
reads it as current evidence. Shared rows retain their other article links.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def identity(article: dict[str, Any]) -> tuple[str, ...]:
    return (str(article.get("article_version", "")).lstrip("vV"),
            str(article.get("revision_mode", "")),
            str(article.get("research_run_id", "")),
            str(article.get("refresh_run_id", "")))


def retire_previous_run(payload: dict[str, Any], request: dict[str, Any]) -> bool:
    article_id = str(request.get("article_id", ""))
    previous = [row for row in payload.get("articles", []) if row.get("article_id") == article_id]
    if len(previous) > 1:
        raise ValueError(f"批次有重复文章成员：{article_id}；未覆盖账本")
    if not previous or request.get("revision_mode") == "knowledge_reuse_rewrite":
        return False
    old = previous[0]
    changed = identity(old) != identity(request)
    current_run = str(request.get("refresh_run_id") or request.get("research_run_id") or payload["batch_id"])
    run_id = str(old.get("refresh_run_id") or old.get("research_run_id") or payload["batch_id"])
    arrays = ("evidence", "capture_inbox", "source_reads", "questions")
    for key in arrays:
        if not isinstance(payload.get(key, []), list):
            raise ValueError(f"批次{key}必须是数组；未覆盖账本")
    if not isinstance(payload.get("run_history", []), list):
        raise ValueError("批次run_history必须是数组；未覆盖账本")

    def owners(row: dict[str, Any]) -> list[str]:
        if not isinstance(row, dict):
            raise ValueError("批次检查点必须是对象；未覆盖账本")
        if row.get("article_id"):
            return [str(row["article_id"])]
        if "article_ids" in row:
            if not isinstance(row["article_ids"], list):
                raise ValueError("检查点article_ids必须是数组；未覆盖账本")
            return list(row["article_ids"])
        # Old source-read checkpoints did not always carry article_ids.
        # Infer only from the same recorded source/run, never from a title.
        linked = {str(aid) for item in [*payload.get("evidence", []), *payload.get("capture_inbox", [])]
                  if item.get("retrieval_run_id") == row.get("retrieval_run_id")
                  and item.get("source_path_or_url") == row.get("source_path_or_url")
                  and item.get("source_sha256") == row.get("source_sha256")
                  for aid in (item.get("article_ids") or [item.get("article_id")]) if aid}
        if linked:
            return sorted(linked)
        if row.get("retrieval_run_id") == run_id:
            matching = [str(a["article_id"]) for a in payload.get("articles", [])
                        if str(a.get("refresh_run_id") or a.get("research_run_id") or payload["batch_id"]) == run_id]
            if len(matching) == 1:
                return matching
            raise ValueError("旧来源读取记录无法唯一归属文章；保留原账本，先核对来源与运行关联")
        return []

    retired: dict[str, Any] = {"article": deepcopy(old), "retired_at": datetime.now(timezone.utc).isoformat(),
                               "reason": "提交新版本或修复已提交成员遗留的旧运行记录，非当前记录退出活动区", "superseded_by": deepcopy(request)}
    updates = {}
    for key in arrays:
        active, saved = [], []
        for row in payload.get(key, []):
            if not isinstance(row, dict):
                raise ValueError("批次检查点必须是对象；未覆盖账本")
            row_run = str(row.get("retrieval_run_id") or "")
            stale = (changed if key == "questions" else row_run != current_run and (changed or bool(row_run)))
            if not stale:
                active.append(row)
                continue
            linked = owners(row)
            if article_id not in linked:
                active.append(row)
                continue
            saved.append(deepcopy(row))
            remaining = [aid for aid in linked if aid != article_id]
            if remaining:
                copy = deepcopy(row)
                copy.pop("article_id", None)
                copy["article_ids"] = remaining
                active.append(copy)
        retired[key] = saved
        updates[key] = active
    if not changed and not any(retired[key] for key in arrays):
        return False
    retired["retired_run_ids"] = sorted({str(row["retrieval_run_id"]) for key in arrays for row in retired[key] if row.get("retrieval_run_id")})
    payload.setdefault("run_history", []).append(retired)
    payload.update(updates)
    payload["status"] = "evidence_incomplete" if payload.get("evidence") else "collecting_requests"
    payload.pop("validation_errors", None)
    payload.pop("capture_sync_errors", None)
    return True
