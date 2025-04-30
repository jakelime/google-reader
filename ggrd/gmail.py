import base64
import dataclasses
import os
import re
import tempfile
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from ggrd.auth import GoogleAuthManager
from ggrd.custom_logger import getLogger

lg = getLogger()

DEBUG_LIMIT = 1


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
    # cleaned_html = "\n".join([line.strip() for line in cleaned_html.splitlines()])
    return cleaned_html


class HtmlCleaner:
    def __init__(self, html_content: str):
        soup = BeautifulSoup(html_content, "html.parser")
        data = {}
        data["apple_account"] = self.find_text_after_label(soup, "APPLE\xa0ACCOUNT")
        data["invoice_date"] = self.find_text_after_label(soup, "INVOICE DATE")
        data["sequence_no"] = self.find_text_after_label(soup, "SEQUENCE NO.")
        data["billed_to"] = self.find_text_after_label(soup, "BILLED TO")
        data["order_id"] = self.find_text_after_label(soup, "ORDER ID")
        data["document_no"] = self.find_text_after_label(soup, "DOCUMENT NO.")

        # price (Targeting the TOTAL row)
        total_label_td = soup.find("td", string="TOTAL")
        print(f"{total_label_td=}")
        if total_label_td:
            price_td = total_label_td.find_next_sibling("td").find_next_sibling("td")
            print(f"{price_td=}")
            data["price"] = self.get_cleaned_text(price_td)
        else:
            # Fallback: find the last price-like span if TOTAL isn't found
            price_spans = soup.find_all("span", string=re.compile(r"S\$\s*\d+\.\d+"))
            if price_spans:
                # Assume last one is total
                data["price"] = self.get_cleaned_text(price_spans[-1])
            else:
                data["price"] = None

        for key, value in data.items():
            print(f"{key}: {value}")

    def get_cleaned_text(self, element):
        if element:
            # Replace non-breaking space \xa0 with regular space
            return element.text.replace("\xa0", " ").strip()
        return None

    def find_text_after_label_original(self, soup, label_text):
        label_span = soup.find("span", string=lambda t: t and label_text in t)
        if not label_span:
            return None
        parent_td = label_span.find_parent("td")
        if not parent_td:
            return None

        # Find the text node directly following the <br> tag after the label span
        found_br = False
        text_content = []
        for content in label_span.next_siblings:
            if isinstance(content, Tag) and content.name == "br":
                found_br = True
                continue
            # Handle the specific case for Order ID where text is inside a nested span/link
            if (
                label_text == "ORDER ID"
                and isinstance(content, Tag)
                and content.find("a")
            ):
                link = content.find("a")
                if link:
                    return self.get_cleaned_text(link)
            # Handle the specific case for Invoice Date where text is inside a nested span
            if (
                label_text == "INVOICE DATE"
                and isinstance(content, Tag)
                and content.name == "span"
            ):
                return self.get_cleaned_text(content)
            # Handle Billed To multi-line text
            if label_text == "BILLED TO":
                if isinstance(content, NavigableString):
                    line = content.strip().replace("\xa0", " ")
                    if line:
                        text_content.append(line)
                elif isinstance(content, Tag) and content.name == "br":
                    continue  # Keep lines separate for potential joining later
            # General case for other text nodes
            elif found_br and isinstance(content, NavigableString):
                cleaned_text = content.strip().replace("\xa0", " ")
                if cleaned_text:
                    return cleaned_text  # Return the first non-empty text node found after <br>

        if label_text == "BILLED TO" and text_content:
            return " ".join(text_content)  # Join Billed To lines with spaces

        # Fallback if specific logic didn't return
        return None

    def find_text_after_label(self, soup, label_text):
        is_debug_target = label_text == "APPLE ACCOUNT"  # Flag for targeted prints
        if is_debug_target:
            print(f"--- Debugging find_text_after_label for: {label_text} ---")

        label_span = soup.find("span", string=lambda t: t and label_text in t)
        if not label_span:
            if is_debug_target:
                print("  Label span NOT found.")
            return None
        if is_debug_target:
            print(f"  Found label span: {label_span}")

        parent_td = label_span.find_parent("td")
        if not parent_td:
            if is_debug_target:
                print("  Parent TD NOT found.")
            return None
        if is_debug_target:
            print(f"  Found parent TD: {parent_td.prettify()}")  # Print TD content

        # Find the text node directly following the <br> tag after the label span
        found_br = False
        text_content = []
        sibling_counter = 0
        for content in label_span.next_siblings:
            sibling_counter += 1
            if is_debug_target:
                print(f"\n  Processing sibling #{sibling_counter}:")
            if is_debug_target:
                print(f"    Type: {type(content)}")
            if is_debug_target:
                print(f"    Repr: {repr(content)}")
            if is_debug_target:
                print(f"    found_br state: {found_br}")

            if isinstance(content, Tag) and content.name == "br":
                found_br = True
                if is_debug_target:
                    print("    -> Matched <br>, setting found_br = True")
                continue
            # Handle the specific case for Order ID where text is inside a nested span/link
            if (
                label_text == "ORDER ID"
                and isinstance(content, Tag)
                and content.find("a")
            ):
                # ... (rest of specific handlers) ...
                pass  # Keep logic but add print if needed

            # Handle Billed To multi-line text
            elif label_text == "BILLED TO":
                # ... (billed to logic) ...
                pass

            # General case for other text nodes
            elif found_br and isinstance(content, NavigableString):
                if is_debug_target:
                    print("    -> Checking general NavigableString condition...")
                cleaned_text = content.strip().replace("\xa0", " ")
                if is_debug_target:
                    print(f"      Cleaned text attempt: '{cleaned_text}'")
                if cleaned_text:
                    if is_debug_target:
                        print(
                            f"      --> SUCCESS: Returning cleaned text: '{cleaned_text}'"
                        )
                    return cleaned_text
                elif is_debug_target:
                    print("      --> Text node was empty after strip.")
            elif is_debug_target:
                # Print why the general case didn't match for this sibling
                print(
                    f"    -> Did not match general case (found_br={found_br}, is_navstring={isinstance(content, NavigableString)})"
                )

        if label_text == "BILLED TO" and text_content:
            # ... (return for billed to) ...
            pass

        # Fallback if specific logic didn't return
        if is_debug_target:
            print("--- End Debug: Exited loop, returning fallback None ---")
        return None


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
        lg.info(f"{msg=}")

        return EmailContent(sender=sender, subject=subject, body_text="helloworld")

    def run(self, before_date: Optional[str] = None, after_date: Optional[str] = None):
        # Get and print the messages in the user's inbox
        self.get_messages(before_date=before_date, after_date=after_date)

    def logout(self):
        os.remove(self.service.token)
        lg.info("logout successful")


class AppleEmailClient(EmailClient):
    def __init__(self):
        super().__init__()

    def run(self, after_date: Optional[str] = None):
        # Get and print the messages in the user's inbox
        self.get_messages(
            sender_email="no_reply@email.apple.com",
            after_date=after_date,
            subject='"Your invoice from Apple."',
            limit=DEBUG_LIMIT,
        )

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

        payload = msg["payload"]
        parts = payload.get("parts", None)

        if parts:
            res_parts = self.parse_parts(parts)
            res_parts = clean_html_newline_chars(res_parts)
            HtmlCleaner(res_parts)
            # lg.info(f"{res_parts=}")

        return EmailContent(
            sender=sender, subject=subject, body_text="helloworld2", df=pd.DataFrame()
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


def main():
    ap = AppleEmailClient()
    ap.run()


if __name__ == "__main__":
    main()
