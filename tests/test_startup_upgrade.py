from contextlib import ExitStack, nullcontext
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from shahtoot_finance import APP_ID
from shahtoot_finance import app, platform_services as windows
from shahtoot_finance.platform_services import WindowsRelease


OLD_EXE = r"C:\Accounting\v1\ShahtootFinance.exe"
NEW_EXE = r"C:\Accounting Apps\v1.4\ShahtootFinance.exe"
OLD_COMMAND = OLD_EXE + " --background"
NEW_COMMAND = f'"{NEW_EXE}" --background'


class RunRegistry:
    HKEY_CURRENT_USER = "user"
    KEY_SET_VALUE = 2
    REG_SZ = 1
    REG_EXPAND_SZ = 2

    def __init__(self):
        self.values = {"UnrelatedApp": ("unrelated.exe", self.REG_SZ)}
        self.writes = []

    def OpenKey(self, root, subkey, *_args):
        assert root == self.HKEY_CURRENT_USER and subkey == windows.RUN_KEY
        return nullcontext(subkey)

    CreateKey = OpenKey

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    def SetValueEx(self, key, name, reserved, kind, command):
        self.values[name] = (command, kind)
        self.writes.append(name)


class StartupUpgradeTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        self.data = Path(folder)
        self.release_path = self.data / "active-release.json"
        self.registry = RunRegistry()
        self.enterContext(patch.dict(sys.modules, winreg=self.registry))
        self.enterContext(patch.object(windows, "IS_WINDOWS", True))
        self.enterContext(patch.object(app, "IS_WINDOWS", True))
        self.enterContext(patch.object(windows.sys, "frozen", True, create=True))

    def launch(self, *, version="1.4.0", exe=NEW_EXE, locked=False, configured=True, args=()):
        instance = Mock()
        instance.acquire.return_value = not locked
        instance.request_activation.return_value = True
        store = Mock()
        store.setting.return_value = int(configured)
        application = Mock()
        application.exec.return_value = 0
        with ExitStack() as stack:
            stack.enter_context(patch.object(app.sys, "argv", [exe, *args]))
            stack.enter_context(patch.object(app.sys, "executable", exe))
            stack.enter_context(patch.object(app, "VERSION", version))
            stack.enter_context(patch.object(app, "QApplication", return_value=application))
            stack.enter_context(patch.object(app.QStandardPaths, "writableLocation", return_value=str(self.data)))
            stack.enter_context(patch.object(app, "SingleInstance", return_value=instance))
            stack.enter_context(patch.object(app, "configure_logging"))
            stack.enter_context(patch.object(app, "apply_theme"))
            stack.enter_context(patch.object(app, "brand_icon"))
            stack.enter_context(patch.object(app.QTimer, "singleShot"))
            store_factory = stack.enter_context(patch.object(app, "Store", return_value=store))
            desktop = stack.enter_context(patch.object(app, "DesktopApp"))
            message = stack.enter_context(patch.object(app, "QMessageBox"))
            self.assertEqual(app.main(), 0)
        instance.close.assert_called_once()
        return instance, store_factory, desktop, message

    def test_migrates_legacy_path_in_same_run_value(self):
        self.registry.values[APP_ID] = (OLD_COMMAND, self.registry.REG_SZ)
        self.launch()
        self.assertEqual(self.registry.values, {
            APP_ID: (NEW_COMMAND, self.registry.REG_SZ),
            "UnrelatedApp": ("unrelated.exe", self.registry.REG_SZ),
        })
        self.assertEqual(self.registry.writes, [APP_ID])
        self.assertEqual(WindowsRelease.read(self.release_path), WindowsRelease("1.4.0", NEW_COMMAND))
        self.launch()
        self.assertEqual(self.registry.writes, [APP_ID])

    def test_first_launch_enables_startup_and_records_configuration(self):
        _, store, _, _ = self.launch(configured=False)
        store.return_value.set_setting.assert_called_once_with("startup_configured", 1)
        self.assertEqual(self.registry.values[APP_ID], (NEW_COMMAND, self.registry.REG_SZ))

    def test_preserves_disabled_startup_while_recording_latest_release(self):
        self.launch()
        self.assertNotIn(APP_ID, self.registry.values)
        self.assertEqual(self.registry.writes, [])
        self.assertEqual(WindowsRelease.read(self.release_path), WindowsRelease("1.4.0", NEW_COMMAND))

    def test_new_or_relocated_copy_waits_for_active_instance(self):
        self.registry.values[APP_ID] = (OLD_COMMAND, self.registry.REG_SZ)
        instance, store, desktop, message = self.launch(locked=True)
        instance.request_activation.assert_not_called()
        store.assert_not_called()
        desktop.assert_not_called()
        message.information.assert_called_once()
        self.assertEqual(self.registry.writes, [])
        self.assertFalse(self.release_path.exists())

        WindowsRelease("1.4.0", OLD_COMMAND).save(self.release_path)
        self.launch(locked=True)
        self.assertEqual(self.registry.writes, [])
        self.launch()
        self.assertEqual(self.registry.values[APP_ID], (NEW_COMMAND, self.registry.REG_SZ))

    def test_same_copy_activates_existing_window_and_login_reminder(self):
        WindowsRelease("1.4.0", NEW_COMMAND).save(self.release_path)
        for args in ((), ("--background",)):
            instance, store, desktop, _ = self.launch(locked=True, args=args)
            instance.request_activation.assert_called_once_with(at_login=bool(args))
            store.assert_not_called()
            desktop.assert_not_called()
        self.assertEqual(self.registry.writes, [])

    def test_older_copy_does_not_open_data_or_replace_startup(self):
        active = WindowsRelease("1.10.0", NEW_COMMAND)
        active.save(self.release_path)
        for args in ((), ("--background",)):
            with self.subTest(args=args):
                _, store, desktop, message = self.launch(version="1.9.9", exe=OLD_EXE, args=args)
                store.assert_not_called()
                desktop.assert_not_called()
                self.assertEqual(message.warning.call_count, int(not args))
        self.assertEqual(self.registry.writes, [])
        self.assertEqual(WindowsRelease.read(self.release_path), active)

    def test_login_registers_in_place_version_only_without_touching_run(self):
        self.registry.values[APP_ID] = (NEW_COMMAND, self.registry.REG_SZ)
        active = WindowsRelease("1.3.0", NEW_COMMAND)
        active.save(self.release_path)
        self.launch(exe=OLD_EXE, args=("--background",))
        self.assertEqual(WindowsRelease.read(self.release_path), active)
        _, _, desktop, _ = self.launch(args=("--background",))
        self.assertTrue(desktop.call_args.kwargs["launched_at_login"])
        self.assertEqual(self.registry.writes, [])
        self.assertEqual(WindowsRelease.read(self.release_path), WindowsRelease("1.4.0", NEW_COMMAND))

    def test_failed_registry_write_leaves_old_registration_and_release(self):
        self.registry.values[APP_ID] = (OLD_COMMAND, self.registry.REG_SZ)
        active = WindowsRelease("1.3.0", OLD_COMMAND)
        active.save(self.release_path)
        with patch.object(self.registry, "SetValueEx", side_effect=PermissionError), self.assertLogs(app.log, level="ERROR"):
            _, _, desktop, _ = self.launch()
        self.assertTrue(desktop.call_args.args[4])
        self.assertEqual(self.registry.values[APP_ID][0], OLD_COMMAND)
        self.assertEqual(WindowsRelease.read(self.release_path), active)
        self.launch()
        self.assertEqual(self.registry.values[APP_ID][0], NEW_COMMAND)

    def test_alternate_data_directory_bypasses_windows_profile(self):
        active = WindowsRelease("2.0.0", NEW_COMMAND)
        active.save(self.release_path)
        alternate = self.data / "isolated"
        _, store, _, _ = self.launch(args=("--data-dir", str(alternate)))
        store.assert_called_once_with(alternate.resolve() / "finance.sqlite3")
        self.assertFalse((alternate / self.release_path.name).exists())
        self.assertEqual(WindowsRelease.read(self.release_path), active)
        self.assertEqual(self.registry.writes, [])


@unittest.skipUnless(sys.platform == "win32", "requires the Windows registry")
class NativeStartupRegistryTest(unittest.TestCase):
    def test_replaces_one_named_value_in_an_isolated_registry_key(self):
        import winreg

        scratch = rf"Software\ShahtootFinance-Test-{uuid4().hex}"
        root = winreg.HKEY_CURRENT_USER
        with winreg.CreateKey(root, scratch) as key:
            self.addCleanup(winreg.DeleteKey, root, scratch)
            winreg.SetValueEx(key, "UnrelatedApp", 0, winreg.REG_SZ, "unrelated.exe")
        with patch.object(windows, "RUN_KEY", scratch):
            windows.set_startup(True, command=OLD_COMMAND)
            windows.set_startup(True, command=NEW_COMMAND)
            self.assertEqual(windows.registered_startup_command(), NEW_COMMAND)
            with winreg.OpenKey(root, scratch) as key:
                self.assertEqual(winreg.QueryInfoKey(key)[1], 2)
                self.assertEqual(winreg.QueryValueEx(key, "UnrelatedApp")[0], "unrelated.exe")
            windows.set_startup(False)
            self.assertIsNone(windows.registered_startup_command())
