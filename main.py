from __future__ import annotations

import argparse

from src.app import build_app


def parse_args() -> argparse.Namespace:
    # 运行参数：入口 URL 与发现轮询间隔。
    parser = argparse.ArgumentParser(description="HX Auction crawler")
    parser.add_argument("--discovery-url", required=True, help="专场发现入口 URL")
    parser.add_argument("--interval", type=int, default=43200, help="发现轮询间隔（秒），默认 12 小时")
    return parser.parse_args()


def main() -> None:
    # 组装应用并启动主循环。
    args = parse_args()
    app = build_app()
    app.run_forever(discovery_url=args.discovery_url, discovery_interval_seconds=args.interval)


if __name__ == "__main__":
    main()
