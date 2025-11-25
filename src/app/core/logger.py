import logging
import logging.config
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pythonjsonlogger.json import JsonFormatter


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


def log_directory() -> Path:
    """Ensure log directory exists and return the path."""
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_logging_config() -> dict[str, Any]:
    """Get logging configuration."""

    # We read logging settings from environment variables instead of settings in config.py
    # to ensure logging is configured as early as possible, before settings are instantiated.
    # In this way we can also capture any logs during settings validation.
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_to_file = os.environ.get("LOG_TO_FILE", "False").lower() == "true"
    log_format_as_json = os.environ.get("LOG_FORMAT_AS_JSON", "False").lower() == "true"

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "colored_text": {
                "()": ColoredFormatter,
                "format": "%(asctime)s- %(levelname)s - %(name)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "plain_text": {
                "format": "%(asctime)s- %(levelname)s - %(name)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()": JsonFormatter,
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "stream": "ext://sys.stdout",
                "formatter": "colored_text",
            },
        },
        "root": {"level": log_level, "handlers": ["console"]},
        "loggers": {
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,  # Don't propagate to root logger to avoid double logging
            },
            "uvicorn.error": {"level": "INFO"},
            "sqlalchemy.engine": {"level": "WARNING"},  # Hide SQL queries unless warning/error
            "sqlalchemy.pool": {"level": "WARNING"},
            "httpx": {"level": "WARNING"},  # External HTTP client logs
            "httpcore": {"level": "WARNING"},
        },
    }

    if log_to_file:
        # Create file handler only when needed
        log_dir = log_directory()
        # Keeping filename timestamp granularity to minutes to avoid too
        # many log files during development and reloding. Keeping it human
        # readable for easier debugging using 3 letter month, in AM/PM format
        # and without the year. It has to be in UTC as it runs in containers.
        timestamp = datetime.now(UTC).strftime("%d-%b_%I-%M%p_UTC")
        log_file = log_dir / f"web_{timestamp}.log"

        config["handlers"]["file"] = {  # type: ignore[index]
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_level,
            "filename": str(log_file),
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "formatter": "file",
        }
        config["root"]["handlers"].append("file")  # type: ignore[index]
        config["loggers"]["uvicorn.access"]["handlers"].append("file")  # type: ignore[index]
        if log_format_as_json:
            config["handlers"]["file"]["formatter"] = "json"  # type: ignore[index]
        else:
            config["handlers"]["file"]["formatter"] = "plain_text"  # type: ignore[index]

    if log_format_as_json:
        config["handlers"]["console"]["formatter"] = "json"  # type: ignore[index]

    return config


def setup_logging() -> None:
    """Setup logging configuration based on environment."""
    config = get_logging_config()
    logging.config.dictConfig(config)

    # Log startup information
    logger = logging.getLogger(__name__)
    logger.info(f"Log level set to {config['root']['level']}")
    if config["handlers"]["console"]["formatter"] == "json":
        logger.info("Logs will be written in JSON format")
    if "console" in config["root"]["handlers"]:
        logger.info("Logs will be written to the console")
    if "file" in config["root"]["handlers"]:
        logger.info(f"Logs will be written to the file {config['handlers']['file']['filename']}")
