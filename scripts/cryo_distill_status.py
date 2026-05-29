"""teacher_distill 数量快照."""
from sqlalchemy import func, select

from apps.cryo_guard.db.models import TeacherDistill
from apps.cryo_guard.db.sync_session import session_scope

ENGINES = ("financial_fraud", "shareholder_integrity", "related_party")

with session_scope() as s:
    total = s.scalar(select(func.count()).select_from(TeacherDistill)) or 0
    print(f"  总计 {total} 条（扩展期目标 3500）")
    for eng in ENGINES:
        n = s.scalar(
            select(func.count()).select_from(TeacherDistill).where(TeacherDistill.engine_name == eng)
        ) or 0
        print(f"  {eng}: {n}")
