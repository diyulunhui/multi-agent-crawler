from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class QueueConfig:
    # 进程内队列容量与 worker 并发参数。
    max_size: int = 10000
    worker_count: int = 4
    # worker 拉取队列的轮询间隔，不等同于抓取间隔。
    poll_interval_seconds: float = 0.5
    # 页面抓取最小间隔（秒），默认 3 秒（在时效与风控间取平衡）。
    request_interval_seconds: float = 3.0


@dataclass(frozen=True)
class ScheduleConfig:
    # 拍卖时序策略开关与关键时间参数。
    enable_pre1: bool = False
    enable_final_monitor: bool = True
    enable_d3_backfill: bool = False
    pre5_minutes: int = 5
    pre1_minutes: int = 1
    special_post_close_minutes: int = 60
    next_day_hour: int = 10
    d3_hour: int = 10
    # FINAL 顺延监控降频：默认每 60 秒轮询，最多监控 30 分钟。
    extension_poll_seconds: int = 60
    extension_max_minutes: int = 30


@dataclass(frozen=True)
class RetryConfig:
    # 失败重试策略（指数退避）参数。
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0


@dataclass(frozen=True)
class AppConfig:
    site_name: str
    timezone: ZoneInfo
    db_url: str
    storage_root: Path
    queue: QueueConfig
    schedule: ScheduleConfig
    retry: RetryConfig
    model_settings_path: Path
    enable_dynamic_orchestration: bool

    @staticmethod
    def from_env() -> "AppConfig":
        # 统一从环境变量加载配置，避免散落在业务逻辑中。
        tz_name = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
        return AppConfig(
            site_name=os.getenv("SITE_NAME", "hxguquan"),
            timezone=ZoneInfo(tz_name),
            db_url=os.getenv("DB_URL", "sqlite:///data/hx_auction.db"),
            storage_root=Path(os.getenv("STORAGE_ROOT", "data/raw_snapshots")),
            queue=QueueConfig(
                max_size=int(os.getenv("QUEUE_MAX_SIZE", "10000")),
                worker_count=int(os.getenv("WORKER_COUNT", "4")),
                poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "0.5")),
                request_interval_seconds=float(os.getenv("REQUEST_INTERVAL_SECONDS", "3")),
            ),
            schedule=ScheduleConfig(
                enable_pre1=os.getenv("ENABLE_PRE1", "false").lower() == "true",
                enable_final_monitor=os.getenv("ENABLE_FINAL_MONITOR", "true").lower() == "true",
                enable_d3_backfill=os.getenv("ENABLE_D3_BACKFILL", "false").lower() == "true",
                pre5_minutes=int(os.getenv("PRE5_MINUTES", "5")),
                pre1_minutes=int(os.getenv("PRE1_MINUTES", "1")),
                special_post_close_minutes=int(os.getenv("SPECIAL_POST_CLOSE_MINUTES", "60")),
                next_day_hour=int(os.getenv("NEXT_DAY_HOUR", "10")),
                d3_hour=int(os.getenv("D3_HOUR", "10")),
                extension_poll_seconds=int(os.getenv("EXTENSION_POLL_SECONDS", "60")),
                extension_max_minutes=int(os.getenv("EXTENSION_MAX_MINUTES", "30")),
            ),
            retry=RetryConfig(
                max_retries=int(os.getenv("MAX_RETRIES", "3")),
                base_delay_seconds=float(os.getenv("BASE_DELAY_SECONDS", "1")),
                max_delay_seconds=float(os.getenv("MAX_DELAY_SECONDS", "30")),
            ),
            model_settings_path=Path(os.getenv("MODEL_SETTINGS_PATH", "model_settings.yaml")),
            enable_dynamic_orchestration=os.getenv("ENABLE_DYNAMIC_ORCHESTRATION", "true").lower() == "true",
        )
