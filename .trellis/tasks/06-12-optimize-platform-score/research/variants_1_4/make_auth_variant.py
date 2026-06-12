#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate auth-config variants for the 1_4 reproduction bench.

The hidden variant moves the service host:port and "adjusts auth rules", i.e.
auth_config.json's field names/structure may change while it stays the ONLY
authoritative address source. These variants keep test_cases.json / api_doc.md
byte-identical to the public set and ONLY rewrite auth_config.json, so a
harness run isolates the base-url derivation chain:

  variant_auth_renamed   baseUrl -> serviceUrl (named-field step)
  variant_auth_nested    no named field; the URL only appears inside a full
                         token-endpoint URL (recursive-scan step)
  variant_auth_hostport  host + port declared separately (join step)
  variant_auth_missing   no address anywhere (answer() must fail fast)

All variants still point at the local mock (127.0.0.1:18081) so an offline
harness run against variant_auth_renamed/nested/hostport must reproduce the
public baseline answer exactly (TC009,...,TC020 / 6/6).

Usage:
    PYTHONIOENCODING=utf-8 python make_auth_variant.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = Path(r"D:\code\python_projects\python_demo\publish\publish_V1\测试用例接口文档")


def _load_public_auth() -> dict:
    return json.loads((PUBLIC / "auth_config.json").read_text(encoding="utf-8"))


def _write_variant(name: str, auth_config: dict) -> Path:
    out = HERE / name
    out.mkdir(exist_ok=True)
    for fname in ("test_cases.json", "api_doc.md"):
        shutil.copyfile(PUBLIC / fname, out / fname)
    (out / "auth_config.json").write_text(
        json.dumps(auth_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def main() -> None:
    public = _load_public_auth()
    base = public["baseUrl"]
    token = public["token"]

    renamed = dict(public)
    del renamed["baseUrl"]
    renamed = {"serviceUrl": base + "/", **renamed}
    _write_variant("variant_auth_renamed", renamed)

    nested = dict(public)
    del nested["baseUrl"]
    nested_token = dict(token)
    # The token endpoint becomes a FULL url; no other address field exists.
    nested_token["endpoint"] = base + token["endpoint"]
    nested["token"] = nested_token
    _write_variant("variant_auth_nested", nested)

    hostport = dict(public)
    del hostport["baseUrl"]
    host, _, port = base.split("//", 1)[1].partition(":")
    hostport = {"service": {"host": host, "port": int(port)}, **hostport}
    _write_variant("variant_auth_hostport", hostport)

    missing = dict(public)
    del missing["baseUrl"]
    _write_variant("variant_auth_missing", missing)

    print("wrote variant_auth_renamed / variant_auth_nested / "
          "variant_auth_hostport / variant_auth_missing under", HERE)


if __name__ == "__main__":
    main()
