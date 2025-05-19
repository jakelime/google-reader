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
        if not documents:
            lg.error("No documents found or connection failed.")
            return

        df = Reader().read_documents_to_dataframe(mongo_documents=documents)  # type: ignore
        df.to_csv("output-readback.csv")
        print(df)


def extract_from_gmail(limit: int = 20):
    # TODO:
    # Now, we are able to retreive emails from Gmail, then insert them to MongoDB
    # Next,
    # 1. In AppleEmailClient.run(), we need to query based on the last date range
    # 2. In AppleEmailClient.run(), we need to use a while loop to retreive all emails
    # 3. Parse the email content to get the invoice details
    # 4. Save the parsed data to MongoDB Parsed collection
    ap = AppleEmailClient()
    ap.run(debug_email_limit=limit)
    for email in ap.emails:
        data = email.data
        metadata = email.metadata
        timestamp = metadata["rcv_date"]
        email_record_hash = utils.hash_metadata(metadata)
        metadata["email_record_hash"] = email_record_hash
        inserted_result = None

        # Gets email record from MongoDB, if not found, save to timeseries collection
        with MongoDBHelper(
            config.MONGO_CONNECTION_STRING,
            database_name="googlereader",
            collection_name="apple_invoices_emails_raw",
        ) as mgdb:
            # Check if the document already exists in the collection
            doc = mgdb.get_email_by_hash(email_record_hash=email_record_hash)
            if doc is None:
                # If it doesn't exist, save the new document
                inserted_result = mgdb.save_doc_to_timeseries(
                    metadata=metadata,
                    data_in=data,
                    timestamp=timestamp,
                )
                lg.info(f"inserted new record: {inserted_result=}")
                doc = mgdb.get_email_by_hash(email_record_hash=email_record_hash)

        # Writes a record of the transaction saved to timeseries collection
        with MongoDBHelper(
            config.MONGO_CONNECTION_STRING,
            database_name="googlereader",
            collection_name="gmail_transactions",
        ) as mgdb:
            if inserted_result is not None:
                # If it doesn't exist, save the new document
                inserted_transaction_result = mgdb.save_doc_to_timeseries(
                    metadata={"email_record_hash": email_record_hash},
                    data_in={
                        "sender": metadata["sender"],
                        "subject": metadata["subject"],
                        "email_rcv_date": metadata["rcv_date"],
                    },
                    timestamp=utils.get_utc_timestamp_now(),
                )
                lg.info(f"recorded transaction: {inserted_transaction_result=}")


if __name__ == "__main__":
    extract_from_gmail()
