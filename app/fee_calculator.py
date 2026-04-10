from app.config import FEE_ADMIN_PORC, FEE_REFERIDO_PORC


class FeeCalculator:
    def __init__(self, fee_admin=FEE_ADMIN_PORC, fee_referido=FEE_REFERIDO_PORC):
        self.fee_admin = fee_admin
        self.fee_referido = fee_referido

    def calcular_fee(self, ganancia):
        ganancia = max(float(ganancia or 0), 0.0)
        return {
            "admin": ganancia * self.fee_admin,
            "referido": ganancia * self.fee_referido,
        }
