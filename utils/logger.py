"""Logger utility for ISEA"""
import logging
from pathlib import Path
from datetime import datetime
from typing import Union


class Logger:
    """Simple logger with file and console output"""

    def __init__(self, log_dir: Union[str, Path], log_filename: str):
        """Initialize logger with directory and filename"""
        self.log_dir = Path(log_dir)
        self.log_file = self.log_dir / log_filename

        # Create log directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Setup logger
        self.logger = logging.getLogger(f"isea_{id(self)}")
        self.logger.setLevel(logging.DEBUG)

        # Remove existing handlers to avoid duplicates
        self.logger.handlers.clear()

        # File handler
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)
        self.logger.addHandler(console_handler)

        # Log startup
        self.log("info", f"Logger initialized - log file: {self.log_file}")

    def log(self, level: str, message: str):
        """Log a message at the specified level"""
        level = level.lower()

        # Add timestamp to message for file logs
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if level == "debug":
            self.logger.debug(message)
        elif level == "info":
            self.logger.info(message)
        elif level == "warning" or level == "warn":
            self.logger.warning(message)
        elif level == "error":
            self.logger.error(message)
        elif level == "critical":
            self.logger.critical(message)
        else:
            # Default to info level for unknown levels
            self.logger.info(f"[{level.upper()}] {message}")

    def debug(self, message: str):
        """Log debug message"""
        self.log("debug", message)

    def info(self, message: str):
        """Log info message"""
        self.log("info", message)

    def warning(self, message: str):
        """Log warning message"""
        self.log("warning", message)

    def error(self, message: str):
        """Log error message"""
        self.log("error", message)

    def critical(self, message: str):
        """Log critical message"""
        self.log("critical", message)


def create_logger(name: str = None, log_dir: str = None) -> Logger:
    """Create a logger instance with default settings"""
    if name is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = f"isea_{timestamp}.log"

    if log_dir is None:
        log_dir = Path.cwd() / "logs"

    return Logger(log_dir, name)