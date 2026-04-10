import logging

from app.bot import Bot as TradingBot
from app.config import LOG_LEVEL
from app.models import ensure_indexes
from app.scheduler import Scheduler
from app.trading_engine import TradingEngine


def configure_logging():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main():
    configure_logging()
    ensure_indexes()

    scheduler = Scheduler()
    scheduler.start()

    engine = TradingEngine()
    engine.start()

    bot = TradingBot()
    bot.start_bot()


if __name__ == "__main__":
    main()
