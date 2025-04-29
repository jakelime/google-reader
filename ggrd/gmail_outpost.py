import base64
import dataclasses
import os
import tempfile
from typing import Optional

import pandas as pd

from ggrd.auth import GoogleAuthManager
from ggrd.common_vars import APP_NAME
from ggrd.utils import CustomLogger

lg = CustomLogger(APP_NAME).getLogger()

DEBUG_LIMIT = 1
@dataclasses.dataclass
class EmailContent:
    sender: str
    subject: str
    body_text: str
    df: Optional[pd.DataFrame] = None

    def __post_init__(self, preview_length: int = 50):
        self.body_preview = (
            self.body_text
            if len(self.body_text) < preview_length
            else self.body_text[:preview_length]
        )


class EmailClient:
    def __init__(self):
        self.emails = []
        self.gga = GoogleAuthManager()
        self.service = self.gga.get_gmail_service()
        lg.info("gmail service loaded")

    def get_messages(
        self,
        user_id="me",
        sender_email: Optional[str] = None,
        after_date: Optional[str] = None,
        before_date: Optional[str] = None,
        subject: Optional[str] = None,
        limit: int = 0,
    ):
        try:
            # Build a query string to filter messages by sender
            query_parts = []
            if sender_email:
                query_parts.append(f"from:{sender_email}")
            if before_date:
                query_parts.append(f"before:{before_date}")
            if after_date:
                query_parts.append(f"after:{after_date}")
            if subject:
                query_parts.append(f"subject:{subject}")

            query = " ".join(query_parts)

            # Get a list of messages thatÏ match the query
            response = (
                self.service.users().messages().list(userId=user_id, q=query).execute()
            )
            messages = response.get("messages", [])

            # Print the subject and sender of each message
            for i, message in enumerate(messages, 1):
                e = self.get_message(message_id=message["id"], user_id=user_id)
                self.emails.append(e)
                if limit:
                    if i >= DEBUG_LIMIT:
                        break

        except Exception as error:
            lg.error(f"An error occurred: {error}", exc_info=True)

    def get_message(self, message_id, user_id="me") -> EmailContent:
        msg = (
            self.service.users().messages().get(userId=user_id, id=message_id).execute()
        )
        headers = msg["payload"]["headers"]
        subject = next(
            (header["value"] for header in headers if header["name"] == "Subject"),
            "No Subject",
        )
        sender = next(
            (header["value"] for header in headers if header["name"] == "From"),
            "No Sender",
        )
        lg.info(f"{msg=}")

        # Get the content of the email
        decoded_body = None
        # payload = msg["payload"]
        # [print(f"{k=}") for k,v in payload.items()]
        # parts = payload["parts"]
        # [print(f"{p.keys()}") for p in parts]
        # part =
        # body =
        # body = base64.urlsafe_b64decode(parts[1]["body"]["data"]).decode("utf-8")
        # print(f"{decoded_body=}")

        # if "parts" in payload:
        #     for part in payload["parts"]:
        #         if part["mimeType"] == "text/plain":
        #             body = part["body"]["data"]
        #             decoded_body = base64.urlsafe_b64decode(body).decode("utf-8")
        #             # print(f"{decoded_body}")
        #             # raise NotImplementedError("Not implemented - email in text")
        #             break  # Stop after finding the first text/plain part
        # else:
        #     # If the email has no parts, assume it is plaintext
        #     body = payload["body"]["data"]
        #     decoded_body = base64.urlsafe_b64decode(body).decode("utf-8")

        # body = decoded_body if decoded_body is not None else "No Body"
        # raise Exception("STOP HERE")

        return EmailContent(sender=sender, subject=subject, body_text=body)

    def run(self, before_date: Optional[str] = None, after_date: Optional[str] = None):
        # Get and print the messages in the user's inbox
        self.get_messages(before_date=before_date, after_date=after_date)

    def logout(self):
        os.remove(self.service.token)
        lg.info("logout successful")


class OutpostEmailClient(EmailClient):
    def __init__(self):
        super().__init__()

    def run(self, after_date: Optional[str] = None) -> pd.DataFrame:
        # Get and print the messages in the user's inbox
        self.get_messages(
            sender_email="no-reply@outpostclimbing.rezeve.com",
            after_date=after_date,
            subject="Booking confirmed:",
            limit=0,
        )
        df = self.consolidate_all_emails()
        return df

    def print_emails(self) -> None:
        for email in self.emails:
            print(email.df)

    def parse_html(self, html_str: str) -> pd.DataFrame:
        dfs = [None]
        with tempfile.NamedTemporaryFile(delete=True) as fp:
            with open(fp.name, "w") as fwriter:
                fwriter.write(html_str)
            dfs = pd.read_html(fp)  # type: ignore
        for df in dfs:
            dff = df[df[0].isin(self.kws)]
            if len(dff) < len(self.kws):
                continue
            else:
                df = dff.copy()
                df[0] = df[0].replace(self.kws)
                df.set_index(0, inplace=True)
                df = df.T
                df["datetime"] = pd.to_datetime(
                    df["datetime"], format="%d %b %Y @ %H:%M %p", errors="raise"
                )
                return df
        return pd.DataFrame()

    def get_message(self, message_id, user_id="me") -> EmailContent:
        e = super().get_message(message_id, user_id)
        df = self.parse_html(e.body_text)
        return EmailContent(
            sender=e.sender, subject=e.subject, body_text=e.body_text, df=df
        )

    def consolidate_all_emails(self) -> pd.DataFrame:
        df = pd.concat([email.df for email in self.emails])
        df.sort_values(by="datetime", inplace=True, ascending=True)
        df.reset_index(drop=True, inplace=True)
        df = df[self.kws.values()]
        return df


class AppleEmailClient(EmailClient):
    def __init__(self):
        super().__init__()

    def run(self, after_date: Optional[str] = None) -> pd.DataFrame:
        # Get and print the messages in the user's inbox
        self.get_messages(
            sender_email="no_reply@email.apple.com",
            after_date=after_date,
            subject='"Your invoice from Apple."',
            limit=DEBUG_LIMIT,
        )
        df = self.consolidate_all_emails()
        # return df

    def print_emails(self) -> None:
        for email in self.emails:
            print(email.df)

    def parse_html(self, html_str: str) -> pd.DataFrame:
        ## The HTML is too complicated and without any ID to extract
        dfs = [None]
        # with open("hello.html", "w") as fwriter:
        #     fwriter.write(html_str)
        # raise Exception("STOP HERE")
        with tempfile.NamedTemporaryFile(delete=True) as fp:
            with open(fp.name, "w") as fwriter:
                fwriter.write(html_str)
            dfs = pd.read_html(fp)  # type: ignore
            for i, df in enumerate(dfs):
                print(f"\n\n{i}:\n{df}")

            raise Exception("STOP HERE")
        # for df in dfs:
        #     dff = df[df[0].isin(self.kws)]
        #     if len(dff) < len(self.kws):
        #         continue
        #     else:
        #         df = dff.copy()
        #         df[0] = df[0].replace(self.kws)
        #         df.set_index(0, inplace=True)
        #         df = df.T
        #         df["datetime"] = pd.to_datetime(
        #             df["datetime"], format="%d %b %Y @ %H:%M %p", errors="raise"
        #         )
        #         return df
        # return pd.DataFrame()

    def get_message(self, message_id, user_id="me") -> EmailContent:
        # e = super().get_message(message_id, user_id)
        msg = (
            self.service.users().messages().get(userId=user_id, id=message_id).execute()
        )
        headers = msg["payload"]["headers"]
        subject = next(
            (header["value"] for header in headers if header["name"] == "Subject"),
            "No Subject",
        )
        sender = next(
            (header["value"] for header in headers if header["name"] == "From"),
            "No Sender",
        )

        # Get the content of the email
        decoded_body = None
        payload = msg["payload"]

        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    body = part["body"]["data"]
                    decoded_body = base64.urlsafe_b64decode(body).decode("utf-8")
                    break  # Stop after finding the first text/plain part
        else:
            raise Exception("No text/plain parts found in email payload")

        body = decoded_body if decoded_body is not None else "No Body"
        e = EmailContent(sender=sender, subject=subject, body_text=body)
        lg.info(f"{e=}")
        # df = self.parse_text(e.body_text)
        # print(df)
        # raise Exception("STOP HERE")
        # Figure out why "Email subject INVOICE and RECEIPT requires different functions"
        return EmailContent(
            sender=e.sender, subject=e.subject, body_text=e.body_text, df=df
        )

    def parse_text(self, txt: str) -> pd.DataFrame:
        APPLE_ID = "APPLE ID"
        ORDER_ID = "ORDER ID:"
        DOC_NO = "DOCUMENT NO.:"
        SEQ_NO = "SEQUENCE NO.:"
        INVOICE_DATE = "INVOICE DATE:"
        TOTAL = "TOTAL:"
        try:
            data = {}
            lines = txt.split("\n")
            iter_lines = iter(lines)
            line = next(iter_lines)
            while APPLE_ID not in line:
                line = next(iter_lines)
            data["email"] = next(iter_lines).strip()  # acetothestars@gmail.com
            while ORDER_ID not in line:
                line = next(iter_lines)
            data["order_id"] = line.split(ORDER_ID)[-1].strip()  # ORDER ID: MVS0KQVLGX
            while DOC_NO not in line:
                line = next(iter_lines)
            data["doc_no"] = line.split(DOC_NO)[
                -1
            ].strip()  # DOCUMENT NO.: 145796783741
            while SEQ_NO not in line:
                line = next(iter_lines)
            data["sequence_no"] = line.split(SEQ_NO)[
                -1
            ].strip()  # DOCUMENT NO.: 145796783741
            while INVOICE_DATE not in line:
                line = next(iter_lines)
            data["invoice_date"] = line.split(INVOICE_DATE)[
                -1
            ].strip()  # DOCUMENT NO.: 145796783741
            while TOTAL not in line:
                line = next(iter_lines)
            data["total_amount"] = line.split(TOTAL)[
                -1
            ].strip()  # DOCUMENT NO.: 145796783741
            while (
                "--------------------------------------------------------------------------------"
                not in line
            ):
                line = next(iter_lines)
            descr = []
            while "TOTAL" not in line:
                line = next(iter_lines)
                # if line
                if (
                    "--------------------------------------------------------------------------------"
                    in line
                ):
                    line = next(iter_lines)
                    continue
                if len(line) > 1:  # avoids the /r character
                    descr.append(line.strip())
            data["descr_text"] = "\n".join(descr)
            # df = pd.DataFrame(data, index=[0])
            # print(df)
            # return df
        except StopIteration:
            print(f"STOPPED ITERATION! {data=}\n{lines=}")
        finally:
            df = pd.DataFrame(data, index=[0])
            return df

    def consolidate_all_emails(self) -> pd.DataFrame:
        df = pd.concat([email.df for email in self.emails])
        # df.sort_values(by="datetime", inplace=True, ascending=True)
        # df.reset_index(drop=True, inplace=True)
        # df.to_csv("helloworld.csv")
        print(df)
        # df = df[self.kws.values()]
        return df


def main():
    # ec = EmailClient()
    ap = AppleEmailClient()
    ap.run()
    # ap.get_messages(
    # sender_email="no_reply@email.apple.com",
    # after_date=after_date,
    # subject="Booking confirmed:",
    # limit=1,
    # )
    # op = OutpostEmailClient()
    # df = op.run(after_date="2023-12-01")
    # print(df)


if __name__ == "__main__":
    main()
