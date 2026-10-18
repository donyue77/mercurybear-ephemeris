"""Run the service: `mercurybear-ephemeris` (defaults to 127.0.0.1:8100; CALC_HOST / CALC_PORT override)."""
import os

import uvicorn


def main() -> None:
    uvicorn.run("mercurybear_ephemeris.app:app", host=os.environ.get("CALC_HOST", "127.0.0.1"),
                port=int(os.environ.get("CALC_PORT", "8100")), log_level=os.environ.get("CALC_LOG_LEVEL", "warning"),
                access_log=False)


if __name__ == "__main__":
    main()
