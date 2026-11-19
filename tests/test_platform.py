from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

from shahtoot_finance.platform_services import SingleInstance, startup_command


class PlatformTest(unittest.TestCase):
    def test_frozen_windows_startup_handles_paths_with_spaces(self):
        executable = r"C:\Accounting Apps\ShahtootFinance.exe"
        with patch("sys.frozen", True, create=True), patch("sys.executable", executable):
            self.assertEqual(startup_command(), f'"{executable}" --background')

    def test_running_instance_receives_activation_and_releases_lock(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        with TemporaryDirectory() as folder:
            primary = SingleInstance(Path(folder))
            secondary = SingleInstance(Path(folder))
            self.assertTrue(primary.acquire())
            try:
                app.processEvents()
                self.assertFalse(secondary.acquire())
                activated = QSignalSpy(primary.activated)
                self.assertTrue(secondary.request_activation())
                app.processEvents()
                self.assertTrue(activated.count() or activated.wait(1000))
                login = QSignalSpy(primary.login_requested)
                self.assertTrue(secondary.request_activation(at_login=True))
                app.processEvents()
                self.assertTrue(login.count() or login.wait(1000))
                self.assertEqual(activated.count(), 1)
            finally:
                primary.close()
            self.assertTrue(secondary.acquire())
            secondary.close()


if __name__ == "__main__":
    unittest.main()
