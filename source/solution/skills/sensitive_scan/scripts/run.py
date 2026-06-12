"""Sensitive-data scanner skill.

Reads a JSON request from stdin, scans a (possibly deeply nested) archive for
four kinds of sensitive data, and prints a JSON result to stdout.

Request shape (stdin):
    {
      "zip_path": "sensitive_data_2_1.zip",   # required
      "do_ocr": true,                           # optional, default true
      "_runtime": {                             # injected by the runner
        "question_dir": "...",
        "allowed_file_paths": ["..."],
        "question_id": "2_2"
      }
    }

Result shape (stdout):
    {
      "answer": "phone,email,id,apikey",
      "breakdown": {"text": [...], "image": [...], "total": [...]},
      "images_total": int,
      "images_ocr_ok": int,
      "warnings": [...]
    }

Counting is deterministic (boundary-aware regex, total occurrences, no dedup).
Image extraction asks the multimodal model for structured sensitive-token lists
per category, then code validates those items and counts occurrences. Image
work degrades gracefully: if the model is unconfigured or fails, image counts
are skipped and the text-only counts are returned with a warning. The skill
never raises to the caller for image extraction problems.

Pure standard library, Python 3.9 compatible.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import tarfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple


# --- sensitive-data patterns (boundaries matter) ---------------------------
# phone: 1-led 11 digits, bounded so it never matches inside an 18-digit ID.
RE_PHONE = re.compile(r"(?<!\d)1\d{10}(?!\d)")
# email: only .com appears in the public set.
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.com")
# ID card: 18 chars, 17 digits + trailing digit or X, bounded.
RE_ID = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
# API key: sk- prefixed token.
RE_KEY = re.compile(r"sk-\S+")

ORDER = ("phone", "email", "id", "key")

TEXT_EXTS = (".txt", ".log")
IMAGE_EXTS = (".png", ".jpg", ".jpeg")

# Recursion safety cap so a malicious / pathological archive cannot loop forever.
MAX_DEPTH = 12


def _empty_counts() -> Dict[str, int]:
    return {key: 0 for key in ORDER}


def count_text(text: str) -> Dict[str, int]:
    return {
        "phone": len(RE_PHONE.findall(text)),
        "email": len(RE_EMAIL.findall(text)),
        "id": len(RE_ID.findall(text)),
        "key": len(RE_KEY.findall(text)),
    }


def _add(into: Dict[str, int], delta: Dict[str, int]) -> None:
    for key in ORDER:
        into[key] += delta.get(key, 0)


def _ext(name: str) -> str:
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return ("." + base.rsplit(".", 1)[-1].lower()) if "." in base else ""


def _looks_like_zip(data: bytes) -> bool:
    return data[:4] == b"PK\x03\x04"


def _looks_like_tar(data: bytes) -> bool:
    # POSIX tar / ustar magic lives at byte offset 257.
    return len(data) > 262 and data[257:262] == b"ustar"


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


class Collector:
    """Walks archives, accumulating text counts and image payloads."""

    def __init__(self) -> None:
        self.text_counts = _empty_counts()
        self.images: List[Tuple[str, bytes]] = []  # (name, raw bytes)
        self.warnings: List[str] = []

    def walk_bytes(self, data: bytes, name: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            self.warnings.append("max recursion depth reached at: %s" % name)
            return

        ext = _ext(name)
        # Treat as a container if the extension says so OR the content sniffs.
        if ext == ".zip" or _looks_like_zip(data):
            if self._walk_zip(data, name, depth):
                return
        if ext == ".tar" or _looks_like_tar(data):
            if self._walk_tar(data, name, depth):
                return

        if ext in IMAGE_EXTS:
            self.images.append((name, data))
            return
        if ext in TEXT_EXTS:
            _add(self.text_counts, count_text(_decode_text(data)))
            return
        # Unknown extension: ignore (matches "scan .txt/.log/.tar/.png/.jpg").

    def _walk_zip(self, data: bytes, name: str, depth: int) -> bool:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, OSError):
            return False
        for info in archive.infolist():
            if info.is_dir():
                continue
            try:
                member = archive.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                self.warnings.append("unreadable zip member %s: %s" % (info.filename, exc))
                continue
            self.walk_bytes(member, info.filename, depth + 1)
        return True

    def _walk_tar(self, data: bytes, name: str, depth: int) -> bool:
        try:
            archive = tarfile.open(fileobj=io.BytesIO(data))
        except (tarfile.TarError, OSError):
            return False
        try:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                self.walk_bytes(handle.read(), member.name, depth + 1)
        finally:
            archive.close()
        return True


# --- path resolution -------------------------------------------------------

def resolve_archive_path(zip_path: str, runtime: Dict[str, Any]) -> str:
    """Resolve the archive path: absolute -> as is; relative -> question_dir
    then cwd fallback. Returns the first existing candidate, or the best guess.
    """
    if not zip_path:
        raise ValueError("zip_path is required")

    if os.path.isabs(zip_path):
        return zip_path

    candidates: List[str] = []
    question_dir = str(runtime.get("question_dir") or "").strip()
    if question_dir:
        candidates.append(os.path.join(question_dir, zip_path))
    candidates.append(os.path.join(os.getcwd(), zip_path))
    candidates.append(zip_path)

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    # Nothing existed; return the most meaningful candidate for a clear error.
    return candidates[0]


# --- image extraction (graceful) -------------------------------------------

def _model_config() -> Optional[Dict[str, str]]:
    """Build model config from the environment, or None if not configured."""
    chat_url = (os.getenv("MODEL_CHAT_COMPLETIONS_URL") or "").strip()
    base_url = (os.getenv("MODEL_BASE_URL") or "").strip()
    if not chat_url and base_url:
        chat_url = base_url.rstrip("/") + "/chat/completions"
    if chat_url and not chat_url.rstrip("/").endswith("/chat/completions"):
        chat_url = chat_url.rstrip("/") + "/chat/completions"

    api_key = (os.getenv("MODEL_API_KEY") or "").strip()
    model = (os.getenv("MODEL_NAME") or "").strip()
    if not (chat_url and api_key and model):
        return None

    package_id = (os.getenv("PACKAGE_ID") or "").strip() or (os.getenv("packageId") or "").strip()
    return {
        "url": chat_url,
        "api_key": api_key,
        "model": model,
        "package_id": package_id,
    }


def _image_mime(name: str) -> str:
    ext = _ext(name)
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "image/png"


_IMAGE_EXTRACT_PROMPT = (
    "You are reading one image for a sensitive-data counting task. Extract ONLY "
    "the visible sensitive tokens and return strict JSON with exactly these keys: "
    '{"phones":[],"emails":[],"ids":[],"api_keys":[]}. '
    "Rules: phones are 11 digits starting with 1; emails are user@domain.com; "
    "IDs are 18 characters with 17 digits plus a final digit or X; API keys start "
    "with sk-. Include duplicate occurrences separately; do not deduplicate. "
    "Do not include labels, explanations, markdown, or any text outside JSON."
)


def extract_image_counts(config: Dict[str, str], name: str, data: bytes, timeout: int) -> Dict[str, int]:
    """Call the model gateway to extract image tokens; return validated counts.

    Raises on failure; the caller handles graceful degradation.
    """
    import http.client
    import urllib.request

    b64 = base64.b64encode(data).decode("ascii")
    data_url = "data:%s;base64,%s" % (_image_mime(name), b64)
    payload = {
        "model": config["model"],
        "temperature": 0.0,
        "stream": False,
        # enable_thinking is read from chat_template_kwargs by the contest gateway.
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _IMAGE_EXTRACT_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer %s" % config["api_key"],
        "Content-Type": "application/json",
    }
    if config["package_id"]:
        # Spec is inconsistent about the header name; send both.
        headers["package_id"] = config["package_id"]
        headers["packageId"] = config["package_id"]

    request = urllib.request.Request(config["url"], data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except http.client.RemoteDisconnected:
        raw = _post_with_http_client(config["url"], body, headers, timeout)

    content = _extract_content(raw)
    items = _parse_image_items(content)
    return _count_extracted_items(items)


def _parse_image_items(content: str) -> Dict[str, List[str]]:
    """Parse the model's strict JSON extraction result into category lists."""
    text = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()
    candidates = [text]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    )
    object_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0))

    parsed: Optional[Dict[str, Any]] = None
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            parsed = value
            break
    if parsed is None:
        raise ValueError("image extraction did not return a JSON object")

    aliases = {
        "phone": ("phones", "phone", "手机号", "mobile", "mobiles"),
        "email": ("emails", "email", "邮箱"),
        "id": ("ids", "id", "id_cards", "idcards", "身份证", "身份证号"),
        "key": ("api_keys", "apiKeys", "apikeys", "api_key", "keys", "key", "APIKey"),
    }
    result: Dict[str, List[str]] = {key: [] for key in ORDER}
    for target, names in aliases.items():
        for name in names:
            if name in parsed:
                result[target].extend(_coerce_items(parsed.get(name)))
    return result


def _coerce_items(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: List[str] = []
        for item in value:
            if isinstance(item, (str, int, float)):
                text = str(item).strip()
                if text and text.lower() not in {"none", "null", "n/a"}:
                    items.append(text)
        return items
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        if not text or text.lower() in {"none", "null", "n/a"}:
            return []
        return [part.strip() for part in re.split(r"[\n,，;；]+", text) if part.strip()]
    return []


def _count_extracted_items(items: Dict[str, List[str]]) -> Dict[str, int]:
    counts = _empty_counts()
    for item in items.get("phone", []):
        if _valid_phone_item(item):
            counts["phone"] += 1
    for item in items.get("email", []):
        if _valid_email_item(item):
            counts["email"] += 1
    for item in items.get("id", []):
        if _valid_id_item(item):
            counts["id"] += 1
    for item in items.get("key", []):
        if _valid_key_item(item):
            counts["key"] += 1
    return counts


def _valid_phone_item(item: str) -> bool:
    if RE_PHONE.search(item):
        return True
    digits = re.sub(r"\D", "", item)
    return bool(re.fullmatch(r"1\d{10}", digits))


def _valid_email_item(item: str) -> bool:
    return bool(RE_EMAIL.search(item))


def _valid_id_item(item: str) -> bool:
    if RE_ID.search(item):
        return True
    compact = re.sub(r"[^0-9Xx]", "", item)
    return bool(re.fullmatch(r"\d{17}[\dXx]", compact))


def _valid_key_item(item: str) -> bool:
    text = item.strip().strip("\"'`，,;；。")
    return bool(RE_KEY.search(text) or re.fullmatch(r"sk-[A-Za-z0-9._:/+=\-]+", text))


def _post_with_http_client(url: str, body: bytes, headers: Dict[str, str], timeout: int) -> str:
    import http.client
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("unsupported gateway url: %s" % url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = conn_cls(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
    finally:
        connection.close()
    if response.status >= 400:
        raise RuntimeError("gateway HTTP %s: %s" % (response.status, raw[:300]))
    return raw


def _extract_content(raw: str) -> str:
    data = json.loads(raw)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("gateway returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        # Some gateways return content as a list of parts.
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "".join(parts)
    return str(content or "")


# --- main ------------------------------------------------------------------

def scan(args: Dict[str, Any]) -> Dict[str, Any]:
    runtime = args.get("_runtime") or {}
    if not isinstance(runtime, dict):
        runtime = {}
    do_ocr = args.get("do_ocr", True)
    if not isinstance(do_ocr, bool):
        do_ocr = str(do_ocr).strip().lower() not in {"false", "0", "no", ""}

    archive_path = resolve_archive_path(str(args.get("zip_path", "")), runtime)
    if not os.path.isfile(archive_path):
        raise FileNotFoundError("archive not found: %s" % archive_path)

    collector = Collector()
    with open(archive_path, "rb") as handle:
        collector.walk_bytes(handle.read(), os.path.basename(archive_path), 0)

    text_counts = collector.text_counts
    image_counts = _empty_counts()
    images_total = len(collector.images)
    images_ocr_ok = 0
    warnings = list(collector.warnings)

    if do_ocr and images_total:
        config = _model_config()
        if config is None:
            warnings.append(
                "model gateway not configured (MODEL_* env missing); skipped image extraction for %d image(s)"
                % images_total
            )
        else:
            timeout = _ocr_timeout()
            retries = _env_int("SENSITIVE_SCAN_RETRIES", 2, minimum=1)
            workers = _env_int("SENSITIVE_SCAN_WORKERS", 4, minimum=1)

            # Bounded concurrency: the production gateway takes ~50-60s per
            # image, so many sequential images can blow past the skill timeout.
            # Concurrent image extraction keeps wall-clock near a single image's latency.
            # One failed image degrades to a warning, never kills the scan.
            def ocr_one(item: Tuple[str, bytes]) -> Tuple[Dict[str, int], Optional[str]]:
                name, data = item
                last_exc: Optional[Exception] = None
                for _ in range(retries):
                    try:
                        return extract_image_counts(config, name, data, timeout), None
                    except Exception as exc:  # noqa: BLE001 - graceful degradation
                        last_exc = exc
                return _empty_counts(), "image extraction failed for %s: %s" % (name, last_exc)

            if workers <= 1 or images_total == 1:
                outcomes = [ocr_one(item) for item in collector.images]
            else:
                with ThreadPoolExecutor(max_workers=min(workers, images_total)) as pool:
                    outcomes = list(pool.map(ocr_one, collector.images))

            for counts, warning in outcomes:
                if warning:
                    warnings.append(warning)
                else:
                    _add(image_counts, counts)
                    images_ocr_ok += 1
    elif do_ocr and not images_total:
        # nothing to extract from images
        pass

    total_counts = _empty_counts()
    _add(total_counts, text_counts)
    _add(total_counts, image_counts)

    answer = ",".join(str(total_counts[key]) for key in ORDER)
    return {
        "answer": answer,
        "breakdown": {
            "text": [text_counts[key] for key in ORDER],
            "image": [image_counts[key] for key in ORDER],
            "total": [total_counts[key] for key in ORDER],
        },
        "images_total": images_total,
        "images_ocr_ok": images_ocr_ok,
        "warnings": warnings,
    }


def _ocr_timeout() -> int:
    raw = os.getenv("AGENT_DEMO_TIMEOUT_SECONDS")
    if raw is None:
        return 60
    try:
        return max(5, int(raw))
    except ValueError:
        return 60


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def main() -> None:
    raw = sys.stdin.read().strip() or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": "invalid JSON input: %s" % exc}, ensure_ascii=False))
        raise SystemExit(1)

    if not isinstance(args, dict):
        print(json.dumps({"error": "input must be a JSON object"}, ensure_ascii=False))
        raise SystemExit(1)

    try:
        result = scan(args)
    except (FileNotFoundError, ValueError) as exc:
        # Hard input errors: report and fail (the runner surfaces stderr/stdout).
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
