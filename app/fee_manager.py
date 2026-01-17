from datetime import datetime
from app.fees.fee_calculator import FeeCalculator
from app.models.models import UsuarioModel, ReferidoModel

class FeeManager:
    """
    Gestiona el cobro diario de las fees de los usuarios.
    """

    def __init__(self):
        self.calculadora = FeeCalculator()

    def cobrar_fee_diaria(self, usuarios):
        """
        Calcula y registra la fee de cada usuario.
        Ejecutarse a las 12:00 hora Cuba.
        usuarios: lista de objetos Usuario
        """
        for usuario in usuarios:
            # Solo usuarios activos
            if not getattr(usuario, "bot_activo", False):
                continue

            # Iterar sobre operaciones cerradas del día
            operaciones = getattr(usuario, "operaciones_cerradas_dia", [])
            total_fee_admin = 0
            total_comision_referido = 0

            for operacion in operaciones:
                ganancia = operacion.get("ganancia", 0)
                fee = self.calculadora.calcular_fee(ganancia)

                # Fee del administrador
                total_fee_admin += fee.get("admin", 0)

                # Comision del referidor
                if hasattr(usuario, "referidor_id") and usuario.referidor_id:
                    comision = fee.get("referidor", 0)
                    total_comision_referido += comision
                    # Actualizar ganancia del referidor en la base de datos
                    ReferidoModel.actualizar_ganancia_referido(usuario.referidor_id, comision)

            # Actualizar fee acumulada del usuario en la DB
            UsuarioModel.actualizar_fee(usuario.telegram_id, total_fee_admin)

            # Restablecer operaciones cerradas del día
            usuario.operaciones_cerradas_dia = []

        print(f"✅ Fee diaria cobrada a todos los usuarios a las {datetime.now().strftime('%H:%M:%S')}")
