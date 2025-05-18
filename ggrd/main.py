import dataclasses

import pandas as pd

from ggrd import utils
from ggrd.configs.config import config
from ggrd.custom_logger import getLogger
from ggrd.db import MongoDBHelper
from ggrd.reader import Reader
from ggrd.gmail import AppleEmailClient

lg = getLogger()
# pd.set_option("display.max_columns", None)
# pd.set_option("display.max_rows", None)


def write_from_csv():
    df = pd.read_csv("output.csv", index_col=0)
    if config.MONGO_CONNECTION_STRING is None:
        raise ValueError(
            "MongoDB connection string is not set. Please check your environment variables."
        )

    with MongoDBHelper(config.MONGO_CONNECTION_STRING) as mgdb:
        for i, row in df.iterrows():
            data = {
                "sender": row["sender"],
                "subject": row["subject"],
                "rcv_date": row["rcv_date"],
                "apple_account": row["apple_account"],
                "invoice_date": row["invoice_date"],
                "sequence_no": row["sequence_no"],
                "billed_to": row["billed_to"],
                "order_id": row["order_id"],
                "document_no": row["document_no"],
                "price": row["price"],
                "item": row["item"],
            }
            meta = {
                "email_type": "apple_invoices",
                "apple_account": row["apple_account"],
            }
            unique_data = {
                "email_rcv_date": data["rcv_date"],
                "account": data["apple_account"],
                "invoice_date": data["invoice_date"],
                "order_id": data["order_id"],
            }
            data.update(
                {
                    "unique_hash": utils.create_dict_hash(unique_data),
                }
            )

            result = mgdb.save_doc_to_timeseries(metadata=meta, data_in=data)
            if result is not None:
                lg.info(
                    f"email#{i} (rcv_date={data['rcv_date']})saved to MongoDB (oid={result.inserted_id})"
                )
            else:
                lg.warning(
                    f"email#{i} failed to save to MongoDB, check the connection and data."
                )

    # TODO:
    # 1. parse refund cost -S$5.98 (MNY3W7327B and MNY3W7327B-1)
    # 2. parse format change (MM611014M2) query `from:(no_reply@email.apple.com) before:2024/8/1 `


def reader():
    with MongoDBHelper(config.MONGO_CONNECTION_STRING) as mgdb:
        # Get all documents from the collection
        documents = mgdb.get_all_documents()
        if documents is None:
            lg.error("No documents found or connection failed.")
            return

        df = Reader().read_documents_to_dataframe(mongo_documents=documents)  # type: ignore
        df.to_csv("output-readback.csv")
        print(df)

        # TODO: see the output
        # now, prevent duplicate data from being inserted into MongoDB


def extract_from_gmail():
    ap = AppleEmailClient()
    ap.run(debug_email_limit=10)
    datalist = []
    for em in ap.emails:
        data = {}
        data["sender"] = em.sender
        data["subject"] = em.subject
        data["rcv_date"] = em.rcv_date
        data.update(em.data)
        datalist.append(data)
    df = pd.DataFrame(datalist)
    df.to_csv("output1.csv")
    print(df)


if __name__ == "__main__":
    extract_from_gmail()
