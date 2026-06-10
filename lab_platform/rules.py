from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable


APPROVED_STATUSES = {"已通过", "已完成"}


def combine_date_time(day: date, value: time) -> datetime:
    return datetime.combine(day, value)


def overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def has_class_conflict(
    schedules: Iterable[dict],
    lab_id: str,
    start_dt: datetime,
    end_dt: datetime,
) -> bool:
    for item in schedules:
        if str(item.get("lab_id")) != str(lab_id):
            continue
        if overlaps(start_dt, end_dt, item["start_dt"], item["end_dt"]):
            return True
    return False


def has_device_conflict(
    reservations: Iterable[dict],
    device_id: str | None,
    start_dt: datetime,
    end_dt: datetime,
) -> bool:
    if not device_id:
        return False

    for item in reservations:
        if item.get("status") not in {"待审批", "已通过"}:
            continue
        if str(item.get("device_id")) != str(device_id):
            continue
        if overlaps(start_dt, end_dt, item["start_dt"], item["end_dt"]):
            return True
    return False


def duration_hours(start_dt: datetime, end_dt: datetime) -> float:
    return max((end_dt - start_dt).total_seconds() / 3600, 0)


def open_hours_between(
    start_day: date,
    end_day: date,
    open_start: str = "08:00",
    open_end: str = "21:00",
) -> float:
    start_parts = [int(part) for part in open_start.split(":")]
    end_parts = [int(part) for part in open_end.split(":")]
    daily_hours = (
        datetime.combine(start_day, time(end_parts[0], end_parts[1]))
        - datetime.combine(start_day, time(start_parts[0], start_parts[1]))
    ).total_seconds() / 3600
    days = (end_day - start_day).days + 1
    return max(days * daily_hours, 0)


def utilization_percent(used_hours: float, available_hours: float) -> float:
    if available_hours <= 0:
        return 0.0
    return round(min(used_hours / available_hours * 100, 100), 1)


def clamp_date_range(start_day: date, end_day: date) -> tuple[date, date]:
    if end_day < start_day:
        return end_day, start_day
    return start_day, end_day


def date_range_start_end(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    start_day, end_day = clamp_date_range(start_day, end_day)
    return datetime.combine(start_day, time.min), datetime.combine(end_day + timedelta(days=1), time.min)
