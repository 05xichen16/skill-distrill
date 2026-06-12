#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe infer_steps_from_case on PUBLIC vs REWORDED descriptions.

Shows, per case, the steps the pure-code inferrer emits (and the query it
extracted) for both wordings, so we can see exactly where rewording empties
the query and the inferrer emits a broken-but-confident request instead of
abstaining (returning []).
"""
from __future__ import annotations

import importlib.util
import json
import os

SKILL_PATH = (
    r"D:\code\python_projects\python_demo\source\solution\skills"
    r"\interface_test\scripts\run.py"
)
SRC = (
    r"D:\code\python_projects\python_demo\publish\publish_V1"
    r"\测试用例接口文档"
)
HERE = os.path.dirname(os.path.abspath(__file__))


def load_skill():
    spec = importlib.util.spec_from_file_location("interface_skill", SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    skill = load_skill()
    api_doc = open(os.path.join(SRC, "api_doc.md"), encoding="utf-8").read()
    auth = skill.build_auth(json.load(open(os.path.join(SRC, "auth_config.json"), encoding="utf-8")))

    pub = {c["id"]: c for c in json.load(open(os.path.join(SRC, "test_cases.json"), encoding="utf-8"))}
    rew = {c["id"]: c for c in json.load(open(os.path.join(HERE, "variant_reworded", "test_cases.json"), encoding="utf-8"))}

    focus = ["TC005", "TC006", "TC007", "TC008", "TC009", "TC011", "TC015", "TC016"]
    for cid in focus:
        print("=" * 72)
        print(cid)
        for label, case in (("PUBLIC ", pub[cid]), ("REWORD ", rew[cid])):
            desc = case["description"]
            q = skill._query_from_description(desc)
            steps = skill.infer_steps_from_case(case, api_doc, auth)
            if steps:
                s0 = steps[-1]  # the asserted step
                shape = "%s %s query=%s body=%s" % (
                    s0["method"], s0["path"], json.dumps(s0.get("query"), ensure_ascii=False),
                    json.dumps(s0.get("body"), ensure_ascii=False),
                )
            else:
                shape = "<<< [] abstained -> would fall to model >>>"
            print("  %s query_extracted=%s" % (label, json.dumps(q, ensure_ascii=False)))
            print("            steps: %s" % shape)


if __name__ == "__main__":
    main()
