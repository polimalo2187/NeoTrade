# Comandos exactos de arranque

## Servicio Mini App (Railway / ASGI)
Usa este comando exacto:

```bash
uvicorn asgi:app --host 0.0.0.0 --port ${PORT:-8000}
```

Alternativa equivalente:

```bash
uvicorn main_miniapp:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Servicio Telegram
Usa este comando exacto:

```bash
python main_telegram.py
```

## No usar
No uses `uvicorn main:app` en el servicio Telegram.
No uses `python main.py` si el panel del host está configurado como ASGI.
