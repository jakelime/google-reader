import base64
import dataclasses
import datetime
import email
import email.utils
import os
from typing import Optional

from ggrd.auth import GoogleAuthManager
from ggrd.custom_logger import getLogger
from ggrd.parsers import apple_invoice_parser as aip

lg = getLogger()


class NoEmailFound(Exception):
    """No email found exception."""


@dataclasses.dataclass
class EmailContent:
    sender: Optional[str] = None
    subject: Optional[str] = None
    rcv_date: Optional[datetime.datetime] = None
    body_txt: Optional[str] = None
    data: Optional[dict] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        preview_length = 50
        if self.body_txt:
            # Ensure body_txt is treated as a string for slicing
            body_str = str(self.body_txt) if self.body_txt is not None else ""
            self.body_preview = (
                body_str
                if len(body_str) < preview_length
                else body_str[:preview_length]
                + "..."  # Optional: Add ellipsis for clarity
            )
        else:
            self.body_preview = ""


@dataclasses.dataclass
class RawEmailContent:
    sender: Optional[str] = None
    subject: Optional[str] = None
    rcv_date: Optional[datetime.datetime] = None
    metadata: Optional[dict] = dataclasses.field(default_factory=dict)
    data: Optional[dict] = dataclasses.field(default_factory=dict)


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
        limit: int = 100,
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

            # Get a list of messages that match the query
            lg.info(f"query: {query}")
            response = (
                self.service.users()
                .messages()
                .list(userId=user_id, q=query, maxResults=limit)
                .execute()
            )
            messages = response.get("messages", [])
            if not messages:
                raise NoEmailFound("No emails found matching the criteria.")

            for i, message in enumerate(messages, 1):
                em = self.get_message(message_id=message["id"], user_id=user_id)
                self.emails.append(em)
                lg.info(f" >> get email #{i} - {em.rcv_date}")
                if limit:
                    if i >= limit:
                        break
            lg.info(f"retrieved {len(messages)} emails/messages.")
            return self.emails

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
        rcv_date = next(
            (header["value"] for header in headers if header["name"] == "Received"),
            "No Received",
        )
        try:
            date_string_part = rcv_date.split(";")[-1].strip()
            rcv_date = email.utils.parsedate_to_datetime(date_string_part)
        except Exception as e:
            lg.warning(f"date parsing failed: {e=}")
            rcv_date = None

        return EmailContent(
            sender=sender,
            subject=subject,
            rcv_date=rcv_date,
            # body_txt="helloworld",
            # data={"message": "something"},
        )

    def run(self, before_date: Optional[str] = None, after_date: Optional[str] = None):
        # Get and print the messages in the user's inbox
        self.get_messages(before_date=before_date, after_date=after_date)

    def logout(self):
        os.remove(self.service.token)
        lg.info("logout successful")


class AppleEmailClientWithParser(EmailClient):
    def __init__(self):
        super().__init__()

    def run(self, after_date: Optional[str] = None, debug_email_limit: int = 0):
        # Get and print the messages in the user's inbox
        self.get_messages(
            sender_email="no_reply@email.apple.com",
            after_date=after_date,
            subject='"Your invoice from Apple."',
            limit=debug_email_limit,
        )

    def parse_parts(self, parts):
        """Recursively parse message parts to find the body."""
        for part in parts:
            mime_type = part.get("mimeType")
            body = part.get("body")
            if mime_type == "text/plain" and body and "data" in body:
                # Found the plain text body
                return base64.urlsafe_b64decode(body["data"]).decode("utf-8")
            elif mime_type == "text/html" and body and "data" in body:
                # Found the HTML body - you might prefer this depending on your needs
                # If you want both, you'd store them and decide later
                return base64.urlsafe_b64decode(body["data"]).decode("utf-8")
            elif "parts" in part:
                # This part has nested parts, recurse into them
                nested_body = self.parse_parts(part["parts"])
                if nested_body:
                    return nested_body
        return None

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
        rcv_date = next(
            (header["value"] for header in headers if header["name"] == "Received"),
            "No Received",
        )
        try:
            date_string_part = rcv_date.split(";")[-1].strip()
            rcv_date = email.utils.parsedate_to_datetime(date_string_part)
        except Exception as e:
            lg.warning(f"date parsing failed: {e=}")
            rcv_date = None

        # Get the content of the email
        payload = msg["payload"]
        parts = payload.get("parts", None)

        if parts:
            res_parts = self.parse_parts(parts)
            res_parts = aip.clean_html_newline_chars(res_parts)
            data = aip.HtmlCleaner(res_parts).data

        return EmailContent(
            sender=sender, subject=subject, rcv_date=rcv_date, data=data
        )


class AppleEmailClient(EmailClient):
    def __init__(self):
        super().__init__()

    def run(self, after_date: Optional[str] = None, debug_email_limit: int = 0):
        # Get and print the messages in the user's inbox
        self.get_messages(
            sender_email="no_reply@email.apple.com",
            after_date=after_date,
            subject='"Your invoice from Apple."',
            limit=debug_email_limit,
        )

    def get_message(self, message_id, user_id="me") -> RawEmailContent:
        msg = (
            self.service.users().messages().get(userId=user_id, id=message_id).execute()
        )
        metadata = {}
        payload = msg["payload"]
        headers = payload["headers"]
        subject = next(
            (header["value"] for header in headers if header["name"] == "Subject"),
            "No Subject",
        )
        sender = next(
            (header["value"] for header in headers if header["name"] == "From"),
            "No Sender",
        )
        rcv_date = next(
            (header["value"] for header in headers if header["name"] == "Received"),
            "No Received",
        )

        try:
            date_string_part = rcv_date.split(";")[-1].strip()
            rcv_date = email.utils.parsedate_to_datetime(date_string_part)
        except Exception as e:
            lg.warning(f"date parsing failed: {e=}")
            rcv_date = None

        metadata["subject"] = subject
        metadata["sender"] = sender
        metadata["rcv_date"] = rcv_date

        # TODO: send raw to MongoDB is done
        # 1. parse, send to raw collection
        # 2. convert rcv_date to local timezone
        # 3. create unique hash identifier for datetime_sender_subject
        # 4. review save to MongoDB (avoid duplicate)

        return RawEmailContent(
            sender=sender,
            subject=subject,
            rcv_date=rcv_date,
            metadata=metadata,
            data=payload,
        )
