from ggrd.common_vars import APP_NAME
from ggrd.gmail import OutpostEmailClient
from ggrd.sheets import GoogleSheetClient
from ggrd.utils import CustomLogger

lg = CustomLogger(APP_NAME).getLogger()


class Outpost:
    def __init__(self):
        self.email = OutpostEmailClient()
        # self.gsc = GoogleSheetClient(
        #     spreadsheet_name=f"{APP_NAME}-Outpost-ClimbRecords"
        # )

    def pull_updates_from_email(self, self_reset: bool = True) -> None:
        try:
            # dt = self.gsc.get_last_entry_datetime()
            df = self.email.run()
            lg.info(df)
            # self.gsc.update_data(df)
        except Exception as e:
            lg.error(f"{e=}")
            # if self_reset:
            #     lg.warning("attempting self reset...")
            #     self.reset_data()

    # def reset_data(self) -> None:
    #     df = self.email.run()
    #     self.gsc.reset_and_write_data(df)


def main():
    op = Outpost()
    # op.reset_data()
    op.pull_updates_from_email()


if __name__ == "__main__":
    main()
