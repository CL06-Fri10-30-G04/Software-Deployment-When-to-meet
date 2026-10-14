import os
from pathlib import Path

import mysql.connector
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = Flask(__name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "test"),
        password=os.getenv("DB_PASSWORD", "test-password"),
        database=os.getenv("DB_NAME", "test_database"),
    )

@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.get("/api/health")
def health():
    try:
        connection = get_db_connection()
        connection.close()
        return jsonify({"status": "ok", "database": "connected"})
    except mysql.connector.Error:
        return jsonify({"status": "error", "database": "unavailable"}), 503

@app.get("/api/meetings")
def list_meetings():
    connection = get_db_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT id, title, description, created_at
               FROM meetings ORDER BY created_at DESC, id DESC"""
        )
        meetings = cursor.fetchall()
        for meeting in meetings:
            if meeting["created_at"]:
                meeting["created_at"] = meeting["created_at"].isoformat()
        return jsonify(meetings)
    finally:
        cursor.close()
        connection.close()

@app.post("/api/meetings")
def create_meeting():
    payload = request.get_json(silent=True) or {}
    title = payload.get("title")
    description = payload.get("description", "")

    if not isinstance(title, str) or not title.strip():
        return jsonify({"error": "title is required"}), 400
    if not isinstance(description, str):
        return jsonify({"error": "description must be a string"}), 400

    connection = get_db_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO meetings (title, description) VALUES (%s, %s)",
            (title.strip(), description.strip()),
        )
        connection.commit()
        meeting_id = cursor.lastrowid
        return jsonify({
            "id": meeting_id,
            "title": title.strip(),
            "description": description.strip(),
        }), 201
    finally:
        cursor.close()
        connection.close()


@app.get("/<path:filename>")
def frontend_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)