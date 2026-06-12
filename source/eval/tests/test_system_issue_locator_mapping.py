"""Layered root-cause mapping tests for system_issue_locator (task 1_3).

Platform log evidence: `no mapped root causes for VAL-C-ROLE-7429` -> exit 1
-> bare model loop. The old mapper only consulted a rule's validationCode key,
so variant schemas whose rootCauseRules combine module / validationCode /
fieldPath / schemaVersion mapped nothing. These tests pin the new layers:

  1. strict: combination rule matching (conditions co-occur on one log line);
  2. relaxed: wildcard / prefix / containment / code-token matching, values
     still only from the schema;
  3. LLM fallback: one model call validated against the schema cause set;
  4. all-miss still raises (router model-loop fallback preserved).

Offline: model injected as a fake callable. Standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT / "source" / "solution" / "skills" / "system_issue_locator" / "scripts" / "run.py"
)

REF = "VAL-C-ROLE-7429"


def _load_module():
    spec = importlib.util.spec_from_file_location("issue_locator_mapping", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_source(tmp: Path, schema: dict, backend_lines: list) -> Path:
    source = tmp / "case"
    source.mkdir()
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://demo.example.com/api/role/update",
                        "headers": [{"name": "X-Action-Id", "value": "ACT-1"}],
                    },
                    "response": {
                        "status": 422,
                        "content": {
                            "text": json.dumps(
                                {
                                    "finalUiError": True,
                                    "visualFailureConfirmed": True,
                                    "workflowRole": "primary-submit",
                                    "actionId": "ACT-1",
                                    "validationRef": REF,
                                },
                                ensure_ascii=False,
                            )
                        },
                    },
                }
            ]
        }
    }
    (source / "network.har").write_text(json.dumps(har, ensure_ascii=False), encoding="utf-8")
    (source / "form_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False), encoding="utf-8"
    )
    (source / "backend_validation.log").write_text("\n".join(backend_lines), encoding="utf-8")
    (source / "frontend_log.log").write_text(
        "2026-05-23 12:00:01 INFO submit actionId=ACT-1, workflowId=WF-9\n"
        "2026-05-23 12:00:02 INFO module-open workflowId=WF-9, pageGroup=角色管理\n",
        encoding="utf-8",
    )
    return source


class MappingLayersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        # Offline default: no gateway config unless a test injects one.
        self.module._model_config = lambda: None

    def _answer(self, schema: dict, backend_lines: list):
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_source(Path(tmp), schema, backend_lines)
            return self.module.answer({"source_dir": str(source), "_runtime": {}})

    # --- layer 1: combination matching -------------------------------------

    def test_combination_rule_matches_only_cooccurring_conditions(self) -> None:
        schema = {
            "rootCauseRules": [
                {"validationCode": "ROLE-7429", "fieldPath": "user.role", "rootCause": "角色权限同步异常"},
                {"validationCode": "ROLE-7429", "fieldPath": "user.dept", "rootCause": "部门数据同步异常"},
            ]
        }
        lines = [
            "2026-05-23 12:00:03 WARN  [validation-engine] validationCode=ROLE-7429, "
            "validationRef=%s, fieldPath=user.role, schemaVersion=v7" % REF,
        ]
        result = self._answer(schema, lines)
        # The old validationCode-only mapper would have emitted BOTH causes.
        self.assertEqual(result["answer"], "角色管理,/api/role/update,角色权限同步异常")
        self.assertEqual(result["cause_source"], "strict")

    def test_rule_without_validation_code_matches_field_combination(self) -> None:
        module = self.module
        schema = {
            "rootCauseRules": [
                {"fieldPath": "user.role", "schemaVersion": "v7", "rootCause": "角色权限同步异常"}
            ]
        }
        log = (
            "INFO validation started, validationRef=%s\n"
            "WARN validationCode=R1, validationRef=%s, fieldPath=user.role, schemaVersion=v7"
            % (REF, REF)
        )
        lines = module.collect_effective_lines(log, REF, schema)
        context = {"module": "角色管理", "path": "/api/role/update", "validationref": REF}
        self.assertEqual(
            module.strict_causes(["R1"], schema, lines, context), ["角色权限同步异常"]
        )

    def test_conditions_split_across_lines_do_not_match_strict(self) -> None:
        module = self.module
        schema = {
            "rootCauseRules": [
                {"fieldPath": "user.role", "schemaVersion": "v9", "rootCause": "角色权限同步异常"}
            ]
        }
        log = (
            "WARN validationCode=R1, validationRef=%s, fieldPath=user.role, schemaVersion=v7\n"
            "WARN validationCode=R2, validationRef=%s, fieldPath=user.email, schemaVersion=v9"
            % (REF, REF)
        )
        lines = module.collect_effective_lines(log, REF, schema)
        context = {"module": "角色管理", "path": "/api/role/update", "validationref": REF}
        self.assertEqual(module.strict_causes(["R1", "R2"], schema, lines, context), [])
        # fieldPath/schemaVersion are not code-like: relaxed must not over-fire either.
        self.assertEqual(module.relaxed_causes(["R1", "R2"], schema, lines, context), [])

    def test_module_condition_gates_rule(self) -> None:
        module = self.module
        schema = {
            "rootCauseRules": [
                {"module": "角色管理", "validationCode": "R1", "rootCause": "角色权限同步异常"},
                {"module": "用户管理", "validationCode": "R1", "rootCause": "部门数据同步异常"},
            ]
        }
        log = "WARN validationCode=R1, validationRef=%s" % REF
        lines = module.collect_effective_lines(log, REF, schema)
        context = {"module": "角色管理", "path": "/api/role/update", "validationref": REF}
        self.assertEqual(
            module.strict_causes(["R1"], schema, lines, context), ["角色权限同步异常"]
        )

    def test_effective_rule_filtered_lines_do_not_feed_rules(self) -> None:
        module = self.module
        schema = {
            "effectiveValidationRule": {"source": "manual-submit"},
            "rootCauseRules": [
                {"validationCode": "R1", "rootCause": "角色权限同步异常"}
            ],
        }
        log = "WARN validationCode=R1, validationRef=%s, source=diagnostic-replay" % REF
        codes = module.collect_validation_codes(log, REF, schema)
        lines = module.collect_effective_lines(log, REF, schema)
        context = {"module": "角色管理", "path": "/api/role/update", "validationref": REF}
        self.assertEqual(codes, [])
        self.assertEqual(module.strict_causes(codes, schema, lines, context), [])

    # --- layer 2: relaxed matching ------------------------------------------

    def test_relaxed_wildcard_rule_matches_validation_ref(self) -> None:
        schema = {
            "rootCauseRules": [
                {"validationCode": "VAL-C-ROLE-*", "rootCause": "角色权限同步异常"},
                {"validationCode": "VAL-C-DEPT-*", "rootCause": "部门数据同步异常"},
            ]
        }
        lines = [
            "2026-05-23 12:00:03 WARN validationCode=R0001, validationRef=%s" % REF,
        ]
        result = self._answer(schema, lines)
        self.assertEqual(result["answer"], "角色管理,/api/role/update,角色权限同步异常")
        self.assertEqual(result["cause_source"], "relaxed")

    def test_relaxed_prefix_and_containment_on_code_map(self) -> None:
        module = self.module
        schema = {"validationCodeMap": {"ROLE-7429": "角色权限同步异常", "D5204": "部门数据同步异常"}}
        context = {"module": "角色管理", "path": "/api/role/update", "validationref": REF}
        # Code prefix: collected code extends a map key.
        self.assertEqual(
            module.relaxed_causes(["ROLE-7429-X"], schema, [], context), ["角色权限同步异常"]
        )
        # Containment: the map key is embedded in the validationRef itself.
        self.assertEqual(
            module.relaxed_causes([], schema, [], context), ["角色权限同步异常"]
        )

    # --- layer 3: LLM fallback ----------------------------------------------

    def _llm_case_schema(self) -> dict:
        return {
            "validationCodeMap": {"V2401": "接口契约未同步", "R6205": "角色权限同步异常"}
        }

    def _llm_case_lines(self) -> list:
        # A code that matches no map key strictly or loosely.
        return ["2026-05-23 12:00:03 WARN validationCode=ZX99, validationRef=%s" % REF]

    def test_llm_fallback_called_and_validated(self) -> None:
        prompts = []

        def fake_call(config, prompt, timeout):
            prompts.append(prompt)
            return json.dumps(["角色权限同步异常"], ensure_ascii=False)

        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }
        self.module._call_model = fake_call
        result = self._answer(self._llm_case_schema(), self._llm_case_lines())
        self.assertEqual(result["answer"], "角色管理,/api/role/update,角色权限同步异常")
        self.assertEqual(result["cause_source"], "llm")
        self.assertEqual(len(prompts), 1)
        # The prompt carries the candidates and the evidence.
        self.assertIn("接口契约未同步", prompts[0])
        self.assertIn("角色权限同步异常", prompts[0])
        self.assertIn(REF, prompts[0])
        self.assertIn("ZX99", prompts[0])

    def test_llm_output_outside_candidate_set_rejected(self) -> None:
        def fake_call(config, prompt, timeout):
            return json.dumps(["角色权限同步异常", "自由发挥的根因"], ensure_ascii=False)

        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }
        self.module._call_model = fake_call
        with self.assertRaises(ValueError) as ctx:
            self._answer(self._llm_case_schema(), self._llm_case_lines())
        self.assertIn(REF, str(ctx.exception))

    def test_llm_empty_array_rejected(self) -> None:
        def fake_call(config, prompt, timeout):
            return "[]"

        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }
        self.module._call_model = fake_call
        with self.assertRaises(ValueError):
            self._answer(self._llm_case_schema(), self._llm_case_lines())

    def test_llm_gateway_error_keeps_failure_path(self) -> None:
        def fake_call(config, prompt, timeout):
            raise RuntimeError("gateway down")

        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }
        self.module._call_model = fake_call
        with self.assertRaises(ValueError):
            self._answer(self._llm_case_schema(), self._llm_case_lines())

    # --- layer 4: all-miss raise ---------------------------------------------

    def test_all_layers_miss_raises_with_codes(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._answer(self._llm_case_schema(), self._llm_case_lines())
        message = str(ctx.exception)
        self.assertIn("no mapped root causes for %s" % REF, message)
        self.assertIn("ZX99", message)

    # --- public-set semantics stay intact -------------------------------------

    def test_public_map_only_schema_unchanged(self) -> None:
        schema = {"validationCodeMap": {"R1": "角色权限同步异常", "R2": "部门数据同步异常"}}
        lines = [
            "WARN validationCode=R1, validationRef=%s" % REF,
            "WARN validationCode=R2, validationRef=%s" % REF,
        ]
        result = self._answer(schema, lines)
        self.assertEqual(
            result["answer"], "角色管理,/api/role/update,角色权限同步异常、部门数据同步异常"
        )
        self.assertEqual(result["cause_source"], "strict")


if __name__ == "__main__":
    unittest.main()
