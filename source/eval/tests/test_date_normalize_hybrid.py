"""Hybrid regex/LLM behavior tests for the date_normalize skill.

Platform run #2: the regex decision tree scored 50% on hidden variants while
the generic model loop scored 81%. The hybrid keeps regex for plain absolute
dates, sends relative-reasoning lines to a per-line LLM call (mocked here),
falls back to the regex value when the gateway fails, and raises when too many
lines end up unanswered (so the router falls back to the model loop).

Offline, standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = REPO_ROOT / "source" / "solution" / "skills" / "date_normalize" / "scripts" / "run.py"

ENV_KEYS = ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME")


def _load_module():
    spec = importlib.util.spec_from_file_location("date_normalize_hybrid", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DateNormalizeHybridTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self._saved = {key: os.environ.pop(key, None) for key in ENV_KEYS}

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _answer(self, lines, config=None, model_responses=None):
        calls = []

        if config is not None:
            self.module._model_config = lambda: config
            responses = list(model_responses or [])

            def fake_call(cfg, prompt, timeout):
                calls.append(prompt)
                if not responses:
                    raise RuntimeError("gateway down")
                item = responses.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

            self.module._call_model = fake_call
        else:
            self.module._model_config = lambda: None

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "messages.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            result = self.module.answer({"message_file": str(path), "_runtime": {}})
        return result, calls

    # --- routing decisions --------------------------------------------------
    def test_absolute_date_goes_regex_no_model_call(self) -> None:
        config = {"url": "u", "api_key": "k", "model": "m", "package_id": ""}
        result, calls = self._answer(["订单日期是2026年5月3日。"], config=config, model_responses=[])
        self.assertEqual(result["answer"], "2026-05-03")
        self.assertEqual(result["sources"], ["regex"])
        self.assertEqual(calls, [])

    def test_relative_line_uses_regex_when_solved(self) -> None:
        config = {"url": "u", "api_key": "k", "model": "m", "package_id": ""}
        result, calls = self._answer(
            ["今天是2026年5月6日，下周一能到吗？"],
            config=config,
            model_responses=["2026-05-11"],
        )
        self.assertEqual(result["answer"], "2026-05-11")
        self.assertEqual(result["sources"], ["regex"])
        self.assertEqual(calls, [])

    def test_llm_failure_falls_back_to_regex_value(self) -> None:
        config = {"url": "u", "api_key": "k", "model": "m", "package_id": ""}
        # solve_line handles 明天 via anchor+1; gateway always errors.
        result, _ = self._answer(
            ["今天是2026年5月6日，明天发货。"],
            config=config,
            model_responses=[RuntimeError("boom"), RuntimeError("boom")],
        )
        self.assertEqual(result["answer"], "2026-05-07")
        self.assertEqual(result["sources"], ["regex"])

    def test_llm_only_when_regex_fails(self) -> None:
        config = {"url": "u", "api_key": "k", "model": "m", "package_id": ""}
        result, calls = self._answer(
            ["用户只说帮我约到发布日，材料里没有直接日期。"],
            config=config,
            model_responses=["我无法确定", "2026-05-07 是答案"],
        )
        self.assertEqual(result["answer"], "2026-05-07")
        self.assertEqual(result["sources"], ["llm"])
        self.assertEqual(len(calls), 2)

    def test_offline_equals_legacy_regex_tree(self) -> None:
        result, _ = self._answer(
            [
                "今天是2026年5月6日，明天发货。",
                "订单日期是2026年5月3日。",
            ]
        )
        self.assertEqual(result["answer"], "2026-05-07,2026-05-03")
        self.assertEqual(result["failed_lines"], 0)

    # --- degradation --------------------------------------------------------
    def test_majority_failures_raise_for_router_fallback(self) -> None:
        config = {"url": "u", "api_key": "k", "model": "m", "package_id": ""}
        lines = ["客户说不知道哪天。", "也许吧。", "再说。"]
        with self.assertRaises(RuntimeError):
            self._answer(lines, config=config, model_responses=[])

    def test_single_failure_keeps_positions(self) -> None:
        config = {"url": "u", "api_key": "k", "model": "m", "package_id": ""}
        lines = [
            "订单日期是2026年5月3日。",
            "完全没有日期线索的消息。",
            "订单日期是2026年5月4日。",
            "订单日期是2026年5月5日。",
        ]
        result, _ = self._answer(lines, config=config, model_responses=[])
        self.assertEqual(result["answer"], "2026-05-03,0000-00-00,2026-05-04,2026-05-05")
        self.assertEqual(result["failed_lines"], 1)


if __name__ == "__main__":
    unittest.main()
