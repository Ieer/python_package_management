"""Compatibility entry point for the Dash application in ``src/offline_package``."""

from __future__ import annotations

from src.offline_package.dashboard import *  # noqa: F403
from src.offline_package.dashboard import main


if __name__ == "__main__":
    main()
