#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a reworded variant of the public 1_4 input folder.

The contract held fixed by the platform's hidden variants (per the question's
own explanation) is: the ``assert`` blocks and the case IDs stay; only the
natural-language ``description`` wording may change (plus possibly endpoint
names / data, but here we ISOLATE wording to test the conservative-pass /
infer_steps hypothesis). So we keep ``id`` and ``assert`` byte-for-byte and
only rewrite ``description`` into natural paraphrases.

We produce two variants:
  variant_reworded/   - natural paraphrase; keeps the U#### ids and numbers as
                        tokens, but drops the literal ``key=value`` forms and
                        swaps verbs/nouns for synonyms.
  variant_aggressive/ - heavier paraphrase: spells out params in prose with no
                        ``=`` at all, the way a human QA might write a ticket.

api_doc.md and auth_config.json are copied verbatim (endpoints unchanged), so
the EXPECTED failing IDs remain TC009,TC011,TC014,TC015,TC016,TC020.
"""
from __future__ import annotations

import json
import os
import shutil

SRC = (
    r"D:\code\python_projects\python_demo\publish\publish_V1"
    r"\测试用例接口文档"
)
HERE = os.path.dirname(os.path.abspath(__file__))


# id -> (reworded, aggressive). Intent + asserted facts identical; only prose.
REWORD = {
    # detail update flows (key=value -> prose; verbs swapped)
    "TC001": (
        "先获取访问令牌，把用户 U1003 的邮箱改成 u1003.stable@example.com，"
        "职级调整为 Senior Engineer，随后拉取 U1003 的详情；以最后这次详情查询的返回为准。",
        "请先拿到 token。接着对编号 U1003 的同事做资料维护：联系邮箱写成 "
        "u1003.stable@example.com，岗位级别填 Senior Engineer。完成后再去看一眼 "
        "U1003 的资料卡，核对这张资料卡。",
    ),
    "TC002": (
        "拉取用户 U1003 的详情；核对上一步写入的邮箱与职级。",
        "再看一次 U1003 的资料卡，确认刚才维护的联系邮箱和岗位级别都已生效。",
    ),
    "TC003": (
        "先获取访问令牌，把用户 U1008 的邮箱改成 u1008.stable@example.com，"
        "职级调整为 Auth First，随后拉取 U1008 的详情；以最后这次详情查询的返回为准。",
        "先取令牌。给编号 U1008 的人更新资料：邮箱改 u1008.stable@example.com，"
        "级别改 Auth First。然后翻看 U1008 的资料卡并核对它。",
    ),
    "TC004": (
        "重新拉取用户 U1008 的详情；核对上一步写入的邮箱与职级。",
        "回头再确认 U1008 的资料卡，看邮箱和级别是否如前一步所写。",
    ),
    # batch status (drop the enumeration commas / status= form)
    "TC005": (
        "把 U3001 和 U3002 这两个人成批地标记为停用状态；核对批量更新接口的返回。",
        "请将编号 U3001 与 U3002 的人一起置为不活跃；看一下批量处理接口回了什么。",
    ),
    # search / pagination (drop key=value forms -> prose)
    "TC006": (
        "在平台部门里翻到第二页、每页两条、按升序排列地列出用户；"
        "核对分页信息以及列表里的第一条。",
        "想看 platform 这个部门的人员名单，一页放两条，取第 2 页，从小到大排；"
        "核对翻页字段和打头那一条。",
    ),
    "TC007": (
        "把处于活跃状态的用户列出来，停在第一页、每页一百条、升序；"
        "核对分页、总条数以及第 100 条记录。",
        "列出所有在岗（active）的人，第 1 页就好，一页一百条，正序；"
        "看分页、总数，以及第 100 行那条。",
    ),
    "TC008": (
        "用关键字 Alice 搜索用户，落在第一页、每页十条；核对命中数量与首条姓名。",
        "拿 Alice 当搜索词找用户，第 1 页每页十条；看命中几条以及第一条叫什么。",
    ),
    # detail with verbose (key fact = manager; verbose said in prose)
    "TC009": (
        "查看用户 U1010 的详尽资料（需要返回明细，verbose 打开）；核对其经理信息。",
        "把编号 U1010 的人看个仔细，要带上详细信息那一档；重点核对他的直属经理。",
    ),
    "TC010": (
        "去查一个并不存在的用户 U9999 的详情；核对异常返回。",
        "故意查一个查不到的人 U9999；看接口怎么报错。",
    ),
    # stat active (drop 部门 label adjacency)
    "TC011": (
        "看一下 mobile 这个部门活跃用户的统计数字。",
        "mobile 团队现在有多少活跃的人，给个统计。",
    ),
    "TC012": (
        "看一下 platform 这个部门活跃用户的统计数字。",
        "platform 团队现在有多少活跃的人，给个统计。",
    ),
    "TC013": (
        "查看用户 U1004 的详情；核对基础字段。",
        "翻一下编号 U1004 的资料卡，看基本信息对不对。",
    ),
    "TC014": (
        "查看用户 U1004 的详情；核对其职级字段。",
        "再看编号 U1004 的资料卡，这回盯着岗位级别那一栏。",
    ),
    "TC015": (
        "把活跃用户停在第一页、每页五条、按降序列出；核对打头的那一条。",
        "在岗的人按从大到小排，第 1 页每页五条；看排在最前的是谁。",
    ),
    "TC016": (
        "把停用用户停在第一页、每页五条、按降序列出；核对打头的那一条。",
        "不活跃的人按倒序排，第 1 页每页五条；看排在最前的是谁。",
    ),
    "TC017": (
        "拉取用户 U1003 的详情；核对前序写入后的邮箱与职级。",
        "再看 U1003 的资料卡，核对之前维护过的邮箱与级别。",
    ),
    "TC018": (
        "拉取用户 U1008 的详情；核对前序同令牌复用流程里第一次写入是否生效。",
        "回看 U1008 的资料卡，确认那次复用令牌的流程里首笔写入是否落地。",
    ),
    "TC019": (
        "查看用户 U1005 的详情；核对基础职级字段。",
        "翻一下编号 U1005 的资料卡，看基础的岗位级别。",
    ),
    "TC020": (
        "查看用户 U1005 的详情；核对其职级字段应为 Quality Owner。",
        "再看编号 U1005 的资料卡，岗位级别这一栏应当是 Quality Owner。",
    ),
}


def build(variant_name: str, idx: int) -> None:
    out = os.path.join(HERE, variant_name)
    os.makedirs(out, exist_ok=True)
    # copy api_doc.md + auth_config.json verbatim
    for fn in ("api_doc.md", "auth_config.json"):
        shutil.copyfile(os.path.join(SRC, fn), os.path.join(out, fn))
    cases = json.load(open(os.path.join(SRC, "test_cases.json"), encoding="utf-8"))
    for c in cases:
        cid = c["id"]
        if cid in REWORD:
            c["description"] = REWORD[cid][idx]
    with open(os.path.join(out, "test_cases.json"), "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    build("variant_reworded", 0)
    build("variant_aggressive", 1)
