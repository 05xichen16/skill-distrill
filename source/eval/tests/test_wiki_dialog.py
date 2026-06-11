"""Offline tests for the wiki_dialog skill.

Fully offline: the candidate-selection seam (``select_candidate``) and the Wiki
HTTP fetcher are replaced by injected fakes, and the DB is a tiny SQLite fixture
built in a temp dir -- nothing touches the network or the real ``chat_history.db``.

Covers the behaviours the ``list_equal`` grader depends on:

- persona_phrase is code-generated from the persona naming rule, including the
  empty-name fallback (``ide_ops_003`` style);
- the candidate pool is built from *annotated* DB messages (join to
  ``message_actions``) and *keyed* Wiki FAQs, excluding unannotated/old rows;
- reply is taken VERBATIM from the chosen candidate (DB content or Wiki FAQ a);
- service_action is resolved through ``service_action_key_map`` and is one of
  ``service_action_options`` verbatim;
- DB-annotated candidates are preferred over Wiki candidates for the same topic;
- each element has exactly one ``=>`` and two ``|||``; the element count is
  stable and in dialog order; the answer parses as a JSON array;
- missing config / DB / wiki degrade without crashing.

Nothing about the public answers is hard-coded: every reply/action/key is built
into the fixture and read back through the same machinery the skill uses.

Standard-library unittest. Chinese literals here are test fixture wording; this
module is allowed non-ASCII because it is not a skill entrypoint.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT / "source" / "solution" / "skills" / "wiki_dialog" / "scripts" / "run.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("wiki_dialog_run", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load_module()


# --- fixtures --------------------------------------------------------------

# Verbatim reply texts (Chinese / English / mixed), as they would live in the
# sources. NONE contain "=>", "|||" or a newline.
REPLY_LOGIN_NEW = "不要直接删除整个 ~/.devpilot 目录；只允许清理 ~/.devpilot/auth/session.json 和 login_state.json"
REPLY_LOGIN_OLD = "可以直接删除整个 ~/.devpilot 目录后重新登录"  # stale, unannotated
REPLY_COMPLETION = "先确认 completion-service 是否 running，再查看最近一次 completion 请求的 traceId 和模型网关返回码"
REPLY_INDEX_DB = "不要默认删除整个 workspace_index；先检查 index.lock 与 metadata.db"
REPLY_INDEX_WIKI = "本地索引异常时可以删除 workspace_index 后重建。"  # wiki, keyed but stale text
REPLY_MCP_WIKI = "MCP 连接失败时先检查 mcp.json 与 MCP server 配置，确认 stdio/http 模式，不要直接关闭全部 MCP 功能"

# Persona naming rule pieces (Chinese), built so the fixture mirrors persona.md.
GREET = chr(0x60A8) + chr(0x597D)              # "nin hao"
SUFFIX = chr(0x603B)                            # "zong" U+603B
FALLBACK = GREET + chr(0x8001) + chr(0x5E08)    # "nin hao lao shi"

PERSONA_MD = "\n".join(
    [
        "# FSE Persona",
        "## 称呼规则",
        "如果题目中提供 user.name，则使用：%s{user.name}%s。" % (GREET, SUFFIX),
        "如果题目中未提供 user.name 或 user.name 为空，则使用：%s。" % FALLBACK,
    ]
)

# Action map + options (the single source of truth the skill reads).
SOURCE_ACCESS = {
    "wiki_service": {
        "base_url": "http://127.0.0.1:18080",
        "endpoints": {
            "list_pages": "/api/wiki/pages",
            "get_page": "/api/wiki/pages/{page_id}",
            "submit_update_proposal": "/api/wiki/pages/{page_id}/update_proposal",
        },
    },
    "service_action_options": [
        "标准答复",
        "阻止高风险操作",
        "要求补充定位信息",
        "更新Wiki为最新指导",
    ],
    "service_action_key_map": {
        "PUB-K01": "标准答复",
        "PUB-K02": "阻止高风险操作",
        "PUB-K03": "要求补充定位信息",
        "PUB-K12": "更新Wiki为最新指导",
    },
}

# Dialogs: one with a name, one with an empty name (fallback), one more.
DIALOGS = [
    {"id": "ide_ops_001", "user": {"name": "张伟"}, "question": "login failure / auth session 异常，能删除整个 ~/.devpilot 吗？应该清理哪些 session files？"},
    {"id": "ide_ops_002", "user": {"name": "李明"}, "question": "code completion no response，completion-service 状态怎么查？traceId？"},
    {"id": "ide_ops_003", "user": {"name": ""}, "question": "MCP tool connection failed，能不能直接关闭全部 MCP 功能？mcp.json 怎么查？"},
]


def _build_db(path: str) -> None:
    """Create a tiny chat_history.db with the three real tables and fixtures.

    Includes annotated messages (joined via message_actions) AND unannotated
    noise/old messages that MUST NOT enter the candidate pool.
    """
    connection = sqlite3.connect(path)
    cursor = connection.cursor()
    cursor.execute(
        "CREATE TABLE conversations (conversation_id TEXT PRIMARY KEY, title TEXT, "
        "created_at TEXT, updated_at TEXT, tags TEXT)"
    )
    cursor.execute(
        "CREATE TABLE messages (message_id TEXT PRIMARY KEY, conversation_id TEXT, "
        "role TEXT, content TEXT, created_at TEXT)"
    )
    cursor.execute(
        "CREATE TABLE message_actions (message_id TEXT PRIMARY KEY, "
        "service_action_key TEXT NOT NULL, action_basis TEXT NOT NULL)"
    )
    cursor.execute(
        "INSERT INTO conversations VALUES (?,?,?,?,?)",
        ("conv_login", "login", "2026-05-25", "2026-05-25", "login"),
    )

    messages = [
        # message_id, conversation, role, content, created_at
        ("m_login_old", "conv_login", "assistant", REPLY_LOGIN_OLD, "2026-05-10 10:00:00"),
        ("m_login_new", "conv_login", "assistant", REPLY_LOGIN_NEW, "2026-05-25 11:00:00"),
        ("m_completion", "conv_completion", "assistant", REPLY_COMPLETION, "2026-05-24 14:00:00"),
        ("m_index_new", "conv_index", "assistant", REPLY_INDEX_DB, "2026-05-25 15:20:00"),
        ("m_noise", "conv_noise", "assistant", "今天天气不错，中午吃什么？", "2026-05-01 09:00:00"),
    ]
    cursor.executemany("INSERT INTO messages VALUES (?,?,?,?,?)", messages)

    # Only these messages are annotated (authoritative). m_login_old, m_noise
    # are deliberately left out so they cannot be selected as replies.
    actions = [
        ("m_login_new", "PUB-K02", "exact reply source action key"),
        ("m_completion", "PUB-K03", "exact reply source action key"),
        ("m_index_new", "PUB-K12", "exact reply source action key"),
    ]
    cursor.executemany("INSERT INTO message_actions VALUES (?,?,?)", actions)
    connection.commit()
    connection.close()


def _fake_wiki_fetcher() -> Any:
    """A fetcher stub returning a list_pages list and per-page get_page payloads.

    Page WKP-INDEX has a keyed FAQ whose text differs from the DB (stale wiki
    wording) -> proves DB-annotated preference. Page WKP-MCP has a keyed FAQ with
    NO DB counterpart -> proves wiki candidates are used when DB lacks the topic.
    Page WKP-NOISE has an FAQ with NO service_action_key -> must be excluded.
    """
    pages = {
        "WKP-INDEX": {
            "id": "WKP-INDEX",
            "faqs": [
                {"id": "index_old", "q": "workspace_index?", "a": REPLY_INDEX_WIKI, "service_action_key": "PUB-K12"},
            ],
        },
        "WKP-MCP": {
            "id": "WKP-MCP",
            "faqs": [
                {"id": "mcp", "q": "MCP failed?", "a": REPLY_MCP_WIKI, "service_action_key": "PUB-K02"},
            ],
        },
        "WKP-NOISE": {
            "id": "WKP-NOISE",
            "faqs": [
                {"id": "noise", "q": "theme?", "a": "随便设置主题颜色即可"},  # no key -> excluded
            ],
        },
    }
    listing = [{"id": pid, "title": pid, "faq_count": len(p["faqs"])} for pid, p in pages.items()]

    def fetcher(url: str, timeout: int) -> Any:
        if url.endswith("/api/wiki/pages"):
            return listing
        for pid, payload in pages.items():
            if url.endswith("/api/wiki/pages/" + pid):
                return payload
        raise RuntimeError("unexpected url %s" % url)

    return fetcher


def _selector_by_reply(reply_for_question: Dict[str, str]):
    """A selection seam stub: map a question fragment to the desired reply text.

    Returns the index (within the ranked candidates the skill passes in) of the
    candidate whose ``reply`` equals the desired text, so tests assert on the
    chosen source rather than guessing an index. Falls back to index 0.
    """

    def selector(config: Dict[str, str], question: str, candidates: List[Dict[str, Any]], timeout: int) -> int:
        for fragment, desired_reply in reply_for_question.items():
            if fragment in question:
                for index, candidate in enumerate(candidates):
                    if candidate.get("reply") == desired_reply:
                        return index
                return 0
        return 0

    return selector


def _force_offline_env() -> None:
    for key in ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL", "MODEL_API_KEY",
                "MODEL_NAME", "PACKAGE_ID", "packageId"):
        os.environ.pop(key, None)


def _set_fake_config() -> None:
    os.environ["MODEL_CHAT_COMPLETIONS_URL"] = "http://example.invalid/v1/chat/completions"
    os.environ["MODEL_API_KEY"] = "sk-test"
    os.environ["MODEL_NAME"] = "test-model"


def _write_inputs(tmp: Path) -> Path:
    source_dir = tmp / "IDE_FSE"
    source_dir.mkdir()
    (source_dir / "persona.md").write_bytes(PERSONA_MD.encode("utf-8"))
    (source_dir / "source_access.json").write_bytes(
        json.dumps(SOURCE_ACCESS, ensure_ascii=False).encode("utf-8")
    )
    (source_dir / "dialog_tests_complex.json").write_bytes(
        json.dumps(DIALOGS, ensure_ascii=False).encode("utf-8")
    )
    _build_db(str(source_dir / "chat_history.db"))
    return source_dir


# --- persona naming rule ---------------------------------------------------

class PersonaTest(unittest.TestCase):
    def test_parses_rule_and_builds_phrase(self) -> None:
        rule = MOD.parse_naming_rule(PERSONA_MD)
        self.assertEqual(rule["greet"], GREET)
        self.assertEqual(rule["suffix"], SUFFIX)
        self.assertEqual(rule["fallback"], FALLBACK)
        self.assertEqual(MOD.persona_phrase("张伟", rule), GREET + "张伟" + SUFFIX)

    def test_empty_name_uses_fallback(self) -> None:
        rule = MOD.parse_naming_rule(PERSONA_MD)
        self.assertEqual(MOD.persona_phrase("", rule), FALLBACK)
        self.assertEqual(MOD.persona_phrase(None, rule), FALLBACK)
        self.assertEqual(MOD.persona_phrase("   ", rule), FALLBACK)

    def test_phrase_has_no_spaces_or_drift(self) -> None:
        rule = MOD.parse_naming_rule(PERSONA_MD)
        phrase = MOD.persona_phrase("李明", rule)
        self.assertNotIn(" ", phrase)
        self.assertTrue(phrase.endswith(SUFFIX))
        self.assertTrue(phrase.startswith(GREET))

    def test_default_rule_when_persona_missing(self) -> None:
        # Empty persona text -> documented defaults, still code-generated.
        rule = MOD.parse_naming_rule("")
        self.assertEqual(MOD.persona_phrase("王芳", rule), GREET + "王芳" + SUFFIX)
        self.assertEqual(MOD.persona_phrase("", rule), FALLBACK)


# --- candidate pool --------------------------------------------------------

class CandidatePoolTest(unittest.TestCase):
    def test_db_pool_only_annotated_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "chat_history.db")
            _build_db(db_path)
            candidates = MOD.load_db_candidates(db_path)
            replies = {c["reply"] for c in candidates}
            # Annotated rows present:
            self.assertIn(REPLY_LOGIN_NEW, replies)
            self.assertIn(REPLY_COMPLETION, replies)
            self.assertIn(REPLY_INDEX_DB, replies)
            # Unannotated old / noise rows excluded:
            self.assertNotIn(REPLY_LOGIN_OLD, replies)
            self.assertNotIn("今天天气不错，中午吃什么？", replies)
            # Keys are carried verbatim from message_actions.
            by_reply = {c["reply"]: c["key"] for c in candidates}
            self.assertEqual(by_reply[REPLY_LOGIN_NEW], "PUB-K02")
            self.assertEqual(by_reply[REPLY_INDEX_DB], "PUB-K12")
            self.assertTrue(all(c["source"] == "db" for c in candidates))

    def test_wiki_pool_only_keyed_faqs(self) -> None:
        candidates = MOD.load_wiki_candidates(SOURCE_ACCESS, 5, _fake_wiki_fetcher())
        replies = {c["reply"] for c in candidates}
        self.assertIn(REPLY_INDEX_WIKI, replies)
        self.assertIn(REPLY_MCP_WIKI, replies)
        # FAQ without a service_action_key is excluded.
        self.assertNotIn("随便设置主题颜色即可", replies)
        self.assertTrue(all(c["source"] == "wiki" for c in candidates))

    def test_missing_db_returns_empty_no_crash(self) -> None:
        self.assertEqual(MOD.load_db_candidates("/no/such/file.db"), [])

    def test_wiki_fetch_failure_degrades(self) -> None:
        def boom(url: str, timeout: int) -> Any:
            raise RuntimeError("network down")

        self.assertEqual(MOD.load_wiki_candidates(SOURCE_ACCESS, 5, boom), [])


# --- action resolution -----------------------------------------------------

class ActionResolutionTest(unittest.TestCase):
    def test_resolves_key_to_option(self) -> None:
        key_map, options = MOD.load_action_map(SOURCE_ACCESS)
        self.assertEqual(MOD.resolve_action("PUB-K02", key_map, options), "阻止高风险操作")
        self.assertEqual(MOD.resolve_action("PUB-K12", key_map, options), "更新Wiki为最新指导")

    def test_unknown_key_returns_none(self) -> None:
        key_map, options = MOD.load_action_map(SOURCE_ACCESS)
        self.assertIsNone(MOD.resolve_action("PUB-K99", key_map, options))

    def test_action_must_be_in_options(self) -> None:
        # A key mapping to a value not in options is rejected (out of contract).
        key_map = {"PUB-KX": "不在选项里的动作"}
        options = ["标准答复"]
        self.assertIsNone(MOD.resolve_action("PUB-KX", key_map, options))


# --- element grammar -------------------------------------------------------

class ElementTest(unittest.TestCase):
    def test_exactly_one_arrow_two_pipes(self) -> None:
        element = MOD.build_element("ide_ops_001", GREET + "张伟" + SUFFIX, REPLY_LOGIN_NEW, "阻止高风险操作")
        self.assertEqual(element.count("=>"), 1)
        self.assertEqual(element.count("|||"), 2)
        head, rest = element.split("=>", 1)
        self.assertEqual(head, "ide_ops_001")
        persona, reply, action = rest.split("|||")
        self.assertEqual(reply, REPLY_LOGIN_NEW)  # verbatim
        self.assertEqual(action, "阻止高风险操作")


# --- end-to-end ------------------------------------------------------------

class EndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        _force_offline_env()

    def _run(self, selector) -> Dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = _write_inputs(Path(tmp))
            args = {
                "task_description": "answer the dialogs",
                "source_dir": str(source_dir),
                "_runtime": {"question_dir": str(source_dir.parent), "question_id": "3_3"},
            }
            _set_fake_config()
            try:
                return MOD.answer(args, selector=selector, fetcher=_fake_wiki_fetcher())
            finally:
                _force_offline_env()

    def test_verbatim_reply_and_resolved_action_in_order(self) -> None:
        selector = _selector_by_reply(
            {
                "login failure": REPLY_LOGIN_NEW,
                "code completion": REPLY_COMPLETION,
                "MCP tool": REPLY_MCP_WIKI,
            }
        )
        result = self._run(selector)

        self.assertEqual(result["n"], 3)
        parsed = json.loads(result["answer"])  # answer is a JSON array text
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 3)

        # Element 0: DB login reply, verbatim, persona with name.
        head0, rest0 = parsed[0].split("=>", 1)
        persona0, reply0, action0 = rest0.split("|||")
        self.assertEqual(head0, "ide_ops_001")
        self.assertEqual(persona0, GREET + "张伟" + SUFFIX)
        self.assertEqual(reply0, REPLY_LOGIN_NEW)
        self.assertEqual(action0, "阻止高风险操作")

        # Element 1: completion reply -> PUB-K03 -> 要求补充定位信息.
        _, rest1 = parsed[1].split("=>", 1)
        persona1, reply1, action1 = rest1.split("|||")
        self.assertEqual(persona1, GREET + "李明" + SUFFIX)
        self.assertEqual(reply1, REPLY_COMPLETION)
        self.assertEqual(action1, "要求补充定位信息")

        # Element 2: empty name -> fallback persona; wiki MCP reply verbatim.
        head2, rest2 = parsed[2].split("=>", 1)
        persona2, reply2, action2 = rest2.split("|||")
        self.assertEqual(head2, "ide_ops_003")
        self.assertEqual(persona2, FALLBACK)
        self.assertEqual(reply2, REPLY_MCP_WIKI)
        self.assertEqual(action2, "阻止高风险操作")

        # Every element has exactly one => and two |||.
        for element in parsed:
            self.assertEqual(element.count("=>"), 1)
            self.assertEqual(element.count("|||"), 2)
        # Sources recorded.
        self.assertEqual(result["per_dialog"][0]["source"], "db")
        self.assertEqual(result["per_dialog"][2]["source"], "wiki")

    def test_db_annotated_preferred_over_wiki_same_topic(self) -> None:
        # For the index topic the pool has BOTH a DB candidate (REPLY_INDEX_DB)
        # and a stale wiki candidate (REPLY_INDEX_WIKI) with the same key. A
        # selector that just takes index 0 of the ranked list must get the DB one
        # because DB candidates are ordered/ranked ahead of wiki on ties.
        def take_first(config, question, candidates, timeout):
            return 0

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = _write_inputs(Path(tmp))
            # A single index dialog so ranking is about this topic.
            dialogs = [{"id": "d1", "user": {"name": "赵六"}, "question": "workspace_index building 失败，能删除 workspace_index 吗？"}]
            (source_dir / "dialog_tests_complex.json").write_bytes(
                json.dumps(dialogs, ensure_ascii=False).encode("utf-8")
            )
            args = {
                "task_description": "x",
                "source_dir": str(source_dir),
                "_runtime": {"question_dir": str(source_dir.parent)},
            }
            _set_fake_config()
            try:
                result = MOD.answer(args, selector=take_first, fetcher=_fake_wiki_fetcher())
            finally:
                _force_offline_env()
        parsed = json.loads(result["answer"])
        _, rest = parsed[0].split("=>", 1)
        _, reply, action = rest.split("|||")
        # DB wording wins (not the stale wiki text), though both map to PUB-K12.
        self.assertEqual(reply, REPLY_INDEX_DB)
        self.assertEqual(action, "更新Wiki为最新指导")
        self.assertEqual(result["per_dialog"][0]["source"], "db")

    def test_stable_count_and_order_with_constant_selector(self) -> None:
        result = self._run(lambda c, q, cands, t: 0)
        parsed = json.loads(result["answer"])
        self.assertEqual(len(parsed), 3)
        # Order follows dialog file order regardless of selection.
        ids = [el.split("=>", 1)[0] for el in parsed]
        self.assertEqual(ids, ["ide_ops_001", "ide_ops_002", "ide_ops_003"])

    def test_no_config_degrades_to_lexical_no_crash(self) -> None:
        # No MODEL_* env -> config None -> lexical pick; still N elements.
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = _write_inputs(Path(tmp))
            args = {
                "task_description": "x",
                "source_dir": str(source_dir),
                "_runtime": {"question_dir": str(source_dir.parent)},
            }
            result = MOD.answer(args, fetcher=_fake_wiki_fetcher())
        parsed = json.loads(result["answer"])
        self.assertEqual(len(parsed), 3)
        self.assertTrue(any("not configured" in w for w in result["warnings"]))
        # Lexical selection should still match the login dialog to the login reply.
        _, rest0 = parsed[0].split("=>", 1)
        _, reply0, _ = rest0.split("|||")
        self.assertEqual(reply0, REPLY_LOGIN_NEW)

    def test_wiki_down_uses_db_pool_only(self) -> None:
        def boom(url: str, timeout: int) -> Any:
            raise RuntimeError("wiki down")

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = _write_inputs(Path(tmp))
            args = {
                "task_description": "x",
                "source_dir": str(source_dir),
                "_runtime": {"question_dir": str(source_dir.parent)},
            }
            _set_fake_config()
            try:
                # MCP dialog has no DB candidate; with wiki down it falls back to
                # the top DB candidate -> still a valid element, no crash.
                result = MOD.answer(args, selector=lambda c, q, cands, t: 0, fetcher=boom)
            finally:
                _force_offline_env()
        self.assertEqual(result["wiki_candidates"], 0)
        parsed = json.loads(result["answer"])
        self.assertEqual(len(parsed), 3)
        for element in parsed:
            self.assertEqual(element.count("=>"), 1)
            self.assertEqual(element.count("|||"), 2)

    def test_grader_scores_full_with_real_rubric(self) -> None:
        # Feed the assembled answer through the real list_equal grader with a
        # reference built from the SAME verbatim sources -> perfect score, which
        # proves every element matches whole-string.
        import importlib.util as _ilu

        score_path = REPO_ROOT / "source" / "eval" / "score.py"
        spec = _ilu.spec_from_file_location("score_mod_wd", score_path)
        assert spec and spec.loader
        score_mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(score_mod)

        selector = _selector_by_reply(
            {
                "login failure": REPLY_LOGIN_NEW,
                "code completion": REPLY_COMPLETION,
                "MCP tool": REPLY_MCP_WIKI,
            }
        )
        result = self._run(selector)

        reference = json.dumps(
            [
                "ide_ops_001=>" + GREET + "张伟" + SUFFIX + "|||" + REPLY_LOGIN_NEW + "|||阻止高风险操作",
                "ide_ops_002=>" + GREET + "李明" + SUFFIX + "|||" + REPLY_COMPLETION + "|||要求补充定位信息",
                "ide_ops_003=>" + FALLBACK + "|||" + REPLY_MCP_WIKI + "|||阻止高风险操作",
            ],
            ensure_ascii=False,
        )
        earned = score_mod.score_list_equal(reference, result["answer"], 5.0)
        # score_list_equal may return a float or (float, detail) depending on impl.
        if isinstance(earned, tuple):
            earned = earned[0]
        self.assertAlmostEqual(earned, 5.0, places=6)


if __name__ == "__main__":
    unittest.main()
