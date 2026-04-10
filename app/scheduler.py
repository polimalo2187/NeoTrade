import logging
import threading
import time
from datetime import datetime

import pytz

from app.config import ENABLE_SCHEDULER, HORARIO_COBRO_FEE, HORARIO_PAGO_REFERIDOS
from app.fee_manager import FeeManager
from app.models import ReferidoModel, UsuarioModel
from app.referidos import Referido


logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self):
        self.fee_manager = FeeManager()
        self.timezone = pytz.timezone("America/Havana")
        self.running = False
        self._thread = None

    def start(self):
        if not ENABLE_SCHEDULER:
            logger.info("Scheduler deshabilitado por configuración.")
            return
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="scheduler-thread")
        self._thread.start()
        logger.info("Scheduler iniciado.")

    def stop(self):
        self.running = False

    def _run(self):
        while self.running:
            try:
                now = datetime.now(self.timezone)
                if now.strftime("%H:%M") == HORARIO_COBRO_FEE:
                    self._cobrar_fee_diaria()
                    time.sleep(60)
                if now.strftime("%H:%M") == HORARIO_PAGO_REFERIDOS:
                    self._pago_referidos()
                    time.sleep(60)
            except Exception:
                logger.exception("Error en scheduler")
            time.sleep(5)

    def _cobrar_fee_diaria(self):
        usuarios = UsuarioModel.obtener_usuarios_activos()
        if not usuarios:
            logger.info("No hay usuarios activos para cobro diario.")
            return
        self.fee_manager.cobrar_fee_diaria(usuarios)
        logger.info("Cobro diario ejecutado.")

    def _pago_referidos(self):
        referidos_data = ReferidoModel.obtener_referidos({})
        if not referidos_data:
            logger.info("No hay referidos para pagar.")
            return
        for r in referidos_data:
            Referido(
                referidor_id=r["referidor_id"],
                referido_id=r["referido_id"],
                comision=r.get("ganancia_diaria", 0),
            ).pagar_comision()
        logger.info("Pago de referidos ejecutado.")
