"""Запуск приложения: python run.py (или uvicorn app.main:app)."""

from __future__ import annotations

import argparse
import webbrowser
from threading import Timer

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Winners — статистика спортивных ставок")
    parser.add_argument("--host", default="127.0.0.1", help="Адрес прослушивания")
    parser.add_argument("--port", type=int, default=8000, help="Порт")
    parser.add_argument("--reload", action="store_true", help="Автоперезапуск при изменениях")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать браузер")
    args = parser.parse_args()

    url = f"http://{'127.0.0.1' if args.host in {'0.0.0.0', '::'} else args.host}:{args.port}"
    if not args.no_browser and not args.reload:
        Timer(1.5, lambda: webbrowser.open(url)).start()

    print(f"Winners запускается: {url}")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
