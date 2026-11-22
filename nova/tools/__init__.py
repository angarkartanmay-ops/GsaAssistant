"""Importing this package registers every tool in REGISTRY."""
from . import chats, core, dashboard, gmail, system, web  # noqa: F401
from .registry import REGISTRY  # noqa: F401
