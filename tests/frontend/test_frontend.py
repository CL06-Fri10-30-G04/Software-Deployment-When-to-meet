from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer
from threading import Thread
from pathlib import Path

from playwright.sync_api import sync_playwright


def test_frontend_loads_and_displays_title():
    frontend_dir = Path("frontend").resolve()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(frontend_dir), **kwargs)

    server = TCPServer(("127.0.0.1", 8000), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto("http://127.0.0.1:8000")

            assert page.title() == "When to Meet"

            browser.close()
    finally:
        server.shutdown()
        server.server_close()