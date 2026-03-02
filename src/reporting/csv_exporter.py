from __future__ import annotations

import csv
from pathlib import Path

from src.reporting.report_service import DailyReport


class CsvExporter:
    def __init__(self, output_dir: Path) -> None:
        # 报表导出目录。
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_daily_report(self, report: DailyReport, file_name: str | None = None) -> str:
        # 导出 CSV，并附加窗口与质量摘要字段。
        name = file_name or f"daily-report-{report.window_start.strftime('%Y%m%d')}.csv"
        path = self.output_dir / name

        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "site",
                    "session_id",
                    "category",
                    "lot_count",
                    "avg_price",
                    "min_price",
                    "max_price",
                    "avg_confidence",
                    "window_start",
                    "window_end",
                    "quality_avg_confidence",
                    "quality_low_conf_count",
                    "quality_total_count",
                ]
            )

            for row in report.rows:
                writer.writerow(
                    [
                        row.site,
                        row.session_id,
                        row.category,
                        row.lot_count,
                        row.avg_price,
                        row.min_price,
                        row.max_price,
                        row.avg_confidence,
                        report.window_start.isoformat(),
                        report.window_end.isoformat(),
                        report.quality_summary.get("avg_confidence", 0),
                        report.quality_summary.get("low_conf_count", 0),
                        report.quality_summary.get("total_count", 0),
                    ]
                )

        return str(path)
