from datetime import datetime
from fees.fee_calculator import FeeCalculator

class FeeManager:
    """
    Gestiona el cobro diario de las fees de los usuarios.
    """

    def __init__(self):
        self.calculadora = FeeCalculator()

    def cobrar_fee_diaria(self, usuarios):
        """
        Calcula y registra la fee de cada usuario.
        Debe ejecutarse a las 12:00 hora Cuba.
        
        usuarios: lista de objetos Usuario
        """
        for usuario in usuarios:
            # Suponiendo que cada usuario tiene una lista de operaciones cerradas del día
            for operacion in getattr(usuario, "operaciones_cerradas_dia", []):
                ganancia = operacion.get("ganancia", 0)
                fee = self.calculadora.calcular_fee(ganancia)
                
                # Registrar fee en el usuario o en la base de datos
                if not hasattr(usuario, "fee_acumulada"):
                    usuario.fee_acumulada = 0
                usuario.fee_acumulada += fee["admin"]
                
                # Registrar comisión de referidor
                if hasattr(usuario, "referidor_id") and usuario.referidor_id:
                    # Aquí se podría integrar con la clase Referido para registrar la comisión
                    pass

        print(f"✅ Fee diaria cobrada a todos los usuarios a las {datetime.now().strftime('%H:%M:%S')}")
