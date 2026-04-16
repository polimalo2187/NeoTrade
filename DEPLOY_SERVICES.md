# Despliegue en 2 servicios separados

Este repositorio ya no debe arrancarse como proceso monolítico.

Usa el mismo comando en ambos despliegues:

```bash
python main.py
```

Y cambia **solo** `APP_SERVICE` y sus variables de entorno.

## Servicio 1: Mini App / Web
- `APP_SERVICE=miniapp`
- API exclusiva
- No arranca bot, ni engine, ni scheduler

## Servicio 2: Telegram operativo
- `APP_SERVICE=telegram`
- Arranca bot Telegram + trading engine + scheduler
- No arranca API

## Regla crítica
No actives `ENABLE_TRADING_ENGINE` en el servicio miniapp.
No actives `ENABLE_API_SERVER` en el servicio telegram.
El arranque aborta si detecta configuración cruzada.
