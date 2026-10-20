import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from .db.connection import create_client
from .db.setup import ensure_database

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"

app = Flask(__name__)

if os.getenv("APP_ENV") != "test" and any(
    os.getenv(variable)
    for variable in (
        "COSMOS_ENDPOINT",
        "COSMOS_KEY",
        "COSMOS_DB_NAME",
    )
):
    cosmos_client = create_client()
    cosmos_db = ensure_database(cosmos_client)
    app.extensions["cosmos_client"] = cosmos_client
    app.extensions["cosmos_db"] = cosmos_db


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/<path:filename>")
def frontend_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
