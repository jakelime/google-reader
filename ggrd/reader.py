import dataclasses
import datetime
from typing import Any

import pandas as pd

from ggrd.configs.config import config


@dataclasses.dataclass
class DataStructure:
    doc_id: str
    doc_timestamp: datetime.datetime
    docmeta_account: str
    docmeta_email_type: str

    sender: str
    subject: str
    apple_account: str
    invoice_date: str
    sequence_no: str
    billed_to: str
    order_id: str
    document_no: str
    price: float
    item: str
    unique_hash: str


class Reader:
    def __init__(self):
        self.data_list: list[DataStructure] = []

    def read_documents_to_dataframe(
        self, mongo_documents: list[dict[str, Any]]
    ) -> pd.DataFrame:
        self.data_list = [self.read_document_to_datastructure(doc) for doc in mongo_documents]
        df = pd.DataFrame([dataclasses.asdict(data) for data in self.data_list])
        df["doc_timestamp"] = pd.to_datetime(df["doc_timestamp"], unit="s")
        df["rcv_date"] = pd.to_datetime(df["doc_timestamp"], unit="s")
        df["rcv_date"] = (
            df["rcv_date"].dt.tz_localize("UTC").dt.tz_convert(config.LOCAL_TZ)
        )
        return df

    def read_document_to_datastructure(self, doc: dict[str, Any]) -> DataStructure:
        data = DataStructure(
            doc_id=doc["_id"],
            doc_timestamp=doc["timestamp"],
            docmeta_account=doc["metadata"]["apple_account"],
            docmeta_email_type=doc["metadata"]["email_type"],
            sender=doc["sender"],
            subject=doc["subject"],
            apple_account=doc["apple_account"],
            invoice_date=doc["invoice_date"],
            sequence_no=doc["sequence_no"],
            billed_to=doc["billed_to"],
            order_id=doc["order_id"],
            document_no=doc["document_no"],
            price=doc["price"],
            item=doc["item"],
            unique_hash=doc["unique_hash"],
        )
        return data
