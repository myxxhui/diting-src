"""技术雷达 · 成本追踪与预算控制"""
from datetime import datetime


class CostTracker:
    """每日 ASR 预算保护：避免意外超支。

    用法：
        tracker = CostTracker(daily_budget_minutes=60, cost_per_minute=0.016)
        if tracker.check_budget(estimated_minutes):
            # 调用 ASR
            tracker.record_usage(actual_minutes)
        else:
            # 排入明日队列
    """

    def __init__(self, daily_budget_minutes: float, cost_per_minute: float):
        self._budget = daily_budget_minutes
        self._cost_per_min = cost_per_minute
        self._today_used = 0.0

    def sync_usage(self, today_used_minutes: float):
        """从已处理记录同步今日用量（启动时调用）"""
        self._today_used = today_used_minutes

    def check_budget(self, estimated_minutes: float) -> bool:
        """检查是否有足够预算处理此音频。

        Args:
            estimated_minutes: 预估需要花费的分钟数

        Returns:
            True = 预算充足，可以处理
            False = 预算耗尽，跳过
        """
        if self._today_used + estimated_minutes > self._budget:
            remaining = self._budget - self._today_used
            print(
                f"⛔ 今日预算耗尽\n"
                f"   已用 {self._today_used:.0f}/{self._budget} 分钟\n"
                f"   此文件需 {estimated_minutes:.0f} 分钟，超出 {abs(remaining):.0f} 分钟\n"
                f"   明早再跑 pipeline.py 即可继续"
            )
            return False
        return True

    def record_usage(self, actual_minutes: float) -> dict:
        """记录实际使用量，返回花费。

        Args:
            actual_minutes: 实际 ASR 处理时长（分钟）

        Returns:
            {"minutes": float, "cost": float}
        """
        self._today_used += actual_minutes
        cost = actual_minutes * self._cost_per_min
        remaining = self._budget - self._today_used

        print(
            f"💰 本次费用 ¥{cost:.2f} "
            f"| 今日累计 {self._today_used:.0f}/{self._budget} 分钟"
        )
        if remaining > 0:
            print(f"   今日剩余额度 {remaining:.0f} 分钟")

        return {"minutes": actual_minutes, "cost": cost}

    @property
    def today_used(self) -> float:
        return self._today_used

    @property
    def budget_remaining(self) -> float:
        return max(0.0, self._budget - self._today_used)
