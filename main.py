import logging

from app.config import APP_SERVICE, LOG_LEVEL
from app.runtime import ServiceConfigurationError, ServiceRuntimeFactory
from app.api.app import create_api_app


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


# Compatibilidad ASGI robusta:
# `uvicorn main:app` debe devolver una app válida o fallar en startup,
# nunca arrancar con `app=None` y romper recién al primer request.
app = create_api_app()


if __name__ == "__main__":
    try:
        main()
    except ServiceConfigurationError as exc:
        logging.getLogger(__name__).error("Configuración de servicio inválida: %s", exc)
        raise SystemExit(2) from exc
