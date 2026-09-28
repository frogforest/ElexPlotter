import multiprocessing
import os
import sys
import time
import webbrowser

import uvicorn


def run_lore_service() -> None:
    """Runs Lore Service (FastAPI) on port 8001."""
    # Ensure lore_service directory is in pythonpath
    sys.path.insert(0, os.path.abspath("services/lore_service"))
    from lore_app.main import app as lore_app

    uvicorn.run(lore_app, host="127.0.0.1", port=8001, log_level="warning")


def run_story_service() -> None:
    """Runs Story Service (FastAPI) on port 8002."""
    sys.path.insert(0, os.path.abspath("services/story_service"))
    from story_app.main import app as story_app

    uvicorn.run(story_app, host="127.0.0.1", port=8002, log_level="warning")


def run_ui_server() -> None:
    """Serves the frontend static files on port 3000."""
    import http.server
    import socketserver

    ui_dir = os.path.abspath("ui")

    from typing import Any

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=ui_dir, **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # quiet mode

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", 3000), Handler) as httpd:
        httpd.serve_forever()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("Запуск Canon Story Studio...")
    print("   * Lore Service:   http://127.0.0.1:8001 (Docs: /docs)")
    print("   * Story Service:  http://127.0.0.1:8002 (Docs: /docs)")
    print("   * Веб-интерфейс:  http://127.0.0.1:3000")
    print("=" * 60)

    # Spawn processes for services
    p_lore = multiprocessing.Process(target=run_lore_service, daemon=True)
    p_story = multiprocessing.Process(target=run_story_service, daemon=True)
    p_ui = multiprocessing.Process(target=run_ui_server, daemon=True)

    p_lore.start()
    p_story.start()
    p_ui.start()

    time.sleep(1.5)
    print("🌐 Открываю интерфейс в браузере...")
    webbrowser.open("http://127.0.0.1:3000")

    print("\n[OK] Приложение запущено и готово к работе.")
    print("Нажмите Ctrl+C в терминале для остановки серверов.\n")

    try:
        p_ui.join()
    except KeyboardInterrupt:
        print("\nОстановка серверов...")
        p_lore.terminate()
        p_story.terminate()
        p_ui.terminate()
        print("Готово. До свидания!")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
