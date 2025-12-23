import os

from dotenv import load_dotenv

from .core.logger import setup_logging

env_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".env")
load_dotenv(env_path, encoding="utf-8")
setup_logging()
