import logging
import threading
from typing import Optional

import uvicorn

from app.config import API_HOST, API_PORT
from .app import create_api_app


logger = logging.getLogger(__name__)


class ApiServer:
    def __init__(self):
        self.app = create_api_app()
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.info("API server ya estaba iniciado")
            return

        config = uvicorn.Config(
            app=self.app,
            host=API_HOST,
            port=API_PORT,
            log_level="info",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="miniapp-api", daemon=True)
        self._thread.start()
        logger.info("API server iniciado en http://%s:%s", API_HOST, API_PORT)
