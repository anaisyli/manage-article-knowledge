#!/usr/bin/env python3
"""Append one compact per-step token usage record to a project JSONL file."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterator


LEDGER_RELATIVE = Path("05_数据与审核/50_运行记录/token_usage.jsonl")
ALLOWED_STATUS = {"success", "partial", "failed", "unknown"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def locked_append(path: Path, timeout_seconds: float = 10.0) -> Iterator[BinaryIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
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
                    raise TimeoutError("等待token用量账本写入锁超时")
                time.sleep(0.02)
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


def make_record(
    *, project_id: str, step: str, input_tokens: int | None, output_tokens: int | None,
    model: str | None, reasoning_effort: str | None, status: str,
    run_id: str | None, article_id: str | None,
    note: str | None,
) -> dict:
    if not project_id.strip() or not step.strip():
        raise ValueError("project_id and step are required")
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of: {', '.join(sorted(ALLOWED_STATUS))}")
    for name, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
        if value is not None and value < 0:
            raise ValueError(f"{name} cannot be negative")
    return {
        "schema_version": 1,
        "record_id": f"TOK-{datetime.now().astimezone():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
        "recorded_at": now_iso(),
        "project_id": project_id.strip(),
        "article_id": article_id,
        "run_id": run_id,
        "step": step.strip(),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": (input_tokens + output_tokens)
        if input_tokens is not None and output_tokens is not None else None,
        "status": status,
        "note": note,
    }


def append_record(project_root: Path, record: dict) -> Path:
    project_root = project_root.expanduser().resolve()
    if not project_root.is_dir():
        raise FileNotFoundError(f"项目根目录不存在：{project_root}")
    ledger = project_root / LEDGER_RELATIVE
    line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    with locked_append(ledger) as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return ledger


def validate_ledger(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"missing ledger: {path}"]
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid JSON ({exc})")
                continue
            for field in ("schema_version", "record_id", "recorded_at", "project_id", "step", "status"):
                if not item.get(field):
                    errors.append(f"line {line_number}: missing {field}")
            if item.get("status") not in ALLOWED_STATUS:
                errors.append(f"line {line_number}: invalid status")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--article-id")
    parser.add_argument("--run-id")
    parser.add_argument("--step")
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"))
    parser.add_argument("--status", choices=sorted(ALLOWED_STATUS), default="success")
    parser.add_argument("--note")
    return parser.parse_args()


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="token-usage-test-") as temp:
        root = Path(temp) / "DEMO-001"
        root.mkdir()
        append_record(root, make_record(
            project_id="DEMO-001", step="索引", input_tokens=10,
            output_tokens=3, model="test", reasoning_effort="high", status="success", run_id=None,
            article_id=None, note=None,
        ))
        append_record(root, make_record(
            project_id="DEMO-001", step="未知步骤", input_tokens=None,
            output_tokens=None, model=None, reasoning_effort=None, status="unknown", run_id=None,
            article_id=None, note="provider did not return usage",
        ))
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(
                    append_record,
                    root,
                    make_record(
                        project_id="DEMO-001", step=f"concurrent-{index}",
                        input_tokens=index, output_tokens=1, model="test",
                        reasoning_effort="low", status="success", run_id="RUN-1",
                        article_id=None, note=None,
                    ),
                )
                for index in range(8)
            ]
            for future in futures:
                future.result()
        errors = validate_ledger(root / LEDGER_RELATIVE)
        line_count = len((root / LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines())
        if errors or line_count != 10:
            if line_count != 10:
                errors.append(f"expected 10 records, found {line_count}")
            print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False))
            return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if not args.project_root or not args.project_id or not args.step:
        raise SystemExit("--project-root, --project-id and --step are required")
    record = make_record(
        project_id=args.project_id, step=args.step,
        input_tokens=args.input_tokens, output_tokens=args.output_tokens,
        model=args.model, reasoning_effort=args.reasoning_effort,
        status=args.status, run_id=args.run_id,
        article_id=args.article_id, note=args.note,
    )
    ledger = append_record(args.project_root, record)
    print(json.dumps({"ok": True, "ledger": str(ledger), "record_id": record["record_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TimeoutError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
