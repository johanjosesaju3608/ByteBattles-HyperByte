import logging
from pathlib import Path


def setup_logger(name, log_file):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(process)d | %(levelname)s | %(message)s"
    )

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    if logger.handlers:
        return logger
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
