"""发电量核算接口：维护发电记录，覆盖提交核算、复核确认、标记争议等动作。

操作人身份通过请求头传入：X-Operator-Name（账号名）、X-Operator-Role（核算岗/复核岗/值班人）。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.generation import GenerationService

router = APIRouter(prefix="/api/generation", tags=["发电量核算"])

service = GenerationService()

LIST_FIELDS = ["记录编号", "电站名称", "统计日期", "理论发电量", "实际发电量", "等效利用小时", "弃光电量", "记录状态"]
STATUSES = ["待核算", "已核算", "已复核", "有争议"]


def _identity(raw: str | None) -> str:
    """身份头按百分号编码传输（HTTP 头只能是 ASCII），这里解码还原中文。"""
    return unquote(raw) if raw else ""


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="待核算、已核算、已复核、有争议"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤发电量核算列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条发电记录明细（含争议说明与流转记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"发电记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(
    payload: EntryPayload,
    x_operator_name: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> ActionResult:
    """登记一条发电记录；越权、缺字段或记录编号重复时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(
        payload.values,
        operator=_identity(x_operator_name),
        role=_identity(x_operator_role),
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator_name: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> ActionResult:
    """对单条发电记录执行提交核算、复核确认、标记争议；越权或状态不符的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    note = str(payload.remark or payload.values.get("争议说明") or "")
    entry, message = service.run_action(
        entry_id,
        action,
        operator=_identity(x_operator_name),
        role=_identity(x_operator_role),
        note=note,
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出发电量核算清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "generation", "total": total, "items": items}
