import logging
import os

from app.config import APP_SERVICE, LOG_LEVEL
from app.runtime import ServiceConfigurationError, ServiceRuntimeFactory


def configure_logging():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main():
    configure_logging()
    logging.getLogger(__name__).info("Boot service requested | APP_SERVICE=%s", APP_SERVICE or "<unset>")
    runtime = ServiceRuntimeFactory.create()
    runtime.start()


# Compatibilidad ASGI: solo exponer app cuando el servicio sea miniapp.
# Esto evita el error `Attribute 'app' not found in module 'main'` si el host
# intenta arrancar con `uvicorn main:app` en el servicio web.
app = None
if (os.getenv("APP_SERVICE", "").strip().lower() == "miniapp"):
    try:
        from app.api.app import create_api_app

        app = create_api_app()
    except Exception:  # pragma: no cover
        app = None


if __name__ == "__main__":
    try:
        main()
    except ServiceConfigurationError as exc:
        logging.getLogger(__name__).error("Configuración de servicio inválida: %s", exc)
        raise SystemExit(2) from exc
