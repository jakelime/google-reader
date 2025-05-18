import copy
import datetime
from typing import Any, Optional

import pymongo as pymg
from pymongo import MongoClient, cursor
from pymongo.errors import ConfigurationError, ConnectionFailure
from pymongo.results import InsertOneResult

from ggrd.custom_logger import getLogger
from ggrd.utils import get_utc_timestamp_now

lg = getLogger()


class MongoDBHelper:
    client: Optional[MongoClient] = None
    db: Optional[Any] = None
    collection: Optional[Any] = None

    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        database_name: Optional[str] = "googlereader",
        collection_name: Optional[str] = "apple_gmail",
    ):
        self.mongo_uri = mongo_uri
        self.database_name = database_name
        self.collection_name = collection_name
        self.client = None
        self.db = None
        self.collection = None

    def connect_to_apple_gmail_collections(
        self,
        db: Any,
        collection_name: str,
        timeseries: dict = {
            "timeField": "timestamp",
            "metaField": "metadata",
            "granularity": "seconds",
        },
    ):
        if collection_name not in db.list_collection_names():
            collection = db[collection_name]
            lg.warning(f"creating {collection_name=}")
            db.create_collection(
                collection_name,
                timeseries=timeseries,
            )
        collection = db.get_collection(collection_name)
        lg.debug(f"connected to {collection_name=}")
        return collection

    def __enter__(self):
        if self.client is None:
            self.connect_by_default()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Closes the MongoDB connection.
        This method is called when exiting a 'with' statement, even if an exception occurred.

        Args:
            exc_type: The type of the exception (if any).
            exc_val: The exception instance (if any).
            exc_tb: The traceback object (if any).
        """
        if self.client:
            self.client.close()
            lg.debug("MongoDB connection closed.")

        # If an exception occurred within the 'with' block, exc_type will not be None.
        # Returning False (or None) will propagate the exception.
        # Returning True would suppress it. We want to propagate by default.
        if exc_type:
            print(
                f"Exception occurred within 'with' block: {exc_type.__name__}: {exc_val}"
            )
        return False  # Propagate exceptions

    def connect_by_default(self):
        try:
            if not all([self.mongo_uri, self.database_name, self.collection_name]):
                raise ValueError(
                    "mongo_uri, database_name, and collection_name cannot be empty."
                )
            self.client = MongoClient(self.mongo_uri)
            # The ismaster command is cheap and does not require auth.
            self.client.admin.command("ismaster")  # Verifies connection
            self.db = self.client[self.database_name]  # type: ignore
            self.collection = self.connect_to_apple_gmail_collections(
                db=self.db,
                collection_name=self.collection_name,  # type: ignore
            )
            lg.info("successfully connected to MongoDB.")
            lg.info("connection parameters:")
            lg.info(f"connected to {self.mongo_uri=}")
            lg.info(f"connected to {self.database_name=}")
            lg.info(f"connected to {self.collection_name=}")
            return self
        except ConnectionFailure as e:
            lg.error(f"Connection failed: {e}")
            # Reraise to ensure __exit__ is called and to inform the caller
            raise ConnectionFailure(
                f"Could not connect to MongoDB at {self.mongo_uri}: {e}"
            )
        except ConfigurationError as e:
            lg.error(f"Configuration error: {e}")
            raise ConfigurationError(f"MongoDB URI or configuration is invalid: {e}")
        except Exception as e:  # Catch any other potential exceptions during connection
            lg.error(f"An unexpected error occurred during connection: {e}")
            raise

    def save_doc_to_timeseries(
        self,
        metadata: dict[Any, Any],
        data_in: dict[Any, Any],
        timestamp: str | datetime.datetime | None = None,
    ) -> InsertOneResult | None:
        if self.collection is None:
            lg.error(
                "Error: Collection is not initialized. Ensure connection was successful."
            )
            return None
        data = copy.deepcopy(data_in)
        match timestamp:
            case datetime.datetime():
                dt_object = timestamp
            case str():
                dt_object = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S%z")
            case _:
                dt_object = get_utc_timestamp_now()
                lg.warning(
                    "no timestamp found from gmail received date, using current time"
                )
        data.update(
            {
                "timestamp": dt_object,
                "metadata": metadata,
            }
        )
        result = self.collection.insert_one(data)
        return result

    def get_all_documents(self) -> list:
        if self.collection is None:
            lg.error("collection is not initialized.")
            return []
        query = {}
        documents = self.collection.find(query)
        return list(documents)
