"""Atomic file replacement that tolerates short Windows sharing locks."""

from __future__ import annotations

import time
from pathlib import Path


def replace_with_retry(temporary: Path, target: Path, attempts: int = 5, delay: float = 0.4) -> None:
    """Move a finished temporary file over its target.

    Obsidian, OneDrive and antivirus scanners briefly hold Markdown/CSV files
    open on Windows, which makes ``os.replace`` raise PermissionError.  Retry a
    few times; if the target stays locked, remove the temporary file so failed
    writes never leave ``tmp*.tmp`` residue in a project, then re-raise.
    """
    for attempt in range(attempts):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(delay * (attempt + 1))
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
