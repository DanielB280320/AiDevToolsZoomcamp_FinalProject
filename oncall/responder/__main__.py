"""Run the responder: `python -m responder` (host/port from ONCALL_HOST / ONCALL_PORT)."""

import os

import uvicorn

from responder.app import create_app


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("ONCALL_HOST", "127.0.0.1"),
        port=int(os.environ.get("ONCALL_PORT", "8099")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
