"""Label Studio Webhook 路由 + HMAC 校验 + labelings 状态回写.

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_03_C2_Label_Studio部署.md §7.1]
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import update

from apps.super_evo.db.database import get_session
from apps.super_evo.db.models import LabelingRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/labeling", tags=["labeling"])

_WEBHOOK_SECRET = os.environ.get("LS_WEBHOOK_SECRET", "")

# Label Studio 事件类型：https://labelstud.io/guide/webhooks.html
_ANNOTATION_EVENTS = frozenset({
    "ANNOTATION_CREATED",
    "ANNOTATION_UPDATED",
    "ANNOTATION_DELETED",
})


def _verify_hmac(body: bytes, sig_header: str | None) -> bool:
    """验证 Label Studio HMAC-SHA256 签名.

    LS 发送：X-LSE-Signature: <hex>
    若 LS_WEBHOOK_SECRET 未配置，跳过校验（仅启动期本地联调时可接受）.
    """
    if not _WEBHOOK_SECRET:
        logger.warning("LS_WEBHOOK_SECRET 未配置，跳过 HMAC 校验（仅限启动期本地联调）")
        return True
    if not sig_header:
        return False
    expected = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.lower())


def _resolve_status(event: str, annotation: dict[str, Any]) -> str:
    """将 LS 事件 + 标注内容映射为 labelings.status."""
    if event == "ANNOTATION_DELETED":
        return "deleted"
    # 双盲：结果非空视为 verified
    if annotation.get("result"):
        return "verified"
    return "pending_review"


@router.post("/ls_webhook")
async def ls_webhook(
    request: Request,
    x_lse_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """接收 Label Studio 标注事件，回写 labelings 表状态.

    Label Studio Webhook payload 格式（核心字段）::

        {
          "action": "ANNOTATION_CREATED",
          "annotation": {
            "id": 42,
            "task": 101,
            "result": [...]
          },
          "project": {...}
        }
    """
    body = await request.body()
    if not _verify_hmac(body, x_lse_signature):
        raise HTTPException(status_code=401, detail="HMAC 签名验证失败")

    try:
        payload: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"无效 JSON: {exc}") from exc

    action: str = payload.get("action", "")
    if action not in _ANNOTATION_EVENTS:
        # 非标注事件（如 PROJECT_CREATED）直接忽略
        logger.debug("忽略非标注事件 action=%s", action)
        return {"ok": True, "action": action, "handled": False}

    annotation: dict[str, Any] = payload.get("annotation") or {}
    ls_task_id: int | None = annotation.get("task")
    annotation_id: int | None = annotation.get("id")
    new_status = _resolve_status(action, annotation)

    updated = 0
    if ls_task_id is not None:
        session = get_session()
        try:
            result = session.execute(
                update(LabelingRecord)
                .where(LabelingRecord.ls_task_id == ls_task_id)
                .values(status=new_status)
                .returning(LabelingRecord.id)
            )
            updated = len(result.fetchall())
            session.commit()
        finally:
            session.close()

    logger.info(
        "ls_webhook action=%s ls_task_id=%s annotation_id=%s status=%s updated_rows=%s",
        action, ls_task_id, annotation_id, new_status, updated,
    )
    return {
        "ok": True,
        "action": action,
        "ls_task_id": ls_task_id,
        "annotation_id": annotation_id,
        "new_status": new_status,
        "updated_rows": updated,
    }
