import os
from typing import Optional


class Config:
    MONGO_HOST: str = os.getenv("MONGO_HOST", "localhost")
    MONGO_PORT: str = os.getenv("MONGO_PORT", "27017")
    MONGO_USERNAME: str = os.getenv("MONGO_USERNAME", "root")
    MONGO_PASSWORD: str = os.getenv("MONGO_PASSWORD", "root")
    MONGO_CONNECTION_STRING: Optional[str] = os.getenv("MONGO_CONNECTION_STRING", None)
    DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
    LOCAL_TZ = "Asia/Singapore"

    def __init__(self):
        self.init_databases()

    def init_databases(self):
        self.init_mongo_connection_string()

    def init_mongo_connection_string(self):
        if not self.MONGO_CONNECTION_STRING:
            self.MONGO_CONNECTION_STRING = f"mongodb://{self.MONGO_USERNAME}:{self.MONGO_PASSWORD}@{self.MONGO_HOST}:{self.MONGO_PORT}/"


config = Config()
