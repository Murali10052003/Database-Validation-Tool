"""Convenience launcher for the web UI (``migration-validator-web``)."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.getenv("MV_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("MV_WEB_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
