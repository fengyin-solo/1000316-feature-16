"""发电量核算接口：维护发电记录，覆盖提交核算、复核确认、标记争议与记录锁定等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.generation import ROLES
from app.services.generation import GenerationService

router = APIRouter(prefix="/api/generation", tags=["发电量核算"])

service = GenerationService()

LIST_FIELDS = ["记录编号", "电站名称", "统计日期", "理论发电量", "实际发电量", "等效利用小时", "弃光电量", "记录状态"]
STATUSES = ["待核算", "已核算", "已复核", "有争议"]


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


# 注意：export 必须排在 /{entry_id} 之前，否则会被当成记录编号触发 422
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出发电量核算清单：返回全量数据，含争议说明与处理留痕。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "generation", "total": total, "items": items}


@router.get("/roles")
def list_roles() -> dict[str, Any]:
    """返回系统认可的岗位职责，前端按此渲染账号切换。"""
    return {"roles": ROLES}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条发电记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"发电记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条发电记录，缺字段或越权时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条发电记录执行提交核算、复核确认、标记争议；越权、并发或状态不符都会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/lock", response_model=ActionResult)
def acquire_lock(entry_id: int, payload: EntryPayload) -> ActionResult:
    """领取记录处理权：占用后其他账号不能推进同一条记录，锁有超时保护。"""
    entry, message = service.acquire_lock(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.delete("/{entry_id}/lock", response_model=ActionResult)
def release_lock(entry_id: int, payload: EntryPayload) -> ActionResult:
    """主动释放处理权，只能由占锁账号本人释放。"""
    entry, message = service.release_lock(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
