import logging
from dataclasses import dataclass

from app.api import ApiServer
from app.bot import Bot
from app.config import APP_SERVICE, ENABLE_API_SERVER, ENABLE_SCHEDULER, ENABLE_TELEGRAM_BOT, ENABLE_TRADING_ENGINE
from app.models import ensure_indexes
from app.scheduler import Scheduler
from app.trading_engine import TradingEngine


logger = logging.getLogger(__name__)


class ServiceConfigurationError(RuntimeError):
    pass


@dataclass
class ServicePlan:
    name: str
    description: str


class MiniAppRuntime:
    plan = ServicePlan(
        name="miniapp",
        description="API web exclusiva para Mini App.",
    )

    @staticmethod
    def validate() -> None:
        if not ENABLE_API_SERVER:
            raise ServiceConfigurationError("APP_SERVICE=miniapp requiere ENABLE_API_SERVER=true")
        if ENABLE_TELEGRAM_BOT:
            raise ServiceConfigurationError("APP_SERVICE=miniapp requiere ENABLE_TELEGRAM_BOT=false")
        if ENABLE_TRADING_ENGINE:
            raise ServiceConfigurationError("APP_SERVICE=miniapp requiere ENABLE_TRADING_ENGINE=false")
        if ENABLE_SCHEDULER:
            raise ServiceConfigurationError("APP_SERVICE=miniapp requiere ENABLE_SCHEDULER=false")

    def start(self) -> None:
        self.validate()
        ensure_indexes()
        logger.info("Iniciando servicio miniapp (API only)")
        ApiServer().run()


class TelegramRuntime:
    plan = ServicePlan(
        name="telegram",
        description="Servicio operativo con bot Telegram + engine + scheduler.",
    )

    @staticmethod
    def validate() -> None:
        if ENABLE_API_SERVER:
            raise ServiceConfigurationError("APP_SERVICE=telegram requiere ENABLE_API_SERVER=false")
        if not ENABLE_TELEGRAM_BOT:
            raise ServiceConfigurationError("APP_SERVICE=telegram requiere ENABLE_TELEGRAM_BOT=true")
        if not ENABLE_TRADING_ENGINE:
            raise ServiceConfigurationError("APP_SERVICE=telegram requiere ENABLE_TRADING_ENGINE=true")

    def start(self) -> None:
        self.validate()
        ensure_indexes()
        scheduler = Scheduler()
        engine = TradingEngine()
        bot = Bot()
        scheduler.start()
        engine.start()
        logger.info(
            "Iniciando servicio telegram | scheduler=%s | engine=%s | bot=%s",
            ENABLE_SCHEDULER,
            ENABLE_TRADING_ENGINE,
            ENABLE_TELEGRAM_BOT,
        )
        bot.start_bot()


class ServiceRuntimeFactory:
    @staticmethod
    def create():
        service = (APP_SERVICE or "").strip().lower()
        if service == "miniapp":
            return MiniAppRuntime()
        if service == "telegram":
            return TelegramRuntime()
        raise ServiceConfigurationError(
            "APP_SERVICE inválido. Valores permitidos: miniapp, telegram. "
            "Este repositorio ya no debe arrancarse en modo monolítico."
        )
