from datetime import datetime

from app.fee_calculator import FeeCalculator
from app.models import FeeModel, ReferidoModel, UsuarioModel


class FeeManager:
    def __init__(self):
        self.calculadora = FeeCalculator()

    def cobrar_fee_diaria(self, usuarios):
        for usuario in usuarios:
            telegram_id = usuario["telegram_id"] if isinstance(usuario, dict) else getattr(usuario, "telegram_id")
            operaciones = []
            if isinstance(usuario, dict):
                operaciones = usuario.get("operaciones_cerradas_dia", [])
                referidor_id = usuario.get("referidor_id")
            else:
                operaciones = getattr(usuario, "operaciones_cerradas_dia", [])
                referidor_id = getattr(usuario, "referidor_id", None)

            total_fee_admin = 0.0
            total_comision_referido = 0.0
            for operacion in operaciones:
                ganancia = operacion.get("ganancia", operacion.get("pnl_quote", 0))
                fee = self.calculadora.calcular_fee(ganancia)
                total_fee_admin += fee["admin"]
                if referidor_id:
                    total_comision_referido += fee["referido"]
                    ReferidoModel.actualizar_ganancia_referido(referidor_id, fee["referido"])

            if total_fee_admin > 0:
                FeeModel.registrar_fee(
                    {
                        "telegram_id": telegram_id,
                        "fee_admin": total_fee_admin,
                        "fee_referido": total_comision_referido,
                        "fecha": datetime.utcnow(),
                    }
                )
                UsuarioModel.incrementar_stats(telegram_id, {"pnl_quote": -total_fee_admin})
