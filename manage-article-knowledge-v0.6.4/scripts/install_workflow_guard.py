#!/usr/bin/env python3
"""Merge this skill's synchronous lifecycle hooks; never grant hook trust."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys


def install(config_dir: Path) -> Path:
    script = Path(__file__).resolve().with_name("workflow_guard.py")
    command = subprocess.list2cmdline([sys.executable, str(script), "hook"])
    path = config_dir / "hooks.json"
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError("现有hooks.json格式不正确，保留原文件，请先检查")
    hooks = data.setdefault("hooks", {})
    for event in ("Stop", "Interrupt"):
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"现有{event}钩子格式不正确，保留原文件")
        handler = {"type": "command", "command": command, "commandWindows": command,
                   "timeout": 20 if event == "Stop" else 3,
                   "statusMessage": "检查文章任务是否仍可继续" if event == "Stop" else "保存文章暂停位置"}
        # Update only this exact installed script's handler; retain every other hook.
        found = False
        for group in groups:
            for prior in group.get("hooks", []):
                if prior.get("type") == "command" and str(script) in prior.get("commandWindows", prior.get("command", "")):
                    prior.clear()
                    prior.update(handler)
                    found = True
        if not found:
            groups.append({"hooks": [handler]})
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8-sig") == content:
        return path
    config_dir.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name("hooks.json.mak-backup-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
        shutil.copy2(path, backup)
    from workflow_guard import write
    write(path, data)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=Path.home() / ".codex")
    args = parser.parse_args()
    print(f"hooks_config={install(args.config_dir)}")
    print("钩子配置已写入；仍需Codex加载并信任。未进行信任绕过，客户端实际续跑需单独验收。")
