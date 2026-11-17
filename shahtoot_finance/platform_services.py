from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QFileSystemWatcher, QLockFile, QObject, QTimer, Signal

from . import APP_ID

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
IS_WINDOWS = sys.platform == "win32"


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        arguments = [sys.executable]
    else:
        python = Path(sys.executable).with_name("pythonw.exe")
        launcher = Path(__file__).resolve().parents[1] / "main.py"
        arguments = [str(python if python.is_file() else sys.executable), str(launcher)]
    return subprocess.list2cmdline([*arguments, "--background"])


def startup_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, _kind = winreg.QueryValueEx(key, APP_ID)
    except FileNotFoundError:
        return False
    return command == startup_command()


def set_startup(enabled: bool):
    if not IS_WINDOWS:
        raise ValueError("شروع خودکار در نسخهٔ ویندوز در دسترس است.")
    import winreg

    if enabled:
        command = startup_command()
        if len(command.encode("utf-16-le")) // 2 > 260:
            raise ValueError("مسیر برنامه طولانی است. پوشهٔ برنامه را به مسیری کوتاه‌تر منتقل کنید.")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP_ID)
        except FileNotFoundError:
            pass


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.pending = data_dir / "show-window.request"
        self.lock = QLockFile(str(data_dir / "app.lock"))
        self.lock.setStaleLockTime(0)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._activate)
        self.fallback = QTimer(self)
        self.fallback.timeout.connect(self._activate)

    def acquire(self) -> bool:
        if not self.lock.tryLock(0):
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise OSError("قفل پوشهٔ داده‌ها در دسترس نیست.")
            return False
        if not self.watcher.addPath(str(self.data_dir)):
            self.fallback.start(500)
        QTimer.singleShot(0, self, self._activate)
        return True

    def request_activation(self) -> bool:
        try:
            self.pending.touch()
        except OSError:
            return False
        return True

    def _activate(self, _changed_path=None):
        try:
            self.pending.unlink()
        except OSError:
            return
        self.activated.emit()

    def close(self):
        self.fallback.stop()
        if self.watcher.directories():
            self.watcher.removePath(str(self.data_dir))
        self.lock.unlock()
