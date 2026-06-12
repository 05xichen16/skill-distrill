#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch the RESEARCH prototype (run_proto.py) only — never the real skill.

Two-part fix being validated:
  (1) search branch: ABSTAIN (return []) when the assertion needs rows
      (data.list.* / data.total) but we failed to recover a discriminating
      filter (status/department/keyword) -> falls through to the model seam
      instead of emitting a confident-but-wrong /api/user/search request.
  (2) (left as-is) the model seam already rescues abstained cases when MODEL_*
      is configured; offline it goes conservative-pass.
"""
import io
import os

PROTO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_proto.py")

OLD = '''    if _has_any_path(paths, "data.page", "data.pageSize", "data.total", "data.list."):
        endpoint = _endpoint(catalog, "search", "/api/user/search", "GET")
        query = _merge_asserted_query_values(query, values)
        if not query:
            return []
        steps.append(_normalise_step({'''

NEW = '''    if _has_any_path(paths, "data.page", "data.pageSize", "data.total", "data.list."):
        endpoint = _endpoint(catalog, "search", "/api/user/search", "GET")
        query = _merge_asserted_query_values(query, values)
        if not query:
            return []
        # PROTO FIX: a row-shaped assertion (data.list.* or data.total) is only
        # answerable if we recovered the DISCRIMINATING filter
        # (status / department / keyword). With only pagination/sort keys the
        # request hits the wrong result set, so ABSTAIN ([]) and let the model
        # parse the reworded description instead of mis-failing a passing case.
        needs_rows = _has_any_path(paths, "data.list.", "data.total")
        has_discriminator = any(k in query for k in ("status", "department", "keyword"))
        if needs_rows and not has_discriminator:
            return []
        steps.append(_normalise_step({'''


def main():
    with io.open(PROTO, "r", encoding="utf-8") as f:
        src = f.read()
    if "PROTO FIX" in src:
        print("already patched")
        return
    if OLD not in src:
        raise SystemExit("anchor not found - prototype shape changed")
    src = src.replace(OLD, NEW, 1)
    with io.open(PROTO, "w", encoding="utf-8") as f:
        f.write(src)
    print("patched run_proto.py search branch")


if __name__ == "__main__":
    main()
