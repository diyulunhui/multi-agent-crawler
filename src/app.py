from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from src.classification.lot_classifier_agent import LotClassifierAgent
from src.config.settings import AppConfig
from src.domain.events import EventType, Task, TaskPriority
from src.orchestration.dynamic_skill_orchestrator import DispatchTarget, DynamicSkillOrchestrator
from src.queue.multi_task_queue import MultiTaskQueue
from src.scheduler.recovery_service import RecoveryService
from src.scheduler.task_scheduler import TaskScheduler
from src.scraping.adapter import ScraplingAdapter
from src.services.result_service import ResultService
from src.services.snapshot_service import SnapshotService
from src.storage.db import Database
from src.storage.object_store import LocalObjectStore
from src.storage.repositories.lot_classification_repo import LotClassificationRepository
from src.storage.repositories.lot_detail_repo import LotDetailRepository
from src.storage.repositories.lot_repo import LotRepository
from src.storage.repositories.lot_structured_repo import LotStructuredRepository
from src.storage.repositories.review_queue_repo import ReviewQueueRepository
from src.storage.repositories.session_repo import SessionRepository
from src.storage.repositories.task_repo import TaskRepository
from src.structuring.title_description_structured_agent import TitleDescriptionStructuredAgent
from src.workers.executors.discovery_executor import DiscoveryExecutor
from src.workers.executors.lot_executor import LotDiscoveryExecutor
from src.workers.executors.snapshot_executor import SnapshotExecutor
from src.workers.monitor.extension_monitor import ExtensionMonitor
from src.workers.pool import WorkerPool
from src.workers.retry_policy import ExponentialBackoffRetryPolicy


class AuctionCrawlerApp:
    def __init__(self, config: AppConfig) -> None:
        # 统一在应用层完成依赖装配。
        self.config = config
        self.db = Database(config)
        self.task_repo = TaskRepository(self.db)
        self.session_repo = SessionRepository(self.db)
        self.lot_repo = LotRepository(self.db)
        self.lot_detail_repo = LotDetailRepository(self.db)
        self.lot_classification_repo = LotClassificationRepository(self.db)
        self.lot_structured_repo = LotStructuredRepository(self.db)
        self.review_queue_repo = ReviewQueueRepository(self.db)
        self.lot_classifier_agent = LotClassifierAgent()
        self.title_desc_structured_agent = TitleDescriptionStructuredAgent(
            # 结构化默认走 LLM 主流程；动态编排开关不再影响该链路。
            enable_llm=True,
            settings_path=config.model_settings_path,
            enable_react=True,
            react_max_steps=3,
        )
        self.dynamic_orchestrator = DynamicSkillOrchestrator(config)

        self.queue = MultiTaskQueue(
            max_size=config.queue.max_size,
            poll_interval_seconds=config.queue.poll_interval_seconds,
        )
        self.scheduler = TaskScheduler(config, self.task_repo, self.queue)

        self.adapter = ScraplingAdapter(
            min_fetch_interval_seconds=config.queue.request_interval_seconds
        )
        self.object_store = LocalObjectStore(config.storage_root)
        self.snapshot_service = SnapshotService(config, self.db, self.object_store)
        self.result_service = ResultService(self.db)
        self.monitor = ExtensionMonitor(
            adapter=self.adapter,
            poll_seconds=config.schedule.extension_poll_seconds,
            max_minutes=config.schedule.extension_max_minutes,
        )

        self.discovery_executor = DiscoveryExecutor(config, self.adapter, self.session_repo, self.scheduler)
        self.lot_executor = LotDiscoveryExecutor(
            config,
            self.adapter,
            self.lot_repo,
            self.lot_detail_repo,
            self.lot_classification_repo,
            self.lot_classifier_agent,
            self.lot_structured_repo,
            self.review_queue_repo,
            self.title_desc_structured_agent,
            self.scheduler,
        )
        self.snapshot_executor = SnapshotExecutor(
            config,
            self.adapter,
            self.monitor,
            self.snapshot_service,
            self.result_service,
            reschedule_final_monitor=self._reschedule_final_monitor,
        )

        self.retry_policy = ExponentialBackoffRetryPolicy(
            max_retries=config.retry.max_retries,
            base_delay_seconds=config.retry.base_delay_seconds,
            max_delay_seconds=config.retry.max_delay_seconds,
        )
        self.recovery_service = RecoveryService(self.task_repo, self.queue, self.retry_policy)

        main_event_types = {
            EventType.DISCOVER_SESSIONS,
            EventType.DISCOVER_LOTS,
            EventType.SNAPSHOT_PRE5,
            EventType.SNAPSHOT_PRE1,
            EventType.SNAPSHOT_FINAL_MONITOR,
            EventType.SESSION_FINAL_SCRAPE,
        }
        # 专用结构化 worker：与抓取主链路解耦，避免结构化任务占满主线程池。
        self.structure_worker_pool = WorkerPool(
            config=config,
            queue=self.queue,
            task_repo=self.task_repo,
            dispatcher=self.dispatch,
            retry_policy=self.retry_policy,
            allowed_event_types={EventType.STRUCTURE_LOT},
            worker_name_prefix="worker-structure",
        )
        self.main_worker_pool = WorkerPool(
            config=config,
            queue=self.queue,
            task_repo=self.task_repo,
            dispatcher=self.dispatch,
            retry_policy=self.retry_policy,
            allowed_event_types=main_event_types,
            worker_name_prefix="worker-main",
        )
        # 兼容旧代码引用。
        self.worker_pool = self.main_worker_pool
        self._running = False

    def bootstrap(self) -> None:
        # 初始化表结构，回收未完成任务，并触发首次发现任务。
        self.db.init_schema()
        # 恢复上限与队列容量对齐，避免重启后仅回收部分任务导致“看起来很慢”。
        self.recovery_service.recover(limit=self.config.queue.max_size)

    def start(self) -> None:
        if self._running:
            return
        self.bootstrap()
        main_worker_count = max(1, self.config.queue.worker_count - 1)
        self.main_worker_pool.start(worker_count=main_worker_count)
        self.structure_worker_pool.start(worker_count=1)
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self.main_worker_pool.stop(graceful=True)
        self.structure_worker_pool.stop(graceful=True)
        self._running = False

    def dispatch(self, task: Task):
        # 动态编排器优先选择 skill 路由，失败时自动回退静态规则。
        target = self.dynamic_orchestrator.select_dispatch_target(task)
        if target == DispatchTarget.DISCOVERY:
            return self.discovery_executor.execute(task)
        if target == DispatchTarget.LOT:
            return self.lot_executor.execute(task)
        if target == DispatchTarget.SNAPSHOT:
            return self.snapshot_executor.execute(task)
        raise ValueError(f"未支持的任务类型: {task.event_type}")

    def _reschedule_final_monitor(self, task: Task, run_at: datetime, payload_updates: dict[str, object]) -> None:
        # FINAL 未闭合时以新 task_id 延后重排，避免单任务长阻塞 worker。
        if task.event_type != EventType.SNAPSHOT_FINAL_MONITOR:
            return
        next_payload = dict(task.payload)
        next_payload.update(payload_updates)
        followup = Task(
            event_type=EventType.SNAPSHOT_FINAL_MONITOR,
            entity_id=task.entity_id,
            run_at=run_at.astimezone(timezone.utc),
            priority=TaskPriority.FINAL_MONITOR,
            payload=next_payload,
            max_retries=task.max_retries,
        )
        self.task_repo.upsert_task(followup)
        self.queue.put(followup)

    def run_forever(self, discovery_url: str, discovery_interval_seconds: int = 21600) -> None:
        # 主循环：周期派发 DISCOVER_SESSIONS。
        self.start()
        try:
            while True:
                now = datetime.now(timezone.utc)
                self.scheduler.schedule_discovery(now=now, entry_url=discovery_url)
                time.sleep(discovery_interval_seconds)
        except KeyboardInterrupt:
            self.stop()


def build_app() -> AuctionCrawlerApp:
    return AuctionCrawlerApp(AppConfig.from_env())
