class FeeCalculator:
    """
    Calcula la fee del administrador y la comisión del referidor
    basada en las ganancias de cada operación.
    """

    def __init__(self, fee_admin=0.12, fee_referido=0.03):
        self.fee_admin = fee_admin
        self.fee_referido = fee_referido

    def calcular_fee(self, ganancia):
        """
        Calcula la fee del administrador y la comisión del referidor.
        Retorna un diccionario con los valores calculados.
        """
        return {
            "admin": ganancia * self.fee_admin,
            "referido": ganancia * self.fee_referido
        }
