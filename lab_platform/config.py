from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()


def get_streamlit_secret(key: str) -> str | None:
    try:
        import streamlit as st
    except Exception:
        return None

    try:
        value: Any = st.secrets.get(key)
    except Exception:
        return None

    if value is None:
        return None
    return str(value)


def get_config_value(key: str, default: str) -> str:
    return os.getenv(key) or get_streamlit_secret(key) or default


MONGODB_URI = get_config_value("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = get_config_value("MONGODB_DB", "lab_management_platform")

RESERVATION_STATUSES = ["待审批", "已通过", "已驳回", "已完成"]
DEVICE_STATUSES = ["可用", "借用中", "维护中", "停用"]
REPAIR_PRIORITIES = ["一般", "较急", "紧急"]
REPAIR_STATUSES = ["待处理", "处理中", "已修复", "已关闭"]
USER_ROLES = ["管理员", "教师", "学生"]
