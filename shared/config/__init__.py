# shared.config package
from shared.config.settings import Settings  # noqa: F401

settings = Settings()  # singleton

__all__ = ['Settings', 'settings']
