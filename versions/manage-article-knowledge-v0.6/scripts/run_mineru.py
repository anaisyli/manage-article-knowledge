#!/usr/bin/env python3
"""Call MinerU's official API and archive one on-demand technical extraction."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from record_project_run import append_record, make_record


TOKEN_ENV = "MINERU_API_TOKEN"
TOKEN_ENV_COMPAT = "MINERU_TOKEN"
EXPIRES_ENV = "MINERU_API_EXPIRES_ON"
STATE_DIR_ENV = "MANAGE_ARTICLE_KNOWLEDGE_STATE_DIR"
DEFAULT_API_BASE = "https://mineru.net/api/v4"
SOURCE_HEADER = "manage-article-knowledge"
STATUS_SCHEMA_VERSION = 1
CODEX_EXTRACTION_RELATIVE = Path("02_源资料/20_MinerU按需提取")
REMOTE_SCHEMES = ("http://", "https://", "data:", "mailto:", "#")
IMAGE_LINK_RE = re.compile(r"(!\[[^\]]*\]\()([^\r\n)]+)(\))")
FINAL_STATES = {"done", "failed"}
API_REQUEST_RETRY_DELAYS = (2.0, 5.0)
class MinerUError(RuntimeError):
    def __init__(self, message: str, stage: str, *, retryable: bool = False):
        super().__init__(message)
        self.stage = stage
        self.retryable = retryable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .")
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned[:120] or "MinerU提取稿"


def resolve_token() -> tuple[str | None, str | None]:
    for name in (TOKEN_ENV, TOKEN_ENV_COMPAT):
        token = os.environ.get(name, "").strip()
        if token:
            return token, name
    return None, None


def status_file_paths() -> list[Path]:
    configured = os.environ.get(STATE_DIR_ENV, "").strip()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured) / "mineru-api-status.json")
    candidates.append(Path(tempfile.gettempdir()) / "manage-article-knowledge" / "mineru-api-status.json")
    if local_app_data:
        candidates.append(Path(local_app_data) / "manage-article-knowledge" / "mineru-api-status.json")

    unique = []
    for path in candidates:
        if path not in unique:
            unique.append(path)
    return unique


def status_file_path() -> Path:
    return status_file_paths()[0]


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def load_status() -> dict:
    for path in status_file_paths():
        try:
            if not path.is_file():
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except (OSError, json.JSONDecodeError):
            continue
    return {"schema_version": STATUS_SCHEMA_VERSION}


def save_status(status: dict) -> Path | None:
    clean = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "token_fingerprint": status.get("token_fingerprint"),
        "expires_on": status.get("expires_on"),
        "reminders": status.get("reminders", {}),
        "last_online_check": status.get("last_online_check"),
        "last_online_failure": status.get("last_online_failure"),
    }
    for path in status_file_paths():
        temporary = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, path)
            return path
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return None


def parse_expiry(raw: str | None) -> tuple[date | None, str | None]:
    value = (raw or "").strip()
    if not value:
        return None, "未设置到期日"
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, f"到期日格式不正确：{value}；应为YYYY-MM-DD"


def expiry_status(*, mark_reminder: bool = False, today: date | None = None) -> dict:
    today = today or date.today()
    raw = os.environ.get(EXPIRES_ENV)
    expires_on, error = parse_expiry(raw)
    result = {
        "expires_on": expires_on.isoformat() if expires_on else None,
        "days_remaining": (expires_on - today).days if expires_on else None,
        "level": "unknown",
        "reminder_due": False,
        "message": error,
    }
    if not expires_on:
        return result
    days = result["days_remaining"]
    if days < 0:
        result.update(level="expired", reminder_due=True, message="MinerU API Token已过期，请更换后再自动解析")
        return result
    if days <= 1:
        threshold = "1-day"
        level = "urgent"
        message = "MinerU API Token将在1天内到期，请立即更换；更换前不要开启大批量解析"
    elif days <= 7:
        threshold = "7-day"
        level = "warning"
        message = "MinerU API Token将在7天内到期，请API负责人安排更换"
    else:
        result.update(level="ok", message="MinerU API Token未临近到期")
        return result
    status = load_status()
    reminders = status.get("reminders") if isinstance(status.get("reminders"), dict) else {}
    reminder_key = f"{expires_on.isoformat()}:{threshold}"
    due = reminder_key not in reminders
    result.update(level=level, reminder_due=due, message=message)
    if mark_reminder and due:
        reminders[reminder_key] = datetime.now().astimezone().isoformat(timespec="seconds")
        status["reminders"] = reminders
        status["expires_on"] = expires_on.isoformat()
        save_status(status)
    return result


def classify_failure(exc: MinerUError, stage: str) -> str:
    text = str(exc).casefold()
    if stage == "token-check":
        return "credential-missing-or-expired"
    if "winerror 10013" in text or "访问套接字" in text:
        return "codex-network-permission"
    if any(item in text for item in ("401", "unauthorized", "token", "鉴权", "认证")):
        return "credential-invalid"
    if "429" in text or "quota" in text or "rate" in text or "额度" in text:
        return "quota-or-rate-limit"
    if stage == "file-upload" and "403" in text:
        return "upload-signature-or-clock"
    if exc.retryable:
        return "temporary-network-or-service"
    if stage in {"basic-quality-check", "asset-check", "output-discovery"}:
        return "output-quality"
    if stage in {"api-submit", "api-poll", "result-download", "file-upload"}:
        return "api-or-file-processing"
    return "local-workflow"


FAILURE_TYPE_LABELS = {
    "credential-missing-or-expired": "Token缺失或已过期",
    "credential-invalid": "Token鉴权失败",
    "quota-or-rate-limit": "额度或频率限制",
    "codex-network-permission": "Codex网络权限未授权",
    "temporary-network-or-service": "临时网络或服务故障",
    "upload-signature-or-clock": "上传签名或系统时间异常",
    "output-quality": "提取结果质量不足",
    "api-or-file-processing": "API或文件处理失败",
    "local-workflow": "本地流程或输入问题",
}


FAILURE_STAGE_LABELS = {
    "input-check": "输入检查", "token-check": "Token检查", "api-submit": "提交解析任务",
    "api-poll": "等待解析结果", "result-download": "下载解析结果", "output-discovery": "查找解析文件",
    "archive": "归档解析结果", "file-upload": "上传文件", "basic-quality-check": "基础质量检查",
    "asset-check": "附件检查",
}


def source_page_count(input_file: Path, explicit: int | None = None) -> int | None:
    if explicit is not None:
        return explicit
    if input_file.suffix.casefold() == ".pptx":
        try:
            with zipfile.ZipFile(input_file) as archive:
                return sum(
                    1
                    for name in archive.namelist()
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", name, flags=re.I)
                ) or None
        except (OSError, zipfile.BadZipFile):
            return None
    if input_file.suffix.casefold() == ".pdf":
        for module_name in ("pypdf", "PyPDF2"):
            try:
                module = __import__(module_name, fromlist=["PdfReader"])
                return len(module.PdfReader(str(input_file)).pages)
            except (ImportError, OSError, ValueError):
                continue
            except Exception:
                return None
    return None


class MinerUApi:
    def __init__(
        self,
        token: str,
        base_url: str,
        request_timeout: int = 120,
        *,
        retry_submit: bool = False,
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self.retry_submit = retry_submit

    @staticmethod
    def _safe_error_body(exc: HTTPError) -> str:
        try:
            raw = exc.read(4096).decode("utf-8", errors="replace")
            body = json.loads(raw)
            return str(body.get("msg") or body.get("message") or f"HTTP {exc.code}")
        except Exception:
            return f"HTTP {exc.code}"

    def _json_request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "source": SOURCE_HEADER,
        }
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        last_error: MinerUError | None = None
        retry_delays = API_REQUEST_RETRY_DELAYS if method == "GET" or self.retry_submit else ()
        for attempt in range(len(retry_delays) + 1):
            request = Request(url, data=data, headers=headers, method=method)
            try:
                with urlopen(request, timeout=self.request_timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                retryable = exc.code == 429 or exc.code >= 500
                last_error = MinerUError(
                    f"HTTP {exc.code}：{self._safe_error_body(exc)}",
                    "api-request",
                    retryable=retryable,
                )
                if not retryable:
                    raise last_error from exc
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = MinerUError(
                    f"MinerU API连接失败：{exc}",
                    "api-request",
                    retryable=True,
                )
            else:
                if body.get("code", 0) == 0:
                    return body
                code = body.get("code")
                message = body.get("msg") or "unknown API error"
                retryable = str(code) in {"-10005", "-60008"}
                last_error = MinerUError(
                    f"MinerU API错误 {code}：{message}",
                    "api-request",
                    retryable=retryable,
                )
                if not retryable:
                    raise last_error

            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
        assert last_error is not None
        raise last_error

    def submit_file(self, input_file: Path, options: dict) -> str:
        file_entry = {"name": input_file.name}
        if options.get("ocr") is not None:
            file_entry["is_ocr"] = options["ocr"]
        if options.get("pages"):
            file_entry["page_ranges"] = options["pages"]
        payload = {
            "files": [file_entry],
            "model_version": options["model"],
            "enable_formula": options["formula"],
            "enable_table": options["table"],
        }
        if options.get("language"):
            payload["language"] = options["language"]
        body = self._json_request("POST", "/file-urls/batch", payload)
        try:
            batch_id = body["data"]["batch_id"]
            upload_url = body["data"]["file_urls"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise MinerUError("MinerU没有返回有效上传地址", "api-submit") from exc
        self.upload(upload_url, input_file)
        return str(batch_id)

    def upload(self, upload_url: str, input_file: Path) -> None:
        parsed = urlparse(upload_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise MinerUError("MinerU返回了无效上传地址", "file-upload")
        connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        data = input_file.read_bytes()
        last_error: MinerUError | None = None
        for attempt in range(len(API_REQUEST_RETRY_DELAYS) + 1):
            connection: http.client.HTTPConnection | None = None
            try:
                connection = connection_class(parsed.hostname, parsed.port, timeout=600)
                connection.request("PUT", target, body=data, headers={"Content-Length": str(len(data))})
                response = connection.getresponse()
                if response.status >= 300:
                    response.read(4096)
                    last_error = MinerUError(
                        f"文件上传失败：HTTP {response.status}",
                        "file-upload",
                        retryable=response.status == 429 or response.status >= 500,
                    )
                    if not last_error.retryable:
                        raise last_error
                else:
                    response.read()
                    return
            except MinerUError:
                if last_error is not None and not last_error.retryable:
                    raise
            except (HTTPError, URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
                last_error = MinerUError(f"文件上传失败：{exc}", "file-upload", retryable=True)
            finally:
                if connection is not None:
                    connection.close()
            if attempt < len(API_REQUEST_RETRY_DELAYS):
                time.sleep(API_REQUEST_RETRY_DELAYS[attempt])
        assert last_error is not None
        raise last_error

    def get_batch(self, batch_id: str) -> list[dict]:
        body = self._json_request("GET", f"/extract-results/batch/{batch_id}")
        try:
            return list(body["data"].get("extract_result", []))
        except (KeyError, TypeError) as exc:
            raise MinerUError("MinerU返回了无法识别的任务状态", "api-poll") from exc

    def wait(self, batch_id: str, timeout: int) -> dict:
        deadline = time.monotonic() + timeout
        interval = 2.0
        while True:
            results = self.get_batch(batch_id)
            if results:
                item = results[0]
                state = str(item.get("state", "unknown"))
                if state in FINAL_STATES:
                    if state == "failed":
                        reason = item.get("err_msg") or item.get("err_code") or "unknown error"
                        raise MinerUError(f"MinerU解析失败：{reason}", "api-poll")
                    if not item.get("full_zip_url"):
                        raise MinerUError("MinerU任务完成但没有返回结果下载地址", "result-download")
                    return item
            if time.monotonic() >= deadline:
                raise MinerUError(f"等待MinerU完成超过{timeout}秒", "api-poll", retryable=True)
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
            interval = min(interval * 1.7, 30.0)

    def download_zip(self, url: str) -> bytes:
        last_error: MinerUError | None = None
        for attempt in range(len(API_REQUEST_RETRY_DELAYS) + 1):
            try:
                with urlopen(Request(url, method="GET"), timeout=600) as response:
                    return response.read()
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = MinerUError(f"MinerU结果下载失败：{exc}", "result-download", retryable=True)
            if attempt < len(API_REQUEST_RETRY_DELAYS):
                time.sleep(API_REQUEST_RETRY_DELAYS[attempt])
        assert last_error is not None
        raise last_error


def make_health_check_pdf(path: Path) -> None:
    """Create a tiny one-page PDF without third-party packages or customer content."""
    stream = b"BT /F1 14 Tf 72 760 Td (MinerU API health check) Tj 0 -24 Td /F1 10 Tf (No customer data.) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode("ascii"))
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(data)


def current_health_status(token: str) -> dict:
    status = load_status()
    expected = token_fingerprint(token)
    check = status.get("last_online_check") if isinstance(status.get("last_online_check"), dict) else None
    if not check or status.get("token_fingerprint") != expected:
        return {"current_month_passed": False, "last_online_check": check}
    checked_at = str(check.get("checked_at") or "")
    current_month = date.today().strftime("%Y-%m")
    return {
        "current_month_passed": check.get("ok") is True and checked_at.startswith(current_month),
        "last_online_check": check,
    }


def run_health_check(args: argparse.Namespace, api: MinerUApi | None = None) -> int:
    token, _ = resolve_token()
    if api is not None and not token:
        token = "self-test-token"
    expiry = expiry_status(mark_reminder=args.mark_reminder)
    if not token:
        emit({
            "ok": False,
            "check": "MinerU API在线健康检查",
            "failure_type": "credential-missing-or-expired",
            "expiry": expiry,
            "message": f"没有读取到{TOKEN_ENV}；请配置后完全重启Codex",
        }, error=True)
        return 2
    if expiry["level"] == "expired":
        emit({
            "ok": False,
            "check": "MinerU API在线健康检查",
            "failure_type": "credential-missing-or-expired",
            "expiry": expiry,
            "message": "Token已过期，未发送测试文件",
        }, error=True)
        return 2
    cached = current_health_status(token)
    if cached["current_month_passed"] and not args.force:
        emit({
            "ok": True,
            "check": "MinerU API在线健康检查",
            "reused_current_month_result": True,
            "expiry": expiry,
            "last_online_check": cached["last_online_check"],
            "message": "本机本月已通过在线检查，无需重复消耗测试额度",
        })
        return 0
    if api is None:
        api = MinerUApi(token, args.api_base, args.request_timeout, retry_submit=True)
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    failure_type = None
    try:
        with tempfile.TemporaryDirectory(prefix="manage-article-knowledge-mineru-health-") as temp:
            test_pdf = Path(temp) / "mineru_api_health_check.pdf"
            make_health_check_pdf(test_pdf)
            batch_id = api.submit_file(test_pdf, {
                "model": "pipeline", "ocr": False, "formula": False,
                "table": False, "language": "en", "pages": "1",
            })
            result = api.wait(batch_id, args.timeout)
            zip_data = api.download_zip(str(result["full_zip_url"]))
            output = Path(temp) / "result"
            output.mkdir()
            safe_extract_zip(zip_data, output)
            selected, _ = choose_markdown(output, test_pdf)
            content = selected.read_text(encoding="utf-8-sig", errors="replace")
            if "MinerU API health check" not in content:
                raise MinerUError("在线测试返回内容无法对应测试PDF", "basic-quality-check")
        checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
        status = load_status()
        status.update({
            "token_fingerprint": token_fingerprint(token),
            "expires_on": expiry.get("expires_on"),
            "last_online_check": {"checked_at": checked_at, "ok": True, "api_version": "v4"},
            "last_online_failure": None,
        })
        save_status(status)
        emit({
            "ok": True,
            "check": "MinerU API在线健康检查",
            "reused_current_month_result": False,
            "expiry": expiry,
            "checked_at": checked_at,
            "duration_seconds": round((datetime.fromisoformat(checked_at) - datetime.fromisoformat(started)).total_seconds(), 1),
            "message": "Token、上传、解析和下载均正常；测试文件和结果已删除",
        })
        return 0
    except MinerUError as exc:
        stage = exc.stage
        failure_type = classify_failure(exc, stage)
        checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
        status = load_status()
        status.update({
            "token_fingerprint": token_fingerprint(token),
            "expires_on": expiry.get("expires_on"),
            "last_online_failure": {
                "checked_at": checked_at, "ok": False,
                "failure_type": failure_type, "failure_stage": stage,
            },
        })
        save_status(status)
        emit({
            "ok": False,
            "check": "MinerU API在线健康检查",
            "failure_type": failure_type,
            "failure_stage": stage,
            "expiry": expiry,
            "message": str(exc),
        }, error=True)
        return 3 if failure_type in {"temporary-network-or-service", "codex-network-permission"} else 2


def safe_extract_zip(data: bytes, destination: Path) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = destination.resolve()
            for info in archive.infolist():
                target = (destination / PurePosixPath(info.filename)).resolve()
                try:
                    target.relative_to(root)
                except ValueError as exc:
                    raise MinerUError("MinerU结果压缩包包含不安全路径", "result-download") from exc
            archive.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise MinerUError("MinerU返回的结果不是有效ZIP文件", "result-download") from exc


def choose_markdown(output_root: Path, input_file: Path) -> tuple[Path, list[Path]]:
    candidates = [path for path in output_root.rglob("*.md") if path.is_file() and path.stat().st_size > 0]
    if not candidates:
        raise MinerUError("MinerU没有生成可用的Markdown文件", "output-discovery")
    exact = [path for path in candidates if path.stem.casefold() == input_file.stem.casefold()]
    selected = max(exact or candidates, key=lambda path: path.stat().st_size)
    return selected, candidates


def split_link_target(raw: str) -> tuple[str, str, bool]:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        end = value.index(">")
        return value[1:end], value[end + 1 :], True
    match = re.match(r"(\S+)(.*)$", value)
    return (match.group(1), match.group(2), False) if match else (value, "", False)


def stage_markdown(selected: Path, stage_root: Path, destination_name: str) -> tuple[Path, Path | None, int]:
    text = selected.read_text(encoding="utf-8-sig", errors="replace")
    meaningful = re.sub(r"!\[[^\]]*\]\([^)]*\)|<[^>]+>|\s+", "", text)
    if len(meaningful) < 40:
        raise MinerUError("MinerU Markdown几乎没有可读文字", "basic-quality-check")
    destination = stage_root / destination_name
    removed_local_images = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal removed_local_images
        raw_target, suffix, angle = split_link_target(match.group(2))
        decoded = unquote(raw_target).replace("\\", "/")
        if decoded.casefold().startswith(REMOTE_SCHEMES):
            return match.group(0)
        removed_local_images += 1
        alt = match.group(1)[2:-2].strip() or "无图注"
        return f"*[MinerU图片未归档：{alt}；视觉内容请回看原PDF/PPT对应位置]*"

    rewritten = IMAGE_LINK_RE.sub(replace, text)
    destination.write_text(rewritten, encoding="utf-8", newline="\n")
    return destination, None, removed_local_images


def publish(stage_md: Path, stage_assets: Path | None, destination_root: Path) -> tuple[Path, list[Path], bool]:
    destination_root.mkdir(parents=True, exist_ok=True)
    final_md = destination_root / stage_md.name
    final_assets = destination_root / stage_assets.name if stage_assets else None
    if final_md.exists():
        if sha256_file(final_md) == sha256_file(stage_md):
            return final_md, [final_assets] if final_assets and final_assets.exists() else [], True
        raise MinerUError(f"目标已有不同内容的同名文件：{final_md}", "archive-conflict")
    if final_assets and final_assets.exists():
        raise MinerUError(f"目标已有同名附件目录：{final_assets}", "archive-conflict")
    published: list[Path] = []
    if stage_assets and final_assets:
        shutil.copytree(stage_assets, final_assets)
        published.append(final_assets)
    try:
        shutil.copy2(stage_md, final_md)
    except OSError:
        if final_assets and final_assets.exists():
            shutil.rmtree(final_assets)
        raise
    return final_md, published, False


def operator_action(source_id: str, input_file: Path) -> str:
    return (
        f"请使用MinerU处理Codex点名的文件“{input_file.name}”（资料ID：{source_id}），"
        "导出Markdown后不要删改、重新排版或改文件名，直接把生成的.md文件发给Codex。"
        "不需要放入Obsidian或选择知识库目录。"
    )


def failure_actions(
    failure_type: str,
    retry_count: int,
    source_id: str,
    input_file: Path,
) -> dict:
    """Route failures to Codex, the API owner, or content operations."""
    common = {
        "operator_action": None,
        "api_owner_action": None,
        "codex_action": None,
        "human_required": False,
    }
    if failure_type in {"credential-missing-or-expired", "credential-invalid"}:
        common.update(
            api_owner_action=(
                f"由API负责人创建或更换{TOKEN_ENV}，同步登记{EXPIRES_ENV}，"
                "完全退出并重启Codex后执行probe和无敏感信息在线检查。"
            ),
            human_required=True,
        )
    elif failure_type == "quota-or-rate-limit":
        common.update(
            api_owner_action="由API负责人检查账号额度、频率限制和服务状态；不要把额度问题误当成Token失效。",
            codex_action="暂停批量提交，保留当前任务状态；确认额度恢复后再继续。",
            human_required=True,
        )
    elif failure_type == "codex-network-permission":
        common.update(
            api_owner_action=(
                "当前Codex沙箱未授权本脚本联网。由管理员在Codex弹窗中允许本次调用，"
                "并在可用时保存run_mineru.py调用前缀；不要更换Token。"
            ),
            codex_action="由Codex以最小范围申请在沙箱外重试同一MinerU命令。",
            human_required=True,
        )
    elif failure_type == "temporary-network-or-service":
        if retry_count < 2:
            common["codex_action"] = f"由Codex稍后重试，累计最多2次；当前已记录重试次数为{retry_count}。"
        else:
            common.update(
                api_owner_action="已重试2次仍失败，请API负责人检查网络和MinerU服务状态。",
                human_required=True,
            )
    elif failure_type == "upload-signature-or-clock":
        common["codex_action"] = "由Codex重新取得上传地址，并检查电脑系统时间和脚本请求；不要求内容运营换Token。"
    elif failure_type == "output-quality":
        common.update(
            operator_action=operator_action(source_id, input_file),
            human_required=True,
        )
    elif failure_type == "api-or-file-processing":
        if retry_count < 2:
            common["codex_action"] = (
                "由Codex先核对文件格式、大小、页数和任务状态，再重试；累计最多2次。"
            )
        else:
            common.update(
                operator_action=operator_action(source_id, input_file),
                human_required=True,
            )
    else:
        common["codex_action"] = "由Codex修正输入、路径、归档冲突、脚本或账本问题，不交给内容运营处理。"
    return common


def emit(payload: dict, *, error: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr if error else sys.stdout)


def options_from_args(args: argparse.Namespace) -> dict:
    return {
        "model": args.model,
        "ocr": args.ocr,
        "formula": args.formula,
        "table": args.table,
        "language": args.language,
        "pages": args.pages,
    }


def run_extract(args: argparse.Namespace, api: MinerUApi | None = None) -> int:
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    project_root = args.project_root.expanduser().resolve()
    input_file = args.input.expanduser().resolve()
    destination_root = project_root / CODEX_EXTRACTION_RELATIVE
    options = options_from_args(args)
    output_paths: list[Path] = []
    batch_id: str | None = None
    task_id: str | None = None
    stage = "input-check"
    token_source: str | None = None
    expiry = expiry_status(mark_reminder=True)
    try:
        if not project_root.is_dir():
            raise MinerUError(f"Obsidian项目路径不存在：{project_root}", stage)
        if not input_file.is_file():
            raise MinerUError(f"输入文件不存在：{input_file}", stage)
        if api is None:
            stage = "token-check"
            token, token_source = resolve_token()
            if not token:
                raise MinerUError(f"没有读取到{TOKEN_ENV}；请在Windows用户环境变量中保存Token后重启Codex", stage)
            if expiry["level"] == "expired":
                raise MinerUError("MinerU API Token已过期；请更换Token并重启Codex", stage)
            api = MinerUApi(token, args.api_base, args.request_timeout)
        else:
            token_source = "self-test"
        page_count = source_page_count(input_file, args.source_page_count)
        with tempfile.TemporaryDirectory(prefix="manage-article-knowledge-mineru-api-") as temp:
            temp_root = Path(temp)
            raw_output = temp_root / "mineru-output"
            raw_output.mkdir()
            stage = "api-submit"
            batch_id = api.submit_file(input_file, options)
            stage = "api-poll"
            result = api.wait(batch_id, args.timeout)
            task_id = str(result.get("task_id") or "") or None
            stage = "result-download"
            zip_data = api.download_zip(str(result["full_zip_url"]))
            safe_extract_zip(zip_data, raw_output)
            stage = "output-discovery"
            selected, candidates = choose_markdown(raw_output, input_file)
            destination_name = args.destination_name or (
                f"{sanitize_name(args.source_id)}_{sanitize_name(args.display_name or input_file.stem)}_MinerU.md"
            )
            if not destination_name.lower().endswith(".md"):
                destination_name += ".md"
            stage_root = temp_root / "archive-stage"
            stage_root.mkdir()
            stage_md, stage_assets, asset_count = stage_markdown(
                selected, stage_root, sanitize_name(Path(destination_name).stem) + ".md"
            )
            stage = "archive"
            final_md, published_assets, reused = publish(stage_md, stage_assets, destination_root)
            output_paths = [final_md, *published_assets]
        ended_at = datetime.now().astimezone().isoformat(timespec="seconds")
        tool_call = {
            "tool": "MinerU API",
            "version": "v4",
            "parameters": {
                **options,
                "api_base_host": urlparse(args.api_base).hostname,
                "timeout_seconds": args.timeout,
                "source_page_count": page_count,
            },
            "batch_id": batch_id,
            "task_id": task_id,
            "candidate_markdown_count": len(candidates),
            "selected_markdown": selected.name,
            "referenced_asset_count": asset_count,
            "archived_asset_count": 0,
        }
        record = make_record(
            project_root=project_root,
            project_id=args.project_id,
            article_ids=args.article_id,
            task="MinerU API提取",
            status="success",
            started_at=started_at,
            ended_at=ended_at,
            inputs=[input_file],
            read_files=[input_file],
            tool_calls=[tool_call],
            outputs=output_paths,
            retry_count=args.retry_count,
            note="已通过脚本基础检查；是否进入已就绪仍由Codex对照原文件核验。",
        )
        ledger = append_record(project_root, record)
        emit({
            "ok": True,
            "source_id": args.source_id,
            "api_version": "v4",
            "markdown": str(final_md),
            "output_sha256": sha256_file(final_md),
            "reused_existing_identical_output": reused,
            "ledger": str(ledger),
            "run_id": record["run_id"],
            "next_step": "Codex对照原文件检查页段、顺序、数字、表格、公式和图示；合格后再标记资料已就绪。",
            "api_expiry": expiry,
        })
        return 0
    except (MinerUError, OSError, ValueError) as exc:
        failure_stage = exc.stage if isinstance(exc, MinerUError) else stage
        if failure_stage == "api-request":
            failure_stage = stage
        reason = str(exc)
        failure_type = classify_failure(exc, failure_stage) if isinstance(exc, MinerUError) else "local-workflow"
        actions = failure_actions(failure_type, args.retry_count, args.source_id, input_file)
        try:
            record = make_record(
                project_root=project_root,
                project_id=args.project_id,
                article_ids=args.article_id,
                task="MinerU API提取",
                status="failed",
                started_at=started_at,
                inputs=[input_file],
                read_files=[input_file] if input_file.is_file() else [],
                tool_calls=[{
                    "tool": "MinerU API",
                    "version": "v4",
                    "parameters": {
                        **options,
                        "api_base_host": urlparse(args.api_base).hostname,
                    },
                    "batch_id": batch_id,
                    "task_id": task_id,
                }],
                outputs=output_paths,
                retry_count=args.retry_count,
                failure_stage=failure_stage,
                human_required=actions["human_required"],
                human_reason=reason if actions["human_required"] else None,
            )
            ledger = append_record(project_root, record)
            ledger_text, run_id = str(ledger), record["run_id"]
        except (OSError, ValueError) as ledger_exc:
            ledger_text, run_id = None, None
            reason = f"{reason}；运行账本也未能写入：{ledger_exc}"
        emit({
            "ok": False,
            "source_id": args.source_id,
            "failure_stage": failure_stage,
            "failure_stage_label": FAILURE_STAGE_LABELS.get(failure_stage, failure_stage),
            "failure_type": failure_type,
            "failure_type_label": FAILURE_TYPE_LABELS.get(failure_type, failure_type),
            "error": reason,
            "operator_action": actions["operator_action"],
            "api_owner_action": actions["api_owner_action"],
            "codex_action": actions["codex_action"],
            "project_can_continue": "除依赖这份PDF/PPT自动提取的任务外，立项、网页处理和其他知识工作可以继续。",
            "ledger": ledger_text,
            "run_id": run_id,
        }, error=True)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MinerU API按需解析与技术提取稿归档")
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe", help="检查Token、到期日、提醒窗口和本月在线检查状态")
    probe.add_argument("--mark-reminder", action="store_true", help="本次已向API负责人展示提醒时去重登记")
    health = subparsers.add_parser("health-check", help="用无敏感信息单页PDF验证Token、上传、解析和下载")
    health.add_argument("--force", action="store_true", help="即使本月已通过也重新测试")
    health.add_argument("--mark-reminder", action="store_true")
    health.add_argument("--api-base", default=os.environ.get("MINERU_API_BASE", DEFAULT_API_BASE))
    health.add_argument("--request-timeout", type=int, default=120)
    health.add_argument("--timeout", type=int, default=600)
    extract = subparsers.add_parser("extract", help="通过MinerU API按需解析一份当前文章需要的文件")
    extract.add_argument("--project-root", type=Path, required=True)
    extract.add_argument("--project-id")
    extract.add_argument("--article-id", action="append", default=[])
    extract.add_argument("--source-id", required=True)
    extract.add_argument("--input", type=Path, required=True)
    extract.add_argument("--display-name")
    extract.add_argument("--destination-name")
    extract.add_argument("--model", choices=("vlm", "pipeline"), default="vlm")
    extract.add_argument("--ocr", action=argparse.BooleanOptionalAction, default=False)
    extract.add_argument("--formula", action=argparse.BooleanOptionalAction, default=True)
    extract.add_argument("--table", action=argparse.BooleanOptionalAction, default=True)
    extract.add_argument("--language", default="ch")
    extract.add_argument("--pages")
    extract.add_argument("--api-base", default=os.environ.get("MINERU_API_BASE", DEFAULT_API_BASE))
    extract.add_argument("--request-timeout", type=int, default=120)
    extract.add_argument("--timeout", type=int, default=1800)
    extract.add_argument("--retry-count", type=int, default=0)
    extract.add_argument("--source-page-count", type=int)
    return parser


class FakeApi:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.zip_data = self._make_zip()

    @staticmethod
    def _make_zip() -> bytes:
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("sample/images/figure.png", b"png")
            archive.writestr(
                "sample/sample.md",
                "# Sample\n\nMinerU API health check\n\n" + "Useful extracted text. " * 8 + "\n![](images/figure.png)\n",
            )
        return data.getvalue()

    def submit_file(self, input_file: Path, options: dict) -> str:
        if self.fail:
            raise MinerUError("simulated API failure", "api-submit")
        return "batch-test"

    def wait(self, batch_id: str, timeout: int) -> dict:
        return {"state": "done", "task_id": "task-test", "full_zip_url": "https://example.invalid/result.zip"}

    def download_zip(self, url: str) -> bytes:
        return self.zip_data


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="mineru-api-wrapper-test-") as temp:
        root = Path(temp)
        original_local_app_data = os.environ.get("LOCALAPPDATA")
        original_expires = os.environ.get(EXPIRES_ENV)
        os.environ["LOCALAPPDATA"] = str(root / "local-app-data")
        os.environ[EXPIRES_ENV] = "2099-12-31"
        project = root / "DEMO-001_测试项目"
        project.mkdir()
        source = root / "sample.pdf"
        source.write_bytes(b"%PDF-test")
        args = argparse.Namespace(
            project_root=project, project_id="DEMO-001", article_id=["DEMO-ART-001"],
            source_id="DEMO-SRC-001", input=source, display_name="Sample", destination_name=None,
            model="vlm", ocr=False, formula=True, table=True, language="ch", pages=None,
            api_base=DEFAULT_API_BASE, request_timeout=30, timeout=30, retry_count=0,
            source_page_count=1,
        )
        if run_extract(args, FakeApi()) != 0:
            return 1
        expected = project / CODEX_EXTRACTION_RELATIVE / "DEMO-SRC-001_Sample_MinerU.md"
        ledger = project / "05_数据与审核/50_运行记录/项目运行账本.jsonl"
        if not expected.is_file() or not ledger.is_file():
            return 1
        expected_text = expected.read_text(encoding="utf-8")
        if "MinerU图片未归档" not in expected_text or "_assets/figure.png" in expected_text:
            return 1
        if list((project / CODEX_EXTRACTION_RELATIVE).glob("*_assets")):
            return 1
        record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
        serialized_record = json.dumps(record, ensure_ascii=False)
        if "credential_source" in serialized_record or TOKEN_ENV in serialized_record or TOKEN_ENV_COMPAT in serialized_record:
            return 1
        failed_project = root / "DEMO-002_失败测试"
        failed_project.mkdir()
        failed_args = argparse.Namespace(**vars(args))
        failed_args.project_root = failed_project
        failed_args.source_id = "DEMO-SRC-002"
        failed_args.retry_count = 2
        if run_extract(failed_args, FakeApi(fail=True)) != 2:
            return 1
        failed_ledger = failed_project / "05_数据与审核/50_运行记录/项目运行账本.jsonl"
        failed_record = json.loads(failed_ledger.read_text(encoding="utf-8").strip())
        if failed_record["status"] != "failed" or not failed_record["human_intervention"]["required"]:
            return 1
        permission_error = MinerUError(
            "MinerU API连接失败：<urlopen error [WinError 10013] socket access denied>",
            "api-request",
            retryable=True,
        )
        if classify_failure(permission_error, "api-request") != "codex-network-permission":
            return 1
        test_today = date(2026, 1, 1)
        os.environ[EXPIRES_ENV] = "2026-01-09"
        if expiry_status(today=test_today)["level"] != "ok":
            return 1
        os.environ[EXPIRES_ENV] = "2026-01-08"
        if expiry_status(today=test_today)["level"] != "warning":
            return 1
        os.environ[EXPIRES_ENV] = "2026-01-02"
        if expiry_status(today=test_today)["level"] != "urgent":
            return 1
        os.environ[EXPIRES_ENV] = "2025-12-31"
        if expiry_status(today=test_today)["level"] != "expired":
            return 1
        os.environ[EXPIRES_ENV] = "2099-12-31"
        health_args = argparse.Namespace(
            mark_reminder=False, force=True, api_base=DEFAULT_API_BASE,
            request_timeout=30, timeout=30,
        )
        if run_health_check(health_args, FakeApi()) != 0:
            return 1
        status_text = status_file_path().read_text(encoding="utf-8")
        if TOKEN_ENV in status_text or TOKEN_ENV_COMPAT in status_text or "Bearer" in status_text:
            return 1
        health_args.force = False
        if run_health_check(health_args, FakeApi(fail=True)) != 0:
            return 1
        if original_local_app_data is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = original_local_app_data
        if original_expires is None:
            os.environ.pop(EXPIRES_ENV, None)
        else:
            os.environ[EXPIRES_ENV] = original_expires
    emit({"ok": True, "self_test": True})
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return run_self_test()
    args = build_parser().parse_args()
    if args.command == "probe":
        token, source = resolve_token()
        expiry = expiry_status(mark_reminder=args.mark_reminder)
        health = current_health_status(token) if token else {"current_month_passed": False, "last_online_check": None}
        emit({
            "ok": bool(token),
            "credential_source": source,
            "expiry": expiry,
            "health": health,
            "status_file": str(status_file_path()),
            "message": "已读取MinerU API Token" if token else f"未读取到{TOKEN_ENV}",
        }, error=not bool(token))
        return 0 if token else 2
    if args.command == "health-check":
        return run_health_check(args)
    return run_extract(args)


if __name__ == "__main__":
    raise SystemExit(main())
