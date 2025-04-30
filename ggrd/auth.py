from pathlib import Path
from typing import Optional

import gspread
from google.auth import exceptions as g_exceptions
from google.auth.credentials import Credentials as BaseCredentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as Oauth2Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ggrd.custom_logger import getLogger

lg = getLogger()


class GoogleAuthManager:
    def __init__(self):
        self.emails = []
        # If modifying these SCOPES, delete the file token.json.
        self.scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        self.init_paths_and_files()
        self.creds = self.get_google_credentials(scopes=self.scopes)

    def init_paths_and_files(self):
        self.secrets_dirpath = Path(__file__).parent / "secrets"
        if not self.secrets_dirpath.is_dir():
            self.secrets_dirpath.mkdir()
        self.creds_file = self.get_credentials_json(self.secrets_dirpath)
        self.token_file = self.secrets_dirpath / "token.json"

    def get_google_credentials(
        self, scopes: Optional[list[str]] = None
    ) -> Optional[BaseCredentials]:
        creds = None

        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if self.token_file.is_file():
            creds = Oauth2Credentials.from_authorized_user_file(self.token_file)

        # If there are no (valid) credentials available, let the user log in.
        if creds is None or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except g_exceptions.RefreshError as e:
                    lg.error(f"refresh error. try deleting token. {e=}")
                    raise
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.creds_file, scopes
                )
                creds = flow.run_local_server(port=0)

            # Save the credentials for the next run
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())
        lg.debug("google cred initialized")
        return creds

    def get_credentials_json(self, secrets_dirpath: Path) -> Path:
        json_file = None
        for kw in ["client_secret_*.json", "*credentials.json"]:
            try:
                json_file = next(secrets_dirpath.glob(kw))
            except StopIteration:
                pass
        if json_file is None:
            raise FileNotFoundError("google credentials json file not found")
        return json_file

    def get_gmail_service(self):
        """Shows basic usage of the Gmail API.
        Lists the user's Gmail labels.
        """
        # Build the Gmail API service
        service = build("gmail", "v1", credentials=self.creds)
        return service

    def get_sheets_service(self):
        ## Original implementation without gspread library dependencies
        service = build("sheets", "v4", credentials=self.creds)
        return service

    def get_gspread(self):
        return gspread.oauth(
            credentials_filename=self.creds_file,
            authorized_user_filename=self.token_file,
        )
