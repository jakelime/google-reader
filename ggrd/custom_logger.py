"""Custom Logger

Contains a helper class to generate a logger object, from
python best practices logging module.

Simple use case:
    from custom_logger import getLogger
    logger = getLogger()

Advanced use cse:
    log_mgr = LoggerManager()
    log_mgr.getLogger()


Init method will set up a python logger object using a customised
settings by default.
- Rotating filehandler (5 files, 2MB)
- Logger name = global APP_NAME
- StreamHandler enabled

By best practices, log files will be stored in the log directory
`$OS_LOG_DIRECTORY / $APP_NAME / main_application.log.1`
"""

import logging
import os
import platform
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .common_vars import APP_NAME


def getLogger(app_name: str = APP_NAME, debug: bool = False) -> logging.Logger:
    log_mgr = LoggerManager(app_name=app_name)
    logger = log_mgr.getLogger()
    if debug:
        logger.info(f"{log_mgr.logger_filepath=}")
    return logger


def get_default_application_log_path() -> Path:
    preferred = Path("~/Library/Logs").expanduser()
    os_name = platform.system()
    match os_name:
        case "Windows":
            if localappdata := os.getenv("LOCALAPPDATA"):
                path = Path(localappdata)
            else:
                raise NotADirectoryError("LOCALAPPDATA not found")
            return path / "Logs"
        case "Darwin":
            return preferred
        case "Linux":
            return Path("/var/log")
        case _:
            return preferred


class LoggerManager:
    """Helper class to generate a logger object, based from logging.Logger.
    Init method will set up a python logger object using my customised settings.
    - Rotating filehandler (5 files, 2MB)
    - Logger name = global APP_NAME
    - StreamHandler enabled

    Simple use case is to import custom_logger.py, then call function getLogger().
    Advanced use case is to from custome_logger import LoggerManager, then call
    LoggerManager.getLogger().

    Following best practices, log files will be stored in the log directory
    $OS_LOG_DIRECTORY / $APP_NAME / main_application.log.1
    """

    logger_filepath = None

    def __init__(
        self,
        app_name: str = "",
        logfile_backupCount: int = 5,
        logfile_maxBytes: int = 2_097_152,
        default_level=logging.INFO,
        debug_mode: bool = False,
    ):
        if not app_name:
            app_name = __name__
        self.default_level = default_level
        if debug_mode:
            self.default_level = logging.DEBUG
        self.logfile_backupCount = logfile_backupCount
        self.logfile_maxBytes = logfile_maxBytes
        self.app_name = app_name
        self.logger_name = app_name
        self.logger = logging.getLogger(self.app_name)
        if not self.logger.handlers:
            # Set ups the logger if it is not already initialised
            self.init_logger(self.logger)

    def init_logger(self, logger):
        self.logger_filepath = self.set_log_filepath()
        logger.setLevel(self.default_level)
        formatter = logging.Formatter("%(asctime)s-%(levelname)s: %(message)s")
        fhandler = RotatingFileHandler(
            filename=self.logger_filepath,
            maxBytes=self.logfile_maxBytes,
            backupCount=self.logfile_backupCount,
        )
        fhandler.setFormatter(formatter)
        fhandler.setLevel(self.default_level)
        chandler = logging.StreamHandler()
        chandler.setLevel(self.default_level)
        chandler.setFormatter(formatter)
        logger.addHandler(fhandler)
        logger.addHandler(chandler)
        return logger

    def get_logger(self):
        return self.getLogger()

    def getLogger(self):
        return self.logger

    def change_level(self, level: str = "info"):
        self.setLevel(level)

    def set_log_filepath(self, dirpath: str = "") -> Path:
        if not dirpath:
            logs_dirpath = get_default_application_log_path()
        else:
            logs_dirpath = Path(dirpath).expanduser()
        if not logs_dirpath.exists():
            logs_dirpath.mkdir(parents=True)
            print(f"created {logs_dirpath}")
        if not os.access(logs_dirpath, os.W_OK):
            raise OSError(f"logs directory is not writeable - {dirpath=}")
        logger_filepath = logs_dirpath / self.app_name / "main_application.log"
        if not logger_filepath.parent.is_dir():
            logger_filepath.parent.mkdir()
        self.logger_filepath = logger_filepath
        return logger_filepath

    def setLevel(self, level: str = "INFO") -> logging.Logger:
        match level.lower():
            case "info":
                self.logger.setLevel("INFO")
                for h in self.logger.handlers:
                    h.setLevel("INFO")
            case "debug":
                self.logger.setLevel("DEBUG")
                for h in self.logger.handlers:
                    h.setLevel("DEBUG")
            case "warning" | "warn":
                self.logger.setLevel("WARNING")
                for h in self.logger.handlers:
                    h.setLevel("WARNING")
            case "error":
                self.logger.setLevel("ERROR")
                for h in self.logger.handlers:
                    h.setLevel("ERROR")
            case "critical":
                self.logger.setLevel("CRITICAL")
                for h in self.logger.handlers:
                    h.setLevel("CRITICAL")
            case _:
                raise RuntimeError(f"unknown log {level=}")
        self.logger.critical(f"logger level changed to {level}")

    def set_level(self, level: str = "info"):
        self.setLevel(level)


def main():
    log = getLogger(debug=True)
    log.info("Logger set up successful!")


if __name__ == "__main__":
    main()
