import os

os.environ.setdefault("APP_SERVICE", "miniapp")

from app.api.app import create_api_app

app = create_api_app()
