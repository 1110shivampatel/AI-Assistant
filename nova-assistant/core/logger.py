"""
Nova Assistant — Logging Setup
Configures structured logging with file and console output.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False


class ColoredFormatter(logging.Formatter):
    """Console formatter with color-coded log levels."""

    LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",     # Cyan
        logging.INFO: "\033[32m",      # Green
        logging.WARNING: "\033[33m",   # Yellow
        logging.ERROR: "\033[31m",     # Red
        logging.CRITICAL: "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(config: dict) -> logging.Logger:
    """
    Configure the Nova logging system.

    Args:
        config: Full settings dict (expects 'logging' key).

    Returns:
        Root 'nova' logger.
    """
    log_cfg = config.get("logging", {})
    level_str = log_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    log_file = log_cfg.get("file", "logs/nova.log")
    max_bytes = log_cfg.get("max_size_mb", 10) * 1024 * 1024
    backup_count = log_cfg.get("backup_count", 3)

    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Root nova logger
    logger = logging.getLogger("nova")
    logger.setLevel(level)
    logger.handlers.clear()

    # --- File handler (rotating) ---
    file_fmt = logging.Formatter(
        fmt="%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    # --- Console handler (colored) ---
    console_fmt = ColoredFormatter(
        fmt="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    logger.info("Nova logging initialized [level=%s, file=%s]", level_str, log_file)
    return logger
