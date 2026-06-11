"""Prompt-learning image classifier skill (generic).

Given a labelled training set (image + same-named ``.txt`` label) the skill
learns the *label set* dynamically (deduplicated, order-preserving), then walks
a validation set and classifies every image one-by-one against a task
description supplied by the caller. It is deliberately task-agnostic: nothing
about the public glove question (the labels, the rule, the count of classes,
the size of the validation set) is hard-coded. Everything is derived from the
inputs.

Request shape (stdin):
    {
      "task_description": "<the question's task description, verbatim>",  # required
      "train_dir": "train",      # optional; inferred from _runtime/defaults
      "val_dir": "val",          # optional; inferred from _runtime/defaults
      "few_shot_k": 0,           # optional, default 0 (zero-shot)
      "_runtime": {               # injected by the runner
        "question_dir": "...",
        "allowed_file_paths": ["...", "..."],
        "question_id": "3_1"
      }
    }

Result shape (stdout):
    {
      "answer": "1PASS,2FAIL,...",                # <i><LABEL> joined by ',', numeric order
      "predictions": [{"idx": 1, "label": "PASS"}, ...],
      "classes": ["PASS", "FAIL", "NOT_INVOLVED"],
      "val_total": 100, "ok": 100, "failed": 0, "fallback_used": 0,
      "accuracy": {"n": 20, "correct": 17, "acc": 0.85},  # only when .txt exist
      "warnings": []
    }

The label produced for the i-th validation image is normalised so it matches
the ``matchN`` grader (segment strip-equals the literal): exact class match
first, then longest-class substring match (so a long label like
``NOT_INVOLVED`` is never stolen by a shorter one such as ``PASS``), then a
deterministic fallback. A single image never crashes the run and never drops a
segment: on repeated failure it gets the fallback label so the segment count
and positions stay intact.

Image classification is performed by ``classify_image``; the caller can
monkeypatch that single callable to inject fake responses for offline tests, so
no network is touched at import time.

Pure standard library, Python 3.9 compatible.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

# Heuristic name fragments used to pick the train / val directory out of the
# runtime's allowed file paths when the caller does not name them explicitly.
# "xun lian" / "yan zheng" are the Chinese words for train / validation; built
# from codepoints so this module stays pure-ASCII on disk.
_TRAIN_HINTS = ("train", chr(0x8BAD) + chr(0x7EC3))  # ascii + "xun lian" (train)
_VAL_HINTS = ("val", "valid", "verif", chr(0x9A8C) + chr(0x8BC1))  # + "yan zheng" (val)


# --- small helpers ---------------------------------------------------------

def _ext(name: str) -> str:
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return ("." + base.rsplit(".", 1)[-1].lower()) if "." in base else ""


def _stem(name: str) -> str:
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def _numeric_key(stem: str) -> Tuple[int, str]:
    """Sort key that orders ``1, 2, ..., 10`` numerically, names lexically.

    Files named ``<n>.jpg`` are ordered by the integer ``n``; anything that is
    not a pure integer falls back to a stable lexical order after the numbers.
    """
    if stem.isdigit():
        return (0, "%020d" % int(stem))
    return (1, stem)


def _image_mime(name: str) -> str:
    ext = _ext(name)
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".bmp":
        return "image/bmp"
    if ext == ".webp":
        return "image/webp"
    return "image/png"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"false", "0", "no", "off", ""}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


# --- directory resolution --------------------------------------------------

def _candidate_dirs(name: str, runtime: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    if os.path.isabs(name):
        candidates.append(name)
        return candidates
    question_dir = str(runtime.get("question_dir") or "").strip()
    if question_dir:
        candidates.append(os.path.join(question_dir, name))
    candidates.append(os.path.join(os.getcwd(), name))
    candidates.append(name)
    return candidates


def _pick_from_allowed(runtime: Dict[str, Any], hints: Tuple[str, ...], order_index: int) -> Optional[str]:
    """Pick a directory from the runtime's allowed_file_paths by name hint.

    Falls back to positional selection (order_index) over the directory entries
    when no hint matches.
    """
    paths = [str(p) for p in (runtime.get("allowed_file_paths") or [])]
    dirs = [p for p in paths if os.path.isdir(p.rstrip("/\\"))]
    # Hint match first (case-insensitive on the basename and full path).
    for path in dirs:
        low = path.lower()
        base = os.path.basename(path.rstrip("/\\")).lower()
        if any(h.lower() in low or h.lower() in base for h in hints):
            return path
    # Positional fallback over the declared directories.
    if 0 <= order_index < len(dirs):
        return dirs[order_index]
    return None


def resolve_dir(name: Optional[str], runtime: Dict[str, Any], hints: Tuple[str, ...],
                order_index: int, default_name: str) -> str:
    """Resolve a train/val directory to an existing path, or the best guess.

    Precedence: an explicit ``name`` resolved against question_dir/cwd; then a
    runtime allowed-path picked by hint/position; then the default name
    resolved against question_dir/cwd. Returns the first existing candidate, or
    the most meaningful candidate so callers can raise a clear error.
    """
    if name:
        candidates = _candidate_dirs(name, runtime)
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return candidates[0]

    from_allowed = _pick_from_allowed(runtime, hints, order_index)
    if from_allowed and os.path.isdir(from_allowed.rstrip("/\\")):
        return from_allowed.rstrip("/\\")

    candidates = _candidate_dirs(default_name, runtime)
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return candidates[0]


# --- dataset loading -------------------------------------------------------

def list_images(directory: str) -> List[str]:
    """Return image file paths in *directory*, ordered by numeric-aware stem."""
    if not os.path.isdir(directory):
        return []
    names = [
        entry
        for entry in os.listdir(directory)
        if _ext(entry) in IMAGE_EXTS and os.path.isfile(os.path.join(directory, entry))
    ]
    names.sort(key=lambda entry: _numeric_key(_stem(entry)))
    return [os.path.join(directory, entry) for entry in names]


def _read_label_file(image_path: str) -> Optional[str]:
    """Read the same-named ``.txt`` label next to *image_path*, if present."""
    label_path = os.path.splitext(image_path)[0] + ".txt"
    if not os.path.isfile(label_path):
        return None
    try:
        with open(label_path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return text.strip()


def load_training(train_dir: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Load (image_path, label) pairs and the ordered, deduplicated class set.

    The class set is discovered purely from the training labels (order of first
    appearance preserved). Images without a label file are ignored for class
    discovery but do not raise.
    """
    pairs: List[Tuple[str, str]] = []
    classes: List[str] = []
    for image_path in list_images(train_dir):
        label = _read_label_file(image_path)
        if not label:
            continue
        pairs.append((image_path, label))
        if label not in classes:
            classes.append(label)
    return pairs, classes


# --- label normalisation ---------------------------------------------------

def normalize_label(raw: str, classes: List[str], fallback: str) -> Tuple[str, bool]:
    """Map a raw model response to one of *classes*.

    Returns ``(label, matched)``. Resolution order:
      1. exact (case-insensitive, stripped) equality with a class;
      2. substring containment, trying the LONGEST class names first so a long
         label (``NOT_INVOLVED``) is never stolen by a shorter one (``PASS``)
         that happens to be a substring of the response;
      3. fallback label (``matched`` is False) so the caller can warn.
    """
    text = (raw or "").strip()
    upper = text.upper()

    # 1. exact match against a known class.
    for cls in classes:
        if upper == cls.strip().upper():
            return cls, True

    # 2. longest-class-first substring match.
    for cls in sorted(classes, key=lambda c: len(c), reverse=True):
        token = cls.strip().upper()
        if token and token in upper:
            return cls, True

    # 3. fallback.
    return fallback, False


# --- model config + image classification -----------------------------------

def _model_config() -> Optional[Dict[str, str]]:
    """Build model config from the environment, or None if not configured.

    Mirrors the sensitive_scan skill: reads MODEL_CHAT_COMPLETIONS_URL (or
    MODEL_BASE_URL), MODEL_API_KEY, MODEL_NAME and the optional PACKAGE_ID.
    """
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


def _data_url(name: str, data: bytes) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return "data:%s;base64,%s" % (_image_mime(name), b64)


def classify_image(
    config: Dict[str, str],
    prompt: str,
    images: List[Tuple[str, bytes]],
    timeout: int,
) -> str:
    """Call the model gateway to classify; return the raw response text.

    *images* is a list of (name, raw bytes); the last image is the one to
    classify, any earlier images are few-shot exemplars already described in the
    prompt. Raises on failure; the caller handles retries / graceful fallback.

    This is the single injectable seam: offline tests monkeypatch this function
    so nothing reaches the network. The multimodal payload (data-URL images,
    ``chat_template_kwargs.enable_thinking``, dual ``package_id``/``packageId``
    headers, urllib with an http.client fallback) reuses the structure proven by
    the sensitive_scan skill.
    """
    import http.client
    import urllib.request

    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for name, data in images:
        content.append({"type": "image_url", "image_url": {"url": _data_url(name, data)}})

    payload = {
        "model": config["model"],
        "temperature": 0.0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": _env_bool("AGENT_DEMO_ENABLE_THINKING", False)},
        "messages": [{"role": "user", "content": content}],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer %s" % config["api_key"],
        "Content-Type": "application/json",
    }
    if config["package_id"]:
        headers["package_id"] = config["package_id"]
        headers["packageId"] = config["package_id"]

    request = urllib.request.Request(config["url"], data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except http.client.RemoteDisconnected:
        raw = _post_with_http_client(config["url"], body, headers, timeout)

    return _extract_content(raw)


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
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "".join(parts)
    return str(content or "")


# --- prompt construction ---------------------------------------------------

def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def select_few_shot(pairs: List[Tuple[str, str]], classes: List[str], k: int) -> List[Tuple[str, str]]:
    """Pick up to *k* training pairs balanced across the discovered classes.

    Round-robins over the classes so every class is represented before any class
    is repeated. Returns (image_path, label) pairs in selection order.
    """
    if k <= 0 or not pairs:
        return []
    by_class: Dict[str, List[Tuple[str, str]]] = {cls: [] for cls in classes}
    for image_path, label in pairs:
        by_class.setdefault(label, []).append((image_path, label))

    selected: List[Tuple[str, str]] = []
    cursor = {cls: 0 for cls in by_class}
    order = list(classes) + [c for c in by_class if c not in classes]
    while len(selected) < k:
        progressed = False
        for cls in order:
            bucket = by_class.get(cls) or []
            idx = cursor[cls]
            if idx < len(bucket):
                selected.append(bucket[idx])
                cursor[cls] = idx + 1
                progressed = True
                if len(selected) >= k:
                    break
        if not progressed:
            break
    return selected


def build_prompt(task_description: str, classes: List[str], few_shot: List[Tuple[str, str]]) -> str:
    """Assemble the classification prompt.

    = task_description (verbatim rule) + optional few-shot label captions + a
    closing hard constraint that pins the output to exactly one valid label.
    The few-shot *images* are attached separately by the caller; here we only
    add the captions that say what each attached exemplar's label is.
    """
    sections: List[str] = []
    sections.append(task_description.strip())

    if few_shot:
        lines = [
            "Here are labelled training examples. Each image below is followed "
            "by its correct label; use them to calibrate your decision:"
        ]
        for offset, (_, label) in enumerate(few_shot, start=1):
            lines.append("Example %d label: %s" % (offset, label))
        sections.append("\n".join(lines))

    valid = ", ".join(classes) if classes else ""
    if valid:
        sections.append(
            "Classify the LAST image. Valid labels: %s. "
            "Respond with EXACTLY one label from this list, uppercase, nothing else." % valid
        )
    else:
        sections.append(
            "Classify the LAST image. Respond with EXACTLY one short uppercase "
            "label, nothing else."
        )
    return "\n\n".join(sections)


# --- per-image prediction with retry + fallback ----------------------------

def _predict_one(
    image_path: str,
    config: Optional[Dict[str, str]],
    prompt: str,
    few_shot_images: List[Tuple[str, bytes]],
    classes: List[str],
    fallback: str,
    timeout: int,
    retries: int,
    classifier: Callable[..., str],
) -> Tuple[str, bool, bool, Optional[str]]:
    """Predict the label for one image.

    Returns ``(label, ok, used_fallback, warning)``. Never raises: on repeated
    failure it returns the fallback label so the segment is still emitted.
    """
    name = os.path.basename(image_path)
    if config is None:
        return fallback, False, True, "model gateway not configured; fallback for %s" % name

    try:
        data = _read_bytes(image_path)
    except OSError as exc:
        return fallback, False, True, "unreadable image %s: %s" % (name, exc)

    images = list(few_shot_images) + [(name, data)]
    last_error: Optional[str] = None
    for attempt in range(max(1, retries)):
        try:
            raw = classifier(config, prompt, images, timeout)
        except Exception as exc:  # noqa: BLE001 - graceful per-image degradation
            last_error = str(exc)
            if attempt + 1 < max(1, retries):
                time.sleep(min(8.0, 0.5 * (2 ** attempt)))
            continue
        label, matched = normalize_label(raw, classes, fallback)
        if matched:
            return label, True, False, None
        # Model answered but the response did not map to a class: keep the
        # fallback label, count it, and warn (no further retries help here).
        snippet = (raw or "").strip().replace("\n", " ")[:60]
        return label, True, True, "unparsed label for %s: %r -> %s" % (name, snippet, fallback)

    return fallback, False, True, "classification failed for %s: %s" % (name, last_error)


# --- main flow -------------------------------------------------------------

def classify(args: Dict[str, Any], classifier: Callable[..., str] = classify_image) -> Dict[str, Any]:
    runtime = args.get("_runtime") or {}
    if not isinstance(runtime, dict):
        runtime = {}

    task_description = str(args.get("task_description") or "").strip()
    if not task_description:
        raise ValueError("task_description is required")

    train_dir = resolve_dir(
        args.get("train_dir"), runtime, _TRAIN_HINTS, order_index=0, default_name="train",
    )
    val_dir = resolve_dir(
        args.get("val_dir"), runtime, _VAL_HINTS, order_index=1, default_name="val",
    )
    if not os.path.isdir(val_dir):
        raise FileNotFoundError("validation directory not found: %s" % val_dir)

    few_shot_k = args.get("few_shot_k", 0)
    try:
        few_shot_k = int(few_shot_k)
    except (TypeError, ValueError):
        few_shot_k = 0

    warnings: List[str] = []

    # --- discover classes from the training labels (dynamic) ---------------
    train_pairs, classes = load_training(train_dir)
    if not os.path.isdir(train_dir):
        warnings.append("training directory not found: %s (proceeding without examples)" % train_dir)
    elif not train_pairs:
        warnings.append("no labelled training pairs found in %s" % train_dir)

    # Fallback label: most frequent training class, else the first class, else
    # empty. Used whenever a prediction cannot be mapped to a class.
    fallback = ""
    if train_pairs:
        freq: Dict[str, int] = {}
        for _, label in train_pairs:
            freq[label] = freq.get(label, 0) + 1
        # Tie-break by first appearance order for determinism.
        fallback = max(classes, key=lambda c: (freq.get(c, 0), -classes.index(c)))
    elif classes:
        fallback = classes[0]

    # --- few-shot exemplars (default 0) ------------------------------------
    few_shot = select_few_shot(train_pairs, classes, few_shot_k) if few_shot_k > 0 else []
    few_shot_images: List[Tuple[str, bytes]] = []
    for image_path, _ in few_shot:
        try:
            few_shot_images.append((os.path.basename(image_path), _read_bytes(image_path)))
        except OSError as exc:
            warnings.append("skipped few-shot example %s: %s" % (os.path.basename(image_path), exc))

    prompt = build_prompt(task_description, classes, few_shot)

    # --- enumerate the validation set (numeric order) ----------------------
    val_images = list_images(val_dir)
    val_total = len(val_images)
    if val_total == 0:
        raise FileNotFoundError("no images found in validation directory: %s" % val_dir)

    config = _model_config()
    if config is None:
        warnings.append(
            "model gateway not configured (MODEL_* env missing); all %d image(s) get the fallback label"
            % val_total
        )

    timeout = _env_int("AGENT_DEMO_TIMEOUT_SECONDS", 60, minimum=5)
    retries = _env_int("PROMPT_LEARN_RETRIES", 3, minimum=1)
    workers = _env_int("PROMPT_LEARN_WORKERS", 4, minimum=1)

    # --- predict every validation image (bounded concurrency) --------------
    results: List[Optional[Tuple[str, bool, bool, Optional[str]]]] = [None] * val_total

    def work(index: int) -> Tuple[int, Tuple[str, bool, bool, Optional[str]]]:
        outcome = _predict_one(
            val_images[index], config, prompt, few_shot_images, classes,
            fallback, timeout, retries, classifier,
        )
        return index, outcome

    if workers <= 1 or val_total == 1:
        for index in range(val_total):
            _, results[index] = work(index)
    else:
        with ThreadPoolExecutor(max_workers=min(workers, val_total)) as pool:
            for index, outcome in pool.map(work, range(val_total)):
                results[index] = outcome

    # --- assemble answer strictly in numeric order -------------------------
    predictions: List[Dict[str, Any]] = []
    segments: List[str] = []
    ok = 0
    fallback_used = 0
    eval_total = 0
    eval_correct = 0

    for offset, image_path in enumerate(val_images):
        outcome = results[offset]
        if outcome is None:  # defensive; should not happen
            outcome = (fallback, False, True, "missing result for %s" % os.path.basename(image_path))
        label, was_ok, used_fallback, warning = outcome
        idx = offset + 1  # 1-based segment index
        predictions.append({"idx": idx, "label": label})
        segments.append("%d%s" % (idx, label))
        if was_ok:
            ok += 1
        if used_fallback:
            fallback_used += 1
        if warning:
            warnings.append(warning)

        # self-eval: only when a same-named .txt ground truth exists. Never
        # fed to the model; purely for the accuracy field.
        truth = _read_label_file(image_path)
        if truth:
            eval_total += 1
            if label.strip() == truth.strip():
                eval_correct += 1

    answer = ",".join(segments)
    result: Dict[str, Any] = {
        "answer": answer,
        "predictions": predictions,
        "classes": classes,
        "val_total": val_total,
        "ok": ok,
        "failed": val_total - ok,
        "fallback_used": fallback_used,
        "warnings": warnings,
    }
    if eval_total:
        result["accuracy"] = {
            "n": eval_total,
            "correct": eval_correct,
            "acc": round(eval_correct / eval_total, 4),
        }
    return result


def _read_stdin_text() -> str:
    """Read stdin as bytes and decode robustly.

    The runner pipes the JSON request via ``subprocess.run(text=True)``, which on
    Windows encodes the pipe with the locale codec (cp936/GBK) while the child's
    text stdin may default to UTF-8 (e.g. under PYTHONIOENCODING=utf-8). When the
    request carries non-ASCII directory names that mismatch crashes a plain
    ``sys.stdin.read()``. Reading the raw bytes and trying UTF-8 then the locale
    codec makes the skill accept the request regardless of how it was encoded.
    """
    import locale

    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        # No binary stream (unusual); fall back to the text stream as-is.
        return sys.stdin.read()
    data = buffer.read()
    if not data:
        return ""
    encodings = ["utf-8"]
    preferred = (locale.getpreferredencoding(False) or "").lower()
    if preferred and preferred not in {"utf-8", "utf8"}:
        encodings.append(preferred)
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _emit(payload: Dict[str, Any]) -> None:
    """Write a JSON payload to stdout as pure-ASCII UTF-8 bytes.

    ``ensure_ascii=True`` plus a raw byte write avoids the Windows pipe codec
    mismatch: the runner reads stdout with ``text=True`` (locale/cp936 on
    Windows) while the child may emit UTF-8. Non-ASCII content (e.g. a directory
    name in a warning) would otherwise crash the reader, so we keep the wire
    bytes ASCII and let the JSON ``\\uXXXX`` escapes carry any non-ASCII text.
    """
    line = json.dumps(payload, ensure_ascii=True) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(line)
        sys.stdout.flush()
        return
    buffer.write(line.encode("ascii"))
    buffer.flush()


def main() -> None:
    raw = _read_stdin_text().strip() or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit({"error": "invalid JSON input: %s" % exc})
        raise SystemExit(1)

    if not isinstance(args, dict):
        _emit({"error": "input must be a JSON object"})
        raise SystemExit(1)

    try:
        result = classify(args)
    except (FileNotFoundError, ValueError) as exc:
        _emit({"error": str(exc)})
        raise SystemExit(1)

    _emit(result)


if __name__ == "__main__":
    main()
