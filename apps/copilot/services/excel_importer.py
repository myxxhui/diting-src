"""Excel 持仓批量导入服务。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02]
"""
from io import BytesIO

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import Holding, User

REQUIRED_COLUMNS = ["股票代码", "股票名称", "持仓数量", "成本价"]


class ExcelImportError(ValueError):
    """Excel 解析或字段缺失错误。"""


def parse_excel(file_bytes: bytes) -> list[dict]:
    """解析 Excel 字节流，返回字典列表，不入库。"""
    try:
        df = pd.read_excel(BytesIO(file_bytes))
    except Exception as exc:
        raise ExcelImportError(f"Excel 文件解析失败: {exc}") from exc

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ExcelImportError(f"缺少必填列: {', '.join(missing)}")

    rows: list[dict] = []
    for idx, row in df.iterrows():
        try:
            rows.append(
                {
                    "symbol": str(row["股票代码"]).strip().zfill(6),
                    "name": str(row["股票名称"]).strip(),
                    "shares": float(row["持仓数量"]),
                    "cost_price": float(row["成本价"]),
                    "notes": str(row.get("备注", "") or "").strip() or None,
                }
            )
        except (TypeError, ValueError) as exc:
            raise ExcelImportError(f"第 {idx + 2} 行数据非法: {exc}") from exc
    return rows


async def upsert_holdings(session: AsyncSession, user_pk: int, rows: list[dict]) -> int:
    """按 (user_pk, symbol) upsert，返回写入条数。"""
    count = 0
    for r in rows:
        existing = await session.scalar(
            select(Holding).where(
                Holding.user_pk == user_pk, Holding.symbol == r["symbol"]
            )
        )
        if existing:
            existing.name = r["name"]
            existing.shares = r["shares"]
            existing.cost_price = r["cost_price"]
            existing.notes = r["notes"]
        else:
            session.add(Holding(user_pk=user_pk, **r))
        count += 1
    await session.commit()
    return count


async def ensure_default_user(session: AsyncSession) -> User:
    """启动期单用户：确保默认 user_id='default' 存在并返回。"""
    user = await session.scalar(select(User).where(User.user_id == "default"))
    if user is None:
        user = User(user_id="default", name="默认用户")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user
