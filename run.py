"""Запуск приложения: python run.py (или uvicorn app.main:app).

На Windows приложение работает как приложение системного трея: консольное окно
скрывается, а в трее появляется значок с меню. Окно «Winners — сервер» показывает
адрес и журнал; его закрытие сворачивает окно в трей, сервер при этом продолжает
работать. Полностью остановить сервер можно пунктом «Выход».

Режим ``--reload`` тоже работает с треем: сервер с автоперезапуском выносится в
отдельный процесс (reloader uvicorn перехватывает сигналы, что несовместимо с окном
Tk в главном потоке). Флаг ``--no-tray`` возвращает обычный консольный запуск uvicorn.
"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from threading import Timer

import uvicorn

from app.config import APP_TITLE, BASE_DIR, DATA_DIR, LOG_FILE
from app.services.logging_service import configure_console_utf8

APP_NAME = "Winners"
WINDOW_TITLE = "Winners — сервер"
LOG_MAX_LINES = 1000
POLL_INTERVAL_MS = 1000
SERVER_LOG_FILE = DATA_DIR / "winners-server.log"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _hide_console() -> None:
    """Скрыть консольное окно: всё управление уходит в трей."""
    if sys.platform != "win32":
        return
    import ctypes

    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE


class ServerThread(threading.Thread):
    """uvicorn в фоновом потоке: закрытие окна не должно останавливать сервер."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__(name="uvicorn", daemon=True)
        config = uvicorn.Config("app.main:app", host=host, port=port, log_level="info")
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True


class ServerProcess:
    """uvicorn с автоперезапуском в отдельном процессе.

    Reloader uvicorn ставит обработчики сигналов, а ``signal.signal`` работает только
    в главном потоке — в одном процессе с окном Tk это невозможно. Поэтому сервер
    уходит в отдельный процесс, а его вывод пишется в файл журнала.
    """

    def __init__(self, host: str, port: int) -> None:
        self._stream = SERVER_LOG_FILE.open("w", encoding="utf-8", errors="replace")
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                host,
                "--port",
                str(port),
                "--reload",
                "--log-level",
                "info",
            ],
            cwd=str(BASE_DIR),
            stdout=self._stream,
            stderr=subprocess.STDOUT,
            env={
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
            creationflags=_NO_WINDOW,
        )

    def stop(self) -> None:
        """Остановить сервер вместе с дочерними процессами reloader."""
        if self._process.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self._process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        else:
            self._process.terminate()

    def join(self, timeout: float | None = None) -> None:
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self._stream.close()


def _tray_image(size: int = 64):
    """Значок трея: зелёный круг с буквой W."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((1, 1, size - 1, size - 1), fill=(31, 138, 94, 255))
    draw.line(
        [
            (size * 0.28, size * 0.32),
            (size * 0.39, size * 0.70),
            (size * 0.50, size * 0.48),
            (size * 0.61, size * 0.70),
            (size * 0.72, size * 0.32),
        ],
        fill=(255, 255, 255, 255),
        width=max(2, size // 10),
        joint="curve",
    )
    return image


class TrayApplication:
    """Сервер в фоновом потоке + окно «Winners — сервер» + значок в трее.

    Меню трея и кнопки окна не работают с сервером напрямую: они кладут действие
    в очередь, а выполняет его главный поток (там же живёт окно Tk).
    """

    def __init__(
        self, url: str, log_file: Path, server: ServerThread | ServerProcess
    ) -> None:
        self._url = url
        self._log_file = log_file
        self._server = server
        self._actions: queue.Queue[str] = queue.Queue()
        self._offset = 0
        self._icon = None

        import tkinter as tk

        self._tk = tk
        self._root = tk.Tk()
        self._build_window()

    # --- окно -------------------------------------------------------------
    def _build_window(self) -> None:
        tk, root = self._tk, self._root
        root.title(WINDOW_TITLE)
        root.geometry("760x480")
        root.minsize(560, 340)
        root.protocol("WM_DELETE_WINDOW", self.hide)

        tk.Label(
            root, text=APP_TITLE, font=("Segoe UI", 12, "bold"), anchor="w"
        ).pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(
            root, text=f"Сервер работает: {self._url}", anchor="w"
        ).pack(fill="x", padx=12, pady=(0, 8))

        buttons = tk.Frame(root)
        buttons.pack(fill="x", padx=12)
        tk.Button(buttons, text="Открыть в браузере", command=self.open_browser).pack(side="left")
        tk.Button(buttons, text="Копировать", command=self.copy_selection).pack(
            side="left", padx=(8, 0)
        )
        tk.Button(buttons, text="Свернуть в трей", command=self.hide).pack(side="left", padx=(8, 0))

        log_frame = tk.Frame(root)
        log_frame.pack(fill="both", expand=True, padx=12, pady=12)
        scroll = tk.Scrollbar(log_frame)
        scroll.pack(side="right", fill="y")
        self._log = tk.Text(
            log_frame,
            wrap="none",
            state="disabled",
            background="#101418",
            foreground="#d6dade",
            yscrollcommand=scroll.set,
        )
        self._log.pack(side="left", fill="both", expand=True)
        scroll.config(command=self._log.yview)

        self._menu = tk.Menu(root, tearoff=0)
        self._menu.add_command(label="Копировать", command=self.copy_selection)
        self._menu.add_command(label="Выделить всё", command=self.select_all)
        self._log.bind("<Button-3>", self._show_menu)
        self._log.bind("<Control-c>", self._copy_event)
        self._log.bind("<Control-C>", self._copy_event)

    def copy_selection(self) -> None:
        """Скопировать выделенный фрагмент журнала в буфер обмена."""
        try:
            text = self._log.get("sel.first", "sel.last")
        except self._tk.TclError:
            return
        self._root.clipboard_clear()
        self._root.clipboard_append(text)

    def select_all(self) -> None:
        """Выделить весь журнал."""
        self._log.tag_add("sel", "1.0", "end-1c")

    def _copy_event(self, _event) -> str:
        self.copy_selection()
        return "break"

    def _show_menu(self, event) -> None:
        """Контекстное меню журнала по правой кнопке мыши."""
        state = "normal" if self._log.tag_ranges("sel") else "disabled"
        self._menu.entryconfig("Копировать", state=state)
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def hide(self) -> None:
        """Свернуть окно в трей; сервер продолжает работать."""
        self._root.withdraw()

    def show(self) -> None:
        """Показать окно сервера поверх остальных."""
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def open_browser(self) -> None:
        webbrowser.open(self._url)

    # --- трей -------------------------------------------------------------
    def start_tray(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Отобразить окно сервера", self._emit("show"), default=True),
            pystray.MenuItem("Открыть в браузере", self._emit("browser")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._emit("quit")),
        )
        self._icon = pystray.Icon(APP_NAME, _tray_image(), WINDOW_TITLE, menu)
        threading.Thread(target=self._icon.run, name="tray", daemon=True).start()

    def _emit(self, action: str):
        """Вернуть обработчик пункта меню, который ставит действие в очередь."""
        return lambda: self._actions.put(action)

    # --- цикл -------------------------------------------------------------
    def run(self) -> None:
        self.start_tray()
        self._root.withdraw()  # стартуем свёрнутыми в трей
        self._refresh_log()
        self._root.after(POLL_INTERVAL_MS, self._tick)
        self._root.mainloop()

    def _tick(self) -> None:
        self._refresh_log()
        if self._pump_actions():
            self._root.after(POLL_INTERVAL_MS, self._tick)

    def _pump_actions(self) -> bool:
        """Выполнить накопленные действия. ``False`` — приложение завершается."""
        while True:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                return True
            if action == "show":
                self.show()
            elif action == "browser":
                self.open_browser()
            elif action == "quit":
                self._quit()
                return False

    def _refresh_log(self) -> None:
        """Дописать в окно новые строки журнала.

        Текст только добавляется в конец: так выделение пользователя не сбивается и
        его можно спокойно скопировать.
        """
        try:
            size = self._log_file.stat().st_size
        except OSError:
            return
        if size < self._offset:  # журнал пересоздан или ротирован
            self._offset = 0
            self._log_clear()
        if size == self._offset:
            return
        try:
            with self._log_file.open("rb") as stream:
                stream.seek(self._offset)
                chunk = stream.read()
                self._offset = stream.tell()
        except OSError:
            return
        self._log_append(chunk.decode("utf-8", errors="replace"))

    def _log_append(self, text: str) -> None:
        if not text:
            return
        at_end = self._log.yview()[1] >= 1.0  # не уводим вид, если журнал прокручен вверх
        self._log.configure(state="normal")
        self._log.insert("end", text)
        lines = int(self._log.index("end-1c").split(".")[0])
        if lines > LOG_MAX_LINES:
            self._log.delete("1.0", f"{lines - LOG_MAX_LINES + 1}.0")
        self._log.configure(state="disabled")
        if at_end:
            self._log.see("end")

    def _log_clear(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _quit(self) -> None:
        """Остановить сервер, убрать значок и закрыть окно."""
        self._server.stop()
        if self._icon is not None:
            self._icon.stop()
        self._root.destroy()
        self._server.join(timeout=3)


def _tray_available() -> bool:
    """Трей работает только на Windows и требует tkinter и pystray."""
    if sys.platform != "win32":
        return False
    try:
        import pystray  # noqa: F401
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def main() -> None:
    configure_console_utf8()
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--host", default="127.0.0.1", help="Адрес прослушивания")
    parser.add_argument("--port", type=int, default=8000, help="Порт")
    parser.add_argument("--reload", action="store_true", help="Автоперезапуск при изменениях")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать браузер")
    parser.add_argument("--no-tray", action="store_true", help="Запуск без значка в трее")
    args = parser.parse_args()

    url = f"http://{'127.0.0.1' if args.host in {'0.0.0.0', '::'} else args.host}:{args.port}"
    use_tray = not args.no_tray and _tray_available()
    if not args.no_browser and (use_tray or not args.reload):
        Timer(1.5, lambda: webbrowser.open(url)).start()

    print(f"Winners запускается: {url}")

    if not use_tray:
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info",
        )
        return

    server: ServerThread | ServerProcess
    if args.reload:
        server = ServerProcess(args.host, args.port)
        log_file = SERVER_LOG_FILE
    else:
        server = ServerThread(args.host, args.port)
        server.start()
        log_file = LOG_FILE

    application = TrayApplication(url, log_file, server)
    _hide_console()
    try:
        application.run()
    finally:
        server.stop()


if __name__ == "__main__":
    main()
