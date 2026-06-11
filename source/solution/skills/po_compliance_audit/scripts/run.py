from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import date
from typing import Any, Dict, List, Optional


MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _read_stdin_text() -> str:
    import locale

    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    data = buffer.read()
    if not data:
        return ""
    encodings = ["utf-8"]
    preferred = (locale.getpreferredencoding(False) or "").lower()
    if preferred and preferred not in {"utf-8", "utf8"}:
        encodings.append(preferred)
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _emit(payload: Dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=True) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(line)
        sys.stdout.flush()
        return
    buffer.write(line.encode("ascii"))
    buffer.flush()


def resolve_source_dir(name: str, runtime: Dict[str, Any]) -> str:
    candidates: List[str] = []
    if name:
        if os.path.isabs(name):
            candidates.append(name)
        else:
            qd = str(runtime.get("question_dir") or "").strip()
            if qd:
                candidates.append(os.path.join(qd, name))
            candidates.extend([os.path.join(os.getcwd(), name), name])
    for path in runtime.get("allowed_file_paths") or []:
        text = str(path)
        candidates.append(text if os.path.isdir(text) else os.path.dirname(text))
    for candidate in candidates:
        if candidate and os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "purchase_orders_raw.csv")):
            return candidate
    raise FileNotFoundError("PO audit source directory not found")


def read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_text(path: str) -> str:
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def parse_iso(value: str) -> date:
    y, m, d = [int(part) for part in value.split("-")]
    return date(y, m, d)


def parse_date_text(text: str) -> Optional[date]:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})", text)
    if match:
        month = MONTHS.get(match.group(1).lower())
        if month:
            return date(int(match.group(3)), month, int(match.group(2)))
    match = re.search(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def is_terminal_status(status: str) -> bool:
    value = status.strip().lower()
    bad = ["draft", "under_review", "cancel", "cancelled", "草稿", "评审中", "审批中", "待补件", "取消", "作废"]
    if any(token in value for token in bad):
        return False
    good = ["completed", "closed", "accepted", "paid", "已完成", "已支付", "已验收", "已关闭", "已结案"]
    return any(token in value for token in good)


def split_items(text: str) -> List[str]:
    raw = re.split(r"[、,，]|和", text)
    result = []
    for item in raw:
        cleaned = re.sub(r"\s*\d+\s*台", "", item).strip()
        cleaned = cleaned.replace("采购", "").strip()
        if cleaned:
            result.append(cleaned)
    return result


def item_in_scope(item: str, scope: str) -> bool:
    normalized_item = item.replace(" ", "")
    normalized_scope = scope.replace(" ", "")
    if normalized_item in normalized_scope:
        return True
    for token in ["服务器", "交换机", "员工笔记本", "测试手机", "边缘盒子", "联调样机", "培训"]:
        if token in normalized_item:
            return token in normalized_scope
    return False


def service_scope_ok(po: Dict[str, str], vendor_scope: str) -> bool:
    return all(item_in_scope(item, vendor_scope) for item in split_items(po.get("service_items", "")))


def load_roles(rows: List[Dict[str, str]]) -> Dict[str, List[Dict[str, Any]]]:
    roles: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        email = row.get("email", "").strip().lower()
        roles.setdefault(email, []).append(
            {
                "role": row.get("role", "").strip(),
                "valid_from": parse_iso(row.get("valid_from", "")),
                "valid_to": parse_iso(row.get("valid_to", "")),
            }
        )
    return roles


def is_valid_vp(email: str, sent_date: date, roles: Dict[str, List[Dict[str, Any]]]) -> bool:
    for role in roles.get(email.lower(), []):
        if role["role"] == "VP" and role["valid_from"] <= sent_date <= role["valid_to"]:
            return True
    return False


def message_blocks(text: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    current: Dict[str, str] = {"from": "", "date": "", "body": ""}
    for line in text.splitlines():
        if line.startswith("From: "):
            if current.get("from") or current.get("body"):
                blocks.append(current)
            current = {"from": line, "date": "", "body": ""}
        elif line.startswith("Date: "):
            current["date"] = line
        else:
            current["body"] += line + "\n"
    if current.get("from") or current.get("body"):
        blocks.append(current)
    return blocks


def approval_positive(body: str) -> bool:
    positives = ["批准", "同意", "确认", "通过", "可以采购", "可以按当前报价执行", "均已看过并批准"]
    negatives = ["先不要", "待确认", "先评估", "补材料后再看", "另开评估", "不放进这封批准", "原单据编号归档"]
    return any(word in body for word in positives) and not any(word in body for word in negatives)


def approval_covers_all(po: Dict[str, str], body: str) -> bool:
    broad = ["整张 PO", "完整清单", "都在本次批准范围内", "都在批准范围内", "三项一起批", "均已看过并批准", "清单按正文所列"]
    if any(word in body for word in broad):
        return True
    return all(item in body for item in split_items(po.get("service_items", "")))


def has_valid_approval(po: Dict[str, str], evidence_texts: List[str], roles: Dict[str, List[Dict[str, Any]]]) -> bool:
    po_date = parse_iso(po.get("po_date", ""))
    po_id = po.get("po_id", "")
    for text in evidence_texts:
        for block in message_blocks(text):
            from_match = re.search(r"<([^>]+)>", block.get("from", ""))
            sent_date = parse_date_text(block.get("date", ""))
            if not from_match or not sent_date:
                continue
            if sent_date > po_date or not is_valid_vp(from_match.group(1), sent_date, roles):
                continue
            body = block.get("body", "")
            if po_id not in body and po_id not in block.get("date", "") and po_id not in block.get("from", ""):
                if po_id not in text:
                    continue
            if approval_positive(body) and approval_covers_all(po, body):
                return True
    return False


def answer(args: Dict[str, Any]) -> Dict[str, Any]:
    runtime = args.get("_runtime") if isinstance(args.get("_runtime"), dict) else {}
    source_dir = resolve_source_dir(str(args.get("source_dir") or ""), runtime)
    pos = read_csv(os.path.join(source_dir, "purchase_orders_raw.csv"))
    vendors = {row["vendor_id"]: row for row in read_csv(os.path.join(source_dir, "vendors.csv"))}
    roles = load_roles(read_csv(os.path.join(source_dir, "people_roles.csv")))
    evidence_rows = read_csv(os.path.join(source_dir, "approval_evidence.csv"))
    evidence_by_id = {row["evidence_id"]: row for row in evidence_rows}

    bad: List[str] = []
    for po in pos:
        try:
            amount = int(float(po.get("amount_cny") or "0"))
        except ValueError:
            amount = 0
        if not is_terminal_status(po.get("status", "")) or amount < 50000:
            continue

        vendor = vendors.get(po.get("vendor_id", ""))
        scope_ok = bool(vendor) and service_scope_ok(po, vendor.get("service_scope", ""))

        texts = []
        for evidence_id in [part.strip() for part in po.get("evidence_ids", "").split(";") if part.strip()]:
            row = evidence_by_id.get(evidence_id)
            if not row:
                continue
            path = os.path.join(source_dir, row.get("file_path", ""))
            if os.path.isfile(path):
                texts.append(read_text(path))
        approval_ok = has_valid_approval(po, texts, roles)
        if not scope_ok or not approval_ok:
            bad.append(po.get("po_id", ""))

    bad = sorted(item for item in bad if item)
    return {"answer": ",".join(bad), "count": len(bad)}


def main() -> None:
    raw = _read_stdin_text().strip() or "{}"
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            raise ValueError("input must be an object")
        _emit(answer(args))
    except Exception as exc:
        _emit({"error": str(exc)})
        raise SystemExit(1)


if __name__ == "__main__":
    main()
