#!/usr/bin/env python3
"""Append one compact, validated run record to a project's JSONL ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterator


LEDGER_RELATIVE = Path("05_数据与审核/50_运行记录/项目运行账本.jsonl")
REQUIRED_FIELDS = {
    "schema_version",
    "run_id",
    "project_id",
    "task",
    "status",
    "started_at",
    "ended_at",
    "skill",
    "inputs",
    "read_files",
    "tool_calls",
    "outputs",
    "retry_count",
    "failure_stage",
    "human_intervention",
    "usage",
}
ALLOWED_STATUS = {"success", "partial", "failed", "blocked"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_path(path: str | Path, project_root: Path) -> str:
    candidate = Path(path).expanduser()
    try:
        return candidate.resolve().relative_to(project_root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(candidate)


def file_record(path: str | Path, project_root: Path) -> dict:
    candidate = Path(path).expanduser()
    record = {"path": portable_path(candidate, project_root), "sha256": None}
    if candidate.is_file():
        record["sha256"] = sha256_file(candidate)
    return record


def infer_project_id(project_root: Path) -> str:
    info = project_root / "01_工作台/10_项目基础信息.md"
    if info.is_file():
        text = info.read_text(encoding="utf-8-sig", errors="replace")
        match = re.search(r"(?m)^-?\s*项目ID[：:]\s*(\S+)", text)
        if match:
            return match.group(1).strip()
    return project_root.name.split("_", 1)[0]


def current_skill(skill_file: Path | None = None) -> dict:
    skill_file = skill_file or Path(__file__).resolve().parent.parent / "SKILL.md"
    skill_text = skill_file.read_text(encoding="utf-8-sig", errors="replace") if skill_file.is_file() else ""
    version_match = re.search(r"-v(\d+(?:\.\d+)*)$", skill_file.parent.name)
    if not version_match:
        version_match = re.search(r"(?im)^# .*?\bv(\d+(?:\.\d+)*)\b", skill_text)
    return {
        "name": "manage-article-knowledge",
        "version": f"v{version_match.group(1)}" if version_match else None,
        "sha256": sha256_file(skill_file) if skill_file.is_file() else None,
    }


def make_record(
    *,
    project_root: Path,
    task: str,
    status: str,
    started_at: str | None = None,
    ended_at: str | None = None,
    project_id: str | None = None,
    article_ids: list[str] | None = None,
    inputs: list[str | Path] | None = None,
    read_files: list[str | Path] | None = None,
    tool_calls: list[dict] | None = None,
    outputs: list[str | Path] | None = None,
    retry_count: int = 0,
    failure_stage: str | None = None,
    human_required: bool = False,
    human_reason: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost: float | None = None,
    currency: str | None = None,
    note: str | None = None,
) -> dict:
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of: {', '.join(sorted(ALLOWED_STATUS))}")
    if retry_count < 0:
        raise ValueError("retry_count cannot be negative")
    if human_required and not human_reason:
        raise ValueError("human_reason is required when human_required is true")
    started = started_at or now_iso()
    ended = ended_at or now_iso()
    return {
        "schema_version": 1,
        "run_id": f"RUN-{datetime.now().astimezone():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
        "project_id": project_id or infer_project_id(project_root),
        "article_ids": article_ids or [],
        "task": task,
        "status": status,
        "started_at": started,
        "ended_at": ended,
        "skill": current_skill(),
        "inputs": [file_record(item, project_root) for item in inputs or []],
        "read_files": [file_record(item, project_root) for item in read_files or []],
        "tool_calls": tool_calls or [],
        "outputs": [file_record(item, project_root) for item in outputs or []],
        "retry_count": retry_count,
        "failure_stage": failure_stage,
        "human_intervention": {
            "required": human_required,
            "reason": human_reason,
        },
        "usage": {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "currency": currency,
        },
        "note": note,
    }


def validate_record(record: dict) -> None:
    missing = sorted(REQUIRED_FIELDS - set(record))
    if missing:
        raise ValueError("run record missing fields: " + ", ".join(missing))
    if record["schema_version"] != 1:
        raise ValueError("unsupported run ledger schema_version")
    if record["status"] not in ALLOWED_STATUS:
        raise ValueError("invalid run status")
    if not isinstance(record["human_intervention"], dict):
        raise ValueError("human_intervention must be an object")
    if record["human_intervention"].get("required") and not record[
        "human_intervention"
    ].get("reason"):
        raise ValueError("human intervention reason is required")


@contextmanager
def locked_ledger(ledger_path: Path, timeout_seconds: float = 15.0) -> Iterator[BinaryIO]:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    handle = ledger_path.open("a+b")
    deadline = time.monotonic() + timeout_seconds
    locked = False
    try:
        while not locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("等待项目运行账本写入锁超时")
                time.sleep(0.05)
        handle.seek(0, os.SEEK_END)
        yield handle
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def append_record(project_root: Path, record: dict) -> Path:
    project_root = project_root.expanduser().resolve()
    if not project_root.is_dir():
        raise FileNotFoundError(f"Obsidian项目路径不存在：{project_root}")
    validate_record(record)
    ledger = project_root / LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    with locked_ledger(ledger) as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return ledger


def validate_ledger(path: Path) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
                if not isinstance(record, dict):
                    raise ValueError("record must be an object")
                validate_record(record)
                run_id = str(record["run_id"])
                if run_id in seen:
                    raise ValueError(f"duplicate run_id: {run_id}")
                seen.add(run_id)
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(f"line {line_number}: {exc}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="向项目唯一JSONL运行账本追加一条记录")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--article-id", action="append", default=[])
    parser.add_argument("--task")
    parser.add_argument("--status", choices=sorted(ALLOWED_STATUS))
    parser.add_argument("--started-at")
    parser.add_argument("--ended-at")
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--read-file", action="append", default=[])
    parser.add_argument("--output", action="append", default=[])
    parser.add_argument("--tool-call-json", action="append", default=[])
    parser.add_argument("--retry-count", type=int, default=0)
    parser.add_argument("--failure-stage")
    parser.add_argument("--human-required", action="store_true")
    parser.add_argument("--human-reason")
    parser.add_argument("--model")
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--cost", type=float)
    parser.add_argument("--currency")
    parser.add_argument("--note")
    return parser.parse_args()


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="run-ledger-test-") as temp:
        root = Path(temp) / "DEMO-001_测试项目"
        root.mkdir()
        source = root / "source.txt"
        source.write_text("source", encoding="utf-8")
        record = make_record(
            project_root=root,
            task="self-test",
            status="success",
            inputs=[source],
            read_files=[source],
            outputs=[],
            tool_calls=[{"tool": "test", "version": "1", "parameters": {}}],
        )
        ledger = append_record(root, record)
        append_record(root, make_record(project_root=root, task="self-test-2", status="partial"))
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(
                    append_record,
                    root,
                    make_record(project_root=root, task=f"concurrent-{index}", status="success"),
                )
                for index in range(8)
            ]
            for future in futures:
                future.result()
        errors = validate_ledger(ledger)
        lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line]
        if errors or len(lines) != 10:
            print(json.dumps({"ok": False, "errors": errors, "lines": len(lines)}, ensure_ascii=False))
            return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if not args.project_root or not args.task or not args.status:
        raise SystemExit("--project-root, --task and --status are required")
    tool_calls = [json.loads(item) for item in args.tool_call_json]
    record = make_record(
        project_root=args.project_root,
        project_id=args.project_id,
        article_ids=args.article_id,
        task=args.task,
        status=args.status,
        started_at=args.started_at,
        ended_at=args.ended_at,
        inputs=args.input,
        read_files=args.read_file,
        tool_calls=tool_calls,
        outputs=args.output,
        retry_count=args.retry_count,
        failure_stage=args.failure_stage,
        human_required=args.human_required,
        human_reason=args.human_reason,
        model=args.model,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        cost=args.cost,
        currency=args.currency,
        note=args.note,
    )
    ledger = append_record(args.project_root, record)
    print(
        json.dumps(
            {"ok": True, "ledger": str(ledger), "run_id": record["run_id"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
