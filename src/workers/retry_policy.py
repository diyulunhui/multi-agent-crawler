from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    # 重试决策结果：是否重试、下一次计数、退避秒数。
    should_retry: bool
    next_retry_count: int
    delay_seconds: float


class ExponentialBackoffRetryPolicy:
    def __init__(self, max_retries: int, base_delay_seconds: float, max_delay_seconds: float) -> None:
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds

    def decide(self, current_retry_count: int) -> RetryDecision:
        # 指数退避：1x,2x,4x...，并受最大延迟与最大重试次数限制。
        next_retry = current_retry_count + 1
        if next_retry > self.max_retries:
            return RetryDecision(should_retry=False, next_retry_count=current_retry_count, delay_seconds=0)

        delay = min(self.base_delay_seconds * (2 ** (next_retry - 1)), self.max_delay_seconds)
        return RetryDecision(should_retry=True, next_retry_count=next_retry, delay_seconds=delay)
