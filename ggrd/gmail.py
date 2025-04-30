import base64
import dataclasses
import datetime
import email.utils
import os
import re
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from ggrd.auth import GoogleAuthManager
from ggrd.custom_logger import getLogger

lg = getLogger()
# pd.set_option("display.max_columns", None)
# pd.set_option("display.max_rows", None)


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
            text = text.replace(";", " ")
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
        if self.body_txt:
            self.body_preview = (
                self.body_txt
                if len(self.body_txt) < preview_length
                else self.body_txt[:preview_length]
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

            # Get a list of messages thatÏ match the query
            response = (
                self.service.users().messages().list(userId=user_id, q=query).execute()
            )
            messages = response.get("messages", [])

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


def main():
    ap = AppleEmailClient()
    ap.run(debug_email_limit=0)
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
    # print(ap.emails)


if __name__ == "__main__":
    main()
