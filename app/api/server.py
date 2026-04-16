import logging
from typing import Optional

import uvicorn

from app.config import API_HOST, API_PORT, LOG_LEVEL
from .app import create_api_app


logger = logging.getLogger(__name__)


class ApiServer:
    def __init__(self):
        self.app = create_api_app()
        self._server: Optional[uvicorn.Server] = None

    @staticmethod
    def _build_config(app):
        return uvicorn.Config(
            app=app,
            host=API_HOST,
            port=API_PORT,
            log_level=LOG_LEVEL.lower(),
        )

    def run(self) -> None:
        config = self._build_config(self.app)
        self._server = uvicorn.Server(config)
        logger.info("API server iniciado en http://%s:%s", API_HOST, API_PORT)
        self._server.run()
