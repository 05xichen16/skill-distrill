"""Generalization (variant) tests for the sensitive_scan skill.

The public archive is scored verbatim; on the platform only the attachment data
changes, and that is exactly where the old scanner collapsed (platform 2_2 was
stuck low). These tests build synthetic variant archives with KNOWN token counts
that exercise the three structural generalization gaps the rewrite closes:

  1. sensitive data in non-.txt/.log files (.csv/.dat/.json/.out) -- the
     question says the archive "may contain .txt, .log, .tar, .png/.jpg, ETC."
  2. data hidden inside compressed members (.tar.gz / .tgz / .log.gz)
  3. non-.com emails (.cn/.net/.org)

All offline (do_ocr=False); the OCR transcription path is validated live
elsewhere. Standard-library unittest.
"""
from __future__ import annotations

import gzip
import importlib.util
import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT / "source" / "solution" / "skills" / "sensitive_scan" / "scripts" / "run.py"
)


def _load_skill_module():
    spec = importlib.util.spec_from_file_location("sensitive_scan_variant", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _block(phones: int, emails: int, ids: int, keys: int, tld: str = "com") -> str:
    """Build text with EXACTLY the requested count of each token, one per line.

    Tokens are isolated on their own lines so the boundary regexes cannot
    cross-match (an 11-digit phone never sits inside an 18-digit id, etc.).
    """
    lines = []
    for i in range(phones):
        lines.append("phone: 13%09d" % i)  # 1-led, 11 digits total
    for i in range(emails):
        lines.append("mail: user%d@example.%s" % (i, tld))
    for i in range(ids):
        # 18 chars: 17 digits + trailing digit; deterministic and valid-shaped.
        lines.append("id: 4101%014d" % i)
    for i in range(keys):
        lines.append("key: sk-%032d" % i)
    return "\n".join(lines) + "\n"


class SensitiveScanVariantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_skill_module()

    def _scan_bytes(self, archive: bytes):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "variant.zip")
            with open(path, "wb") as handle:
                handle.write(archive)
            return self.module.scan({"zip_path": path, "do_ocr": False})

    def test_variant_structural_recovery(self) -> None:
        # --- compose a nested tar.gz of a .log file ---
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            log_bytes = _block(7, 6, 5, 3, tld="net").encode("utf-8")
            info = tarfile.TarInfo(name="inner/app.log")
            info.size = len(log_bytes)
            tar.addfile(info, io.BytesIO(log_bytes))
        targz = gzip.compress(tar_buffer.getvalue())

        # --- a standalone .log.gz ---
        loggz = gzip.compress(_block(3, 0, 4, 1, tld="org").encode("utf-8"))

        # --- the outer zip with assorted non-.txt/.log members ---
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("records.csv", _block(5, 3, 2, 4, tld="cn"))
            archive.writestr("blob.dat", _block(2, 1, 8, 1, tld="org"))
            archive.writestr("meta.json", _block(1, 4, 0, 2, tld="com"))
            archive.writestr("nested/payload.tar.gz", targz)
            archive.writestr("more/extra.log.gz", loggz)
        result = self._scan_bytes(buffer.getvalue())

        # Expected text totals across every member (incl. compressed/nested):
        #   phone: 5+2+1 +7 +3 = 18
        #   email: 3+1+4 +6 +0 = 14
        #   id:    2+8+0 +5 +4 = 19
        #   key:   4+1+2 +3 +1 = 11
        self.assertEqual(result["breakdown"]["text"], [18, 14, 19, 11])
        self.assertEqual(result["breakdown"]["total"], [18, 14, 19, 11])
        self.assertEqual(result["text_files"], 5)
        self.assertEqual(result["warnings"], [])

    def test_non_com_emails_are_counted(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("a.csv", "x@y.cn\nz@w.net\np@q.org\nr@s.com\n")
        result = self._scan_bytes(buffer.getvalue())
        self.assertEqual(result["breakdown"]["text"][1], 4)  # all four TLDs

    def test_unknown_extension_is_scanned_as_text(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("evidence.out", "phone 13800138000\nkey sk-abcdef123456\n")
        result = self._scan_bytes(buffer.getvalue())
        self.assertEqual(result["breakdown"]["text"][0], 1)  # phone
        self.assertEqual(result["breakdown"]["text"][3], 1)  # key
        self.assertEqual(result["text_files"], 1)


if __name__ == "__main__":
    unittest.main()
