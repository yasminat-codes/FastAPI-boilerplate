import logging
import logging.config
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from .config import EnvironmentOption, settings


class ColoredFormatter(logging.Formatter):
    """Colored formatter for development console output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # Create a copy of the record to avoid modifying the original
        record_copy = logging.makeLogRecord(record.__dict__)
        log_color = self.COLORS.get(record_copy.levelname, "")
        record_copy.levelname = f"{log_color}{record_copy.levelname}{self.RESET}"
        return super().format(record_copy)


def get_log_level() -> int:
    """Get log level from environment with validation."""
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()

    level = logging.getLevelNamesMapping().get(log_level_name)
    if level is None:
        raise ValueError(f"Invalid log level '{log_level_name}'")

    return level


def log_directory() -> Path:
    """Ensure log directory exists and return the path."""
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_logging_config() -> dict[str, Any]:
    """Get logging configuration based on environment."""
    log_level = get_log_level()

    # Base configuration
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "development": {
                "()": ColoredFormatter,
                "format": "%(asctime)s- %(levelname)s - %(name)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "file": {
                "format": "%(asctime)s- %(levelname)s - %(name)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()": JsonFormatter,
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d",
            },
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "level": log_level, "stream": "ext://sys.stdout"},
        },
        "root": {"level": log_level, "handlers": []},
        "loggers": {
            "uvicorn.access": {
                "level": "INFO",
                "handlers": [],
                "propagate": False,  # Don't propagate to root logger to avoid double logging
            },
            "uvicorn.error": {"level": "INFO"},
            "sqlalchemy.engine": {"level": "WARNING"},  # Hide SQL queries unless warning/error
            "sqlalchemy.pool": {"level": "WARNING"},
            "httpx": {"level": "WARNING"},  # External HTTP client logs
            "httpcore": {"level": "WARNING"},
        },
    }

    # Environment-specific configuration
    if settings.ENVIRONMENT == EnvironmentOption.LOCAL:
        # Create file handler only when needed
        log_dir = log_directory()
        # Keeping filename timestamp granularity to minutes to avoid too
        # many log files during development and reloding. Keeping it human
        # readable for easier debugging using 3 letter month, in AM/PM format
        # and without the year. It has to be in UTC as it runs in containers.
        timestamp = datetime.now(UTC).strftime("%d-%b_%I-%M%p_UTC")
        log_file = log_dir / f"web_{timestamp}.log"

        config["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_level,
            "filename": str(log_file),
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "formatter": "file",
        }

        # Plain colored text + file logging
        config["handlers"]["console"]["formatter"] = "development"
        config["root"]["handlers"] = ["console", "file"]
        config["loggers"]["uvicorn.access"]["handlers"] = ["console", "file"]
    else:
        # As JSON messages to console
        config["handlers"]["console"]["formatter"] = "json"
        config["root"]["handlers"] = ["console"]
        config["loggers"]["uvicorn.access"]["handlers"] = ["console"]

    return config


def setup_logging() -> None:
    """Setup logging configuration based on environment."""
    config = get_logging_config()
    logging.config.dictConfig(config)

    # Log startup information
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured for {settings.ENVIRONMENT.value} environment")
    logger.info(f"Log level set to {logging.getLevelName(get_log_level())}")
    if "file" in config["root"]["handlers"]:
        logger.info(f"Logs will be written to the file {config['handlers']['file']['filename']}")
    if "console" in config["root"]["handlers"]:
        extra = ""
        if config["handlers"]["console"]["formatter"] == "json":
            extra = " in JSON format"
        logger.info(f"Logs will be written to the console{extra}")
