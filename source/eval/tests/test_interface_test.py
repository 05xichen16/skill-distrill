"""Offline tests for the interface_test skill.

Fully offline: the model seam (``parse_steps``) is replaced by an injected fake
that returns canned structured steps, and the HTTP seam (``http_request``) is
replaced by an in-memory fake service, so nothing touches the network. Covers
the behaviours the ratio grader depends on:

- dotted-path resolution incl. array indices (``data.list.0.userId``);
- the three assertion classes (status / expectedFields presence / expectedValues
  exact equality), including an expected 404 and a missing-field failure;
- failing IDs joined with ``,`` **in code, in test_cases file order**, with no
  drift (under-report rather than over-report on unjudgeable cases);
- multi-step cases assert the response of the step marked ``assert`` (or the
  last step), not an earlier one;
- a write step fetches a FRESH token first and sends Authorization; a
  ``reuse_token`` step reuses the prior token (to exercise a 401);
- graceful degradation: no model config / no steps / a transport error never
  crashes and never reports the case as failing (positions stay intact).

NO hard-coded public failing IDs (TC009 etc.): the cases, responses and
assertions are all synthetic fixtures, exercising the generic mechanism.

Standard-library unittest. The few Chinese literals here are fixture text; this
module is allowed non-ASCII because it is not a skill entrypoint (the skill
source stays pure-ASCII).
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT
    / "source"
    / "solution"
    / "skills"
    / "interface_test"
    / "scripts"
    / "run.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("interface_test_run", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load_module()


AUTH_CONFIG = {
    "baseUrl": "http://127.0.0.1:18081",
    "packageIdHeader": "X-Package-Id",
    "token": {
        "endpoint": "/api/auth/token",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": {"clientId": "demo", "clientSecret": "secret"},
        "responseTokenPath": "data.accessToken",
        "authorizationHeaderFormat": "Bearer ${accessToken}",
    },
}


def _force_offline_env() -> None:
    for key in ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL", "MODEL_API_KEY",
                "MODEL_NAME", "PACKAGE_ID", "packageId"):
        os.environ.pop(key, None)


def _set_fake_config() -> None:
    os.environ["MODEL_CHAT_COMPLETIONS_URL"] = "http://example.invalid/v1/chat/completions"
    os.environ["MODEL_API_KEY"] = "sk-test"
    os.environ["MODEL_NAME"] = "test-model"
    os.environ["PACKAGE_ID"] = "pkg-test"


# --- dotted path + assertions ----------------------------------------------

class DottedPathTest(unittest.TestCase):
    def test_object_path(self) -> None:
        found, value = MOD.get_dotted({"data": {"userId": "U1"}}, "data.userId")
        self.assertTrue(found)
        self.assertEqual(value, "U1")

    def test_array_index_path(self) -> None:
        body = {"data": {"list": [{"userId": "A"}, {"userId": "B"}]}}
        found, value = MOD.get_dotted(body, "data.list.0.userId")
        self.assertTrue(found)
        self.assertEqual(value, "A")
        found, value = MOD.get_dotted(body, "data.list.1.userId")
        self.assertEqual(value, "B")

    def test_missing_key_not_found(self) -> None:
        found, _ = MOD.get_dotted({"data": {}}, "data.title")
        self.assertFalse(found)

    def test_out_of_range_index_not_found(self) -> None:
        found, _ = MOD.get_dotted({"data": {"list": [{"x": 1}]}}, "data.list.5.x")
        self.assertFalse(found)

    def test_present_null_is_found(self) -> None:
        found, value = MOD.get_dotted({"data": None}, "data")
        self.assertTrue(found)
        self.assertIsNone(value)


class AssertResponseTest(unittest.TestCase):
    def test_pass_all_three_classes(self) -> None:
        body = {"code": 0, "data": {"userId": "U1", "email": "a@b.c"}}
        assertion = {
            "expectedStatus": 200,
            "expectedFields": ["code", "data.userId", "data.email"],
            "expectedValues": {"code": 0, "data.userId": "U1"},
        }
        passed, reason = MOD.assert_response(200, body, assertion)
        self.assertTrue(passed, reason)

    def test_status_mismatch_fails(self) -> None:
        passed, reason = MOD.assert_response(
            200, {"code": 1004}, {"expectedStatus": 404, "expectedValues": {"code": 1004}}
        )
        self.assertFalse(passed)
        self.assertIn("status", reason)

    def test_expected_404_passes(self) -> None:
        body = {"code": 1004, "message": "user not found", "data": None}
        assertion = {
            "expectedStatus": 404,
            "expectedFields": ["code", "message", "data"],
            "expectedValues": {"code": 1004, "message": "user not found", "data": None},
        }
        passed, reason = MOD.assert_response(404, body, assertion)
        self.assertTrue(passed, reason)

    def test_missing_field_fails(self) -> None:
        # Mirrors the "title popped from the response" failure mode.
        body = {"code": 0, "data": {"userId": "U1"}}  # no data.title
        assertion = {
            "expectedStatus": 200,
            "expectedFields": ["data.title"],
            "expectedValues": {"data.title": "Engineer"},
        }
        passed, reason = MOD.assert_response(200, body, assertion)
        self.assertFalse(passed)
        self.assertIn("title", reason)

    def test_value_mismatch_fails(self) -> None:
        body = {"code": 0, "data": {"activeCount": 63}}
        assertion = {"expectedValues": {"data.activeCount": 64}}
        passed, reason = MOD.assert_response(200, body, assertion)
        self.assertFalse(passed)

    def test_int_float_equal(self) -> None:
        passed, _ = MOD.assert_response(200, {"data": {"n": 2}}, {"expectedValues": {"data.n": 2.0}})
        self.assertTrue(passed)

    def test_bool_not_equal_to_int(self) -> None:
        passed, _ = MOD.assert_response(200, {"data": {"ok": True}}, {"expectedValues": {"data.ok": 1}})
        self.assertFalse(passed)


# --- auth config parsing ---------------------------------------------------

class AuthConfigTest(unittest.TestCase):
    def test_reads_from_file_not_hardcoded(self) -> None:
        auth = MOD.build_auth(AUTH_CONFIG)
        self.assertEqual(auth["base_url"], "http://127.0.0.1:18081")
        self.assertEqual(auth["pkg_header"], "X-Package-Id")
        self.assertEqual(auth["token_endpoint"], "/api/auth/token")
        self.assertEqual(auth["token_path"], "data.accessToken")
        self.assertEqual(auth["token_body"], {"clientId": "demo", "clientSecret": "secret"})

    def test_variant_endpoint_respected(self) -> None:
        variant = {
            "baseUrl": "http://svc:9000",
            "packageIdHeader": "X-Pkg",
            "token": {"endpoint": "/v2/auth", "responseTokenPath": "result.token"},
        }
        auth = MOD.build_auth(variant)
        self.assertEqual(auth["base_url"], "http://svc:9000")
        self.assertEqual(auth["pkg_header"], "X-Pkg")
        self.assertEqual(auth["token_endpoint"], "/v2/auth")
        self.assertEqual(auth["token_path"], "result.token")

    def test_auth_header_format(self) -> None:
        self.assertEqual(MOD._format_auth_header("Bearer ${accessToken}", "T1"), "Bearer T1")
        self.assertEqual(MOD._format_auth_header("Token {accessToken}", "T1"), "Token T1")


# --- step normalisation + JSON extraction ----------------------------------

class StepParsingHelpersTest(unittest.TestCase):
    def test_normalise_infers_write_from_method(self) -> None:
        step = MOD._normalise_step({"method": "post", "path": "/api/user/update"})
        self.assertEqual(step["method"], "POST")
        self.assertTrue(step["write"])
        step = MOD._normalise_step({"method": "get", "path": "/api/user/detail/U1"})
        self.assertFalse(step["write"])

    def test_normalise_explicit_write_flag_wins(self) -> None:
        step = MOD._normalise_step({"method": "GET", "path": "/x", "write": True})
        self.assertTrue(step["write"])

    def test_extract_json_array_plain(self) -> None:
        arr = MOD._extract_json_array('[{"method":"GET","path":"/x"}]')
        self.assertEqual(arr, [{"method": "GET", "path": "/x"}])

    def test_extract_json_array_fenced(self) -> None:
        text = "here you go:\n```json\n[{\"method\":\"GET\"}]\n```\nthanks"
        self.assertEqual(MOD._extract_json_array(text), [{"method": "GET"}])

    def test_extract_json_array_embedded(self) -> None:
        text = 'prose [{"a":1}] trailing'
        self.assertEqual(MOD._extract_json_array(text), [{"a": 1}])


class DeterministicInferenceTest(unittest.TestCase):
    def test_english_one_line_endpoint_catalog(self) -> None:
        api_doc = """
### User detail
GET /v2/users/{userId}

### Search users
GET /v2/users/search

### Remove user
DELETE /v2/users/{userId}
"""
        catalog = MOD.parse_endpoint_catalog(api_doc)
        self.assertEqual(catalog["detail"]["path"], "/v2/users/{userId}")
        self.assertEqual(catalog["search"]["path"], "/v2/users/search")
        self.assertEqual(catalog["delete"]["path"], "/v2/users/{userId}")

    def test_update_then_detail_steps(self) -> None:
        case = {
            "id": "T1",
            "description": "获取 token，更新用户 U1003 的邮箱为 u@example.com、职级为 Senior，然后查询 U1003 详情。",
            "assert": {
                "expectedValues": {
                    "data.userId": "U1003",
                    "data.email": "u@example.com",
                    "data.title": "Senior",
                }
            },
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["method"], "POST")
        self.assertTrue(steps[0]["write"])
        self.assertEqual(steps[0]["body"], {"userId": "U1003", "email": "u@example.com", "title": "Senior"})
        self.assertFalse(steps[0]["assert"])
        self.assertEqual(steps[1]["method"], "GET")
        self.assertEqual(steps[1]["path"], "/api/user/detail/U1003")
        self.assertTrue(steps[1]["assert"])

    def test_verbose_detail_for_manager_assertion(self) -> None:
        case = {
            "id": "T2",
            "description": "查询用户 U1010 的详细信息，携带 verbose=true；校验经理信息。",
            "assert": {
                "expectedFields": ["data.userId", "data.manager.userId"],
                "expectedValues": {"data.userId": "U1010"},
            },
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["path"], "/api/user/detail/U1010")
        self.assertEqual(steps[0]["query"], {"verbose": True})

    def test_search_query_from_description(self) -> None:
        case = {
            "id": "T3",
            "description": "按 status=active、page=1、pageSize=5、sortOrder=desc 查询用户列表。",
            "assert": {"expectedFields": ["data.page", "data.list.0.userId"]},
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(steps[0]["path"], "/api/user/search")
        self.assertEqual(steps[0]["query"]["status"], "active")
        self.assertEqual(steps[0]["query"]["page"], 1)
        self.assertEqual(steps[0]["query"]["pageSize"], 5)
        self.assertEqual(steps[0]["query"]["sortOrder"], "desc")

    def test_search_query_from_natural_language_and_assertions(self) -> None:
        case = {
            "id": "T4",
            "description": "查询 platform 部门用户列表，第2页，每页2条，按升序排列。",
            "assert": {
                "expectedFields": ["data.page", "data.pageSize", "data.list.0.userId"],
                "expectedValues": {"data.page": 2, "data.pageSize": 2},
            },
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(steps[0]["path"], "/api/user/search")
        self.assertEqual(steps[0]["query"]["department"], "platform")
        self.assertEqual(steps[0]["query"]["page"], 2)
        self.assertEqual(steps[0]["query"]["pageSize"], 2)
        self.assertEqual(steps[0]["query"]["sortOrder"], "asc")

    def test_delete_then_detail_steps(self) -> None:
        case = {
            "id": "T5",
            "description": "删除用户 U1004，然后查询 U1004 详情；校验异常响应。",
            "assert": {"expectedStatus": 404, "expectedValues": {"code": 1004}},
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["method"], "DELETE")
        self.assertTrue(steps[0]["write"])
        self.assertFalse(steps[0]["assert"])
        self.assertEqual(steps[1]["path"], "/api/user/detail/U1004")
        self.assertTrue(steps[1]["assert"])

    def test_note_create_steps(self) -> None:
        case = {
            "id": "T6",
            "description": "为用户 U1007 创建备注，备注为需要二线跟进；校验创建响应。",
            "assert": {"expectedValues": {"data.userId": "U1007", "data.content": "需要二线跟进"}},
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["path"], "/api/user/note/create")
        self.assertEqual(steps[0]["body"], {"userId": "U1007", "content": "需要二线跟进"})
        self.assertTrue(steps[0]["write"])

    def test_search_abstains_without_discriminator(self) -> None:
        # Fix A: a row-shaped assertion (data.list.* / data.total) with only
        # pagination/sort recovered (no status/department/keyword) must ABSTAIN
        # ([]) rather than fire a confident-but-wrong search that would mis-FAIL
        # a passing case at an early position (zeroing the ratio grader).
        case = {
            "id": "T7",
            "description": "按降序翻到第二页，每页五条列出用户；核对分页与首条。",
            "assert": {
                "expectedFields": ["data.page", "data.total", "data.list.0.userId"],
                "expectedValues": {"data.page": 2},
            },
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(steps, [])  # abstained -> falls through to the model seam

    def test_search_emits_when_discriminator_present(self) -> None:
        # The flip side of Fix A: with a discriminator recovered, the search is
        # high-confidence and IS emitted (no abstain).
        case = {
            "id": "T8",
            "description": "用 status=active 查询用户，第一页每页十条；核对命中。",
            "assert": {
                "expectedFields": ["data.total", "data.list.0.userId"],
                "expectedValues": {"data.total": 1},
            },
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["path"], "/api/user/search")
        self.assertEqual(steps[0]["query"]["status"], "active")

    def test_enum_status_recovered_from_synonyms(self) -> None:
        # Fix D: the status enum may be named with a synonym rather than
        # ``status=active``. Recovering it lets the search be judged in code
        # (paired with Fix A's abstain when nothing is recoverable).
        active = MOD._query_from_description("把处于活跃状态的用户列出来，第一页每页一百条，升序。")
        self.assertEqual(active.get("status"), "active")
        on_duty = MOD._query_from_description("列出所有在岗（active）的人，正序。")
        self.assertEqual(on_duty.get("status"), "active")
        inactive = MOD._query_from_description("把停用用户按降序列出。")
        self.assertEqual(inactive.get("status"), "inactive")
        not_active = MOD._query_from_description("不活跃的人按倒序排列。")
        self.assertEqual(not_active.get("status"), "inactive")

    def test_enum_status_search_emits_with_synonym(self) -> None:
        # End-to-end of Fix D + Fix A: a search case that names the status by a
        # synonym now emits a correct, discriminated search instead of abstaining.
        case = {
            "id": "T9",
            "description": "把活跃用户停在第一页、每页五条、按降序列出；核对打头的那一条。",
            "assert": {
                "expectedFields": ["data.page", "data.total", "data.list.0.userId"],
                "expectedValues": {"data.page": 1},
            },
        }
        steps = MOD.infer_steps_from_case(case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["path"], "/api/user/search")
        self.assertEqual(steps[0]["query"]["status"], "active")
        self.assertEqual(steps[0]["query"]["sortOrder"], "desc")

    def test_sort_order_extra_synonyms(self) -> None:
        # Fix D companion: 从大到小 / 从小到大 also resolve sortOrder.
        self.assertEqual(
            MOD._query_from_description("按从大到小排列").get("sortOrder"), "desc"
        )
        self.assertEqual(
            MOD._query_from_description("一页放两条，从小到大排").get("sortOrder"), "asc"
        )

    def test_missing_field_reason_classification(self) -> None:
        # The Fix B classifier: an absence (missing field/value) is a
        # wrong-request tell, a present-but-wrong value/status is a real failure.
        self.assertTrue(MOD._is_missing_field_reason("missing field data.list.0.userId"))
        self.assertTrue(MOD._is_missing_field_reason("missing value field data.title"))
        self.assertFalse(MOD._is_missing_field_reason("value data.activeCount = 63 != expected 64"))
        self.assertFalse(MOD._is_missing_field_reason("status 200 != expected 404"))
        self.assertFalse(MOD._is_missing_field_reason(""))


# --- a fake in-memory service (the http_request seam) -----------------------

PUBLIC_API_DOC = """
### 查询用户详情
- 路径：`/api/user/detail/{userId}`
- 方法：`GET`

### 分页查询用户列表
- 路径：`/api/user/search`
- 方法：`GET`

### 更新用户信息
- 路径：`/api/user/update`
- 方法：`POST`

### 批量更新用户状态
- 路径：`/api/user/batch-update-status`
- 方法：`POST`

### 查询部门活跃用户统计
- 路径：`/api/user/stat/active`
- 方法：`GET`
"""

class FakeService:
    """A tiny stateful stand-in for the real interface service.

    Records every call. Issues single-use tokens (``token_N``); a write call
    succeeds once per token, then returns 401 on reuse - mirroring the real
    single-write-per-token rule. Serves a couple of read endpoints whose data
    can be mutated by writes, so multi-step "write then read" cases are testable.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._token_seq = 0
        self._spent_tokens: set = set()
        self.users: Dict[str, Dict[str, Any]] = {
            "U1": {"userId": "U1", "email": "old@x.com", "title": "Engineer"},
        }

    def __call__(
        self, method: str, url: str, headers: Dict[str, str], body: Optional[bytes], timeout: int
    ) -> Tuple[int, Any]:
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(url)
        path = parsed.path
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        payload = json.loads(body.decode("utf-8")) if body else None
        auth_header = headers.get("Authorization")
        self.calls.append({"method": method, "path": path, "query": query,
                           "body": payload, "auth": auth_header})

        # Token endpoint.
        if path == "/api/auth/token" and method == "POST":
            self._token_seq += 1
            return 200, {"code": 0, "data": {"accessToken": "token_%d" % self._token_seq}}

        # Write endpoint: consume the token (single use).
        if path == "/api/user/update" and method == "POST":
            token = (auth_header or "").replace("Bearer ", "")
            if not token or token in self._spent_tokens:
                return 401, {"code": 40101, "message": "token expired", "data": None}
            self._spent_tokens.add(token)
            uid = (payload or {}).get("userId")
            if uid in self.users:
                self.users[uid].update({k: v for k, v in (payload or {}).items() if k != "userId"})
            return 200, {"code": 0, "data": self.users.get(uid, {"userId": uid})}

        # Read endpoint: detail.
        if path.startswith("/api/user/detail/") and method == "GET":
            uid = path.rsplit("/", 1)[-1]
            if uid in self.users:
                return 200, {"code": 0, "data": dict(self.users[uid])}
            return 404, {"code": 1004, "message": "user not found", "data": None}

        # Read endpoint: search. A real service keys the result on a
        # discriminating filter (status/department/keyword); a request that
        # carries only pagination/sort hits an EMPTY page (mirrors the wrong
        # -request failure mode the abstain/conservative fixes guard against).
        if path == "/api/user/search" and method == "GET":
            has_discriminator = any(k in query for k in ("status", "department", "keyword"))
            if not has_discriminator:
                return 200, {"code": 0, "data": {"page": int(query.get("page", 1)),
                                                "total": 0, "list": []}}
            return 200, {"code": 0, "data": {"page": int(query.get("page", 1)),
                                            "total": 2,
                                            "list": [{"userId": "A"}, {"userId": "B"}]}}

        return 404, {"code": 1004, "message": "unknown", "data": None}


def _fake_parser(steps_by_id: Dict[str, List[Dict[str, Any]]]) -> Callable[..., List[Dict[str, Any]]]:
    """A parse_steps stub: map a case description fragment to canned steps.

    The case id is embedded in the description so we can key on it. A value that
    is an Exception is raised to exercise the retry/degrade path.
    """

    def parser(config, description, api_doc, auth, timeout):
        for fragment, steps in steps_by_id.items():
            if fragment in description:
                if isinstance(steps, Exception):
                    raise steps
                return [MOD._normalise_step(s) for s in steps]
        return []

    return parser


# --- run_case (token + multi-step) -----------------------------------------

class RunCaseTest(unittest.TestCase):
    def test_write_step_fetches_fresh_token_and_authorizes(self) -> None:
        svc = FakeService()
        auth = MOD.build_auth(AUTH_CONFIG)
        steps = [MOD._normalise_step(s) for s in [
            {"method": "POST", "path": "/api/user/update", "body": {"userId": "U1", "title": "Senior"},
             "write": True, "assert": False},
            {"method": "GET", "path": "/api/user/detail/U1", "write": False, "assert": True},
        ]]
        status, body, error, token = MOD.run_case(steps, auth, "pkg", 30, svc, None)
        self.assertIsNone(error)
        # The asserted response is the LAST (read) step, showing the write took.
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["title"], "Senior")
        # A token was fetched before the write and used as Authorization.
        token_calls = [c for c in svc.calls if c["path"] == "/api/auth/token"]
        self.assertEqual(len(token_calls), 1)
        write_call = [c for c in svc.calls if c["path"] == "/api/user/update"][0]
        self.assertTrue(write_call["auth"].startswith("Bearer token_"))
        # The package-id header rides every call (checked via the seam contract:
        # run_case always sets it; here we just assert the write/read happened).

    def test_two_write_steps_each_get_new_token(self) -> None:
        svc = FakeService()
        auth = MOD.build_auth(AUTH_CONFIG)
        steps = [MOD._normalise_step(s) for s in [
            {"method": "POST", "path": "/api/user/update", "body": {"userId": "U1", "email": "a@a.com"},
             "write": True},
            {"method": "POST", "path": "/api/user/update", "body": {"userId": "U1", "title": "Lead"},
             "write": True, "assert": True},
        ]]
        status, body, error, _ = MOD.run_case(steps, auth, "pkg", 30, svc, None)
        self.assertIsNone(error)
        # Two distinct tokens were issued (one per write) -> second write != 401.
        self.assertEqual(status, 200)
        self.assertEqual(len([c for c in svc.calls if c["path"] == "/api/auth/token"]), 2)

    def test_reuse_token_step_reuses_prior_token(self) -> None:
        svc = FakeService()
        auth = MOD.build_auth(AUTH_CONFIG)
        # First a normal write (gets token_1), then a reuse_token write that must
        # reuse token_1 -> the service returns 401 (token already spent).
        steps = [MOD._normalise_step(s) for s in [
            {"method": "POST", "path": "/api/user/update", "body": {"userId": "U1", "email": "a@a.com"},
             "write": True},
            {"method": "POST", "path": "/api/user/update", "body": {"userId": "U1", "title": "X"},
             "write": True, "reuse_token": True, "assert": True},
        ]]
        status, body, error, _ = MOD.run_case(steps, auth, "pkg", 30, svc, None)
        self.assertIsNone(error)
        self.assertEqual(status, 401)  # reused, spent token rejected
        # Only one token fetch happened (the reuse step did not fetch a new one).
        self.assertEqual(len([c for c in svc.calls if c["path"] == "/api/auth/token"]), 1)

    def test_no_assert_flag_uses_last_response(self) -> None:
        svc = FakeService()
        auth = MOD.build_auth(AUTH_CONFIG)
        steps = [MOD._normalise_step(s) for s in [
            {"method": "GET", "path": "/api/user/detail/U1"},
            {"method": "GET", "path": "/api/user/search", "query": {"page": 2}},
        ]]
        status, body, error, _ = MOD.run_case(steps, auth, "pkg", 30, svc, None)
        self.assertIsNone(error)
        self.assertEqual(body["data"]["page"], 2)  # last step's response


# --- end-to-end answer: ordering, joining, degradation ----------------------

def _write_inputs(tmp: Path, cases: List[Dict[str, Any]]) -> Path:
    doc_dir = tmp / "docs"
    doc_dir.mkdir()
    (doc_dir / "test_cases.json").write_bytes(
        json.dumps(cases, ensure_ascii=False).encode("utf-8")
    )
    (doc_dir / "api_doc.md").write_bytes("# api\n/api/user/detail/{userId}\n".encode("utf-8"))
    (doc_dir / "auth_config.json").write_bytes(
        json.dumps(AUTH_CONFIG, ensure_ascii=False).encode("utf-8")
    )
    return doc_dir


# A synthetic case set: some pass, some fail. NO public IDs / answers.
CASES = [
    {"id": "C1", "description": "case C1 read U1 email",
     "assert": {"expectedStatus": 200, "expectedFields": ["data.userId"],
                "expectedValues": {"data.userId": "U1"}}},
    {"id": "C2", "description": "case C2 read U1 title expect wrong value",
     "assert": {"expectedStatus": 200, "expectedValues": {"data.title": "WRONG"}}},  # will fail
    {"id": "C3", "description": "case C3 read missing user expect 404",
     "assert": {"expectedStatus": 404, "expectedValues": {"code": 1004}}},
    {"id": "C4", "description": "case C4 read U1 expect missing field",
     "assert": {"expectedStatus": 200, "expectedFields": ["data.nope"]}},  # will fail
    {"id": "C5", "description": "case C5 write then read U1 title",
     "assert": {"expectedStatus": 200, "expectedValues": {"data.title": "Senior"}}},
]

STEPS_BY_ID = {
    "case C1": [{"method": "GET", "path": "/api/user/detail/U1", "assert": True}],
    "case C2": [{"method": "GET", "path": "/api/user/detail/U1", "assert": True}],
    "case C3": [{"method": "GET", "path": "/api/user/detail/U404", "assert": True}],
    "case C4": [{"method": "GET", "path": "/api/user/detail/U1", "assert": True}],
    "case C5": [
        {"method": "POST", "path": "/api/user/update", "body": {"userId": "U1", "title": "Senior"},
         "write": True},
        {"method": "GET", "path": "/api/user/detail/U1", "assert": True},
    ],
}


class EndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        _force_offline_env()

    def tearDown(self) -> None:
        _force_offline_env()

    def test_failing_ids_in_order_comma_joined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc_dir = _write_inputs(Path(tmp), CASES)
            _set_fake_config()
            svc = FakeService()
            args = {
                "task_description": "verify the cases",
                "doc_dir": str(doc_dir),
                "_runtime": {"question_dir": str(doc_dir.parent), "question_id": "1_4"},
            }
            result = MOD.answer(args, parser=_fake_parser(STEPS_BY_ID), requester=svc)

        self.assertEqual(result["n"], 5)
        # Only C2 (wrong value) and C4 (missing field) fail; C1/C3/C5 pass.
        self.assertEqual(result["answer"], "C2,C4")
        self.assertEqual(result["failed"], ["C2", "C4"])

    def test_order_is_file_order_even_if_later_case_fails_first(self) -> None:
        # Reorder so the failing cases are not contiguous; the answer must follow
        # file order exactly (position-sensitive ratio grader).
        cases = [CASES[1], CASES[0], CASES[3], CASES[2]]  # C2(fail),C1,C4(fail),C3
        with tempfile.TemporaryDirectory() as tmp:
            doc_dir = _write_inputs(Path(tmp), cases)
            _set_fake_config()
            svc = FakeService()
            args = {
                "task_description": "verify",
                "doc_dir": str(doc_dir),
                "_runtime": {"question_dir": str(doc_dir.parent)},
            }
            result = MOD.answer(args, parser=_fake_parser(STEPS_BY_ID), requester=svc)
        self.assertEqual(result["answer"], "C2,C4")  # C2 before C4 (file order)

    def test_write_case_fetches_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc_dir = _write_inputs(Path(tmp), [CASES[4]])  # C5 write+read
            _set_fake_config()
            svc = FakeService()
            args = {
                "task_description": "verify",
                "doc_dir": str(doc_dir),
                "_runtime": {"question_dir": str(doc_dir.parent)},
            }
            result = MOD.answer(args, parser=_fake_parser(STEPS_BY_ID), requester=svc)
        self.assertEqual(result["answer"], "")  # C5 passes (write took effect)
        self.assertTrue(any(c["path"] == "/api/auth/token" for c in svc.calls))

    def test_no_config_uses_deterministic_inference_when_possible(self) -> None:
        # No MODEL_* env no longer means "all cases unjudged": cases whose
        # assertion/description can be mapped deterministically are still
        # executed. Model-only cases remain conservative.
        with tempfile.TemporaryDirectory() as tmp:
            doc_dir = _write_inputs(Path(tmp), CASES)
            svc = FakeService()
            args = {
                "task_description": "verify",
                "doc_dir": str(doc_dir),
                "_runtime": {"question_dir": str(doc_dir.parent)},
            }
            result = MOD.answer(args, parser=_fake_parser(STEPS_BY_ID), requester=svc)
        self.assertEqual(result["answer"], "C2,C4")
        self.assertEqual(result["failed"], ["C2", "C4"])
        self.assertEqual(result["unjudged"], 2)  # C3/C5 need the model seam in this synthetic fixture.
        self.assertTrue(any("not configured" in w for w in result["warnings"]))

    def test_parse_failure_is_conservative_pass(self) -> None:
        # The model seam raising for a MINORITY of cases must NOT mark them
        # failing (a false positive would shift every later position). With
        # 1/3 unjudgeable the answer stays conservative.
        with tempfile.TemporaryDirectory() as tmp:
            doc_dir = _write_inputs(Path(tmp), [CASES[4], CASES[1], CASES[2]])  # C5(model), C2(fail), C3
            _set_fake_config()
            os.environ["INTERFACE_TEST_RETRIES"] = "1"
            svc = FakeService()
            steps = dict(STEPS_BY_ID)
            steps["case C5"] = RuntimeError("model down")  # C5 cannot be parsed
            args = {
                "task_description": "verify",
                "doc_dir": str(doc_dir),
                "_runtime": {"question_dir": str(doc_dir.parent)},
            }
            try:
                result = MOD.answer(args, parser=_fake_parser(steps), requester=svc)
            finally:
                os.environ.pop("INTERFACE_TEST_RETRIES", None)
        # C1 degraded to a conservative pass; only the genuinely-failing C2 shows.
        self.assertEqual(result["answer"], "C2")
        self.assertEqual(result["unjudged"], 1)

    def test_unjudgeable_majority_raises_for_router_fallback(self) -> None:
        # Platform failure mode (1.07/6): every case silently passed because the
        # service/parse layer was broken. Dominant unjudgeable cases must raise
        # so the router falls back to the model loop instead of submitting "".
        with tempfile.TemporaryDirectory() as tmp:
            doc_dir = _write_inputs(Path(tmp), [CASES[0]])  # C1
            _set_fake_config()

            def boom(method, url, headers, body, timeout):
                raise OSError("connection refused")

            args = {
                "task_description": "verify",
                "doc_dir": str(doc_dir),
                "_runtime": {"question_dir": str(doc_dir.parent)},
            }
            with self.assertRaises(RuntimeError) as ctx:
                MOD.answer(args, parser=_fake_parser(STEPS_BY_ID), requester=boom)
        self.assertIn("degraded output", str(ctx.exception))

    def test_package_id_header_on_every_call(self) -> None:
        # The same X-Package-Id must ride every request for the whole run.
        with tempfile.TemporaryDirectory() as tmp:
            doc_dir = _write_inputs(Path(tmp), [CASES[4]])  # C5 -> token+write+read
            _set_fake_config()
            captured: List[Dict[str, str]] = []

            def capture(method, url, headers, body, timeout):
                captured.append(dict(headers))
                # Delegate to a real fake service for behaviour.
                return FAKE(method, url, headers, body, timeout)

            FAKE = FakeService()
            args = {
                "task_description": "verify",
                "doc_dir": str(doc_dir),
                "_runtime": {"question_dir": str(doc_dir.parent)},
            }
            MOD.answer(args, parser=_fake_parser(STEPS_BY_ID), requester=capture)
        self.assertTrue(captured)
        for headers in captured:
            self.assertEqual(headers.get("X-Package-Id"), "pkg-test")


class MissingFieldConservatismTest(unittest.TestCase):
    """Fix B / Fix C: an absence-shaped failure from an inferred request is the
    signature of a *wrong request*; over-reporting it would shift every later
    failing-ID position (the ratio grader zeroes on an early false failure).
    Pure-code failures stay trusted (the inferrer abstains when unsure), while a
    MODEL-derived missing-field is demoted to a conservative pass and a genuine
    value mismatch is still reported.
    """

    def setUp(self) -> None:
        _force_offline_env()

    def tearDown(self) -> None:
        _force_offline_env()

    def test_pure_code_missing_field_is_reported(self) -> None:
        # A high-confidence pure-code request (a detail-by-userId) whose response
        # is genuinely missing the asserted field IS a real failure and must be
        # reported (mirrors a popped data.title), even offline.
        case = {
            "id": "M1",
            "description": "查看用户 U1 的详情；核对其职级字段。",
            "assert": {"expectedStatus": 200, "expectedFields": ["data.title"],
                       "expectedValues": {"data.title": "Engineer"}},
        }

        def svc(method, url, headers, body, timeout):
            # detail/U1 returns WITHOUT data.title -> genuine missing field.
            return 200, {"code": 0, "data": {"userId": "U1"}}

        passed, reason, _token, judged = MOD._verify_one(
            case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG), "pkg",
            None, 30, 1, _fake_parser({}), svc, None,
        )
        self.assertFalse(passed)   # reported as failing
        self.assertTrue(judged)    # a confirmed, code-judged failure
        self.assertIn("title", reason)

    def test_model_missing_field_is_conservative_pass(self) -> None:
        # The pure-code inferrer abstains for this case (a row-shaped search
        # assertion with no recoverable discriminator), so it falls to the model.
        # The model's request returns an empty list -> missing data.list.0.userId.
        # Fix B: that absence must NOT be reported (it would zero the ratio); the
        # case becomes a conservative pass (judged=False).
        case = {
            "id": "M2",
            "description": "按降序翻页列出用户；核对列表首条。",
            "assert": {"expectedFields": ["data.list.0.userId"]},
        }
        parser = _fake_parser({
            "按降序翻页": [{"method": "GET", "path": "/api/user/search",
                            "query": {"sortOrder": "desc"}, "assert": True}],
        })

        def svc(method, url, headers, body, timeout):
            return 200, {"code": 0, "data": {"total": 0, "list": []}}

        _set_fake_config()
        try:
            passed, reason, _token, judged = MOD._verify_one(
                case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG), "pkg",
                MOD._model_config(), 30, 1, parser, svc, None,
            )
        finally:
            _force_offline_env()
        self.assertTrue(passed)     # NOT over-reported
        self.assertFalse(judged)    # conservative (unjudged), not a confirmed pass
        self.assertIn("not judged", reason)

    def test_model_value_mismatch_is_reported(self) -> None:
        # The flip side of Fix B: a MODEL request that returns the right shape
        # but a WRONG value is a genuine semantic failure and IS reported.
        case = {
            "id": "M3",
            "description": "按降序翻页列出用户；核对列表首条 userId。",
            "assert": {"expectedValues": {"data.list.0.userId": "U2240"}},
        }
        parser = _fake_parser({
            "按降序翻页": [{"method": "GET", "path": "/api/user/search",
                            "query": {"status": "active", "sortOrder": "desc"}, "assert": True}],
        })

        def svc(method, url, headers, body, timeout):
            return 200, {"code": 0, "data": {"list": [{"userId": "U2001"}]}}

        _set_fake_config()
        try:
            passed, reason, _token, judged = MOD._verify_one(
                case, PUBLIC_API_DOC, MOD.build_auth(AUTH_CONFIG), "pkg",
                MOD._model_config(), 30, 1, parser, svc, None,
            )
        finally:
            _force_offline_env()
        self.assertFalse(passed)    # genuine value mismatch -> reported
        self.assertTrue(judged)
        self.assertIn("U2240", reason)

    def test_unjudged_case_never_enters_failed_list(self) -> None:
        # Fix C: only confirmed (judged AND not passed) cases join the answer.
        # A conservative pass (judged=False) must never be inserted into the
        # position-sensitive failing-ID list, even though some other case fails.
        cases = [
            {"id": "K1", "description": "case K1 read U1",
             "assert": {"expectedStatus": 200, "expectedValues": {"data.userId": "U1"}}},
            {"id": "K2", "description": "按降序翻页列出用户；核对首条。",  # search, abstains -> model -> empty list -> conservative
             "assert": {"expectedFields": ["data.list.0.userId"]}},
            {"id": "K3", "description": "case K3 read U1 wrong title",
             "assert": {"expectedStatus": 200, "expectedValues": {"data.title": "WRONG"}}},  # genuine fail
        ]
        parser = _fake_parser({
            "按降序翻页": [{"method": "GET", "path": "/api/user/search",
                            "query": {"sortOrder": "desc"}, "assert": True}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            doc_dir = _write_inputs(Path(tmp), cases)
            _set_fake_config()
            svc = FakeService()
            args = {
                "task_description": "verify",
                "doc_dir": str(doc_dir),
                "_runtime": {"question_dir": str(doc_dir.parent)},
            }
            result = MOD.answer(args, parser=parser, requester=svc)
        # Only the genuinely failing K3 appears; the conservative K2 is omitted
        # and never shifts K3 out of position.
        self.assertEqual(result["answer"], "K3")
        self.assertEqual(result["failed"], ["K3"])
        self.assertEqual(result["unjudged"], 1)


if __name__ == "__main__":
    unittest.main()
