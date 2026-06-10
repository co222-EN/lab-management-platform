from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ServerSelectionTimeoutError

from .config import MONGODB_DB, MONGODB_URI


class MongoStore:
    def __init__(self, uri: str = MONGODB_URI, db_name: str = MONGODB_DB):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=2500)
        self.db: Database = self.client[db_name]

    def ping(self) -> None:
        self.client.admin.command("ping")

    def collection(self, name: str) -> Collection:
        return self.db[name]

    def users(self) -> Collection:
        return self.collection("users")

    def labs(self) -> Collection:
        return self.collection("labs")

    def devices(self) -> Collection:
        return self.collection("devices")

    def schedules(self) -> Collection:
        return self.collection("schedules")

    def reservations(self) -> Collection:
        return self.collection("reservations")

    def maintenance_logs(self) -> Collection:
        return self.collection("maintenance_logs")

    def repair_reports(self) -> Collection:
        return self.collection("repair_reports")

    def ensure_indexes(self) -> None:
        self.users().create_index("username", unique=True)
        self.labs().create_index("name")
        self.devices().create_index([("lab_id", 1), ("name", 1)])
        self.schedules().create_index([("lab_id", 1), ("start_dt", 1), ("end_dt", 1)])
        self.reservations().create_index([("lab_id", 1), ("start_dt", 1), ("end_dt", 1)])
        self.reservations().create_index([("device_id", 1), ("start_dt", 1), ("end_dt", 1)])
        self.repair_reports().create_index("status")
        self.repair_reports().create_index("device_id")
        self.repair_reports().create_index("created_at")
        self.repair_reports().create_index("reporter_username")


def object_id(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    return ObjectId(str(value))


def serialize_doc(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    data = dict(doc)
    data["id"] = str(data.pop("_id"))
    return data


def serialize_many(items: list[dict]) -> list[dict]:
    return [serialize_doc(item) for item in items if item is not None]


def overlapping_query(start_dt: datetime, end_dt: datetime) -> dict:
    return {"start_dt": {"$lt": end_dt}, "end_dt": {"$gt": start_dt}}


def connection_error_message(error: Exception) -> str:
    if isinstance(error, ServerSelectionTimeoutError):
        return "无法连接 MongoDB。请确认 MongoDB 已启动，并检查 MONGODB_URI。"
    return f"数据库连接异常：{error}"
