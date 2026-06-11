from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional


WEEKDAY = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
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


def _candidate_paths(name: str, runtime: Dict[str, Any]) -> List[str]:
    if os.path.isabs(name):
        return [name]
    question_dir = str(runtime.get("question_dir") or "").strip()
    result: List[str] = []
    if question_dir:
        result.append(os.path.join(question_dir, name))
    result.append(os.path.join(os.getcwd(), name))
    result.append(name)
    return result


def resolve_message_file(name: str, runtime: Dict[str, Any]) -> str:
    if name:
        for candidate in _candidate_paths(name, runtime):
            if os.path.isfile(candidate):
                return candidate
    for path in runtime.get("allowed_file_paths") or []:
        if os.path.isfile(str(path)) and str(path).lower().endswith(".txt"):
            return str(path)
    raise FileNotFoundError("message file not found")


def read_lines(path: str) -> List[str]:
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _clean_message(line: str) -> str:
    if "客户说：" in line:
        return line.split("客户说：", 1)[1]
    return re.sub(r"^\s*\d+\s*[.、]\s*", "", line)


def parse_full_dates(text: str) -> List[date]:
    dates: List[date] = []

    patterns = [
        r"(?<!\d)(\d{4})\s*(?:年(?:的)?|[./-])\s*(\d{1,2})\s*(?:月|[./-])\s*(\d{1,2})(?:\s*日)?",
        r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if len(match.group(1)) == 4:
                y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            else:
                d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
            try:
                dates.append(date(y, m, d))
            except ValueError:
                continue
    return dates


def parse_month_day(text: str, default_year: int) -> Optional[date]:
    match = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text)
    if not match:
        match = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!/\d)", text)
    if not match:
        return None
    try:
        return date(default_year, int(match.group(1)), int(match.group(2)))
    except ValueError:
        return None


def add_workdays(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def week_start(anchor: date) -> date:
    return anchor - timedelta(days=anchor.weekday())


def target_weekday(anchor: date, prefix: str, weekday_char: str) -> date:
    base = week_start(anchor)
    if prefix == "上":
        base -= timedelta(days=7)
    elif prefix == "下":
        base += timedelta(days=7)
    return base + timedelta(days=WEEKDAY[weekday_char])


def solve_line(line: str) -> date:
    text = _clean_message(line)
    full_dates = parse_full_dates(text)
    anchor = full_dates[0] if full_dates else None

    explicit_year = None
    year_match = re.search(r"今年是\s*(\d{4})\s*年?", text)
    if year_match:
        explicit_year = int(year_match.group(1))
    if anchor is None and explicit_year is not None:
        anchor = parse_month_day(text, explicit_year)

    if "儿童节" in text:
        year = full_dates[0].year if full_dates else explicit_year or int(re.search(r"(\d{4})", text).group(1))
        return date(year, 6, 1)

    if "去年今天" in text or "去年今天？" in text:
        return date(anchor.year - 1, anchor.month, anchor.day)
    if "昨天" in text:
        return anchor - timedelta(days=1)
    if "明天" in text:
        return anchor + timedelta(days=1)

    stated_next = re.search(r"下周一是\s*(\d{4}年\d{1,2}月\d{1,2}日|\d{4}[./-]\d{1,2}[./-]\d{1,2})", text)
    asked_last = re.search(r"上周(?:周)?([一二三四五六日天])", text)
    if stated_next and asked_last:
        next_monday = parse_full_dates(stated_next.group(1))[0]
        implicit_anchor = next_monday - timedelta(days=7)
        return target_weekday(implicit_anchor, "上", asked_last.group(1))

    week_match = re.search(r"(上|下|这)周(?:周)?([一二三四五六日天])", text)
    if week_match:
        if "下周一是" in text and week_match.group(1) == "上" and full_dates:
            # "next Monday is D, what was last Tuesday?" means the last Tuesday
            # relative to the implicit current week whose next Monday is D.
            implicit_anchor = full_dates[0] - timedelta(days=7)
            return target_weekday(implicit_anchor, "上", week_match.group(2))
        return target_weekday(anchor, week_match.group(1), week_match.group(2))

    if "第2周" in text and "周五" in text and full_dates:
        return full_dates[0] + timedelta(days=4)

    hours_match = re.search(r"(\d+)\s*个?小时", text)
    if hours_match and anchor:
        hour = 0
        hour_match = re.search(r"(\d{1,2})\s*(?:点|:)", text)
        if hour_match:
            hour = int(hour_match.group(1))
        dt = datetime(anchor.year, anchor.month, anchor.day, hour) + timedelta(hours=int(hours_match.group(1)))
        return dt.date()

    workday_match = re.search(r"(\d+)\s*个?工作日后", text)
    if workday_match and anchor:
        return add_workdays(anchor, int(workday_match.group(1)))

    if "两周后" in text and anchor:
        return anchor + timedelta(days=14)

    day_match = re.search(r"(\d+)\s*(?:个自然日|天|日)\s*(?:后|送达|自提|无理由|开始算)", text)
    if day_match and anchor:
        return anchor + timedelta(days=int(day_match.group(1)))

    if "试用期" in text:
        m = re.search(r"试用期\s*(\d+)\s*天", text)
        if m and anchor:
            return anchor + timedelta(days=int(m.group(1)))

    if "发货日期" in text:
        md = parse_month_day(text.split("发货日期", 1)[1], anchor.year if anchor else explicit_year or date.today().year)
        if md:
            return md

    if full_dates:
        return full_dates[-1]

    if explicit_year is not None:
        md = parse_month_day(text, explicit_year)
        if md:
            return md

    raise ValueError("could not parse date from line: %s" % line)


def answer(args: Dict[str, Any]) -> Dict[str, Any]:
    runtime = args.get("_runtime") if isinstance(args.get("_runtime"), dict) else {}
    path = resolve_message_file(str(args.get("message_file") or ""), runtime)
    outputs = [solve_line(line).isoformat() for line in read_lines(path)]
    return {"answer": ",".join(outputs), "n": len(outputs)}


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
