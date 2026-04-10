import os
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database as MongoDatabase

from app.config import MONGODB_DB_NAME, MONGODB_URI


class Database:
    """Conexión robusta y mínima con MongoDB."""

    def __init__(self):
        if not MONGODB_URI:
            raise ValueError("Debe configurar la variable de entorno MONGODB_URI")

        self.client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=15000,
            retryWrites=True,
            appname="NeoTrade",
        )
        self.client.admin.command("ping")

        db_name = MONGODB_DB_NAME
        if not db_name:
            try:
                db_name = self.client.get_default_database().name
            except Exception:
                db_name = None

        if not db_name:
            raise ValueError(
                "No se pudo resolver el nombre de la base de datos. Configure MONGODB_DB_NAME o incluya la DB en MONGODB_URI"
            )

        self.db: MongoDatabase = self.client[db_name]

    def obtener_coleccion(self, nombre_coleccion: str) -> Collection:
        return self.db[nombre_coleccion]

    def insertar_documento(self, nombre_coleccion: str, documento: Dict[str, Any]):
        resultado = self.obtener_coleccion(nombre_coleccion).insert_one(documento)
        return resultado.inserted_id

    def actualizar_documento(
        self,
        nombre_coleccion: str,
        filtro: Dict[str, Any],
        actualizacion: Dict[str, Any],
        upsert: bool = False,
    ) -> int:
        resultado = self.obtener_coleccion(nombre_coleccion).update_one(
            filtro,
            {"$set": actualizacion},
            upsert=upsert,
        )
        return resultado.modified_count

    def incrementar_documento(
        self,
        nombre_coleccion: str,
        filtro: Dict[str, Any],
        incrementos: Dict[str, Any],
        upsert: bool = False,
    ) -> int:
        resultado = self.obtener_coleccion(nombre_coleccion).update_one(
            filtro,
            {"$inc": incrementos},
            upsert=upsert,
        )
        return resultado.modified_count

    def buscar_documento(self, nombre_coleccion: str, filtro: Dict[str, Any]):
        return self.obtener_coleccion(nombre_coleccion).find_one(filtro)

    def buscar_todos_documentos(
        self,
        nombre_coleccion: str,
        filtro: Optional[Dict[str, Any]] = None,
        sort: Optional[List] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        cursor = self.obtener_coleccion(nombre_coleccion).find(filtro or {})
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return list(cursor)

    def eliminar_documento(self, nombre_coleccion: str, filtro: Dict[str, Any]) -> int:
        resultado = self.obtener_coleccion(nombre_coleccion).delete_one(filtro)
        return resultado.deleted_count

    def crear_indice(self, nombre_coleccion: str, *args, **kwargs):
        return self.obtener_coleccion(nombre_coleccion).create_index(*args, **kwargs)
