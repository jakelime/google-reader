import os
import warnings
from typing import Optional

import gspread
import pandas as pd
from gspread.worksheet import Worksheet

from ggrd import auth
from ggrd import _APP_NAME
from ggrd.configs.config import config
from ggrd.custom_logger import getLogger

warnings.filterwarnings("ignore", category=DeprecationWarning)

lg = getLogger()


class GoogleSheetClient:
    def __init__(
        self,
        spreadsheet_id: Optional[str] = None,
        spreadsheet_name: Optional[str] = None,
    ):
        self.gga = auth.GoogleAuthManager()
        self.gs = self.gga.get_gspread()
        lg.debug("google sheets service loaded")
        if spreadsheet_id is not None:
            self.ss = self.gs.open_by_key(spreadsheet_id)
            lg.info(f"spreadsheet loaded - {spreadsheet_id=}")
        elif spreadsheet_name is not None:
            try:
                self.ss = self.gs.open(spreadsheet_name)
                lg.info(f"spreadsheet loaded - {spreadsheet_name=}")
            except gspread.exceptions.SpreadsheetNotFound:
                lg.error(f"{spreadsheet_name=} not found")
                self.ss = self.gs.create(spreadsheet_name)
                lg.info(f"created new spreadsheet - {spreadsheet_name}")
                self.share_spreadsheet(spreadsheet_name)
        else:
            raise ValueError("missing value 'spreadsheet_name' or 'spreadsheet_id'")

    def share_spreadsheet(self, name: str) -> None:
        emails_str = os.getenv("GOOGLE_ACCOUNTS", None)
        if emails_str is None:
            lg.warning("missing environment variable GOOGLE_ACCOUNTS")
            return
        emails = [em.strip() for em in emails_str.split(",")]
        for em in emails:
            self.ss.share(em, perm_type="user", role="writer")
            lg.info(f"ss({name}) shared with {em}")

    def read_data(self, sheet_name: str = "data") -> pd.DataFrame:
        try:
            worksheet = self.ss.worksheet(sheet_name)
        except IndexError:
            lg.warning(f"no worksheet named '{sheet_name}'")
            self.ss.add_worksheet(sheet_name, rows=1000, cols=10)
            lg.info(f"created {sheet_name=}")
            worksheet = self.ss.worksheet(sheet_name)

        try:
            df = pd.DataFrame(worksheet.get_all_records())
            df["datetime"] = pd.to_datetime(df["datetime"], format=config.DATETIME_FMT)
            return df
        except Exception as e:
            lg.error(f"read data from gsheet({sheet_name=}) failed; {e=}")
            return pd.DataFrame()

    def update_data(self, dfin: pd.DataFrame, sheet_name: str = "data") -> None:
        df = self.read_data(sheet_name=sheet_name)

        dfin = self.parse_data_for_gsheet(dfin)

        worksheet = self.ss.worksheet(sheet_name)
        current_row = len(df) + 2
        for _, row in dfin.iterrows():
            if (df["booking_ref"].eq(row.booking_ref)).any():
                continue
            range_name = f"A{current_row}"
            worksheet.update(values=[row.tolist()], range_name=range_name)
            current_row += 1
            lg.info(f"[worksheet-{sheet_name}]: updated {range_name}")

        lg.info(f"updated {current_row - len(df) - 2} entries")

    def get_worksheet(self, sheet_name: str) -> Worksheet:
        try:
            worksheet = self.ss.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            lg.warning(f"no worksheet named '{sheet_name}'")
            self.ss.add_worksheet(sheet_name, rows=1000, cols=10)
            lg.info(f"created {sheet_name=}")
            worksheet = self.ss.worksheet(sheet_name)
        return worksheet

    def reset_and_write_data(self, df: pd.DataFrame, sheet_name: str = "data"):
        worksheet = self.get_worksheet(sheet_name)
        worksheet.clear()
        df = self.parse_data_for_gsheet(df)
        worksheet.update(values=[list(df.columns)], range_name="A1")
        worksheet.update(values=df.values.tolist(), range_name="A2")
        lg.info(f"update completed. {df.shape=}")

    def parse_data_for_gsheet(self, dfin: pd.DataFrame) -> pd.DataFrame:
        df = dfin.copy()
        df["datetime"] = df["datetime"].dt.strftime(config.DATETIME_FMT)
        return df

    def get_last_entry_datetime(self, df: Optional[pd.DataFrame] = None):
        if df is None:
            df = self.read_data()
        if df is None:
            raise RuntimeError("unable to read data")
        ds = df.iloc[-1, :]
        dt = ds["datetime"]
        return dt


def main():
    gsc = GoogleSheetClient(spreadsheet_name=f"{_APP_NAME}-Outpost-ClimbRecords")
    ws = gsc.get_worksheet("data")


if __name__ == "__main__":
    main()
