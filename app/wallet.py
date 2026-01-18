import os

class WalletAdmin:
    """
    Maneja la wallet externa de USDT/BSC del administrador.
    """

    def __init__(self):
        # Claves de la wallet almacenadas en variables de entorno
        self.address = os.environ.get("ADMIN_WALLET_ADDRESS")
        self.private_key = os.environ.get("ADMIN_WALLET_PRIVATE_KEY")

        if not self.address or not self.private_key:
            raise ValueError(
                "❌ ERROR: Debe configurar ADMIN_WALLET_ADDRESS y ADMIN_WALLET_PRIVATE_KEY en las variables de entorno del servidor"
            )

        # Saldo simulado para pruebas o seguimiento
        self.saldo = 0.0

        print("✅ WalletAdmin inicializada correctamente con la wallet externa.")

    def recibir_fee(self, monto):
        """
        Recibe las fees cobradas de los usuarios.
        """
        self.saldo += monto
        print(f"💵 Fee recibida: {monto} USDT. Saldo actual: {self.saldo} USDT")

    def pagar_referido(self, monto, referidor_id):
        """
        Paga la comisión de un referido desde la wallet del administrador.
        """
        if monto > self.saldo:
            print(f"⚠️ Saldo insuficiente para pagar al referido {referidor_id}")
            return False
        self.saldo -= monto
        print(f"💸 Comisión pagada al referido {referidor_id}: {monto} USDT. Saldo restante: {self.saldo} USDT")
        return True

    def obtener_saldo(self):
        """
        Devuelve el saldo actual de la wallet del administrador.
        """
        return self.saldo
