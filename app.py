from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from bson import ObjectId
from pymongo.errors import PyMongoError

from lab_platform.config import DEVICE_STATUSES, REPAIR_PRIORITIES, REPAIR_STATUSES, RESERVATION_STATUSES, USER_ROLES
from lab_platform.db import MongoStore, connection_error_message, object_id, overlapping_query, serialize_doc, serialize_many
from lab_platform.rules import (
    APPROVED_STATUSES,
    combine_date_time,
    date_range_start_end,
    duration_hours,
    has_class_conflict,
    has_device_conflict,
    open_hours_between,
    utilization_percent,
)
from lab_platform.reservation_export import export_open_records_with_template
from lab_platform.schedule_import import (
    PRINT_IMPORT_SOURCE,
    default_section_times,
    expand_courses,
    parse_uploaded_print_schedule,
    section_times_from_strings,
)
from lab_platform.security import hash_password, verify_password


OPEN_RECORD_TEMPLATE = Path("templates/开放记录导出模板.xlsx")


st.set_page_config(
    page_title="高校跨实验室智能预约与精细化管理平台",
    page_icon="🧪",
    layout="wide",
)


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --primary: #2563eb;
            --accent: #0f766e;
            --muted: #64748b;
            --surface: #f8fafc;
            --border: #dbe3ef;
        }
        .main .block-container { padding-top: 1.5rem; }
        .platform-title {
            padding: 18px 20px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: linear-gradient(135deg, #ffffff 0%, #eef6ff 55%, #edfdf9 100%);
            margin-bottom: 18px;
        }
        .platform-title h1 {
            font-size: 30px;
            line-height: 1.25;
            margin: 0 0 6px 0;
            letter-spacing: 0;
        }
        .platform-title p { color: var(--muted); margin: 0; }
        .metric-note { color: var(--muted); font-size: 13px; margin-top: -8px; }
        div[data-testid="stMetric"] {
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            background: white;
        }
        .status-pass { color: #166534; font-weight: 700; }
        .status-warn { color: #b45309; font-weight: 700; }
        .status-stop { color: #b91c1c; font-weight: 700; }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource(show_spinner=False)
def get_store() -> MongoStore:
    store = MongoStore()
    store.ping()
    store.ensure_indexes()
    return store


def safe_store() -> MongoStore | None:
    try:
        return get_store()
    except Exception as exc:  # Streamlit should show a clear MongoDB failure instead of fake data.
        st.error(connection_error_message(exc))
        st.info(
            "本地运行请启动 MongoDB 或设置 `.env`；Streamlit Cloud 运行请在 App Settings -> Secrets "
            "中设置 `MONGODB_URI` 和 `MONGODB_DB`，保存后 Reboot app。"
        )
        return None


def rerun() -> None:
    st.rerun()


def label_map(items: list[dict], label_key: str = "name") -> dict[str, dict]:
    return {f"{item[label_key]} ({item['id'][-6:]})": item for item in items}


def load_labs(store: MongoStore) -> list[dict]:
    return serialize_many(list(store.labs().find().sort("name", 1)))


def load_devices(store: MongoStore, lab_id: str | None = None) -> list[dict]:
    query: dict[str, Any] = {}
    if lab_id:
        query["lab_id"] = object_id(lab_id)
    return serialize_many(list(store.devices().find(query).sort("name", 1)))


def load_schedules(store: MongoStore, start_day: date | None = None, end_day: date | None = None) -> list[dict]:
    query: dict[str, Any] = {}
    if start_day and end_day:
        start_dt, end_dt = date_range_start_end(start_day, end_day)
        query = overlapping_query(start_dt, end_dt)
    return serialize_many(list(store.schedules().find(query).sort("start_dt", 1)))


def load_reservations(store: MongoStore, query: dict | None = None) -> list[dict]:
    return serialize_many(list(store.reservations().find(query or {}).sort("start_dt", -1)))


def safe_dataframe(data: list[dict] | pd.DataFrame, empty_message: str = "暂无数据。") -> None:
    frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    if frame.empty:
        st.info(empty_message)
        return
    st.dataframe(frame, use_container_width=True)


def parse_datetime_value(row: pd.Series, date_col: str, start_col: str | None = None) -> datetime:
    if start_col is None:
        value = row.get(date_col)
        parsed = pd.to_datetime(value, errors="coerce")
    else:
        value = f"{row.get(date_col, '')} {row.get(start_col, '')}"
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"无法解析日期时间：{date_col}" + (f" + {start_col}" if start_col else ""))
    return parsed.to_pydatetime()


def find_lab_id_by_name(labs: list[dict], lab_name: str) -> ObjectId:
    normalized = str(lab_name).strip()
    for lab in labs:
        if lab.get("name") == normalized:
            return object_id(lab["id"])
    raise ValueError(f"未找到实验室：{normalized}")


def lab_name_by_id(labs: list[dict]) -> dict[str, str]:
    return {item["id"]: item["name"] for item in labs}


def device_name_by_id(devices: list[dict]) -> dict[str, str]:
    return {item["id"]: item["name"] for item in devices}


def enrich_reservations(rows: list[dict], labs: list[dict], devices: list[dict]) -> pd.DataFrame:
    lab_names = lab_name_by_id(labs)
    device_names = device_name_by_id(devices)
    data = []
    for item in rows:
        data.append(
            {
                "申请人": item.get("requester_name", item.get("requester_username", "")),
                "角色": item.get("requester_role", ""),
                "实验室": lab_names.get(str(item.get("lab_id")), "未知实验室"),
                "设备": device_names.get(str(item.get("device_id")), "无"),
                "用途": item.get("purpose", ""),
                "实验人数": item.get("participant_count", 1),
                "开始": item.get("start_dt"),
                "结束": item.get("end_dt"),
                "状态": item.get("status", ""),
                "审批意见": item.get("review_comment", ""),
            }
        )
    return pd.DataFrame(data)


def enrich_reservations_for_export(rows: list[dict], labs: list[dict], devices: list[dict], users: list[dict]) -> list[dict]:
    lab_names = lab_name_by_id(labs)
    lab_locations = {item["id"]: item.get("location", "") for item in labs}
    device_names = device_name_by_id(devices)
    user_lookup = {item.get("username", ""): item for item in users}
    enriched = []
    for item in rows:
        row = dict(item)
        lab_id = str(item.get("lab_id"))
        requester = row.get("requester_username", "")
        row["lab_name"] = lab_names.get(lab_id, "未知实验室")
        row["lab_location"] = lab_locations.get(lab_id, "")
        row["device_name"] = device_names.get(str(item.get("device_id")), "无")
        user_doc = user_lookup.get(requester, {})
        row["requester_department"] = user_doc.get("department", "")
        enriched.append(row)
    return enriched


def authenticate(store: MongoStore, username: str, password: str) -> dict | None:
    user = store.users().find_one({"username": username.strip()})
    if not user or not verify_password(password, user.get("password_hash", "")):
        return None
    return serialize_doc(user)


def render_header(user: dict | None) -> None:
    suffix = f"当前用户：{user['name']} · {user['role']}" if user else "跨实验室智能预约与精细化管理"
    st.markdown(
        f"""
        <div class="platform-title">
            <h1>高校跨实验室智能预约与精细化管理平台</h1>
            <p>{suffix}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def login_view(store: MongoStore) -> None:
    render_header(None)
    left, center, right = st.columns([1, 1.2, 1])
    with center:
        st.subheader("账号登录")
        st.caption("跨实验室预约、设备报修与开放记录管理")
        with st.form("login_form"):
            username = st.text_input("账号")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录", use_container_width=True)
        if submitted:
            user = authenticate(store, username, password)
            if user:
                st.session_state["user"] = user
                rerun()
            st.error("账号或密码不正确。")


def reservation_form(store: MongoStore, user: dict, title: str) -> None:
    labs = load_labs(store)
    if not labs:
        st.warning("暂无实验室数据，请管理员先初始化或新增实验室。")
        return

    st.subheader(title)
    lab_options = label_map(labs)
    lab_label = st.selectbox("实验室", list(lab_options.keys()))
    selected_lab = lab_options[lab_label]
    devices = load_devices(store, selected_lab["id"])
    available_devices = [item for item in devices if item.get("status") != "停用"]

    device_choices = {"不预约具体设备": None}
    device_choices.update(label_map(available_devices))

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        day = st.date_input("预约日期", value=date.today())
    with col_b:
        start_value = st.time_input("开始时间", value=time(18, 0), step=timedelta(minutes=30))
    with col_c:
        end_value = st.time_input("结束时间", value=time(20, 0), step=timedelta(minutes=30))

    device_label = st.selectbox("设备", list(device_choices.keys()))
    participant_count = st.number_input("实验（训）人数", min_value=1, max_value=500, value=1, step=1)
    purpose = st.text_area("用途", placeholder="例如：竞赛集训、课程补充实验、机器人调试等")

    start_dt = combine_date_time(day, start_value)
    end_dt = combine_date_time(day, end_value)
    selected_device = device_choices[device_label]

    with st.expander("查看当天正式课表占用", expanded=True):
        schedules = load_schedules(store, day, day)
        lab_schedules = [item for item in schedules if str(item.get("lab_id")) == selected_lab["id"]]
        if lab_schedules:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "课程": item.get("course_name"),
                            "班级": item.get("class_name"),
                            "教师": item.get("teacher"),
                            "开始": item.get("start_dt"),
                            "结束": item.get("end_dt"),
                        }
                        for item in lab_schedules
                    ]
                ),
                use_container_width=True,
            )
        else:
            st.caption("当天无正式课表占用。")

    if st.button("提交预约申请", type="primary", use_container_width=True):
        if end_dt <= start_dt:
            st.error("结束时间必须晚于开始时间。")
            return
        if not purpose.strip():
            st.error("请填写预约用途。")
            return

        schedules = list(store.schedules().find({"lab_id": object_id(selected_lab["id"]), **overlapping_query(start_dt, end_dt)}))
        if has_class_conflict(schedules, selected_lab["id"], start_dt, end_dt):
            st.error("该实验室在所选时间段已有正式课程，不能提交预约。")
            return

        if selected_device and not selected_device.get("shareable"):
            conflicts = list(
                store.reservations().find(
                    {
                        "device_id": object_id(selected_device["id"]),
                        "status": {"$in": ["待审批", "已通过"]},
                        **overlapping_query(start_dt, end_dt),
                    }
                )
            )
            if has_device_conflict(conflicts, selected_device["id"], start_dt, end_dt):
                st.error("该设备在所选时间段已有预约，不能重复预约。")
                return

        store.reservations().insert_one(
            {
                "requester_username": user["username"],
                "requester_name": user["name"],
                "requester_role": user["role"],
                "lab_id": object_id(selected_lab["id"]),
                "device_id": object_id(selected_device["id"]) if selected_device else None,
                "purpose": purpose.strip(),
                "participant_count": int(participant_count),
                "start_dt": start_dt,
                "end_dt": end_dt,
                "status": "待审批",
                "reviewer": "",
                "review_comment": "",
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }
        )
        st.success("预约申请已提交，等待管理员审批。")


def my_reservations_view(store: MongoStore, user: dict) -> None:
    labs = load_labs(store)
    devices = load_devices(store)
    rows = load_reservations(store, {"requester_username": user["username"]})
    st.subheader("我的预约")
    if not rows:
        st.info("暂无预约记录。")
        return
    st.dataframe(enrich_reservations(rows, labs, devices), use_container_width=True)


def schedules_view(store: MongoStore, role: str = "all", username: str | None = None) -> None:
    st.subheader("课表占用")
    labs = load_labs(store)
    lab_names = lab_name_by_id(labs)
    start_day, end_day = st.date_input(
        "日期范围",
        value=(date.today(), date.today() + timedelta(days=7)),
    )
    rows = load_schedules(store, start_day, end_day)
    if role == "teacher" and username:
        rows = [item for item in rows if item.get("teacher_username") == username]

    data = [
        {
            "课程": item.get("course_name"),
            "教师": item.get("teacher"),
            "班级": item.get("class_name"),
            "实验室": lab_names.get(str(item.get("lab_id")), "未知实验室"),
            "开始": item.get("start_dt"),
            "结束": item.get("end_dt"),
            "来源": item.get("source", "教务课表"),
        }
        for item in rows
    ]
    safe_dataframe(data, "当前日期范围内暂无课表占用。")


def admin_dashboard(store: MongoStore) -> None:
    st.subheader("运行数据看板")
    labs = load_labs(store)
    devices = load_devices(store)
    start_day, end_day = st.date_input(
        "统计日期范围",
        value=(date.today() - timedelta(days=7), date.today() + timedelta(days=7)),
        key="dashboard_range",
    )
    start_dt, end_dt = date_range_start_end(start_day, end_day)
    reservations = load_reservations(store, overlapping_query(start_dt, end_dt))
    approved = [item for item in reservations if item.get("status") in APPROVED_STATUSES]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("实验室数量", len(labs))
    col2.metric("设备数量", len(devices))
    col3.metric("预约总数", len(reservations))
    col4.metric("已通过/完成", len(approved))

    available_hours_by_lab = {
        lab["id"]: open_hours_between(start_day, end_day, lab.get("open_start", "08:00"), lab.get("open_end", "21:00"))
        for lab in labs
    }

    lab_usage = []
    for lab in labs:
        used = sum(duration_hours(item["start_dt"], item["end_dt"]) for item in approved if str(item.get("lab_id")) == lab["id"])
        lab_usage.append(
            {
                "实验室": lab["name"],
                "使用小时": round(used, 1),
                "利用率": utilization_percent(used, available_hours_by_lab.get(lab["id"], 0)),
            }
        )

    device_usage = []
    for device in devices:
        lab_id = str(device.get("lab_id"))
        used = sum(
            duration_hours(item["start_dt"], item["end_dt"])
            for item in approved
            if str(item.get("device_id")) == device["id"]
        )
        device_usage.append(
            {
                "设备": device["name"],
                "类型": device.get("type", ""),
                "使用小时": round(used, 1),
                "利用率": utilization_percent(used, available_hours_by_lab.get(lab_id, 0)),
            }
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(px.bar(pd.DataFrame(lab_usage), x="实验室", y="利用率", title="实验室利用率", text="利用率"), use_container_width=True)
    with right:
        st.plotly_chart(px.bar(pd.DataFrame(device_usage), x="设备", y="利用率", color="类型", title="设备利用率"), use_container_width=True)

    status_df = pd.DataFrame(reservations)
    if not status_df.empty:
        chart_a, chart_b = st.columns(2)
        with chart_a:
            status_counts = status_df["status"].value_counts().reset_index()
            status_counts.columns = ["状态", "数量"]
            st.plotly_chart(px.pie(status_counts, names="状态", values="数量", title="预约状态分布"), use_container_width=True)
        with chart_b:
            status_df["hour"] = status_df["start_dt"].dt.hour
            hour_counts = status_df.groupby("hour").size().reset_index(name="预约数")
            st.plotly_chart(px.bar(hour_counts, x="hour", y="预约数", title="高峰时段"), use_container_width=True)

        role_counts = status_df["requester_role"].value_counts().reset_index()
        role_counts.columns = ["角色", "预约数"]
        st.plotly_chart(px.bar(role_counts, x="角色", y="预约数", title="角色使用统计"), use_container_width=True)
    else:
        st.info("当前日期范围内暂无预约数据。")


def approval_view(store: MongoStore, user: dict) -> None:
    st.subheader("预约审批")
    labs = load_labs(store)
    devices = load_devices(store)
    pending = load_reservations(store, {"status": "待审批"})
    if not pending:
        st.info("暂无待审批预约。")
        return

    for item in pending:
        lab_lookup = lab_name_by_id(labs)
        device_lookup = device_name_by_id(devices)
        with st.container(border=True):
            st.write(
                f"**{item.get('requester_name')}** 申请 `{lab_lookup.get(str(item.get('lab_id')), '未知实验室')}` "
                f"({item['start_dt']:%Y-%m-%d %H:%M} - {item['end_dt']:%H:%M})"
            )
            st.caption(f"设备：{device_lookup.get(str(item.get('device_id')), '无')} | 用途：{item.get('purpose', '')}")
            comment = st.text_input("审批意见", key=f"comment_{item['id']}")
            col_a, col_b = st.columns(2)
            if col_a.button("通过", key=f"pass_{item['id']}", use_container_width=True):
                store.reservations().update_one(
                    {"_id": object_id(item["id"])},
                    {
                        "$set": {
                            "status": "已通过",
                            "reviewer": user["name"],
                            "review_comment": comment or "同意预约",
                            "updated_at": datetime.now(),
                        }
                    },
                )
                st.success("已通过。")
                rerun()
            if col_b.button("驳回", key=f"reject_{item['id']}", use_container_width=True):
                store.reservations().update_one(
                    {"_id": object_id(item["id"])},
                    {
                        "$set": {
                            "status": "已驳回",
                            "reviewer": user["name"],
                            "review_comment": comment or "不符合预约条件",
                            "updated_at": datetime.now(),
                        }
                    },
                )
                st.warning("已驳回。")
                rerun()


def reservations_admin_view(store: MongoStore) -> None:
    st.subheader("预约记录")
    labs = load_labs(store)
    devices = load_devices(store)
    status = st.multiselect("状态筛选", RESERVATION_STATUSES, default=RESERVATION_STATUSES)
    query = {"status": {"$in": status}} if status else {}
    rows = load_reservations(store, query)
    safe_dataframe(enrich_reservations(rows, labs, devices), "暂无预约记录。")

    st.markdown("#### 导出开放预约数据")
    if not OPEN_RECORD_TEMPLATE.exists():
        st.error("未找到开放记录导出模板，请检查 templates 目录。")
    else:
        try:
            users = serialize_many(list(store.users().find()))
            export_rows = enrich_reservations_for_export(rows, labs, devices, users)
            exported = export_open_records_with_template(OPEN_RECORD_TEMPLATE.read_bytes(), export_rows)
            filename = f"开放记录导出_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
            st.download_button(
                "导出开放预约记录",
                data=exported,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            st.caption(f"将按当前状态筛选导出 {len(export_rows)} 条预约记录。")
        except Exception as exc:
            st.error(f"导出失败：{exc}")

    selected = st.selectbox("标记完成", ["请选择"] + [f"{r.get('requester_name')} {r['start_dt']:%Y-%m-%d %H:%M} ({r['id'][-6:]})" for r in rows if r.get("status") == "已通过"])
    if selected != "请选择" and st.button("将该预约标记为已完成"):
        target_id = selected.split("(")[-1].strip(")")
        target = next((row for row in rows if row["id"].endswith(target_id)), None)
        if target:
            store.reservations().update_one({"_id": object_id(target["id"])}, {"$set": {"status": "已完成", "updated_at": datetime.now()}})
            st.success("已标记完成。")
            rerun()


def lab_admin_view(store: MongoStore) -> None:
    st.subheader("实验室管理")
    labs = load_labs(store)
    safe_dataframe(pd.DataFrame(labs).drop(columns=["id"], errors="ignore"), "暂无实验室。")

    lab_options = label_map(labs)
    st.markdown("#### 编辑实验室")
    if not labs:
        st.info("暂无可编辑的实验室，请先新增实验室。")
    else:
        edit_label = st.selectbox("选择要编辑的实验室", list(lab_options.keys()), key="edit_lab_select")
        selected_lab = lab_options[edit_label]
        edit_key = selected_lab["id"]
        with st.form(f"edit_lab_form_{edit_key}"):
            edit_name = st.text_input("实验室名称", value=selected_lab.get("name", ""), key=f"edit_lab_name_{edit_key}")
            edit_location = st.text_input("位置", value=selected_lab.get("location", ""), key=f"edit_lab_location_{edit_key}")
            edit_capacity = st.number_input(
                "容量",
                min_value=1,
                value=int(selected_lab.get("capacity") or 1),
                key=f"edit_lab_capacity_{edit_key}",
            )
            edit_open_start = st.text_input(
                "开放开始",
                value=selected_lab.get("open_start", "08:00"),
                key=f"edit_lab_open_start_{edit_key}",
            )
            edit_open_end = st.text_input(
                "开放结束",
                value=selected_lab.get("open_end", "21:00"),
                key=f"edit_lab_open_end_{edit_key}",
            )
            edit_manager = st.text_input("管理员", value=selected_lab.get("manager", ""), key=f"edit_lab_manager_{edit_key}")
            edit_description = st.text_area("说明", value=selected_lab.get("description", ""), key=f"edit_lab_description_{edit_key}")
            if st.form_submit_button("保存修改", use_container_width=True):
                if not edit_name.strip():
                    st.error("请填写实验室名称。")
                else:
                    store.labs().update_one(
                        {"_id": object_id(selected_lab["id"])},
                        {
                            "$set": {
                                "name": edit_name.strip(),
                                "location": edit_location.strip(),
                                "capacity": int(edit_capacity),
                                "open_start": edit_open_start.strip() or "08:00",
                                "open_end": edit_open_end.strip() or "21:00",
                                "manager": edit_manager.strip(),
                                "description": edit_description.strip(),
                            }
                        },
                    )
                    st.success("实验室信息已更新。")
                    rerun()

    with st.form("lab_form"):
        st.markdown("#### 新增实验室")
        name = st.text_input("实验室名称")
        location = st.text_input("位置")
        capacity = st.number_input("容量", min_value=1, value=40)
        open_start = st.text_input("开放开始", value="08:00")
        open_end = st.text_input("开放结束", value="21:00")
        manager = st.text_input("管理员")
        description = st.text_area("说明")
        if st.form_submit_button("保存实验室"):
            if not name:
                st.error("请填写实验室名称。")
            else:
                store.labs().insert_one(
                    {
                        "name": name,
                        "location": location,
                        "capacity": capacity,
                        "open_start": open_start,
                        "open_end": open_end,
                        "manager": manager,
                        "description": description,
                    }
                )
                st.success("实验室已保存。")
                rerun()

    st.markdown("#### 删除实验室")
    if not labs:
        st.info("暂无可删除的实验室。")
        return

    delete_label = st.selectbox("选择要删除的实验室", list(lab_options.keys()), key="delete_lab_select")
    selected_lab = lab_options[delete_label]
    selected_lab_id = object_id(selected_lab["id"])
    references = {
        "设备": store.devices().count_documents({"lab_id": selected_lab_id}),
        "课表": store.schedules().count_documents({"lab_id": selected_lab_id}),
        "预约": store.reservations().count_documents({"lab_id": selected_lab_id}),
        "报修": store.repair_reports().count_documents({"lab_id": selected_lab_id}),
    }
    active_references = {name: count for name, count in references.items() if count}

    if active_references:
        st.warning(
            "该实验室已有业务数据，暂不能直接删除："
            + "，".join(f"{name} {count} 条" for name, count in active_references.items())
            + "。请先处理或保留该实验室，以免历史记录失去归属。"
        )
    else:
        st.caption("该实验室暂无关联设备、课表、预约或报修记录，可以删除。")
        confirm_delete = st.checkbox(
            f"确认删除实验室：{selected_lab.get('name', '')}",
            key=f"confirm_delete_lab_{selected_lab['id']}",
        )
        if st.button("删除实验室", type="primary", use_container_width=True, disabled=not confirm_delete):
            result = store.labs().delete_one({"_id": selected_lab_id})
            if result.deleted_count:
                st.success("实验室已删除。")
                rerun()
            else:
                st.error("删除失败：未找到该实验室。")


def device_admin_view(store: MongoStore) -> None:
    st.subheader("设备台账")
    labs = load_labs(store)
    devices = load_devices(store)
    lab_lookup = lab_name_by_id(labs)
    table = []
    for item in devices:
        table.append(
            {
                "名称": item.get("name"),
                "类型": item.get("type"),
                "所属实验室": lab_lookup.get(str(item.get("lab_id")), ""),
                "状态": item.get("status"),
                "可共享": "是" if item.get("shareable") else "否",
                "责任人": item.get("owner"),
                "备注": item.get("notes"),
            }
        )
    safe_dataframe(table, "暂无设备台账。")

    device_options = label_map(devices)
    lab_options = label_map(labs)

    st.markdown("#### 编辑设备")
    if not devices:
        st.info("暂无可编辑的设备。")
    elif not labs:
        st.warning("暂无实验室数据，无法编辑设备所属实验室。请先维护实验室。")
    else:
        edit_device_label = st.selectbox("选择要编辑的设备", list(device_options.keys()), key="edit_device_select")
        selected_device = device_options[edit_device_label]
        selected_lab_id = str(selected_device.get("lab_id"))
        lab_labels = list(lab_options.keys())
        current_lab_index = next(
            (idx for idx, label in enumerate(lab_labels) if lab_options[label]["id"] == selected_lab_id),
            0,
        )
        device_key = selected_device["id"]
        with st.form(f"edit_device_form_{device_key}"):
            edit_name = st.text_input("设备名称", value=selected_device.get("name", ""), key=f"edit_device_name_{device_key}")
            edit_type = st.text_input("设备类型", value=selected_device.get("type", ""), key=f"edit_device_type_{device_key}")
            edit_lab_label = st.selectbox(
                "所属实验室",
                lab_labels,
                index=current_lab_index,
                key=f"edit_device_lab_{device_key}",
            )
            edit_status = st.selectbox(
                "设备状态",
                DEVICE_STATUSES,
                index=DEVICE_STATUSES.index(selected_device.get("status", "可用"))
                if selected_device.get("status") in DEVICE_STATUSES
                else 0,
                key=f"edit_device_status_{device_key}",
            )
            edit_shareable = st.checkbox(
                "可共享设备",
                value=bool(selected_device.get("shareable")),
                key=f"edit_device_shareable_{device_key}",
            )
            edit_owner = st.text_input("责任人", value=selected_device.get("owner", ""), key=f"edit_device_owner_{device_key}")
            edit_notes = st.text_area("备注", value=selected_device.get("notes", ""), key=f"edit_device_notes_{device_key}")
            if st.form_submit_button("保存设备修改", use_container_width=True):
                if not edit_name.strip():
                    st.error("请填写设备名称。")
                else:
                    store.devices().update_one(
                        {"_id": object_id(selected_device["id"])},
                        {
                            "$set": {
                                "name": edit_name.strip(),
                                "type": edit_type.strip(),
                                "lab_id": object_id(lab_options[edit_lab_label]["id"]),
                                "status": edit_status,
                                "shareable": edit_shareable,
                                "owner": edit_owner.strip(),
                                "notes": edit_notes.strip(),
                            }
                        },
                    )
                    st.success("设备信息已更新。")
                    rerun()

    st.markdown("#### Excel 导入设备台账")
    st.caption("字段：设备名称、设备类型、所属实验室、状态、是否可共享、责任人、备注。所属实验室必须与实验室管理中的名称一致。")
    upload = st.file_uploader("上传设备台账 Excel", type=["xlsx", "xls"], key="device_import")
    if upload is not None:
        try:
            frame = pd.read_excel(upload).fillna("")
            required = {"设备名称", "设备类型", "所属实验室"}
            missing = required - set(frame.columns)
            if missing:
                st.error(f"缺少必需字段：{', '.join(sorted(missing))}")
            else:
                st.dataframe(frame.head(20), use_container_width=True)
                if st.button("确认导入设备台账", use_container_width=True):
                    imported = 0
                    for _, row in frame.iterrows():
                        name = str(row.get("设备名称", "")).strip()
                        if not name:
                            continue
                        lab_id = find_lab_id_by_name(labs, row.get("所属实验室", ""))
                        status = str(row.get("状态", "可用")).strip() or "可用"
                        if status not in DEVICE_STATUSES:
                            status = "可用"
                        shareable_raw = str(row.get("是否可共享", "")).strip().lower()
                        shareable = shareable_raw in {"是", "true", "1", "yes", "y"}
                        store.devices().update_one(
                            {"name": name, "lab_id": lab_id},
                            {
                                "$set": {
                                    "name": name,
                                    "type": str(row.get("设备类型", "")).strip(),
                                    "lab_id": lab_id,
                                    "status": status,
                                    "shareable": shareable,
                                    "owner": str(row.get("责任人", "")).strip(),
                                    "notes": str(row.get("备注", "")).strip(),
                                }
                            },
                            upsert=True,
                        )
                        imported += 1
                    st.success(f"设备台账导入完成：{imported} 条。")
                    rerun()
        except Exception as exc:
            st.error(f"设备台账导入失败：{exc}")

    if not labs:
        st.info("请先在实验室页面新增实验室，再登记设备。")
    else:
        with st.form("device_form"):
            st.markdown("#### 新增 / 登记设备")
            name = st.text_input("设备名称")
            device_type = st.text_input("设备类型", value="机器人")
            lab_label = st.selectbox("所属实验室", list(lab_options.keys()))
            status = st.selectbox("设备状态", DEVICE_STATUSES)
            shareable = st.checkbox("可共享设备")
            owner = st.text_input("责任人")
            notes = st.text_area("备注")
            if st.form_submit_button("保存设备"):
                if not name:
                    st.error("请填写设备名称。")
                else:
                    store.devices().insert_one(
                        {
                            "name": name,
                            "type": device_type,
                            "lab_id": object_id(lab_options[lab_label]["id"]),
                            "status": status,
                            "shareable": shareable,
                            "owner": owner,
                            "notes": notes,
                        }
                    )
                    st.success("设备已保存。")
                    rerun()

    st.markdown("#### 状态更新")
    if devices:
        device_options = label_map(devices)
        target_label = st.selectbox("选择设备", list(device_options.keys()), key="device_status_target")
        new_status = st.selectbox("新状态", DEVICE_STATUSES, key="device_status_new")
        if st.button("更新状态"):
            store.devices().update_one({"_id": object_id(device_options[target_label]["id"])}, {"$set": {"status": new_status}})
            st.success("设备状态已更新。")
            rerun()

    st.markdown("#### 删除设备")
    if not devices:
        st.info("暂无可删除的设备。")
    else:
        delete_device_label = st.selectbox("选择要删除的设备", list(device_options.keys()), key="delete_device_select")
        selected_delete_device = device_options[delete_device_label]
        selected_device_id = object_id(selected_delete_device["id"])
        references = {
            "预约": store.reservations().count_documents({"device_id": selected_device_id}),
            "报修": store.repair_reports().count_documents({"device_id": selected_device_id}),
            "维护日志": store.maintenance_logs().count_documents({"device_id": selected_device_id}),
        }
        active_references = {name: count for name, count in references.items() if count}
        if active_references:
            st.warning(
                "该设备已有业务数据，暂不能直接删除："
                + "，".join(f"{name} {count} 条" for name, count in active_references.items())
                + "。如设备不再使用，建议将状态改为“停用”，以保留历史记录。"
            )
        else:
            st.caption("该设备暂无预约、报修或维护日志，可以删除。")
            confirm_delete = st.checkbox(
                f"确认删除设备：{selected_delete_device.get('name', '')}",
                key=f"confirm_delete_device_{selected_delete_device['id']}",
            )
            if st.button("删除设备", type="primary", use_container_width=True, disabled=not confirm_delete):
                result = store.devices().delete_one({"_id": selected_device_id})
                if result.deleted_count:
                    st.success("设备已删除。")
                    rerun()
                else:
                    st.error("删除失败：未找到该设备。")


def device_status_table(devices: list[dict], labs: list[dict]) -> pd.DataFrame:
    lab_lookup = lab_name_by_id(labs)
    return pd.DataFrame(
        [
            {
                "设备": item.get("name"),
                "类型": item.get("type"),
                "实验室": lab_lookup.get(str(item.get("lab_id")), ""),
                "状态": item.get("status"),
                "状态提示": "请勿预约，等待管理员处理" if item.get("status") in {"维护中", "停用"} else "可正常申请使用",
                "可共享": "是" if item.get("shareable") else "否",
                "责任人": item.get("owner", ""),
                "备注": item.get("notes", ""),
            }
            for item in devices
        ]
    )


def repair_report_form(store: MongoStore, user: dict, devices: list[dict], labs: list[dict]) -> None:
    st.markdown("#### 设备报修")
    if not devices:
        st.info("暂无设备，无法提交报修。")
        return

    lab_lookup = lab_name_by_id(labs)
    device_options = label_map(devices)
    with st.form(f"repair_form_{user['username']}"):
        device_label = st.selectbox("故障设备", list(device_options.keys()))
        title = st.text_input("故障标题", placeholder="例如：电池异常、无法连接、传感器无响应")
        priority = st.selectbox("紧急程度", REPAIR_PRIORITIES)
        description = st.text_area("故障描述", placeholder="请描述出现问题的时间、现象、是否影响使用，以及已尝试的处理方式。")
        submitted = st.form_submit_button("提交报修", type="primary", use_container_width=True)

    if submitted:
        device = device_options[device_label]
        lab_id = str(device.get("lab_id"))
        if not title.strip():
            st.error("请填写故障标题。")
            return
        if not description.strip():
            st.error("请填写故障描述。")
            return

        now = datetime.now()
        store.repair_reports().insert_one(
            {
                "device_id": object_id(device["id"]),
                "device_name": device["name"],
                "lab_id": object_id(lab_id),
                "lab_name": lab_lookup.get(lab_id, ""),
                "title": title.strip(),
                "description": description.strip(),
                "priority": priority,
                "status": "待处理",
                "reporter_username": user["username"],
                "reporter_name": user["name"],
                "reporter_role": user["role"],
                "admin_comment": "",
                "handler": "",
                "created_at": now,
                "updated_at": now,
                "resolved_at": None,
            }
        )
        st.success("设备报修已提交，管理员将在后台处理。")
        rerun()


def device_status_view(store: MongoStore, user: dict, allow_report: bool = True) -> None:
    st.subheader("设备状态")
    devices = load_devices(store)
    labs = load_labs(store)
    frame = device_status_table(devices, labs)
    if frame.empty:
        st.info("暂无设备。")
    else:
        def highlight_device_status(row: pd.Series) -> list[str]:
            if row.get("状态") == "停用":
                return ["background-color: #fee2e2"] * len(row)
            if row.get("状态") == "维护中":
                return ["background-color: #fef3c7"] * len(row)
            return [""] * len(row)

        st.dataframe(frame.style.apply(highlight_device_status, axis=1), use_container_width=True)

    if allow_report:
        repair_report_form(store, user, devices, labs)

    rows = serialize_many(
        list(
            store.repair_reports()
            .find({"reporter_username": user["username"]})
            .sort("created_at", -1)
        )
    )
    if rows:
        st.markdown("#### 我的报修记录")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "设备": item.get("device_name"),
                        "实验室": item.get("lab_name"),
                        "标题": item.get("title"),
                        "紧急程度": item.get("priority"),
                        "状态": item.get("status"),
                        "管理员意见": item.get("admin_comment", ""),
                        "处理人": item.get("handler", ""),
                        "处理时间": item.get("resolved_at") or item.get("updated_at"),
                        "上报时间": item.get("created_at"),
                        "更新时间": item.get("updated_at"),
                    }
                    for item in rows
                ]
            ),
            use_container_width=True,
        )


def user_admin_view(store: MongoStore) -> None:
    st.subheader("用户权限")
    users = serialize_many(list(store.users().find().sort("role", 1)))
    safe_dataframe(
        [
            {
                "姓名": item.get("name"),
                "账号": item.get("username"),
                "角色": item.get("role"),
                "所属单位": item.get("department", ""),
                "创建时间": item.get("created_at"),
            }
            for item in users
        ],
        "暂无用户。",
    )

    with st.form("user_form"):
        st.markdown("#### 新增用户")
        name = st.text_input("姓名")
        username = st.text_input("账号")
        password = st.text_input("初始密码", type="password")
        role = st.selectbox("角色", USER_ROLES)
        department = st.text_input("所属单位")
        if st.form_submit_button("保存用户"):
            if not all([name, username, password]):
                st.error("姓名、账号和密码不能为空。")
            else:
                try:
                    store.users().insert_one(
                        {
                            "name": name,
                            "username": username,
                            "password_hash": hash_password(password),
                            "role": role,
                            "department": department,
                            "created_at": datetime.now(),
                        }
                    )
                    st.success("用户已保存。")
                    rerun()
                except PyMongoError as exc:
                    st.error(f"用户保存失败：{exc}")

    st.markdown("#### 重置密码")
    if users:
        user_options = {f"{item.get('name')} / {item.get('username')} / {item.get('role')}": item for item in users}
        with st.form("reset_password_form"):
            target_label = st.selectbox("选择用户", list(user_options.keys()))
            new_password = st.text_input("新密码", type="password")
            confirm_password = st.text_input("确认新密码", type="password")
            submitted = st.form_submit_button("重置密码", use_container_width=True)
        if submitted:
            if len(new_password) < 6:
                st.error("新密码至少 6 位。")
            elif new_password != confirm_password:
                st.error("两次输入的新密码不一致。")
            else:
                target = user_options[target_label]
                store.users().update_one(
                    {"_id": object_id(target["id"])},
                    {"$set": {"password_hash": hash_password(new_password), "password_updated_at": datetime.now()}},
                )
                st.success(f"已重置 {target.get('name')} 的密码。")


def schedule_admin_view(store: MongoStore) -> None:
    schedules_view(store)
    labs = load_labs(store)
    lab_options = label_map(labs)
    st.markdown("#### 教务课表打印文件导入")
    st.caption("支持教务系统导出的教室课表 `.xls`，可自动识别星期、大节、课程、班级、教师、周次和节次。")
    print_upload = st.file_uploader("上传教务课表打印文件", type=["xls"], key="print_schedule_import")
    default_times = default_section_times()
    first_monday = st.date_input("第1周周一日期", value=date.today(), key="print_schedule_first_monday")
    time_cols = st.columns(5)
    section_inputs: dict[str, tuple[str, str]] = {}
    for idx, (section, (start_t, end_t)) in enumerate(default_times.items()):
        with time_cols[idx]:
            st.caption(section)
            start_raw = st.text_input("开始", value=start_t.strftime("%H:%M"), key=f"section_start_{section}")
            end_raw = st.text_input("结束", value=end_t.strftime("%H:%M"), key=f"section_end_{section}")
            section_inputs[section] = (start_raw, end_raw)

    if print_upload is not None:
        try:
            metadata, parsed_courses, warnings = parse_uploaded_print_schedule(print_upload)
            section_times = section_times_from_strings(section_inputs)
            expanded = expand_courses(parsed_courses, first_monday, section_times)
            st.success(
                f"识别成功：{metadata.get('classroom', '')} / {metadata.get('term', '')}，"
                f"课程片段 {len(parsed_courses)} 条，展开占用 {len(expanded)} 条。"
            )
            if warnings:
                st.warning("存在未识别内容，请检查预览。")
                st.write(warnings[:10])

            preview = [
                {
                    "课程": item.course_name,
                    "班级": item.class_name,
                    "教师": item.teacher,
                    "周次": item.week,
                    "星期": item.weekday_name,
                    "节次": item.section_text,
                    "开始": item.start_dt,
                    "结束": item.end_dt,
                    "教室": item.classroom,
                }
                for item in expanded[:20]
            ]
            safe_dataframe(preview, "暂无可预览的占用。")

            classroom = metadata.get("classroom", "")
            matching_lab = next((lab for lab in labs if lab.get("name") == classroom or classroom.startswith(lab.get("name", ""))), None)
            lab_choice_options = {"自动匹配：" + matching_lab["name"]: matching_lab} if matching_lab else {}
            lab_choice_options.update(lab_options)
            selected_lab_label = st.selectbox("导入到实验室", list(lab_choice_options.keys()), key="print_schedule_lab")
            selected_lab = lab_choice_options[selected_lab_label]

            if st.button("确认导入教务课表", use_container_width=True):
                lab_id = object_id(selected_lab["id"])
                store.schedules().delete_many(
                    {
                        "lab_id": lab_id,
                        "term": metadata.get("term", ""),
                        "source": PRINT_IMPORT_SOURCE,
                    }
                )
                docs = [
                    {
                        "course_name": item.course_name,
                        "teacher": item.teacher,
                        "teacher_username": "",
                        "class_name": item.class_name,
                        "lab_id": lab_id,
                        "start_dt": item.start_dt,
                        "end_dt": item.end_dt,
                        "term": item.term,
                        "week": item.week,
                        "weekday": item.weekday,
                        "weekday_name": item.weekday_name,
                        "section_text": item.section_text,
                        "period_name": item.period_name,
                        "classroom": item.classroom,
                        "source": PRINT_IMPORT_SOURCE,
                    }
                    for item in expanded
                ]
                if docs:
                    store.schedules().insert_many(docs)
                st.success(f"导入完成：已写入 {len(docs)} 条课表占用。")
                rerun()
        except Exception as exc:
            st.error(f"教务课表导入失败：{exc}")

    with st.form("schedule_form"):
        st.markdown("#### 导入 / 新增课表占用")
        course_name = st.text_input("课程名称")
        teacher = st.text_input("教师")
        teacher_username = st.text_input("教师账号", value="teacher_xun")
        class_name = st.text_input("班级")
        lab_label = st.selectbox("实验室", list(lab_options.keys()))
        day = st.date_input("上课日期", value=date.today() + timedelta(days=1))
        start_value = st.time_input("开始时间", value=time(9, 0), step=timedelta(minutes=30), key="schedule_start")
        end_value = st.time_input("结束时间", value=time(11, 30), step=timedelta(minutes=30), key="schedule_end")
        if st.form_submit_button("保存课表"):
            start_dt = combine_date_time(day, start_value)
            end_dt = combine_date_time(day, end_value)
            if end_dt <= start_dt:
                st.error("结束时间必须晚于开始时间。")
            elif not course_name:
                st.error("请填写课程名称。")
            else:
                store.schedules().insert_one(
                    {
                        "course_name": course_name,
                        "teacher": teacher,
                        "teacher_username": teacher_username,
                        "class_name": class_name,
                        "lab_id": object_id(lab_options[lab_label]["id"]),
                        "start_dt": start_dt,
                        "end_dt": end_dt,
                        "source": "手工导入",
                    }
                )
                st.success("课表已保存。")
                rerun()


def maintenance_view(store: MongoStore) -> None:
    st.subheader("维护日志")
    devices = load_devices(store)
    rows = serialize_many(list(store.maintenance_logs().find().sort("recorded_at", -1)))
    safe_dataframe(
        [
            {
                "设备": item.get("device_name"),
                "记录人": item.get("recorder"),
                "问题": item.get("issue"),
                "处理结果": item.get("result"),
                "记录时间": item.get("recorded_at"),
            }
            for item in rows
        ],
        "暂无维护日志。",
    )

    if not devices:
        st.info("暂无设备，无法登记维护日志。")
        return
    device_options = label_map(devices)
    with st.form("maintenance_form"):
        device_label = st.selectbox("设备", list(device_options.keys()))
        recorder = st.text_input("记录人")
        issue = st.text_area("问题")
        result = st.text_area("处理结果")
        if st.form_submit_button("保存维护日志"):
            device = device_options[device_label]
            store.maintenance_logs().insert_one(
                {
                    "device_id": object_id(device["id"]),
                    "device_name": device["name"],
                    "recorder": recorder,
                    "issue": issue,
                    "result": result,
                    "recorded_at": datetime.now(),
                }
            )
            st.success("维护日志已保存。")
            rerun()


def repair_admin_view(store: MongoStore, user: dict) -> None:
    st.subheader("设备报修")
    devices = load_devices(store)
    device_options = {"全部设备": None}
    device_options.update(label_map(devices))

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        status_filter = st.multiselect("处理状态", REPAIR_STATUSES, default=REPAIR_STATUSES)
    with col_b:
        priority_filter = st.multiselect("紧急程度", REPAIR_PRIORITIES, default=REPAIR_PRIORITIES)
    with col_c:
        device_filter = st.selectbox("设备筛选", list(device_options.keys()))

    query: dict[str, Any] = {}
    if status_filter:
        query["status"] = {"$in": status_filter}
    if priority_filter:
        query["priority"] = {"$in": priority_filter}
    selected_device = device_options[device_filter]
    if selected_device:
        query["device_id"] = object_id(selected_device["id"])

    rows = serialize_many(list(store.repair_reports().find(query).sort("created_at", -1)))
    if not rows:
        st.info("暂无符合条件的报修记录。")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "设备": item.get("device_name"),
                    "实验室": item.get("lab_name"),
                    "标题": item.get("title"),
                    "紧急程度": item.get("priority"),
                    "状态": item.get("status"),
                    "上报人": item.get("reporter_name"),
                    "角色": item.get("reporter_role"),
                    "上报时间": item.get("created_at"),
                    "更新时间": item.get("updated_at"),
                    "处理人": item.get("handler", ""),
                    "处理意见": item.get("admin_comment", ""),
                    "处理时间": item.get("resolved_at") or item.get("updated_at"),
                }
                for item in rows
            ]
        ),
        use_container_width=True,
    )

    st.markdown("#### 处理报修")
    report_options = {
        f"{item.get('device_name')} - {item.get('title')} ({item['id'][-6:]})": item
        for item in rows
    }
    report_label = st.selectbox("选择报修记录", list(report_options.keys()))
    report = report_options[report_label]
    st.caption(f"故障描述：{report.get('description', '')}")

    with st.form(f"repair_admin_form_{report['id']}"):
        current_status = report.get("status", "待处理")
        status_index = REPAIR_STATUSES.index(current_status) if current_status in REPAIR_STATUSES else 0
        new_status = st.selectbox("处理状态", REPAIR_STATUSES, index=status_index)
        admin_comment = st.text_area("处理意见", value=report.get("admin_comment", ""))
        sync_device = st.checkbox("同步更新设备状态")
        synced_status = st.selectbox("同步后的设备状态", DEVICE_STATUSES, index=DEVICE_STATUSES.index("维护中"))
        create_maintenance = st.checkbox("同时生成维护日志", value=new_status in {"处理中", "已修复"})
        submitted = st.form_submit_button("保存处理结果", type="primary", use_container_width=True)

    if submitted:
        now = datetime.now()
        resolved_at = now if new_status in {"已修复", "已关闭"} else report.get("resolved_at")
        update_data = {
            "status": new_status,
            "admin_comment": admin_comment.strip(),
            "handler": user["name"],
            "updated_at": now,
            "resolved_at": resolved_at,
        }
        store.repair_reports().update_one({"_id": object_id(report["id"])}, {"$set": update_data})
        if sync_device:
            store.devices().update_one({"_id": object_id(report["device_id"])}, {"$set": {"status": synced_status}})
        if create_maintenance:
            store.maintenance_logs().insert_one(
                {
                    "device_id": object_id(report["device_id"]),
                    "device_name": report.get("device_name", ""),
                    "recorder": user["name"],
                    "issue": f"报修：{report.get('title', '')}\n{report.get('description', '')}",
                    "result": admin_comment.strip() or new_status,
                    "repair_report_id": object_id(report["id"]),
                    "recorded_at": now,
                }
            )
        st.success("报修处理结果已保存。")
        rerun()


def teacher_confirm_view(store: MongoStore, user: dict) -> None:
    st.subheader("学生预约确认")
    labs = load_labs(store)
    devices = load_devices(store)
    rows = load_reservations(store, {"requester_role": "学生", "status": "待审批"})
    if not rows:
        st.info("暂无待确认学生预约。")
        return
    st.caption("教师可先了解学生预约情况；最终通过/驳回仍由管理员完成。")
    st.dataframe(enrich_reservations(rows, labs, devices), use_container_width=True)


def admin_app(store: MongoStore, user: dict) -> None:
    tabs = st.tabs(["数据看板", "预约审批", "预约记录", "实验室", "设备台账", "设备报修", "用户权限", "课表", "维护日志"])
    with tabs[0]:
        admin_dashboard(store)
    with tabs[1]:
        approval_view(store, user)
    with tabs[2]:
        reservations_admin_view(store)
    with tabs[3]:
        lab_admin_view(store)
    with tabs[4]:
        device_admin_view(store)
    with tabs[5]:
        repair_admin_view(store, user)
    with tabs[6]:
        user_admin_view(store)
    with tabs[7]:
        schedule_admin_view(store)
    with tabs[8]:
        maintenance_view(store)


def teacher_app(store: MongoStore, user: dict) -> None:
    tabs = st.tabs(["提交预约", "我的预约", "课表占用", "设备状态"])
    with tabs[0]:
        reservation_form(store, user, "提交预约")
    with tabs[1]:
        my_reservations_view(store, user)
    with tabs[2]:
        schedules_view(store)
    with tabs[3]:
        device_status_view(store, user)


def student_app(store: MongoStore, user: dict) -> None:
    tabs = st.tabs(["提交预约", "我的预约", "课表占用", "设备状态"])
    with tabs[0]:
        reservation_form(store, user, "学生预约")
    with tabs[1]:
        my_reservations_view(store, user)
    with tabs[2]:
        schedules_view(store)
    with tabs[3]:
        device_status_view(store, user)


def sidebar_user_controls(user: dict) -> None:
    st.sidebar.title("平台导航")
    st.sidebar.write(f"**{user['name']}**")
    st.sidebar.caption(f"{user['role']} · {user.get('department', '')}")
    if st.sidebar.button("退出登录", use_container_width=True):
        st.session_state.pop("user", None)
        rerun()


def main() -> None:
    inject_style()
    store = safe_store()
    if store is None:
        return

    user = st.session_state.get("user")
    if not user:
        login_view(store)
        return

    render_header(user)
    sidebar_user_controls(user)

    role = user.get("role")
    if role == "管理员":
        admin_app(store, user)
    elif role == "教师":
        teacher_app(store, user)
    else:
        student_app(store, user)


if __name__ == "__main__":
    main()
