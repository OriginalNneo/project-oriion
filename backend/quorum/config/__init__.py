"""Configuration package — 12-factor settings read from the environment."""

from quorum.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
