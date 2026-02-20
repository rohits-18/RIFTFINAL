import json
import threading
from functools import lru_cache

class ConfigError(Exception):
    pass

class DataProcessor:
    def __init__(self, config_file: str):
        self.config = self.load_config(config_file)
        self.data = []

    def load_config(self, filename: str) -> dict:
        with open(filename, "r") as f:
            config = json.load(f)
        if "multiplier" not in config:
            raise ConfigError("Missing multiplier in config")
        return config

    @lru_cache(maxsize=None)
    def compute(self, value: float) -> float:
        return value * self.config["multiplier"]
