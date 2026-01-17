import threading
import time
from datetime import datetime, timedelta
import pytz
from fees.fee_manager import FeeManager
from users.referidos import Referido

class Scheduler:
    """
    Scheduler para ejecutar tareas automáticas 24/7:
    - Cobro diario de fees a las 12:00 hora Cuba
    - Pago diario de referidos a las 14:00 hora Cuba
    """

    def __init__(self):
        self.fee_manager = FeeManager()
        self.timezone = pytz.timezone("America/Havana")
        self.running = False

    def start(self):
        """
        Inicia el scheduler en un hilo separado para tareas 24/7.
        """
        self.running = True
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        print("Scheduler iniciado ✅")

    def _run(self):
        """
        Loop principal del scheduler.
        """
        while self.running:
            now = datetime.now(self.timezone)
            
            # Cobro de fee diario a las 12:00 hora Cuba
            if now.hour == 12 and now.minute == 0:
                self._cobrar_fee_diaria()
                time.sleep(60)  # Evita ejecución múltiple en el mismo minuto

            # Pago de referidos diario a las 14:00 hora Cuba
            if now.hour == 14 and now.minute == 0:
                self._pago_referidos()
                time.sleep(60)  # Evita ejecución múltiple en el mismo minuto

            time.sleep(5)

    def _cobrar_fee_diaria(self):
        """
        Cobro de fee diaria usando wallet externa USDT/BSC.
        """
        # Obtener todos los usuarios registrados (esto dependerá de la DB)
        usuarios = self._obtener_usuarios()
        self.fee_manager.cobrar_fee_diaria(usuarios)
        print("✅ Cobro de fee diario ejecutado.")

    def _pago_referidos(self):
        """
        Pago de comisiones a referidos desde la wallet externa.
        """
        referidos = self._obtener_referidos()
        for r in referidos:
            r.pagar_comision()
        print("💸 Pago de referidos ejecutado.")

    def _obtener_usuarios(self):
        """
        Método temporal para obtener usuarios.
        En implementación real, consultar la base de datos.
        """
        # Retornar lista vacía temporal
        return []

    def _obtener_referidos(self):
        """
        Método temporal para obtener referidos.
        En implementación real, consultar la base de datos.
        """
        # Retornar lista vacía temporal
        return []
