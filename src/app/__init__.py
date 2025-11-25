import os

# Load environment variables from the .env file at project root.
# This makes variables available via os.environ before any other imports or configuration.
# If the .env file does not exist, load_dotenv does nothing and no error is raised.
# Latter in the application config.py, settings will be read from os.environ as needed.
from dotenv import load_dotenv

from .core.logger import setup_logging

env_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".env")
load_dotenv(env_path, encoding="utf-8")
setup_logging()
