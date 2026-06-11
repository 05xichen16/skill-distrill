from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_stdin_text() -> str:
    import locale

    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
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
    line = json.dumps(payload, ensure_ascii=True) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(line)
        sys.stdout.flush()
        return
    buffer.write(line.encode("ascii"))
    buffer.flush()


def _candidate_dirs(name: str, runtime: Dict[str, Any]) -> List[str]:
    if os.path.isabs(name):
        return [name]
    question_dir = str(runtime.get("question_dir") or "").strip()
    result: List[str] = []
    if question_dir:
        result.append(os.path.join(question_dir, name))
    result.append(os.path.join(os.getcwd(), name))
    result.append(name)
    return result


def resolve_source_dir(name: str, runtime: Dict[str, Any]) -> str:
    if name:
        for candidate in _candidate_dirs(name, runtime):
            if os.path.isdir(candidate):
                return candidate
    for path in runtime.get("allowed_file_paths") or []:
        text = str(path)
        if os.path.isdir(text):
            return text
        if os.path.isfile(text):
            parent = os.path.dirname(text)
            if os.path.isfile(os.path.join(parent, "network.har")):
                return parent
    raise FileNotFoundError("source directory not found")


def read_text(path: str) -> str:
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def load_json(path: str) -> Any:
    return json.loads(read_text(path))


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _header(headers: List[Dict[str, Any]], name: str) -> str:
    for item in headers or []:
        if str(item.get("name") or "").lower() == name.lower():
            return str(item.get("value") or "")
    return ""


def choose_foreground_entry(har: Dict[str, Any]) -> Dict[str, Any]:
    entries = (((har.get("log") or {}).get("entries")) or [])
    candidates = []
    for entry in entries:
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        content = ((response.get("content") or {}).get("text")) or ""
        body = _maybe_json(content)
        if not isinstance(body, dict):
            continue
        if body.get("finalUiError") is True and body.get("visualFailureConfirmed") is True:
            role = str(body.get("workflowRole") or "")
            if role and "diagnostic" in role:
                continue
            candidates.append(entry)
    if candidates:
        return candidates[0]

    # Fallback: any non-diagnostic failing request with a validationRef.
    for entry in entries:
        response = entry.get("response") or {}
        body = _maybe_json(((response.get("content") or {}).get("text")) or "")
        if isinstance(body, dict) and body.get("validationRef") and int(response.get("status") or 0) >= 400:
            if "diagnostic" not in str(body.get("workflowRole") or ""):
                return entry
    raise ValueError("foreground failure request not found")


def collect_validation_codes(log_text: str, validation_ref: str, schema: Dict[str, Any]) -> List[str]:
    codes: List[str] = []
    for line in log_text.splitlines():
        if validation_ref not in line:
            continue
        code_match = re.search(r"validationCode=([A-Za-z0-9_-]+)", line)
        if code_match:
            code = code_match.group(1)
            if _code_effective(line, code, schema):
                codes.append(code)
    result: List[str] = []
    for code in codes:
        if code not in result:
            result.append(code)
    return result


def _code_effective(line: str, code: str, schema: Dict[str, Any]) -> bool:
    rule = schema.get("effectiveValidationRule")
    if isinstance(rule, dict):
        for key, expected in rule.items():
            if str(key) == "validationCode":
                expected_values = expected if isinstance(expected, list) else [expected]
                if code not in {str(v) for v in expected_values}:
                    return False
                continue
            pattern = r"%s=([^,\s]+)" % re.escape(str(key))
            match = re.search(pattern, line)
            if not match:
                return False
            expected_values = expected if isinstance(expected, list) else [expected]
            if match.group(1) not in {str(v) for v in expected_values}:
                return False
    return True


def map_root_causes(codes: List[str], schema: Dict[str, Any]) -> List[str]:
    mapped: List[str] = []
    code_map = schema.get("validationCodeMap") if isinstance(schema.get("validationCodeMap"), dict) else {}
    for code in codes:
        cause = code_map.get(code)
        if cause and cause not in mapped:
            mapped.append(str(cause))
    rules = schema.get("rootCauseRules") if isinstance(schema.get("rootCauseRules"), list) else []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("validationCode") or "") in codes:
            cause = str(rule.get("rootCause") or "")
            if cause and cause not in mapped:
                mapped.append(cause)
    return mapped


def module_from_har(har: Dict[str, Any], action_id: str, fallback: str) -> str:
    entries = (((har.get("log") or {}).get("entries")) or [])
    for entry in entries:
        request = entry.get("request") or {}
        if _header(request.get("headers") or [], "X-Action-Id") != action_id + "-PF":
            continue
        body = _maybe_json((((entry.get("response") or {}).get("content") or {}).get("text")) or "")
        if isinstance(body, dict):
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            module = str(data.get("module") or "")
            if module:
                return module
    if fallback.lower() == "user management":
        return "用户管理"
    return fallback


def frontend_module(frontend_text: str, action_id: str) -> str:
    workflow_id = ""
    for line in frontend_text.splitlines():
        if action_id in line:
            match = re.search(r"workflowId=([^,\s]+)", line)
            if match:
                workflow_id = match.group(1)
                break
    if workflow_id:
        for line in frontend_text.splitlines():
            if workflow_id in line and "module-open" in line:
                match = re.search(r"pageGroup=([^,]+)", line)
                if match:
                    return match.group(1).strip()
    return ""


def answer(args: Dict[str, Any]) -> Dict[str, Any]:
    runtime = args.get("_runtime") if isinstance(args.get("_runtime"), dict) else {}
    source_dir = resolve_source_dir(str(args.get("source_dir") or ""), runtime)
    har = load_json(os.path.join(source_dir, "network.har"))
    schema = load_json(os.path.join(source_dir, "form_schema.json"))
    backend_text = read_text(os.path.join(source_dir, "backend_validation.log"))
    frontend_text = read_text(os.path.join(source_dir, "frontend_log.log"))

    entry = choose_foreground_entry(har)
    request = entry.get("request") or {}
    response = entry.get("response") or {}
    response_body = _maybe_json(((response.get("content") or {}).get("text")) or "")
    if not isinstance(response_body, dict):
        raise ValueError("foreground response is not JSON")

    action_id = str(response_body.get("actionId") or _header(request.get("headers") or [], "X-Action-Id"))
    validation_ref = str(response_body.get("validationRef") or "")
    path = urlparse(str(request.get("url") or "")).path
    module = module_from_har(har, action_id, frontend_module(frontend_text, action_id))
    codes = collect_validation_codes(backend_text, validation_ref, schema)
    causes = map_root_causes(codes, schema)
    if not causes:
        raise ValueError("no mapped root causes for %s" % validation_ref)
    return {
        "answer": "%s,%s,%s" % (module, path, "、".join(causes)),
        "action_id": action_id,
        "validation_ref": validation_ref,
        "codes": codes,
    }


def main() -> None:
    raw = _read_stdin_text().strip() or "{}"
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            raise ValueError("input must be an object")
        _emit(answer(args))
    except Exception as exc:
        _emit({"error": str(exc)})
        raise SystemExit(1)


if __name__ == "__main__":
    main()
