import os
from pymongo import MongoClient

class Database:
    """
    Conexión y operaciones básicas con MongoDB.
    """

    def __init__(self):
        # URI de MongoDB almacenada como variable de entorno
        mongo_uri = os.environ.get("MONGODB_URI")
        if not mongo_uri:
            raise ValueError("Debe configurar la variable de entorno MONGODB_URI")
        
        self.client = MongoClient(mongo_uri)
        self.db = self.client.get_database()  # Base de datos por defecto de la URI

    def obtener_coleccion(self, nombre_coleccion):
        """
        Retorna la colección de la base de datos.
        """
        return self.db[nombre_coleccion]

    def insertar_documento(self, nombre_coleccion, documento):
        """
        Inserta un documento en la colección especificada.
        """
        coleccion = self.obtener_coleccion(nombre_coleccion)
        resultado = coleccion.insert_one(documento)
        return resultado.inserted_id

    def actualizar_documento(self, nombre_coleccion, filtro, actualizacion):
        """
        Actualiza un documento en la colección según un filtro.
        """
        coleccion = self.obtener_coleccion(nombre_coleccion)
        resultado = coleccion.update_one(filtro, {"$set": actualizacion})
        return resultado.modified_count

    def buscar_documento(self, nombre_coleccion, filtro):
        """
        Busca un documento en la colección según un filtro.
        """
        coleccion = self.obtener_coleccion(nombre_coleccion)
        return coleccion.find_one(filtro)

    def buscar_todos_documentos(self, nombre_coleccion, filtro={}):
        """
        Busca todos los documentos que cumplen con un filtro.
        """
        coleccion = self.obtener_coleccion(nombre_coleccion)
        return list(coleccion.find(filtro))
