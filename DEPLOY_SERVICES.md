# Despliegue en 2 servicios separados

Este repositorio no debe arrancarse como proceso monolítico.

## Servicio 1: Mini App / Web
- `APP_SERVICE=miniapp`
- API exclusiva
- No arranca bot, ni engine, ni scheduler
- **Comando exacto recomendado:**

```bash
uvicorn asgi:app --host 0.0.0.0 --port ${PORT:-8000}
```

Alternativa válida:

```bash
uvicorn main_miniapp:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Servicio 2: Telegram operativo
- `APP_SERVICE=telegram`
- Arranca bot Telegram + trading engine + scheduler
- No arranca API
- **Comando exacto recomendado:**

```bash
python main_telegram.py
```

## Regla crítica
No actives `ENABLE_TRADING_ENGINE` en el servicio miniapp.
No actives `ENABLE_API_SERVER` en el servicio telegram.
El arranque aborta si detecta configuración cruzada.

## Error típico a evitar
Si en Railway ves `Attribute "app" not found in module "main"`, el start command está mal.
Eso pasa cuando intentas arrancar la Mini App con `uvicorn main:app` sin exponer un ASGI correcto o cuando el servicio Telegram quedó configurado como web ASGI.
Usa los comandos exactos de arriba.
