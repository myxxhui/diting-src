"""清空 teacher_distill 中 mock Teacher 行 + 可选全清."""
from sqlalchemy import delete, or_

from apps.cryo_guard.db.models import TeacherDistill
from apps.cryo_guard.db.sync_session import session_scope

import sys

purge_all = "--all" in sys.argv

with session_scope() as s:
    if purge_all:
        n = s.execute(delete(TeacherDistill)).rowcount
    else:
        n = s.execute(
            delete(TeacherDistill).where(
                or_(
                    TeacherDistill.teacher_model == "cryo_mock_teacher",
                    TeacherDistill.teacher_model.like("%mock%"),
                )
            )
        ).rowcount
    s.commit()
    print(f"  已删 {n} 条 teacher_distill ✅")
