"""发电量核算业务规则：状态流转、字段校验与筛选口径都收在这里。

按职责分流后的流转约定：
- 核算岗：登记发电记录、提交核算（待核算/有争议 → 已核算）；
- 复核岗：复核确认（已核算 → 已复核）、标记争议（已核算 → 有争议，必须填争议说明）；
- 值班人：只读查看全部记录，不能执行任何动作；
- 已复核为终态：数据不能改动，也不能再被改回已复核；
- 有争议的记录保留在待处理里，争议说明同步到记录详情并留在流转记录中。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "generation"
REQUIRED_FIELDS = ["记录编号", "电站名称", "统计日期"]
# 弃光电量口径照旧：只按登记值原样保存与展示，不在核算流程里重算。
ENTRY_FIELDS = ["记录编号", "电站名称", "统计日期", "理论发电量", "实际发电量", "等效利用小时", "弃光电量"]
STATUS_ORDER = ["待核算", "已核算", "已复核", "有争议"]
TERMINAL_STATUS = "已复核"
PENDING_STATUSES = {"待核算", "已核算", "有争议"}

ROLE_ACCOUNTANT = "核算岗"
ROLE_REVIEWER = "复核岗"
ROLE_VIEWER = "值班人"
KNOWN_ROLES = (ROLE_ACCOUNTANT, ROLE_REVIEWER, ROLE_VIEWER)

# 动作 -> 目标状态 / 允许的角色 / 允许的当前状态；已复核不在任何源状态里，保证终态不可改。
ACTION_RULES: dict[str, dict[str, Any]] = {
    "提交核算": {"target": "已核算", "roles": (ROLE_ACCOUNTANT,), "from": ("待核算", "有争议")},
    "复核确认": {"target": "已复核", "roles": (ROLE_REVIEWER,), "from": ("已核算",)},
    "标记争议": {"target": "有争议", "roles": (ROLE_REVIEWER,), "from": ("已核算",)},
}

# 同一份记录不能被两个账号同时推进：状态判断与推进收在同一把锁里。
_STORE_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class GenerationService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        operator: str = "",
        role: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        if role != ROLE_ACCOUNTANT:
            shown = role or "未分配"
            return None, f"越权提交已拒绝：登记发电记录只能由核算岗执行，当前角色为{shown}"
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = str(values.get("记录编号") or "").strip()
        with _STORE_LOCK:
            rows = store.rows(MODULE)
            if any(str(row.get("记录编号", "")).strip() == code for row in rows):
                return None, f"记录编号 {code} 已存在，不能重复登记；两个账号同时提交时以先入库的为准"
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: values.get(field) for field in ENTRY_FIELDS})
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            entry["登记人"] = operator or "未署名账号"
            entry["登记时间"] = _now()
            entry["流转记录"] = [{
                "时间": entry["登记时间"],
                "操作人": entry["登记人"],
                "角色": role,
                "动作": "登记记录",
                "说明": "",
            }]
            rows.append(entry)
        return entry, "发电记录已登记"

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str = "",
        role: str = "",
        note: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        with _STORE_LOCK:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"发电记录 {entry_id} 不存在或已归档"
            if role not in KNOWN_ROLES:
                return None, f"当前账号未分配核算流程角色（核算岗/复核岗/值班人），无法执行「{action}」"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于发电量核算可执行范围"
            if role == ROLE_VIEWER:
                return None, f"值班人角色只读查看记录，不能执行「{action}」；请由核算岗或复核岗账号处理"
            rule = ACTION_RULES[action]
            if role not in rule["roles"]:
                allowed = "、".join(rule["roles"])
                return None, f"越权提交已拒绝：「{action}」只能由{allowed}执行，当前角色为{role}"
            current = str(entry.get("status") or STATUS_ORDER[0])
            if current == TERMINAL_STATUS:
                return None, f"发电记录已复核归档，数据不能改动也不能改回已复核；「{action}」被拒绝"
            if current not in rule["from"]:
                return None, (
                    f"记录当前状态为「{current}」，不允许执行「{action}」；"
                    "可能已被其他账号处理，请刷新列表后确认"
                )
            note = note.strip()
            if action == "标记争议" and not note:
                return None, "标记争议必须填写争议说明，说明会同步到记录详情并保留在待处理中"

            target = rule["target"]
            now = _now()
            operator_name = operator or "未署名账号"
            entry["status"] = target
            entry["pending"] = target in PENDING_STATUSES
            entry["abnormal"] = action == "标记争议"
            if action == "提交核算":
                entry["核算人"] = operator_name
                entry["核算时间"] = now
            elif action == "复核确认":
                entry["复核人"] = operator_name
                entry["复核时间"] = now
            elif action == "标记争议":
                entry["争议说明"] = note
                entry["争议标记人"] = operator_name
                entry["争议时间"] = now
            entry.setdefault("流转记录", []).append({
                "时间": now,
                "操作人": operator_name,
                "角色": role,
                "动作": action,
                "说明": note,
            })
            return entry, f"发电记录已{action}"
