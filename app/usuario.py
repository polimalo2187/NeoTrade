import uuid
from typing import Tuple

from app.config import CAPITAL_ACTIVO_PORC, QUOTE_ASSET
from app.exchange import CoinWApiError, CoinWEmptySpotBalanceError, ExchangeClient


class Usuario:
    def __init__(self, telegram_id, api_key=None, api_secret=None, capital_total=0, referidor_id=None):
        self.telegram_id = telegram_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.capital_total = float(capital_total or 0)
        self.capital_activo = self.capital_total * CAPITAL_ACTIVO_PORC
        self.operaciones_abiertas = []
        self.referidor_id = referidor_id
        self.bot_activo = False
        self.ganancia_acumulada_referidos = 0.0
        self.ganancia_diaria_referidos = 0.0

    def activar_bot(self):
        self.bot_activo = True

    def detener_bot(self):
        self.bot_activo = False

    def actualizar_capital(self, ganancia):
        self.capital_total += float(ganancia or 0)
        self.calcular_interes_compuesto()

    def calcular_interes_compuesto(self):
        self.capital_activo = self.capital_total * CAPITAL_ACTIVO_PORC

    def registrar_operacion(self, operacion):
        self.operaciones_abiertas.append(operacion)

    def cerrar_operacion(self, orden_id, ganancia):
        self.operaciones_abiertas = [op for op in self.operaciones_abiertas if op.get("orden_id") != orden_id]
        self.actualizar_capital(ganancia)

    def generar_enlace_unico(self):
        return f"https://t.me/TU_BOT?start={self.telegram_id}_{uuid.uuid4().hex}"

    def actualizar_ganancia_referido(self, monto):
        self.ganancia_diaria_referidos += float(monto)
        self.ganancia_acumulada_referidos += float(monto)

    def reset_ganancia_diaria_referidos(self):
        self.ganancia_diaria_referidos = 0.0

    @staticmethod
    def validar_api(api_key: str, api_secret: str, return_error: bool = False) -> Tuple[bool, str]:
        try:
            client = ExchangeClient(api_key=api_key, api_secret=api_secret)
            diagnostico = client.validar_acceso_spot(QUOTE_ASSET)
            disponible = float(diagnostico.get("quote_available") or 0)
            total = float(diagnostico.get("quote_total") or 0)
            if total <= 0:
                mensaje = (
                    f"La API autenticó, pero la cuenta Spot visible por CoinW no tiene saldo utilizable en {QUOTE_ASSET}. "
                    "Verifica que el dinero esté en Spot Trading, que la API pertenezca a la misma cuenta y que tenga acceso Spot."
                )
                return (False, mensaje) if return_error else False
            mensaje = (
                f"API validada correctamente. Spot visible: total={total:.8f} {QUOTE_ASSET}, "
                f"disponible={disponible:.8f} {QUOTE_ASSET}."
            )
            return (True, mensaje) if return_error else True
        except CoinWEmptySpotBalanceError:
            mensaje = (
                "La API autenticó, pero CoinW devolvió la cuenta Spot vacía para esa API. "
                "Revisa que el dinero esté en Spot Trading, que esa API pertenezca a la misma cuenta donde ves el saldo y que tenga acceso Spot."
            )
            return (False, mensaje) if return_error else False
        except CoinWApiError as exc:
            return (False, str(exc)) if return_error else False
        except Exception as exc:
            return (False, f"Error inesperado: {exc}") if return_error else False
