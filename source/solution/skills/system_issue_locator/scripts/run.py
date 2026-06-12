from __future__ import annotations

import fnmatch
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


# --- root-cause resolution (strict -> relaxed -> LLM -> raise) ----------------
#
# Variant schemas replace validationCodeMap with rootCauseRules whose
# conditions combine module / validationCode / fieldPath / schemaVersion etc.
# The old evaluator only looked at the rule's validationCode key, so a
# rules-only schema mapped nothing -> exit 1 -> bare model loop. The resolver
# below degrades through three layers and only raises when all of them miss.
# Causes always come from the schema itself; nothing is free-generated.

_RULE_META_KEYS = {
    "description", "desc", "note", "comment", "reason", "remark",
    "priority", "severity", "weight", "order",
    "id", "ruleid", "rulename", "name", "label",
}
_RULE_CAUSE_KEYS = {
    "rootcause", "rootcauses", "cause", "causes",
    "rootcausekeyword", "rootcausekeywords",
}
# normalized rule key -> context key (matched against the resolved flow, not log lines)
_RULE_GLOBAL_KEYS = {
    "module": "module",
    "validationref": "validationref",
    "ref": "validationref",
    "actionid": "actionid",
    "api": "path",
    "path": "path",
    "apipath": "path",
    "interface": "path",
    "url": "path",
    "endpoint": "path",
}
_CODE_LIKE_KEYS = {"validationcode", "code", "errorcode"}


def _norm_key(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(name or "").strip().lower())


def _schema_code_map(schema: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in schema.items():
        if _norm_key(key) == "validationcodemap" and isinstance(value, dict):
            return value
    return {}


def _schema_rules(schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key, value in schema.items():
        if _norm_key(key) == "rootcauserules" and isinstance(value, list):
            return [rule for rule in value if isinstance(rule, dict)]
    return []


def _parse_line_fields(line: str) -> Dict[str, str]:
    """key=value pairs of one log line, keys normalized."""
    fields: Dict[str, str] = {}
    for key, value in re.findall(r"([A-Za-z][A-Za-z0-9_.\-]*)\s*=\s*([^,\s]+)", line):
        fields.setdefault(_norm_key(key), value)
    return fields


def collect_effective_lines(
    log_text: str, validation_ref: str, schema: Dict[str, Any]
) -> List[Tuple[str, Dict[str, str]]]:
    """(raw line, parsed fields) for the ref's lines that survive
    effectiveValidationRule filtering (lines without a validationCode stay)."""
    lines: List[Tuple[str, Dict[str, str]]] = []
    for line in log_text.splitlines():
        if validation_ref not in line:
            continue
        fields = _parse_line_fields(line)
        code = fields.get("validationcode", "")
        if code and not _code_effective(line, code, schema):
            continue
        lines.append((line, fields))
    return lines


def _rule_cause_values(rule: Dict[str, Any]) -> List[str]:
    causes: List[str] = []
    for key, value in rule.items():
        if _norm_key(key) not in _RULE_CAUSE_KEYS:
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            text = str(item or "").strip()
            if text and text not in causes:
                causes.append(text)
    return causes


def _rule_conditions(rule: Dict[str, Any]) -> Optional[Dict[str, List[str]]]:
    """Condition fields of a rule: every key that is neither metadata nor the
    cause payload participates in matching. None = rule is unevaluable."""
    conditions: Dict[str, List[str]] = {}
    for key, value in rule.items():
        normalized = _norm_key(key)
        if normalized in _RULE_CAUSE_KEYS or normalized in _RULE_META_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)):
            conditions[normalized] = [str(value)]
        elif isinstance(value, list) and all(
            isinstance(item, (str, int, float, bool)) for item in value
        ):
            conditions[normalized] = [str(item) for item in value]
        else:
            return None  # nested/unknown condition shape: never auto-fire
    return conditions


def _tokens(text: str) -> set:
    return {
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+", text or "")
        if len(token) >= 3 and token.lower() != "val"
    }


def _relaxed_value_match(actual: str, expected: str, allow_tokens: bool = False) -> bool:
    left = (actual or "").strip()
    right = (expected or "").strip()
    if not left or not right:
        return False
    if left.lower() == right.lower():
        return True
    if ("*" in right or "?" in right) and fnmatch.fnmatchcase(left.lower(), right.lower()):
        return True
    if ("*" in left or "?" in left) and fnmatch.fnmatchcase(right.lower(), left.lower()):
        return True
    if min(len(left), len(right)) >= 4 and (
        left.lower().startswith(right.lower()) or right.lower().startswith(left.lower())
    ):
        return True
    if min(len(left), len(right)) >= 6 and (
        left.lower() in right.lower() or right.lower() in left.lower()
    ):
        return True
    # Token overlap is reserved for code-like fields (VAL-C-ROLE-7429 ~ ROLE-x);
    # generic fields like fieldPath must not match on shared segments ("user").
    if allow_tokens:
        return bool(_tokens(left) & _tokens(right))
    return False


def _values_match(
    actual: str, expected: List[str], relaxed: bool, allow_tokens: bool = False
) -> bool:
    if relaxed:
        return any(_relaxed_value_match(actual, value, allow_tokens) for value in expected)
    return actual in expected


def _rule_matches(
    conditions: Optional[Dict[str, List[str]]],
    lines: List[Tuple[str, Dict[str, str]]],
    context: Dict[str, str],
    relaxed: bool,
) -> bool:
    if not conditions:
        return False  # unevaluable or unconditional rules never auto-fire
    line_conditions: Dict[str, List[str]] = {}
    for key, expected in conditions.items():
        if key in _RULE_GLOBAL_KEYS:
            actual = str(context.get(_RULE_GLOBAL_KEYS[key]) or "")
            if not _values_match(actual, expected, relaxed):
                return False
        else:
            line_conditions[key] = expected
    if not line_conditions:
        return True
    ref = str(context.get("validationref") or "")
    evaluation_lines = lines if lines else ([("", {})] if relaxed else [])
    for _, fields in evaluation_lines:
        satisfied = True
        for key, expected in line_conditions.items():
            allow_tokens = key in _CODE_LIKE_KEYS
            field_value = fields.get(key)
            if field_value is not None and _values_match(field_value, expected, relaxed, allow_tokens):
                continue
            if (
                relaxed
                and allow_tokens
                and ref
                and _values_match(ref, expected, relaxed=True, allow_tokens=True)
            ):
                continue
            satisfied = False
            break
        if satisfied:
            return True
    return False


def strict_causes(
    codes: List[str],
    schema: Dict[str, Any],
    lines: List[Tuple[str, Dict[str, str]]],
    context: Dict[str, str],
) -> List[str]:
    """Layer 1: exact validationCodeMap lookup plus combination rule matching
    (every condition field of a rule must hold, co-occurring on one line)."""
    mapped: List[str] = []
    code_map = _schema_code_map(schema)
    for code in codes:
        cause = code_map.get(code)
        if cause and str(cause) not in mapped:
            mapped.append(str(cause))
    for rule in _schema_rules(schema):
        if _rule_matches(_rule_conditions(rule), lines, context, relaxed=False):
            for cause in _rule_cause_values(rule):
                if cause not in mapped:
                    mapped.append(cause)
    return mapped


def relaxed_causes(
    codes: List[str],
    schema: Dict[str, Any],
    lines: List[Tuple[str, Dict[str, str]]],
    context: Dict[str, str],
) -> List[str]:
    """Layer 2: wildcard / prefix / token matching against the same schema
    entries; values still come exclusively from the schema."""
    subjects = [code for code in codes if code]
    ref = str(context.get("validationref") or "")
    if ref:
        subjects.append(ref)
    mapped: List[str] = []
    for key, value in _schema_code_map(schema).items():
        if any(_relaxed_value_match(subject, str(key), allow_tokens=True) for subject in subjects):
            text = str(value or "").strip()
            if text and text not in mapped:
                mapped.append(text)
    for rule in _schema_rules(schema):
        if _rule_matches(_rule_conditions(rule), lines, context, relaxed=True):
            for cause in _rule_cause_values(rule):
                if cause not in mapped:
                    mapped.append(cause)
    return mapped


def _collect_candidate_causes(schema: Any) -> List[str]:
    """Every root-cause keyword the schema can possibly award, in schema order."""
    causes: List[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in causes:
            causes.append(text)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                normalized = _norm_key(key)
                if normalized == "validationcodemap" and isinstance(value, dict):
                    for cause in value.values():
                        if isinstance(cause, str):
                            add(cause)
                elif normalized in _RULE_CAUSE_KEYS:
                    if isinstance(value, str):
                        add(value)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                add(item)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return causes


def resolve_root_causes(
    codes: List[str],
    schema: Dict[str, Any],
    lines: List[Tuple[str, Dict[str, str]]],
    context: Dict[str, str],
) -> Tuple[List[str], str]:
    causes = strict_causes(codes, schema, lines, context)
    if causes:
        return causes, "strict"
    causes = relaxed_causes(codes, schema, lines, context)
    if causes:
        return causes, "relaxed"
    if _env_bool("SYSTEM_ISSUE_LLM_FALLBACK", True):
        config = _model_config()
        if config is not None:
            causes = llm_fallback_causes(config, codes, schema, lines, context)
            if causes:
                return causes, "llm"
    return [], "none"


# --- model gateway fallback ----------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"false", "0", "no", ""}


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _model_config() -> Optional[Dict[str, str]]:
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
    return {"url": chat_url, "api_key": api_key, "model": model, "package_id": package_id}


def _call_model(config: Dict[str, str], prompt: str, timeout: int) -> str:
    """Text-only gateway call; the injectable seam for offline tests."""
    import http.client
    import urllib.request

    payload = {
        "model": config["model"],
        "temperature": 0.0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": _env_bool("AGENT_DEMO_ENABLE_THINKING", False)},
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
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
        raise RuntimeError("gateway disconnected")
    data = json.loads(raw)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("gateway returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")


_FALLBACK_PROMPT = """你是系统问题定位审核员。自动规则未能把本次失败链路的校验信息映射到根因关键词，请你从候选列表中选出最可能的一个或多个根因关键词。

【失败链路 validationRef】
{ref}

【该链路的后端校验日志行】
{lines}

【收集到的 validationCode】
{codes}

【form_schema.json 内容】
{schema}

【候选根因关键词（只能从中选择）】
{candidates}

只输出一个 JSON 数组，每个元素必须逐字等于候选列表中的某一项，不要输出解释。例如：["候选根因A","候选根因B"]"""


def llm_fallback_causes(
    config: Dict[str, str],
    codes: List[str],
    schema: Dict[str, Any],
    lines: List[Tuple[str, Dict[str, str]]],
    context: Dict[str, str],
) -> List[str]:
    """Layer 3: one model call, hard-validated. The output is accepted only if
    it is a non-empty JSON array whose every item is verbatim from the schema's
    candidate cause set; anything else keeps the failure path."""
    candidates = _collect_candidate_causes(schema)
    if not candidates:
        return []
    schema_text = json.dumps(schema, ensure_ascii=False)
    if len(schema_text) > 4000:
        schema_text = schema_text[:4000] + "...(truncated)"
    prompt = _FALLBACK_PROMPT.format(
        ref=str(context.get("validationref") or "") or "(unknown)",
        lines="\n".join(raw for raw, _ in lines[:40]) or "(none)",
        codes=", ".join(codes) or "(none)",
        schema=schema_text,
        candidates="\n".join("- " + cause for cause in candidates),
    )
    timeout = _env_int("AGENT_DEMO_TIMEOUT_SECONDS", 60, minimum=5)
    try:
        response = _call_model(config, prompt, timeout)
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group(0))
    except Exception:
        return []
    if not isinstance(data, list) or not data:
        return []
    candidate_set = set(candidates)
    picked: List[str] = []
    for item in data:
        if not isinstance(item, str):
            return []
        text = item.strip()
        if text not in candidate_set:
            return []  # any out-of-set item rejects the whole verdict
        if text not in picked:
            picked.append(text)
    return picked


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
    lines = collect_effective_lines(backend_text, validation_ref, schema)
    context = {
        "module": module,
        "path": path,
        "actionid": action_id,
        "validationref": validation_ref,
    }
    causes, cause_source = resolve_root_causes(codes, schema, lines, context)
    if not causes:
        raise ValueError(
            "no mapped root causes for %s (codes=%s)"
            % (validation_ref, ",".join(codes) or "none")
        )
    return {
        "answer": "%s,%s,%s" % (module, path, "、".join(causes)),
        "action_id": action_id,
        "validation_ref": validation_ref,
        "codes": codes,
        "cause_source": cause_source,
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
