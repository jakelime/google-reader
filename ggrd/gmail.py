import base64
import copy
import dataclasses
import datetime
import email
import email.utils
import hashlib
import json
import os
import re
from typing import Any, Optional

import dotenv
import pandas as pd
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure, ConfigurationError

from ggrd.auth import GoogleAuthManager
from ggrd.custom_logger import getLogger

lg = getLogger()
# pd.set_option("display.max_columns", None)
# pd.set_option("display.max_rows", None)


dotenv.load_dotenv()


def get_utc_timestamp_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def create_dict_hash(data_dict: dict):
    """
    Creates a unique SHA-256 hash for a dictionary.

    Args:
      data_dict: The dictionary to hash.

    Returns:
      A hexadecimal string representing the SHA-256 hash.
    """
    if not isinstance(data_dict, dict):
        raise TypeError("Input must be a dictionary")

    serialized_data = json.dumps(data_dict, sort_keys=True, separators=(",", ":"))
    encoded_data = serialized_data.encode("utf-8")
    hasher = hashlib.sha256()
    hasher.update(encoded_data)
    unique_hash = hasher.hexdigest()
    return unique_hash


class Config:
    MONGO_HOST: str = os.getenv("MONGO_HOST", "localhost")
    MONGO_PORT: str = os.getenv("MONGO_PORT", "27017")
    MONGO_USERNAME: str = os.getenv("MONGO_USERNAME", "root")
    MONGO_PASSWORD: str = os.getenv("MONGO_PASSWORD", "root")
    MONGO_CONNECTION_STRING: Optional[str] = os.getenv("MONGO_CONNECTION_STRING", None)

    def __init__(self):
        self.init_databases()

    def init_databases(self):
        self.init_mongo_connection_string()

    def init_mongo_connection_string(self):
        if not self.MONGO_CONNECTION_STRING:
            self.MONGO_CONNECTION_STRING = f"mongodb://{self.MONGO_USERNAME}:{self.MONGO_PASSWORD}@{self.MONGO_HOST}:{self.MONGO_PORT}/"


class NoEmailFound(Exception):
    """No email found exception."""


def clean_html_newline_chars(html_content):
    """
    Removes extraneous \r\n characters from HTML content.

    Args:
      html_content: A string containing the HTML content with \r\n.

    Returns:
      A cleaned string with \r\n characters removed.
    """
    # Replace all occurrences of \r\n with an empty string
    cleaned_html = html_content.replace("\r\n", "")
    # You might also want to remove leading/trailing whitespace from lines
    # or collapse multiple spaces, but removing \r\n is the primary request.
    # For example, to remove leading/trailing whitespace from each line:
    cleaned_html = "\n".join([line.strip() for line in cleaned_html.splitlines()])
    return cleaned_html


class HtmlCleaner:
    def __init__(self, html_content: str):
        # Use 'html5lib' for potentially better handling of complex/malformed HTML
        soup = BeautifulSoup(html_content, "html5lib")
        self.data = {}  # Store data in an instance variable if needed outside init
        # Common pattern: Find label -> find parent -> find next sibling(s) containing data
        self.data["apple_account"] = self.find_generic_value(soup, "ACCOUNT")
        self.data["invoice_date"] = self.find_generic_value(soup, "INVOICE DATE")
        self.data["sequence_no"] = self.find_generic_value(soup, "SEQUENCE NO.")
        self.data["billed_to"] = self.find_multiline_value(soup, "BILLED TO")
        self.data["order_id"] = self.find_generic_value(
            soup, "ORDER ID", link_text=True
        )
        self.data["document_no"] = self.find_generic_value(soup, "DOCUMENT NO.")

        # --- Price extraction logic (seems okay, keep as is) ---
        total_label_td = soup.find("td", string=re.compile(r"\s*TOTAL\s*"))
        if total_label_td:
            # Find the TD containing the price, assuming it's a few siblings away
            price_td = None
            current_sibling = total_label_td
            for _ in range(3):  # Adjust range if needed based on HTML structure
                if current_sibling:
                    current_sibling = current_sibling.find_next_sibling("td")
                if current_sibling and self.get_cleaned_text(current_sibling):
                    # Check if sibling exists and has text
                    price_td = current_sibling
                    # Found a potential price TD
                    break

            if price_td:
                self.data["price"] = self.get_cleaned_text(price_td)
                # Optional: More specific regex for price format if needed
                price_match = re.search(
                    r"(S\$\s*[\d,]+\.\d{2})", self.data["price"] or ""
                )
                self.data["price"] = (
                    price_match.group(1)
                    if price_match
                    else self.get_cleaned_text(price_td)
                )

            else:
                # Ensure price is None if TD not found
                self.data["price"] = None

        else:
            # Fallback: find the last price-like span/td if TOTAL isn't found
            # Be cautious with this fallback, might grab unrelated prices
            price_elements = soup.find_all(string=re.compile(r"S\$\s*[\d,]+\.\d{2}"))
            if price_elements:
                # Find parent TD if the regex matched text inside another tag
                potential_price = self.get_cleaned_text(
                    price_elements[-1].find_parent("td") or price_elements[-1]
                )
                self.data["price"] = potential_price
            else:
                self.data["price"] = None

        # --- extract template of apple item in invoice ---
        item_cell = soup.find("td", class_="item-cell")
        item_parts = []
        if item_cell:
            title = item_cell.find("span", class_="title")
            artist = item_cell.find("span", class_="artist")
            item_type = item_cell.find("span", class_="type")
            device = item_cell.find("span", class_="device")

            if title:
                item_parts.append(self.get_cleaned_text(title))
            if artist:
                item_parts.append(self.get_cleaned_text(artist))
            if item_type:
                item_parts.append(self.get_cleaned_text(item_type))
            if device:
                item_parts.append(self.get_cleaned_text(device))

        self.data["item"] = (
            " ".join(part for part in item_parts if part) if item_parts else None
        )

    def get_cleaned_text(self, element):
        if element:
            # Get text, replace non-breaking space, strip whitespace, handle multiple spaces
            # Use get_text for robustness
            text = element.get_text(separator=" ", strip=True)
            text = text.replace("\xa0", " ")
            text = re.sub(r"\s+", " ", text).strip()  # Consolidate multiple spaces
            return text if text else None  # Return None if empty after cleaning
        return None

    def find_generic_value(
        self, soup, label_text, link_text=False, is_debug_target: bool = False
    ) -> Optional[str]:
        """
        Finds the text value associated with a label span, typically following a <br>.
        Handles cases where the value is plain text, inside a nested span, or inside a link.
        """

        if is_debug_target:
            lg.info(f"--- Debugging find_generic_value for: {label_text} ---")

        compiled_regex = re.compile(r"\s*" + re.escape(label_text) + r"\s*")
        if is_debug_target:
            lg.info(f"{compiled_regex=}")

        label_span = soup.find("span", string=compiled_regex)

        if not label_span:
            if is_debug_target:
                lg.info("  Label span NOT found.")
            # Fallback: Sometimes the label might be directly in the TD or other tag
            label_parent = soup.find(
                lambda tag: tag.name == "td"
                and re.search(
                    r"\s*" + re.escape(label_text.replace("\xa0", " ")) + r"\s*",
                    tag.get_text(separator=" ", strip=True),
                    re.IGNORECASE,
                )
            )
            if label_parent:
                label_span = label_parent  # Treat the parent as the starting point
                if is_debug_target:
                    lg.info(
                        f"  Found label text within parent TD (using TD as label_span): {label_parent.prettify()}"
                    )
            else:
                if is_debug_target:
                    lg.info("  Label parent TD NOT found either.")
                # Give up if label is truly not found
                return None

        if is_debug_target:
            lg.info(f"  Found label element: {label_span}")

        # Navigate siblings *from the label span*
        found_br = False
        sibling_counter = 0
        current_element = label_span

        while current_element:
            # Process next sibling *after* the current element
            sibling = current_element.next_sibling
            if sibling is None:
                # If no more siblings, try moving up to parent and check its siblings
                parent = current_element.find_parent()
                if parent and parent.name != "body":
                    # Don't go too high
                    current_element = parent
                    if is_debug_target:
                        lg.info(
                            f"  No more siblings for {current_element.name}, moving up to parent {parent.name} and checking its siblings."
                        )
                    # Restart loop to check parent's siblings
                    continue
                else:
                    if is_debug_target:
                        lg.info("  Reached end of siblings and parent traversal.")
                    # Exhausted search space
                    break

            current_element = sibling
            # Move to the next sibling for the next iteration
            sibling_counter += 1

            if is_debug_target:
                lg.info(f"\n  Processing sibling #{sibling_counter}:")
                lg.info(f"    Type: {type(sibling)}")
                lg.info(f"    Repr: {repr(sibling)}")
                lg.info(f"    found_br state: {found_br}")

            if isinstance(sibling, Tag) and sibling.name == "br":
                found_br = True
                if is_debug_target:
                    lg.info("    -> Matched <br>, setting found_br = True")
                continue

            # Look for the value *after* the <br> (or immediately if no <br> expected/found)
            # Allow finding value even if <br> wasn't explicitly found IF it's the immediate next useful element
            if found_br or sibling_counter <= 2:  # Check immediately or after <br>
                # 1. Handle specific link case (e.g., Order ID)
                if link_text and isinstance(sibling, Tag) and sibling.find("a"):
                    link = sibling.find("a")
                    if link:
                        cleaned_text = self.get_cleaned_text(link)
                        if cleaned_text:
                            if is_debug_target:
                                lg.info(
                                    f"    --> SUCCESS (Link): Returning '{cleaned_text}'"
                                )
                            return cleaned_text
                # 2. Handle nested tag case (e.g., Invoice Date in a span)
                elif isinstance(sibling, Tag) and sibling.name in [
                    "span",
                    "td",
                    "div",
                ]:  # Add other relevant tags if needed
                    # Check if the tag itself contains non-empty text
                    cleaned_text = self.get_cleaned_text(sibling)
                    if cleaned_text:
                        if is_debug_target:
                            lg.info(
                                f"    --> SUCCESS (Nested Tag {sibling.name}): Returning '{cleaned_text}'"
                            )
                        return cleaned_text
                    # Check if descendants contain the text
                    descendant_text = sibling.find(
                        string=lambda t: self.get_cleaned_text(t)
                    )
                    if descendant_text:
                        cleaned_text = self.get_cleaned_text(descendant_text)
                        if cleaned_text:
                            if is_debug_target:
                                lg.info(
                                    f"    --> SUCCESS (Nested Tag Descendant): Returning '{cleaned_text}'"
                                )
                            return cleaned_text

                # 3. Handle direct text node case (NavigableString)
                elif isinstance(sibling, NavigableString):
                    cleaned_text = self.get_cleaned_text(sibling)
                    if cleaned_text:
                        if is_debug_target:
                            lg.info(
                                f"    --> SUCCESS (NavigableString): Returning '{cleaned_text}'"
                            )
                        return cleaned_text

            if is_debug_target:
                lg.info("    -> Sibling did not yield value in this pass.")

        if is_debug_target:
            lg.info(
                f"--- End Debug {label_text}: Exited loop/traversal, returning fallback None ---"
            )
        return None

    def find_multiline_value(
        self, soup, label_text, is_debug_target: bool = False
    ) -> Optional[str]:
        """
        Finds multi-line text values associated with a label, typically separated by <br> tags within the same parent.
        Example: Billed To address.
        """
        if is_debug_target:
            lg.info(f"--- Debugging find_multiline_value for: {label_text} ---")

        label_span = soup.find(
            "span",
            string=lambda t: t
            and re.search(
                r"\s*" + re.escape(label_text.replace("\xa0", " ")) + r"\s*",
                t,
                re.IGNORECASE,
            ),
        )

        if not label_span:
            if is_debug_target:
                lg.info("  Label span NOT found.")
            # Add fallback similar to generic_value if needed
            return None

        parent_td = label_span.find_parent("td")
        if not parent_td:
            # Try finding parent div or other containers if TD fails
            parent_container = label_span.find_parent(["div", "p"])
            if not parent_container:
                if is_debug_target:
                    lg.info("  Parent TD or container NOT found.")
                return None
            parent_element = parent_container
            if is_debug_target:
                lg.info(f"  Found parent container: {parent_element.name}")
        else:
            parent_element = parent_td
            if is_debug_target:
                lg.info("  Found parent TD")

        if is_debug_target:
            lg.info(f"  Parent Element Content:\n{parent_element.prettify()}")

        lines = []
        found_label_or_br = (
            False  # Start collecting after the label OR the first <br> following it
        )

        for content in parent_element.contents:  # Iterate direct children of the parent
            if content == label_span:  # Skip the label itself
                found_label_or_br = True
                if is_debug_target:
                    lg.info("  Skipping label span itself.")
                continue
            # Sometimes the label is plain text, not a span
            if isinstance(content, NavigableString) and label_text in content:
                found_label_or_br = True
                if is_debug_target:
                    lg.info("  Skipping label text node itself.")
                continue

            if isinstance(content, Tag) and content.name == "br":
                found_label_or_br = True  # Mark that we are past the initial part
                if is_debug_target:
                    lg.info("  Found <br>")
                continue  # Don't add <br> itself

            if found_label_or_br:
                # Get cleaned text from NavigableStrings or Tags
                line = self.get_cleaned_text(content)
                if line:  # Only add non-empty lines
                    lines.append(line)
                    if is_debug_target:
                        lg.info(f"  Collected line: '{line}' from {type(content)}")
                elif is_debug_target:
                    lg.info(f"  Skipping empty/whitespace content: {repr(content)}")

        if lines:
            result = " ".join(lines).replace(",", " ")
            if is_debug_target:
                lg.info(f"  --> SUCCESS (Multi-line): Returning:\n{result}")
            return result
        else:
            if is_debug_target:
                lg.info("  --> No lines collected.")
            return None

    def print_extracted_data(self):
        # Print final extracted data
        lg.info("--- Extracted Data ---")
        for key, value in self.data.items():
            lg.info(f"{key}: {value}")
        lg.info("----------------------")


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

            # Get a list of messages that match the query
            lg.info(f"query: {query}")
            response = (
                self.service.users().messages().list(userId=user_id, q=query).execute()
            )
            messages = response.get("messages", [])
            if not messages:
                raise NoEmailFound("No emails found matching the criteria.")
            lg.info(f"retrieved {len(messages)} messages")

            for i, message in enumerate(messages, 1):
                em = self.get_message(message_id=message["id"], user_id=user_id)
                self.emails.append(em)
                lg.info(f"parsed email #{i} - {em.rcv_date}")
                if limit:
                    if i >= limit:
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
        # print(f"{headers=}")
        # [print(k) for k in headers]
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
            res_parts = clean_html_newline_chars(res_parts)
            data = HtmlCleaner(res_parts).data

        return EmailContent(
            sender=sender, subject=subject, rcv_date=rcv_date, data=data
        )


class MongoDBHelper:
    """
    A helper class for interacting with MongoDB, designed to be used as a context manager.
    """
    # TODO: Work on MongoDB helper class.
    # MongoDBHelper_old is working,
    # but we need a better one with __enter__ and __exit__ methods.

    def __init__(self, mongo_uri: str, database_name: str, collection_name: str):
        """
        Initializes the MongoHelper with connection details.

        Args:
            mongo_uri (str): The MongoDB connection URI (e.g., "mongodb://localhost:27017/").
            database_name (str): The name of the database to connect to.
            collection_name (str): The name of the collection to operate on.
        """
        if not all([mongo_uri, database_name, collection_name]):
            raise ValueError(
                "mongo_uri, database_name, and collection_name cannot be empty."
            )

        self.mongo_uri = mongo_uri
        self.database_name = database_name
        self.collection_name = collection_name
        self.client = None
        self.db = None
        self.collection = None

    def __enter__(self):
        """
        Establishes the MongoDB connection and returns the helper instance.
        This method is called when entering a 'with' statement.
        """
        try:
            self.client = MongoClient(self.mongo_uri)
            # The ismaster command is cheap and does not require auth.
            self.client.admin.command("ismaster")  # Verifies connection
            self.db = self.client[self.database_name]
            self.collection = self.db[self.collection_name]
            lg.info(
                f"Successfully connected to MongoDB: {self.mongo_uri}, DB: {self.database_name}, Collection: {self.collection_name}"
            )
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

    def write_data(self, data):
        """
        Writes data to the specified MongoDB collection.

        Args:
            data: A dictionary representing a single document or a list of dictionaries
                  representing multiple documents to be inserted.

        Returns:
            The result of the insert operation (e.g., InsertOneResult or InsertManyResult)
            or None if an error occurs or the collection is not available.
        """
        if self.collection is None:
            print(
                "Error: Collection is not initialized. Ensure connection was successful."
            )
            return None

        if not data:
            print("Warning: No data provided to write.")
            return None

        try:
            if isinstance(data, dict):
                result = self.collection.insert_one(data)
                print(f"Successfully inserted 1 document. ID: {result.inserted_id}")
                return result
            elif isinstance(data, list):
                if not all(isinstance(doc, dict) for doc in data):
                    raise TypeError("All items in the list must be dictionaries.")
                if not data:  # Empty list
                    print("Warning: Provided list of documents is empty.")
                    return None
                result = self.collection.insert_many(data)
                print(f"Successfully inserted {len(result.inserted_ids)} documents.")
                return result
            else:
                raise TypeError("Data must be a dictionary or a list of dictionaries.")
        except OperationFailure as e:
            print(f"Error writing data: {e.details.get('errmsg', e)}")
            return None
        except TypeError as e:
            print(f"Type error during write operation: {e}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred during write_data: {e}")
            return None

    def read_data(
        self,
        query: Optional[dict] = None,
        projection: Optional[dict] = None,
        limit: int = 0,
        sort_criteria: Optional[list] = None,
    ):
        """
        Reads data from the specified MongoDB collection.

        Args:
            query (dict, optional): The query criteria (e.g., {"name": "John"}).
                                    Defaults to None (match all documents).
            projection (dict, optional): Specifies the fields to include or exclude
                                         (e.g., {"name": 1, "_id": 0}).
                                         Defaults to None (include all fields).
            limit (int, optional): The maximum number of documents to return.
                                   Defaults to 0 (no limit).
            sort_criteria (list, optional): A list of (key, direction) tuples for sorting.
                                            Example: [("name", 1), ("age", -1)].
                                            1 for ascending, -1 for descending.
                                            Defaults to None (no specific sort order).

        Returns:
            A list of documents matching the criteria, or an empty list if no documents
            are found or an error occurs.
        """
        if not self.collection:
            print(
                "Error: Collection is not initialized. Ensure connection was successful."
            )
            return []

        if query is None:
            query = {}  # Match all documents if no query is provided

        try:
            cursor = self.collection.find(query, projection)

            if sort_criteria:
                # Ensure sort_criteria is a list of tuples
                if not isinstance(sort_criteria, list) or not all(
                    isinstance(item, tuple) and len(item) == 2 for item in sort_criteria
                ):
                    raise ValueError(
                        "sort_criteria must be a list of (key, direction) tuples."
                    )
                cursor = cursor.sort(sort_criteria)

            if limit > 0:
                cursor = cursor.limit(limit)

            documents = list(cursor)
            print(f"Successfully read {len(documents)} documents.")
            return documents
        except OperationFailure as e:
            print(f"Error reading data: {e.details.get('errmsg', e)}")
            return []
        except ValueError as e:  # For invalid sort_criteria
            print(f"Value error during read operation: {e}")
            return []
        except Exception as e:
            print(f"An unexpected error occurred during read_data: {e}")
            return []


class MongoDBHelper_old:
    client: Optional[MongoClient] = None
    db: Optional[Any] = None
    collection: Optional[Any] = None

    def __init__(self, conn_str: str):
        self.conn_str = conn_str
        self.client = self.get_mongo_client(uri=conn_str)

    def connect_to_apple_gmail_collections(
        self,
        client: MongoClient,
        db_name: str = "googlereader",
        collection_name: str = "apple_gmail",
        timeseries: dict = {
            "timeField": "timestamp",
            "metaField": "metadata",
            "granularity": "seconds",
        },
    ):
        if client is None:
            raise ConnectionFailure("MongoDB client is not connected.")
        db = client[db_name]
        if collection_name not in db.list_collection_names():
            collection = db[collection_name]
            lg.warning(f"creating {collection_name=}")
            db.create_collection(
                collection_name,
                timeseries=timeseries,
            )
        collection = db.get_collection(collection_name)
        lg.info(f"connected to {collection_name=}")
        return collection

    def get_mongo_client(self, uri):
        """Connects to MongoDB and returns the client."""
        try:
            client = MongoClient(uri)
            client.admin.command("ping")  # Verify connection
            lg.info("MongoDB connection successful.")
            return client
        except ConnectionFailure:
            lg.error(
                "MongoDB connection failed. Ensure MongoDB is running and URI is correct."
            )
            return None
        except Exception as e:
            print(f"An error occurred with MongoDB connection: {e}")
            return None

    def save_doc_to_timeseries(
        self, metadata: dict[Any, Any], data_in: dict[Any, Any]
    ) -> bool:
        with MongoClient(self.conn_str) as client:
            collection = self.connect_to_apple_gmail_collections(client)
            if collection is None:
                return False

            data = copy.deepcopy(data_in)

            try:
                timestamp_str = data_in.get("rcv_date", None)
                match timestamp_str:
                    case str():
                        dt_object = datetime.datetime.strptime(
                            timestamp_str, "%Y-%m-%d %H:%M:%S%z"
                        )
                        data.pop("rcv_date", None)
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
                result = collection.insert_one(data)
                lg.info(f"Data inserted with ID: {result.inserted_id}")
                return True

            except Exception as e:
                lg.error(f"Error storing data in MongoDB: {e}")
                return False

    def get_from_mongo(self, query):
        pass


def main1():
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
    df.to_csv("output.csv")
    print(df)


def main():
    config = Config()
    df = pd.read_csv("output.csv", index_col=0)
    if config.MONGO_CONNECTION_STRING is None:
        raise ValueError(
            "MongoDB connection string is not set. Please check your environment variables."
        )
    mgdb = MongoDBHelper(config.MONGO_CONNECTION_STRING)

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
                "unique_hash": create_dict_hash(unique_data),
            }
        )

        mgdb.save_doc_to_timeseries(metadata=meta, data_in=data)

    #

    # TODO:
    # 1. parse refund cost -S$5.98 (MNY3W7327B and MNY3W7327B-1)
    # 2. parse format change (MM611014M2) query `from:(no_reply@email.apple.com) before:2024/8/1 `


if __name__ == "__main__":
    main()
