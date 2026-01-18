import uuid
import hmac
import hashlib
import time
import requests
import urllib.parse
from json.decoder import JSONDecodeError


class Usuario:
    """
    Clase que representa a un usuario del bot de trading.
    Maneja capital, operaciones abiertas y referidor asociado.
    """

    def __init__(self, telegram_id, api_key=None, api_secret=None, capital_total=0, referidor_id=None):
        self.telegram_id = telegram_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.capital_total = capital_total
        self.capital_activo = 0
        self.operaciones_abiertas = []
        self.referidor_id = referidor_id
        self.bot_activo = False
        self.ganancia_acumulada_referidos = 0
        self.ganancia_diaria_referidos = 0

    # =========================
    # Activación / Desactivación del bot
    # =========================
    def activar_bot(self):
        self.bot_activo = True
        print(f"Bot activado para el usuario {self.telegram_id}")

    def detener_bot(self):
        self.bot_activo = False
        print(f"Bot detenido para el usuario {self.telegram_id}")

    # =========================
    # Gestión de capital
    # =========================
    def actualizar_capital(self, ganancia):
        self.capital_total += ganancia
        self.calcular_interes_compuesto()

    def calcular_interes_compuesto(self):
        self.capital_activo = self.capital_total * 0.3

    # =========================
    # Gestión de operaciones
    # =========================
    def registrar_operacion(self, operacion):
        self.operaciones_abiertas.append(operacion)

    def cerrar_operacion(self, orden_id, ganancia):
        self.operaciones_abiertas = [
            op for op in self.operaciones_abiertas if op.get("orden_id") != orden_id
        ]
        self.actualizar_capital(ganancia)

    # =========================
    # Sistema de referidos
    # =========================
    def generar_enlace_unico(self):
        return f"https://t.me/TU_BOT?start={self.telegram_id}_{uuid.uuid4().hex}"

    def actualizar_ganancia_referido(self, monto):
        self.ganancia_diaria_referidos += monto
        self.ganancia_acumulada_referidos += monto

    def reset_ganancia_diaria_referidos(self):
        self.ganancia_diaria_referidos = 0

    # =========================
    # Validación de API Key / Secret (CoinW SPOT)
    # =========================
    @staticmethod
    def validar_api(api_key, api_secret, return_error=False):
        """
        Valida la API Key y API Secret de CoinW (Spot)
        usando el endpoint de cuenta.
        """

        try:
            base_url = "https://api.coinw.com"
            path = "/open/api/user/account"

            timestamp = str(int(time.time() * 1000))

            params = {
                "api_key": api_key,
                "timestamp": timestamp
            }

            # 1️⃣ Ordenar parámetros
            query_string = urllib.parse.urlencode(sorted(params.items()))

            # 2️⃣ Firmar SOLO el query string (así lo exige CoinW)
            signature = hmac.new(
                api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

            # 3️⃣ URL final
            url = f"{base_url}{path}?{query_string}&sign={signature}"

            r = requests.get(url, timeout=10)

            try:
                data = r.json()
            except JSONDecodeError:
                msg = f"Respuesta inválida del servidor: {r.text}"
                return (False, msg) if return_error else False

            # CoinW responde con code = 0 si todo es correcto
            if r.status_code != 200 or data.get("code") != 0:
                msg = data.get("msg", str(data))
                return (False, msg) if return_error else False

            return (True, "") if return_error else True

        except Exception as e:
            return (False, str(e)) if return_error else False
