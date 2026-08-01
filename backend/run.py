#!/usr/bin/env python3
"""CLI entry point: run the Agents-in-the-air server.

Usage:
    python run.py                  # dev mode (auto-reload)
    python run.py --prod           # production mode (2 workers, no reload)
    python run.py --host 0.0.0.0 --port 9000
"""
import argparse

import uvicorn

from app.config import get_settings


def main():
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Agents-in-the-air server")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--prod", action="store_true",
                        help="Production mode: 2 workers, no reload, no access log")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    if args.prod:
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            reload=False,
            access_log=False,
        )
    else:
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=True,
        )


if __name__ == "__main__":
    main()
