# One-shot patcher: add the EN->CN retrieval bridge to spec_qa. Kept in the
# task directory for traceability; safe to re-run (asserts guard idempotence).
import pathlib

p = pathlib.Path("source/solution/skills/spec_qa/scripts/run.py")
text = p.read_text(encoding="utf-8")
assert "_is_mostly_english" not in text, "already patched"

old_call = (
    '''        spec_text = "\\n".join(specs[name] for name in spec_names)
        source = "ALL" if spec_text else ""

    snippet = retrieve(spec_text, question_text, max_snippet_chars, window_lines)'''
)
new_call = (
    '''        spec_text = "\\n".join(specs[name] for name in spec_names)
        source = "ALL" if spec_text else ""

    # English questions retrieve poorly against the Chinese spec corpus (the
    # platform's mixed-language paper lost 3/10 here): bridge them with
    # model-generated Chinese keywords before retrieval.
    retrieval_text = question_text
    if config is not None and _is_mostly_english(question_text):
        bridged = _chinese_keywords_via_model(config, question_text, timeout, answerer)
        if bridged:
            retrieval_text = question_text + " " + " ".join(bridged)

    snippet = retrieve(spec_text, retrieval_text, max_snippet_chars, window_lines)'''
)
assert old_call in text, "call site not found"
text = text.replace(old_call, new_call)

marker = "# --- per-question answer with retry + fallback -----------------------------"
helpers = '''# --- EN->CN retrieval bridge -------------------------------------------------

def _is_mostly_english(question_text: str) -> bool:
    """True when CJK characters are (nearly) absent from the question."""
    cjk = sum(len(m.group(0)) for m in _CJK_RE.finditer(question_text))
    visible = len(re.sub(r"\\s", "", question_text))
    return visible > 0 and cjk * 10 < visible


_BRIDGE_PROMPT = (
    "The following programming-specification question is in English, but the "
    "specification documents are written in Chinese. Give 3-6 Chinese keywords "
    "or short phrases most likely to appear verbatim in the Chinese document "
    "about this topic. Output ONLY the keywords separated by commas, nothing "
    "else.\\n\\nQuestion: {question}"
)


def _chinese_keywords_via_model(
    config: Dict[str, str],
    question_text: str,
    timeout: int,
    answerer: Callable[..., str],
) -> List[str]:
    """One small model call turning an English question into Chinese retrieval
    keys. Best-effort: any failure returns [] and retrieval proceeds as before."""
    try:
        raw = answerer(config, _BRIDGE_PROMPT.format(question=question_text.strip()), timeout)
    except Exception:
        return []
    parts = re.split("[,;\\u3001\\uFF0C\\uFF1B\\n]+", raw or "")
    keywords: List[str] = []
    for part in parts:
        cleaned = part.strip().strip("\\"'\\u201C\\u201D")
        if cleaned and len(cleaned) <= 24 and _CJK_RE.search(cleaned):
            keywords.append(cleaned)
        if len(keywords) >= 6:
            break
    return keywords


# --- per-question answer with retry + fallback -----------------------------'''
assert marker in text, "marker not found"
text = text.replace(marker, helpers)
p.write_text(text, encoding="utf-8")
print("patched ok")
