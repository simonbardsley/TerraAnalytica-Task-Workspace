"""Logging strategy (M0). All TWM loggers live under 'ta.twm'."""
import logging

ROOT = "ta.twm"


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{name}" if name else ROOT)


def enable_debug(enabled: bool = True) -> None:
    """Toggle debug mode for every TWM logger."""
    root = logging.getLogger(ROOT)
    root.setLevel(logging.DEBUG if enabled else logging.INFO)
    if enabled and not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        root.addHandler(h)
