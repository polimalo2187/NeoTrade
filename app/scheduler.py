import logging
import threading
import time
from datetime import datetime

import pytz

from app.config import ENABLE_SCHEDULER, HORARIO_COBRO_FEE, HORARIO_PAGO_REFERIDOS
from app.fee_manager import FeeManager
from app.models import ReferidoModel, UsuarioModel


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
                    self._resumen_referidos()
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

    def _resumen_referidos(self):
        """No liquida pagos automáticos.

        Las comisiones de referido pasan a saldo disponible cuando el fee del usuario referido
        queda realmente cobrado y confirmado. El pago al referidor se definirá en una fase aparte.
        """
        referidos_data = ReferidoModel.obtener_referidos({})
        if not referidos_data:
            logger.info("No hay referidos registrados.")
            return

        total_pendiente = sum(float(r.get("total_pendiente", 0) or 0) for r in referidos_data)
        total_disponible = sum(float(r.get("total_disponible", 0) or 0) for r in referidos_data)
        logger.info(
            "RESUMEN_REFERIDOS | relaciones=%s | pendiente=%s | disponible=%s",
            len(referidos_data),
            f"{total_pendiente:.8f}",
            f"{total_disponible:.8f}",
        )
