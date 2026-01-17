import threading
import time
from datetime import datetime
import pytz
from app.fees.fee_manager import FeeManager
from app.user.referidos import Referido
from app.models.models import UsuarioModel, ReferidoModel

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

    # ======================================
    # Cobro diario de fee
    # ======================================
    def _cobrar_fee_diaria(self):
        """
        Cobro de fee diaria usando wallet externa USDT/BSC.
        Solo a usuarios activos.
        """
        usuarios = self._obtener_usuarios_activos()
        if usuarios:
            self.fee_manager.cobrar_fee_diaria(usuarios)
            print("✅ Cobro de fee diario ejecutado.")
        else:
            print("⚠️ No se encontraron usuarios activos para cobrar fee.")

    # ======================================
    # Pago diario de referidos
    # ======================================
    def _pago_referidos(self):
        """
        Pago de comisiones a referidos desde la wallet externa.
        Descuenta del fee del administrador.
        """
        referidos = self._obtener_referidos()
        if referidos:
            for r in referidos:
                r.pagar_comision()
            print("💸 Pago de referidos ejecutado.")
        else:
            print("⚠️ No se encontraron referidos para pagar.")

    # ======================================
    # Obtención de usuarios activos
    # ======================================
    def _obtener_usuarios_activos(self):
        """
        Obtiene todos los usuarios cuyo bot esté activado.
        """
        usuarios_data = UsuarioModel.obtener_todos_usuarios()
        usuarios = []
        for u in usuarios_data:
            if u.get("bot_activo"):
                usuarios.append({
                    "telegram_id": u["telegram_id"],
                    "capital_total": u.get("capital_total", 0),
                    "capital_activo": u.get("capital_activo", 0)
                })
        return usuarios

    # ======================================
    # Obtención de referidos
    # ======================================
    def _obtener_referidos(self):
        """
        Obtiene todos los referidos registrados desde la base de datos.
        """
        referidos_data = ReferidoModel.obtener_referidos({})
        referidos = []
        for r in referidos_data:
            referidos.append(Referido(
                referidor_id=r["referidor_id"],
                referido_id=r["referido_id"],
                comision=r.get("comision", 0)
            ))
        return referidos
