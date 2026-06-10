from __future__ import annotations

from datetime import datetime, timedelta

from lab_platform.db import MongoStore
from lab_platform.security import hash_password


def seed_database(reset: bool = False) -> None:
    store = MongoStore()
    store.ping()

    if reset:
        for name in ["users", "labs", "devices", "schedules", "reservations", "maintenance_logs", "repair_reports"]:
            store.collection(name).delete_many({})

    store.ensure_indexes()

    if store.users().count_documents({}) == 0:
        store.users().insert_many(
            [
                {
                    "name": "系统管理员",
                    "username": "admin",
                    "password_hash": hash_password("admin123"),
                    "role": "管理员",
                    "department": "信息工程学院",
                    "created_at": datetime.now(),
                },
                {
                    "name": "荀菁菁",
                    "username": "teacher_xun",
                    "password_hash": hash_password("teacher123"),
                    "role": "教师",
                    "department": "智能科学与技术系",
                    "created_at": datetime.now(),
                },
                {
                    "name": "李同学",
                    "username": "student_li",
                    "password_hash": hash_password("student123"),
                    "role": "学生",
                    "department": "人工智能专业",
                    "created_at": datetime.now(),
                },
            ]
        )

    if store.labs().count_documents({}) == 0:
        lab_ids = store.labs().insert_many(
            [
                {
                    "name": "智能感知与交互实验室",
                    "location": "实训楼 A301",
                    "capacity": 45,
                    "open_start": "08:00",
                    "open_end": "21:00",
                    "manager": "荀菁菁",
                    "description": "面向无人机、智能小车和空地协同实验教学。",
                },
                {
                    "name": "百度机器人实验室",
                    "location": "实训楼 B205",
                    "capacity": 36,
                    "open_start": "08:00",
                    "open_end": "21:00",
                    "manager": "荀菁菁",
                    "description": "面向机器人平台、ROS 调试和竞赛集训。",
                },
            ]
        ).inserted_ids

        device_ids = store.devices().insert_many(
            [
                {
                    "name": "RoboMaster TT 编队无人机",
                    "type": "无人机",
                    "lab_id": lab_ids[0],
                    "status": "可用",
                    "shareable": False,
                    "owner": "荀菁菁",
                    "notes": "需记录电池循环次数与低压告警。",
                },
                {
                    "name": "Tian Mini 智能小车",
                    "type": "智能小车",
                    "lab_id": lab_ids[0],
                    "status": "可用",
                    "shareable": True,
                    "owner": "荀菁菁",
                    "notes": "支持多人调试，但需登记项目用途。",
                },
                {
                    "name": "机器人 ROS 平台",
                    "type": "机器人",
                    "lab_id": lab_ids[1],
                    "status": "维护中",
                    "shareable": False,
                    "owner": "荀菁菁",
                    "notes": "系统存储清理和传感器标定中。",
                },
            ]
        ).inserted_ids

        today = datetime.now().date()
        store.schedules().insert_many(
            [
                {
                    "course_name": "智能感知技术实验",
                    "teacher": "荀菁菁",
                    "teacher_username": "teacher_xun",
                    "class_name": "人工智能 2301",
                    "lab_id": lab_ids[0],
                    "start_dt": datetime.combine(today + timedelta(days=1), datetime.strptime("09:00", "%H:%M").time()),
                    "end_dt": datetime.combine(today + timedelta(days=1), datetime.strptime("11:30", "%H:%M").time()),
                    "source": "教务课表",
                },
                {
                    "course_name": "机器人系统综合实践",
                    "teacher": "荀菁菁",
                    "teacher_username": "teacher_xun",
                    "class_name": "机器人工程 2302",
                    "lab_id": lab_ids[1],
                    "start_dt": datetime.combine(today + timedelta(days=2), datetime.strptime("14:00", "%H:%M").time()),
                    "end_dt": datetime.combine(today + timedelta(days=2), datetime.strptime("17:00", "%H:%M").time()),
                    "source": "教务课表",
                },
            ]
        )

        store.reservations().insert_many(
            [
                {
                    "requester_username": "student_li",
                    "requester_name": "李同学",
                    "requester_role": "学生",
                    "lab_id": lab_ids[0],
                    "device_id": device_ids[1],
                    "purpose": "竞赛集训",
                    "participant_count": 12,
                    "start_dt": datetime.combine(today, datetime.strptime("18:00", "%H:%M").time()),
                    "end_dt": datetime.combine(today, datetime.strptime("20:00", "%H:%M").time()),
                    "status": "已通过",
                    "reviewer": "系统管理员",
                    "review_comment": "演示数据",
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
            ]
        )

        store.maintenance_logs().insert_one(
            {
                "device_id": device_ids[2],
                "device_name": "机器人 ROS 平台",
                "recorder": "荀菁菁",
                "issue": "底层系统存储空间不足，需清理镜像并重新标定传感器。",
                "result": "维护中",
                "recorded_at": datetime.now(),
            }
        )

    if store.repair_reports().count_documents({}) == 0:
        labs = list(store.labs().find().sort("name", 1))
        devices = list(store.devices().find().sort("name", 1))
        if labs and devices:
            lab_by_id = {item["_id"]: item for item in labs}
            first_device = devices[0]
            first_lab = lab_by_id.get(first_device.get("lab_id"), labs[0])
            second_device = devices[1] if len(devices) > 1 else first_device
            second_lab = lab_by_id.get(second_device.get("lab_id"), first_lab)
            now = datetime.now()
            store.repair_reports().insert_many(
                [
                    {
                        "device_id": first_device["_id"],
                        "device_name": first_device["name"],
                        "lab_id": first_lab["_id"],
                        "lab_name": first_lab["name"],
                        "title": "电池续航异常",
                        "description": "设备使用过程中电池电量下降过快，建议管理员检查电池健康状态。",
                        "priority": "较急",
                        "status": "待处理",
                        "reporter_username": "student_li",
                        "reporter_name": "李同学",
                        "reporter_role": "学生",
                        "admin_comment": "",
                        "handler": "",
                        "created_at": now - timedelta(days=1),
                        "updated_at": now - timedelta(days=1),
                        "resolved_at": None,
                    },
                    {
                        "device_id": second_device["_id"],
                        "device_name": second_device["name"],
                        "lab_id": second_lab["_id"],
                        "lab_name": second_lab["name"],
                        "title": "调试连接不稳定",
                        "description": "连接调试时偶发断开，已尝试重启设备但仍复现。",
                        "priority": "一般",
                        "status": "处理中",
                        "reporter_username": "teacher_xun",
                        "reporter_name": "荀菁菁",
                        "reporter_role": "教师",
                        "admin_comment": "已安排管理员复核网络与驱动配置。",
                        "handler": "系统管理员",
                        "created_at": now - timedelta(hours=8),
                        "updated_at": now - timedelta(hours=2),
                        "resolved_at": None,
                    },
                ]
            )


if __name__ == "__main__":
    seed_database()
    print("演示数据初始化完成。")
