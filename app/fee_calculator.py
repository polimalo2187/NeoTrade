from app.config import FEE_ADMIN_PORC, FEE_REFERIDO_PORC


class FeeCalculator:
    def __init__(self, fee_admin=FEE_ADMIN_PORC, fee_referido=FEE_REFERIDO_PORC):
        self.fee_admin = float(fee_admin)
        self.fee_referido = float(fee_referido)

    def calcular_fee(self, ganancia, referido_activo: bool = False):
        ganancia = max(float(ganancia or 0), 0.0)
        fee_total = ganancia * self.fee_admin
        fee_referido = ganancia * self.fee_referido if referido_activo else 0.0
        fee_admin_neta = max(fee_total - fee_referido, 0.0)
        return {
            "total": fee_total,
            "admin": fee_admin_neta,
            "referido": fee_referido,
        }
