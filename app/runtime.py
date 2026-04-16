import logging
import time
from typing import Optional

from app.config import ENABLE_API_SERVER, ENABLE_TELEGRAM_BOT
from app.api import ApiServer
from app.models import ensure_indexes
from app.scheduler import Scheduler
from app.trading_engine import TradingEngine


logger = logging.getLogger(__name__)


class AppRuntime:
    """Orquesta componentes sin acoplar la vida del proceso a Telegram."""

    def __init__(self):
        self.scheduler = Scheduler()
        self.engine = TradingEngine()
        self.api: Optional[ApiServer] = ApiServer() if ENABLE_API_SERVER else None
        self.bot: Optional[object] = None

    def start(self) -> None:
        ensure_indexes()
        self.scheduler.start()
        self.engine.start()

        if self.api:
            self.api.start()

        if ENABLE_TELEGRAM_BOT:
            from app.bot import Bot

            self.bot = Bot()
            self.bot.start_bot()
            return

        logger.info("Telegram bot deshabilitado. Runtime en modo backend/headless.")
        self._wait_forever()

    @staticmethod
    def _wait_forever() -> None:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Deteniendo runtime por interrupción manual.")
