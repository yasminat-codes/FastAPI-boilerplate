# Setup logging before anything else so that all modules have logging configured at import time
# except for .config.settings as it is imported in logger.py
from .core.logger import setup_logging

setup_logging()
