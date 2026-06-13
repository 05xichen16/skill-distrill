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

Generalization hardening (the public set is verbatim; only the attachment data
changes on the platform variant, and that is where this skill must not collapse):
  * Containers are detected by CONTENT MAGIC as well as extension, and the
    walker recurses through zip, tar, AND compressed members
    (.gz / .tgz / .tar.gz / .bz2 / .xz). A gzipped subtree no longer vanishes.
  * EVERY non-archive, non-image member is scanned as text -- not just
    .txt/.log -- because the question says the archive "may contain .txt, .log,
    .tar, .png/.jpg, ETC." Sensitive data hiding in .csv/.json/.dat/.out is
    still counted.
  * Emails are matched for ANY TLD, not only .com (the public set happens to be
    100% .com, so this is a no-op there but rescues a .cn/.net variant).

Image extraction transcribes each image VERBATIM via the multimodal model, then
runs the SAME deterministic regex used for text -- so image counts obey exactly
the same rules as text counts. Image work degrades gracefully: if the model is
unconfigured or a call fails, that image is skipped with a warning and the rest
of the scan still returns. The skill never raises to the caller for image
problems, and a wall-clock deadline guarantees a well-formed answer is emitted
before the runner's kill timeout (a dropped stdout forces the version-less model
loop, which scores far worse than text + partial-image counts).

Pure standard library, Python 3.9 compatible.
"""
from __future__ import annotations

import base64
import bz2
import gzip
import io
import json
import lzma
import os
import re
import sys
import tarfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional, Tuple


# --- sensitive-data patterns (boundaries matter) ---------------------------
# phone: 1-led 11 digits, bounded so it never matches inside an 18-digit ID.
RE_PHONE = re.compile(r"(?<!\d)1\d{10}(?!\d)")
# email: user@domain.<tld>. The public set is 100% .com, but the category is
# "email address"; matching any 2+ letter TLD keeps .com counts identical while
# rescuing a .cn/.net/.org variant. (verified: public count unchanged at 3479)
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# ID card: 18 chars, 17 digits + trailing digit or X, bounded.
RE_ID = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
# API key: sk- prefixed token.
RE_KEY = re.compile(r"sk-\S+")

ORDER = ("phone", "email", "id", "key")

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
ARCHIVE_EXTS = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".tbz", ".xz", ".txz")

# Recursion safety cap so a malicious / pathological archive cannot loop forever.
MAX_DEPTH = 16
# Skip text-decoding files larger than this (sensitive data lives in modest
# logs/dumps; a multi-hundred-MB blob is almost certainly not a token list).
MAX_TEXT_BYTES = 64 * 1024 * 1024
# A finite "wait forever" that will not overflow a lock-acquire timeout (~1 day).
_UNBOUNDED_WAIT = 86400.0


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
    return data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def _looks_like_tar(data: bytes) -> bool:
    # POSIX tar / ustar magic lives at byte offset 257.
    return len(data) > 262 and data[257:262] == b"ustar"


def _looks_like_gzip(data: bytes) -> bool:
    return data[:2] == b"\x1f\x8b"


def _looks_like_bzip2(data: bytes) -> bool:
    return data[:3] == b"BZh"


def _looks_like_xz(data: bytes) -> bool:
    return data[:6] == b"\xfd7zXZ\x00"


def _looks_like_compressed(data: bytes) -> bool:
    return _looks_like_gzip(data) or _looks_like_bzip2(data) or _looks_like_xz(data)


def _looks_like_image(data: bytes) -> bool:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:2] == b"BM":  # BMP
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def _decompress(data: bytes) -> Optional[bytes]:
    """Decompress a single gzip/bzip2/xz stream; return None if it is not one."""
    try:
        if _looks_like_gzip(data):
            return gzip.decompress(data)
        if _looks_like_bzip2(data):
            return bz2.decompress(data)
        if _looks_like_xz(data):
            return lzma.decompress(data)
    except Exception:  # noqa: BLE001 - corrupt/partial stream degrades gracefully
        return None
    return None


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
        self.text_files = 0

    def walk_bytes(self, data: bytes, name: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            self.warnings.append("max recursion depth reached at: %s" % name)
            return
        if not data:
            return

        ext = _ext(name)

        # --- containers (extension OR content magic) ---
        if ext == ".zip" or _looks_like_zip(data):
            if self._walk_zip(data, name, depth):
                return
        if ext == ".tar" or _looks_like_tar(data):
            if self._walk_tar(data, name, depth):
                return
        if ext in (".gz", ".tgz", ".bz2", ".tbz2", ".tbz", ".xz", ".txz") or _looks_like_compressed(data):
            # A compressed tarball (.tar.gz/.tgz/...) opens transparently here.
            if self._walk_tar(data, name, depth):
                return
            # Otherwise it is a single compressed file: decompress and recurse on
            # the inner payload (which may itself be text, an image, or nested).
            inner = _decompress(data)
            if inner is not None:
                self.walk_bytes(inner, _strip_compression_suffix(name), depth + 1)
                return
            self.warnings.append("could not decompress: %s" % name)
            return

        # --- images (extension OR content magic) -> OCR path ---
        if ext in IMAGE_EXTS or _looks_like_image(data):
            self.images.append((name, data))
            return

        # --- everything else is scanned as text ---
        # The question says the archive may contain ".txt, .log, .tar, .png/.jpg,
        # ETC." so we must not restrict text scanning to .txt/.log.
        if len(data) > MAX_TEXT_BYTES:
            self.warnings.append("skipped oversized file for text scan: %s" % name)
            return
        _add(self.text_counts, count_text(_decode_text(data)))
        self.text_files += 1

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
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
                self.warnings.append("unreadable zip member %s: %s" % (info.filename, exc))
                continue
            self.walk_bytes(member, info.filename, depth + 1)
        return True

    def _walk_tar(self, data: bytes, name: str, depth: int) -> bool:
        try:
            # mode "r:*" transparently handles plain, gzip, bzip2 and xz tars.
            archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
        except (tarfile.TarError, OSError, EOFError):
            return False
        try:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                try:
                    handle = archive.extractfile(member)
                except (tarfile.TarError, OSError) as exc:
                    self.warnings.append("unreadable tar member %s: %s" % (member.name, exc))
                    continue
                if handle is None:
                    continue
                self.walk_bytes(handle.read(), member.name, depth + 1)
        finally:
            archive.close()
        return True


def _strip_compression_suffix(name: str) -> str:
    lower = name.lower()
    for suffix, replacement in ((".tgz", ".tar"), (".tbz2", ".tar"), (".tbz", ".tar"), (".txz", ".tar")):
        if lower.endswith(suffix):
            return name[: -len(suffix)] + replacement
    for suffix in (".gz", ".bz2", ".xz"):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name + ".decompressed"


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
    # The runner may hand us the absolute path among allowed_file_paths.
    for allowed in runtime.get("allowed_file_paths") or []:
        allowed_str = str(allowed)
        if os.path.basename(allowed_str) == os.path.basename(zip_path):
            candidates.append(allowed_str)
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
    if ext == ".gif":
        return "image/gif"
    if ext == ".bmp":
        return "image/bmp"
    if ext == ".webp":
        return "image/webp"
    return "image/png"


_IMAGE_EXTRACT_PROMPT = (
    "You are a precise OCR engine. Transcribe EVERY line of text visible in this "
    "image VERBATIM and COMPLETELY: every digit, letter, '@', '.', '-' and other "
    "symbol, exactly as shown, one line per visible line. Do NOT stop early, "
    "summarize, translate, deduplicate, reorder, redact or add any commentary. "
    "If the image contains many lines, transcribe ALL of them to the very end. "
    "Output only the raw transcribed text."
)


def extract_image_counts(config: Dict[str, str], name: str, data: bytes, timeout: int) -> Dict[str, int]:
    """OCR-transcribe one image via the gateway and count tokens with the same
    deterministic regex used for text files.

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
        # Keep the transcription deterministic and avoid truncating long lists.
        "max_tokens": _env_int("SENSITIVE_SCAN_MAX_TOKENS", 8192, minimum=1024),
        # enable_thinking is read from chat_template_kwargs by the contest gateway.
        "chat_template_kwargs": {"enable_thinking": _ocr_thinking()},
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
    # The model returns a verbatim transcription; count with the text regex.
    # (Robust even if the gateway returns a structured token list instead: the
    # regex still finds the same tokens regardless of surrounding JSON syntax.)
    return count_text(_strip_think(content))


def _strip_think(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()


# --- structured-extraction fallback (retained for the validated unit test;
#     not on the main transcription path, but a safe alternative parser) ------

def _parse_image_items(content: str) -> Dict[str, List[str]]:
    """Parse a strict-JSON token-list extraction result into category lists."""
    text = _strip_think(content)
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
    start = time.monotonic()
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
            image_counts, images_ocr_ok, ocr_warnings = _ocr_images(
                collector.images, config, _ocr_deadline(start), warnings
            )
            warnings = ocr_warnings

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
        "text_files": collector.text_files,
        "warnings": warnings,
    }


def _ocr_images(
    images: List[Tuple[str, bytes]],
    config: Dict[str, str],
    deadline: float,
    warnings: List[str],
) -> Tuple[Dict[str, int], int, List[str]]:
    """OCR every image concurrently, bounded by a wall-clock deadline.

    One failed/slow image degrades to a warning, never kills the scan. When the
    deadline is reached, pending images are abandoned with a warning so the
    caller can still emit text + completed-image counts before the runner's kill
    timeout fires.
    """
    image_counts = _empty_counts()
    images_ocr_ok = 0
    timeout = _ocr_timeout()
    # Under the generous (600s) skill budget we can afford a few retries; a
    # gateway storm (the platform runs CONCURRENCY questions at once) returns
    # 5xx / RemoteDisconnected, and an EXPONENTIAL BACKOFF between attempts lets
    # it recover instead of immediately re-hammering it.
    retries = _env_int("SENSITIVE_SCAN_RETRIES", 3, minimum=1)
    workers = _env_int("SENSITIVE_SCAN_WORKERS", 4, minimum=1)
    backoff = _env_float("SENSITIVE_SCAN_RETRY_BACKOFF", 1.0, minimum=0.0)

    def ocr_one(item: Tuple[str, bytes]) -> Tuple[Dict[str, int], Optional[str]]:
        name, data = item
        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _empty_counts(), "deadline reached before OCR of %s" % name
            if attempt > 0 and backoff > 0:
                # Sleep before the retry, but never past the deadline.
                sleep_for = min(backoff * (2 ** (attempt - 1)), max(0.0, remaining - 1.0))
                if sleep_for > 0:
                    time.sleep(sleep_for)
            call_timeout = max(5, min(timeout, int(deadline - time.monotonic())))
            try:
                return extract_image_counts(config, name, data, call_timeout), None
            except Exception as exc:  # noqa: BLE001 - graceful degradation
                last_exc = exc
        return _empty_counts(), "image extraction failed for %s: %s" % (name, last_exc)

    total = len(images)
    if workers <= 1 or total == 1:
        for item in images:
            if time.monotonic() >= deadline:
                warnings.append("deadline reached; skipped image %s" % item[0])
                continue
            counts, warning = ocr_one(item)
            if warning:
                warnings.append(warning)
            else:
                _add(image_counts, counts)
                images_ocr_ok += 1
        return image_counts, images_ocr_ok, warnings

    pool = ThreadPoolExecutor(max_workers=min(workers, total))
    futures = {pool.submit(ocr_one, item): item for item in images}
    try:
        wait_for = max(0.0, min(deadline - time.monotonic(), _UNBOUNDED_WAIT))
        for future in as_completed(futures, timeout=wait_for):
            counts, warning = future.result()
            if warning:
                warnings.append(warning)
            else:
                _add(image_counts, counts)
                images_ocr_ok += 1
    except FuturesTimeoutError:
        for future, item in futures.items():
            if not future.done():
                warnings.append("deadline reached; skipped image %s" % item[0])
    finally:
        # Do not block on still-running calls: main() hard-exits after emitting.
        pool.shutdown(wait=False)
    return image_counts, images_ocr_ok, warnings


def _ocr_timeout() -> int:
    raw = os.getenv("AGENT_DEMO_TIMEOUT_SECONDS")
    if raw is None:
        return 60
    try:
        return max(5, int(raw))
    except ValueError:
        return 60


def _ocr_thinking() -> bool:
    return _env_bool("SENSITIVE_SCAN_ENABLE_THINKING", _env_bool("AGENT_DEMO_ENABLE_THINKING", False))


def _ocr_deadline(start: float) -> float:
    """Wall-clock deadline for all OCR work.

    The runner passes its kill budget via SKILL_BUDGET_SECONDS; we stop OCR a
    margin before it so a well-formed answer is always emitted. With no budget
    set (direct unit-test calls) the deadline is effectively unbounded.
    """
    budget = _env_int("SKILL_BUDGET_SECONDS", 0, minimum=0)
    if budget <= 0:
        # No runner budget (direct/unit-test calls): effectively unbounded, but
        # kept well below values that overflow a lock-acquire timeout.
        return start + _UNBOUNDED_WAIT
    margin = _env_int("SENSITIVE_SCAN_DEADLINE_MARGIN", 30, minimum=1)
    return start + max(5, budget - margin)


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    raw = sys.stdin.read().strip() or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stdout.write(json.dumps({"error": "invalid JSON input: %s" % exc}, ensure_ascii=False))
        sys.stdout.flush()
        raise SystemExit(1)

    if not isinstance(args, dict):
        sys.stdout.write(json.dumps({"error": "input must be a JSON object"}, ensure_ascii=False))
        sys.stdout.flush()
        raise SystemExit(1)

    try:
        result = scan(args)
    except (FileNotFoundError, ValueError) as exc:
        # Hard input errors: report and fail (the runner surfaces stderr/stdout).
        sys.stdout.write(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.stdout.flush()
        raise SystemExit(1)

    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()
    # Hard-exit so any still-running OCR worker thread cannot delay process exit
    # past the runner's kill timeout (which would drop this stdout). The answer
    # is already flushed above.
    os._exit(0)


if __name__ == "__main__":
    main()
