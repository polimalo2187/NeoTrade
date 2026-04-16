import os

os.environ.setdefault("APP_SERVICE", "miniapp")

from app.api.app import create_api_app  # noqa: E402
from main import main  # noqa: E402

# ASGI entrypoint para Railway / Uvicorn
app = create_api_app()


if __name__ == "__main__":
    main()
