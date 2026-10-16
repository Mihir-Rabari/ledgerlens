"""ASGI entrypoint: uvicorn app:app --port 8788"""

from ledgerlens.service import create_app

app = create_app()
