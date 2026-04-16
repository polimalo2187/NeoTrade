import os

os.environ.setdefault("APP_SERVICE", "miniapp")

from main import main  # noqa: E402


if __name__ == "__main__":
    main()
