from app.database.db import Database
from datetime import datetime

db = Database()

class UsuarioModel:
    """
    Modelo de usuario para MongoDB
    """
    COLECCION = "usuarios"

    @staticmethod
    def crear_usuario(usuario_data):
        usuario_data["fecha_creacion"] = datetime.utcnow()
        return db.insertar_documento(UsuarioModel.COLECCION, usuario_data)

    @staticmethod
    def obtener_usuario(filtro):
        return db.buscar_documento(UsuarioModel.COLECCION, filtro)

    @staticmethod
    def actualizar_usuario(filtro, actualizacion):
        return db.actualizar_documento(UsuarioModel.COLECCION, filtro, actualizacion)

    @staticmethod
    def obtener_todos_usuarios():
        return db.buscar_todos_documentos(UsuarioModel.COLECCION)

class OperacionModel:
    """
    Modelo de operación para MongoDB
    """
    COLECCION = "operaciones"

    @staticmethod
    def registrar_operacion(operacion_data):
        operacion_data["fecha"] = datetime.utcnow()
        return db.insertar_documento(OperacionModel.COLECCION, operacion_data)

    @staticmethod
    def obtener_operaciones(filtro):
        return db.buscar_todos_documentos(OperacionModel.COLECCION, filtro)

class ReferidoModel:
    """
    Modelo de referido para MongoDB
    """
    COLECCION = "referidos"

    @staticmethod
    def registrar_referido(referido_data):
        referido_data["fecha_registro"] = datetime.utcnow()
        return db.insertar_documento(ReferidoModel.COLECCION, referido_data)

    @staticmethod
    def obtener_referidos(filtro):
        return db.buscar_todos_documentos(ReferidoModel.COLECCION, filtro)

class FeeModel:
    """
    Modelo de fees para MongoDB
    """
    COLECCION = "fees"

    @staticmethod
    def registrar_fee(fee_data):
        fee_data["fecha"] = datetime.utcnow()
        return db.insertar_documento(FeeModel.COLECCION, fee_data)

    @staticmethod
    def obtener_fees(filtro):
        return db.buscar_todos_documentos(FeeModel.COLECCION, filtro)
