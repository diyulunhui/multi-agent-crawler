from __future__ import annotations

from datetime import datetime
from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        # 本地对象存储根目录（可替换为 MinIO/S3 适配器）。
        self.root = root

    def save_html(
        self,
        site: str,
        snapshot_time: datetime,
        session_id: str,
        lot_id: str,
        snapshot_type: str,
        html: str,
    ) -> str:
        # 路径规范：/{site}/{date}/{session_id}/{lot_id}/{snapshot_type}.html
        date_str = snapshot_time.strftime("%Y-%m-%d")
        path = self.root / site / date_str / session_id / lot_id
        path.mkdir(parents=True, exist_ok=True)

        file_path = path / f"{snapshot_type}.html"
        file_path.write_text(html, encoding="utf-8")
        return str(file_path)
