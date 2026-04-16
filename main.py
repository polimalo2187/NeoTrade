import logging

from app.config import LOG_LEVEL
from app.runtime import AppRuntime


def configure_logging():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main():
    configure_logging()
    runtime = AppRuntime()
    runtime.start()


if __name__ == "__main__":
    main()
