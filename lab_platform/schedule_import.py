from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO


WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
PRINT_IMPORT_SOURCE = "教务课表打印导入"


@dataclass(frozen=True)
class ParsedCourse:
    course_name: str
    class_name: str
    teacher: str
    weeks_text: str
    weeks: list[int]
    section_text: str
    weekday: int
    weekday_name: str
    period_name: str
    classroom: str
    term: str


@dataclass(frozen=True)
class ExpandedSchedule:
    course_name: str
    teacher: str
    class_name: str
    start_dt: datetime
    end_dt: datetime
    term: str
    week: int
    weekday: int
    weekday_name: str
    section_text: str
    period_name: str
    classroom: str
    source: str = PRINT_IMPORT_SOURCE


def default_section_times() -> dict[str, tuple[time, time]]:
    return {
        "01-02": (time(8, 0), time(9, 40)),
        "03-04": (time(10, 0), time(11, 40)),
        "05-06": (time(14, 0), time(15, 40)),
        "07-08": (time(16, 0), time(17, 40)),
        "09-10": (time(19, 0), time(20, 40)),
    }


def expand_weeks(weeks_text: str) -> list[int]:
    weeks: set[int] = set()
    for part in re.split(r"[,，]\s*", weeks_text.strip()):
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            start = int(start_raw.strip())
            end = int(end_raw.strip())
            weeks.update(range(min(start, end), max(start, end) + 1))
        else:
            weeks.add(int(part.strip()))
    return sorted(weeks)


def parse_course_cell(
    cell_text: str,
    weekday: int,
    weekday_name: str,
    period_name: str,
    classroom: str,
    term: str,
) -> list[ParsedCourse]:
    lines = [line.strip() for line in str(cell_text).replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    courses: list[ParsedCourse] = []
    i = 0
    while i + 3 < len(lines):
        course_name = lines[i]
        class_name = lines[i + 1]
        teacher = lines[i + 2]
        schedule_line = lines[i + 3]
        match = re.search(r"([\d,\-，\s]+)\s*周\s*\[(\d{2}-\d{2})节\]", schedule_line)
        if match:
            weeks_text = match.group(1).replace("，", ",").strip()
            section_text = match.group(2)
            courses.append(
                ParsedCourse(
                    course_name=course_name,
                    class_name=class_name,
                    teacher=teacher,
                    weeks_text=weeks_text,
                    weeks=expand_weeks(weeks_text),
                    section_text=section_text,
                    weekday=weekday,
                    weekday_name=weekday_name,
                    period_name=period_name,
                    classroom=classroom,
                    term=term,
                )
            )
            i += 4
        else:
            i += 1
    return courses


def expand_courses(
    courses: list[ParsedCourse],
    first_monday: date,
    section_times: dict[str, tuple[time, time]],
) -> list[ExpandedSchedule]:
    expanded: list[ExpandedSchedule] = []
    for course in courses:
        if course.section_text not in section_times:
            raise ValueError(f"未配置节次时间：{course.section_text}")
        start_time, end_time = section_times[course.section_text]
        for week in course.weeks:
            day = first_monday + timedelta(days=(week - 1) * 7 + course.weekday)
            expanded.append(
                ExpandedSchedule(
                    course_name=course.course_name,
                    teacher=course.teacher,
                    class_name=course.class_name,
                    start_dt=datetime.combine(day, start_time),
                    end_dt=datetime.combine(day, end_time),
                    term=course.term,
                    week=week,
                    weekday=course.weekday,
                    weekday_name=course.weekday_name,
                    section_text=course.section_text,
                    period_name=course.period_name,
                    classroom=course.classroom,
                )
            )
    return expanded


def _read_workbook(path: str | Path):
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError("缺少 xlrd 依赖，无法读取旧版 .xls 文件。请先安装 xlrd。") from exc
    return xlrd.open_workbook(str(path), formatting_info=False)


def _cell_text(sheet, row: int, col: int) -> str:
    value = sheet.cell_value(row, col)
    if value is None:
        return ""
    return str(value).strip()


def _extract_term(text: str) -> str:
    match = re.search(r"学年学期[:：]\s*([^\s]+)", text)
    return match.group(1) if match else ""


def _extract_classroom(title: str, metadata: str) -> str:
    match = re.search(r"教室[:：]\s*([^\s]+)", metadata)
    if match:
        return match.group(1).strip()
    title = title.replace("教室课表", "").strip()
    parts = title.split()
    return parts[-1] if parts else title


def parse_print_schedule_file(path: str | Path) -> tuple[dict, list[ParsedCourse], list[str]]:
    workbook = _read_workbook(path)
    warnings: list[str] = []
    all_courses: list[ParsedCourse] = []
    metadata = {"sheet": "", "term": "", "classroom": "", "title": ""}

    for sheet in workbook.sheets():
        weekday_row = None
        weekday_cols: dict[int, str] = {}
        for row_idx in range(sheet.nrows):
            for col_idx in range(sheet.ncols):
                text = _cell_text(sheet, row_idx, col_idx)
                if text in WEEKDAY_NAMES:
                    weekday_row = row_idx
                    weekday_cols[col_idx] = text
            if weekday_row is not None:
                break

        if weekday_row is None:
            continue

        title = _cell_text(sheet, 0, 0)
        meta_text = " ".join(_cell_text(sheet, 1, col) for col in range(sheet.ncols))
        term = _extract_term(meta_text)
        classroom = _extract_classroom(title, meta_text)
        metadata = {"sheet": sheet.name, "term": term, "classroom": classroom, "title": title}

        for row_idx in range(weekday_row + 1, sheet.nrows):
            period_name = _cell_text(sheet, row_idx, 0)
            if not period_name or "大节" not in period_name:
                continue
            for col_idx, weekday_name in weekday_cols.items():
                cell_text = _cell_text(sheet, row_idx, col_idx)
                if not cell_text:
                    continue
                parsed = parse_course_cell(
                    cell_text,
                    weekday=WEEKDAY_NAMES.index(weekday_name),
                    weekday_name=weekday_name,
                    period_name=period_name,
                    classroom=classroom,
                    term=term,
                )
                if parsed:
                    all_courses.extend(parsed)
                else:
                    warnings.append(f"{sheet.name} {period_name} {weekday_name} 未识别：{cell_text[:80]}")
        break

    if not all_courses:
        raise ValueError("未在文件中识别到可导入课程。请确认上传的是教室课表打印文件。")
    return metadata, all_courses, warnings


def parse_uploaded_print_schedule(uploaded_file: BinaryIO) -> tuple[dict, list[ParsedCourse], list[str]]:
    suffix = Path(getattr(uploaded_file, "name", "schedule.xls")).suffix or ".xls"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
    try:
        return parse_print_schedule_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def section_times_from_strings(values: dict[str, tuple[str, str]]) -> dict[str, tuple[time, time]]:
    parsed: dict[str, tuple[time, time]] = {}
    for section, (start_raw, end_raw) in values.items():
        parsed[section] = (
            datetime.strptime(start_raw.strip(), "%H:%M").time(),
            datetime.strptime(end_raw.strip(), "%H:%M").time(),
        )
    return parsed
