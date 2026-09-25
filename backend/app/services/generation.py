"""发电量核算业务规则：职责分流、状态流转、记录锁定与争议留痕都收在这里。"""
from __future__ import annotations

import threading
import time
from typing import Any

from app.store import store

MODULE = "generation"
REQUIRED_FIELDS = ["记录编号", "电站名称", "统计日期"]
# 提交核算时落到记录上的核算结果字段；弃光电量沿用提交口径，不在服务端重算
RESULT_FIELDS = ["实际发电量", "等效利用小时", "弃光电量"]
SUBMIT_REQUIRED_FIELDS = ["实际发电量"]
DISPUTE_NOTE = "争议说明"
DISPUTE_HISTORY = "争议记录"

STATUS_DRAFT = "待核算"
STATUS_DONE = "已核算"
STATUS_REVIEWED = "已复核"
STATUS_DISPUTED = "有争议"
STATUS_ORDER = [STATUS_DRAFT, STATUS_DONE, STATUS_REVIEWED, STATUS_DISPUTED]

ROLE_ACCOUNTING = "核算岗"
ROLE_REVIEW = "复核岗"
ROLE_DUTY = "值班人"
ROLES = [ROLE_ACCOUNTING, ROLE_REVIEW, ROLE_DUTY]

ACTION_SUBMIT = "提交核算"
ACTION_CONFIRM = "复核确认"
ACTION_DISPUTE = "标记争议"

# 每个动作允许的发起角色：核算岗只能提交核算，复核岗只能复核/争议，值班人只读
ACTION_ROLES = {
    ACTION_SUBMIT: ROLE_ACCOUNTING,
    ACTION_CONFIRM: ROLE_REVIEW,
    ACTION_DISPUTE: ROLE_REVIEW,
}
# 每个动作允许的来源状态；已复核不出现在任何动作的来源里，数据锁定不可改动
ACTION_STATUSES = {
    ACTION_SUBMIT: (STATUS_DRAFT, STATUS_DISPUTED),
    ACTION_CONFIRM: (STATUS_DONE,),
    ACTION_DISPUTE: (STATUS_DRAFT, STATUS_DONE),
}

LOCK_TTL_SECONDS = 5 * 60

# 进程内互斥：保证「检查占锁 → 写入核算结果」是一个原子过程，
# 两个账号同时提交时只有一个能推进，不会出现互相覆盖或两条核算结果
_global_lock = threading.RLock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


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

    # -- 身份与锁 ---------------------------------------------------------

    def resolve_identity(self, values: dict[str, Any]) -> tuple[str, str] | None:
        """从请求里取当前账号与角色；身份不明时拒绝操作，避免匿名越权。"""
        operator = str(values.get("operator") or "").strip()
        role = str(values.get("role") or "").strip()
        if not operator:
            return None
        if role not in ROLES:
            return None
        return operator, role

    def _lock_owner(self, entry: dict[str, Any]) -> str | None:
        """返回当前有效占锁人；锁超时（如浏览器直接关闭）自动释放。"""
        owner = entry.get("locked_by")
        if not owner:
            return None
        locked_at = float(entry.get("locked_at") or 0)
        if time.time() - locked_at > LOCK_TTL_SECONDS:
            return None
        return str(owner)

    def acquire_lock(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        with _global_lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"发电记录 {entry_id} 不存在或已归档"
            identity = self.resolve_identity(values)
            if identity is None:
                return None, "未能识别当前账号或岗位角色，请重新登录后再操作"
            operator, role = identity
            if role == ROLE_DUTY:
                return None, "值班人为只读角色，只能查看发电记录，不能领取处理"
            if entry.get("status") == STATUS_REVIEWED:
                return None, "发电记录已复核锁定，不能再领取处理"
            owner = self._lock_owner(entry)
            if owner and owner != operator:
                return None, f"发电记录正由「{owner}」处理中，请等待其完成或联系值班长协调"
            entry["locked_by"] = operator
            entry["locked_at"] = time.time()
            return entry, f"已领取发电记录 {entry.get('记录编号', entry_id)}，处理期间其他账号不能推进"

    def release_lock(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        with _global_lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"发电记录 {entry_id} 不存在或已归档"
            identity = self.resolve_identity(values)
            if identity is None:
                return None, "未能识别当前账号或岗位角色，请重新登录后再操作"
            operator, _role = identity
            owner = self._lock_owner(entry)
            if owner is None:
                return entry, "记录当前没有被占用"
            if owner != operator:
                return None, f"记录由「{owner}」占用，只能由其本人或值班长释放"
            entry.pop("locked_by", None)
            entry.pop("locked_at", None)
            return entry, "已释放处理锁"

    # -- 写入 -------------------------------------------------------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        identity = self.resolve_identity(values)
        if identity is None:
            return None, "未能识别当前账号或岗位角色，请重新登录后再操作"
        _operator, role = identity
        if role != ROLE_ACCOUNTING:
            return None, f"{role}无权登记发电记录，只有核算岗可以登记并提交核算"
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        with _global_lock:
            rows = store.rows(MODULE)
            entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            for field in RESULT_FIELDS:
                value = values.get(field)
                if value is not None and str(value).strip():
                    entry[field] = value
            entry["status"] = STATUS_DRAFT
            entry["记录状态"] = STATUS_DRAFT
            entry["pending"] = True
            entry["abnormal"] = False
            entry["version"] = 1
            entry[DISPUTE_NOTE] = ""
            entry[DISPUTE_HISTORY] = []
            rows.append(entry)
        return entry, "发电记录已登记"

    def run_action(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        action = str(values.get("action") or "").strip()
        identity = self.resolve_identity(values)
        if identity is None:
            return None, "未能识别当前账号或岗位角色，请重新登录后再操作"
        operator, role = identity
        with _global_lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"发电记录 {entry_id} 不存在或已归档"
            if action not in ACTION_ROLES:
                return None, f"动作「{action}」不属于发电量核算可执行范围"

            # 1. 职责分流：岗位与动作不匹配直接拒绝并说明原因
            allowed_role = ACTION_ROLES[action]
            if role != allowed_role:
                if role == ROLE_DUTY:
                    return None, f"值班人为只读角色，不能{action}，如需处理请使用{allowed_role}账号"
                return None, f"{role}无权{action}，该操作仅{allowed_role}可执行"

            # 2. 已复核数据永久锁定，不能改动，也不能被任何动作改回已复核
            if entry.get("status") == STATUS_REVIEWED:
                return None, "发电记录已复核锁定，核算结果与状态都不能再改动"

            # 3. 状态流转合法性
            current = entry.get("status")
            if current not in ACTION_STATUSES[action]:
                return None, f"当前状态为「{current}」，不能{action}"

            # 4. 记录级互斥：别人占着锁就拒绝，防止两个账号同时推进同一条
            owner = self._lock_owner(entry)
            if owner and owner != operator:
                return None, f"发电记录正由「{owner}」处理中，请等待其完成后再操作"

            if action == ACTION_DISPUTE:
                note = str(values.get(DISPUTE_NOTE) or "").strip()
                if not note:
                    return None, "标记争议必须填写争议说明，说明会同步到记录详情供核算岗核对"
                return self._mark_dispute(entry, operator, note)

            if action == ACTION_SUBMIT:
                missing = [
                    field for field in SUBMIT_REQUIRED_FIELDS
                    if not str(values.get(field) or "").strip()
                ]
                if missing:
                    return None, f"提交核算缺少核算结果：{'、'.join(missing)}"
                return self._submit(entry, operator, values)

            return self._confirm(entry, operator)

    def _submit(
        self, entry: dict[str, Any], operator: str, values: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        # 锁在写入窗口内一直由当前账号持有，并发的第二个提交会在锁检查处被拦下
        entry["locked_by"] = operator
        entry["locked_at"] = time.time()
        for field in RESULT_FIELDS:
            value = values.get(field)
            if value is not None and str(value).strip():
                entry[field] = value
        entry["status"] = STATUS_DONE
        entry["记录状态"] = STATUS_DONE
        entry["pending"] = True
        entry["abnormal"] = False
        entry["核算人"] = operator
        entry["核算时间"] = _now()
        entry["version"] = int(entry.get("version", 1)) + 1
        entry.pop("locked_by", None)
        entry.pop("locked_at", None)
        return entry, "核算结果已提交，等待复核岗复核确认"

    def _confirm(self, entry: dict[str, Any], operator: str) -> tuple[dict[str, Any], str]:
        entry["status"] = STATUS_REVIEWED
        entry["记录状态"] = STATUS_REVIEWED
        entry["pending"] = False
        entry["abnormal"] = False
        entry["复核人"] = operator
        entry["复核时间"] = _now()
        entry["version"] = int(entry.get("version", 1)) + 1
        entry.pop("locked_by", None)
        entry.pop("locked_at", None)
        return entry, "发电记录已复核确认，数据已锁定"

    def _mark_dispute(
        self, entry: dict[str, Any], operator: str, note: str
    ) -> tuple[dict[str, Any], str]:
        # 争议记录保留在待处理里（pending 不摘除），争议说明同步到详情并保留历史
        entry[DISPUTE_NOTE] = note
        history = entry.setdefault(DISPUTE_HISTORY, [])
        history.append({"争议说明": note, "标记人": operator, "标记时间": _now()})
        entry["status"] = STATUS_DISPUTED
        entry["记录状态"] = STATUS_DISPUTED
        entry["pending"] = True
        entry["abnormal"] = True
        entry["version"] = int(entry.get("version", 1)) + 1
        entry.pop("locked_by", None)
        entry.pop("locked_at", None)
        return entry, "已标记争议，记录保留在待处理列表并通知核算岗重新核对"
