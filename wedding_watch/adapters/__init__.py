"""빈자리 조회 어댑터."""

from __future__ import annotations

from ..config import Config
from .base import Adapter, FetchError, LoginRequired

__all__ = ["Adapter", "FetchError", "LoginRequired", "build_adapter"]


def build_adapter(config: Config) -> Adapter:
    if config.source.mode == "api":
        from .api import ApiAdapter

        return ApiAdapter(
            config.source, config.target.hall_code, timeout=config.poll.timeout_seconds
        )
    from .browser import BrowserAdapter

    return BrowserAdapter(
        config.source, config.target.hall_code, timeout=config.poll.timeout_seconds
    )
