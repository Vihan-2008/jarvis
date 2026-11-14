"""JARVIS must import on macOS and Linux too. A name that only exists on Windows may be used inside a function, or at
module level only under an `if os.name == "nt"` (or `sys.platform == "win32"`) block: anything else breaks the import
of the whole module on a Mac."""

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jcc import system

JCC = Path(__file__).resolve().parents[1] / "jcc"

# Modules that only exist on Windows: importing one at module level fails everywhere else.
WINDOWS_MODULES = {"winreg", "_winreg", "msvcrt", "winsound", "_winapi", "_overlapped"}

# Attributes that only exist on Windows, as module.attribute. ctypes.wintypes itself imports on any system.
WINDOWS_ATTRIBUTES = {
    "ctypes": {"windll", "WinDLL", "oledll", "OleDLL", "WINFUNCTYPE", "HRESULT", "WinError", "FormatError", "GetLastError",
               "get_last_error", "set_last_error"},
    "os": {"startfile"},
    "subprocess": {"CREATE_NO_WINDOW", "STARTUPINFO", "STARTF_USESHOWWINDOW", "STARTF_USESTDHANDLES", "SW_HIDE",
                   "CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NEW_CONSOLE", "CREATE_BREAKAWAY_FROM_JOB",
                   "BELOW_NORMAL_PRIORITY_CLASS", "IDLE_PRIORITY_CLASS", "HIGH_PRIORITY_CLASS"},
    "signal": {"CTRL_BREAK_EVENT", "CTRL_C_EVENT"},
}
WINDOWS_NAMES = {name for names in WINDOWS_ATTRIBUTES.values() for name in names}


def _is_windows_test(test: ast.expr) -> bool | None:
    """True when the test is "this is Windows", False when it is "this is not Windows", None when it is neither."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _is_windows_test(test.operand)
        return None if inner is None else not inner
    if isinstance(test, ast.Name) and test.id == "WINDOWS":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "WINDOWS":
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.comparators[0], ast.Constant):
        left, op, value = ast.unparse(test.left), test.ops[0], test.comparators[0].value
        if (left, value) in (("os.name", "nt"), ("sys.platform", "win32")):
            if isinstance(op, ast.Eq):
                return True
            if isinstance(op, ast.NotEq):
                return False
    if isinstance(test, ast.Call) and ast.unparse(test.func) == "sys.platform.startswith" and test.args \
            and isinstance(test.args[0], ast.Constant) and test.args[0].value == "win":
        return True
    return None


class _ModuleLevel(ast.NodeVisitor):
    """Visits what runs when a module is imported, skipping what only Windows reaches."""

    def __init__(self):
        self.found = []

    def _hit(self, node, what):
        self.found.append(f"line {node.lineno}: {what}")

    def visit_If(self, node):
        windows = _is_windows_test(node.test)
        self.visit(node.test)
        if windows is not True:
            for child in node.body:
                self.visit(child)
        if windows is not False:
            for child in node.orelse:
                self.visit(child)

    def visit_IfExp(self, node):
        windows = _is_windows_test(node.test)
        self.visit(node.test)
        if windows is not True:
            self.visit(node.body)
        if windows is not False:
            self.visit(node.orelse)

    def visit_BoolOp(self, node):
        # `os.name == "nt" and ctypes.windll...` only reaches the right-hand side on Windows.
        for i, value in enumerate(node.values):
            self.visit(value)
            if isinstance(node.op, ast.And) and _is_windows_test(value) is True:
                return
            if isinstance(node.op, ast.Or) and _is_windows_test(value) is False:
                return

    def _function(self, node):
        for decorator in node.decorator_list:
            self.visit(decorator)
        args = node.args
        for default in [*args.defaults, *[d for d in args.kw_defaults if d is not None]]:
            self.visit(default)

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node):
        for default in node.args.defaults:
            self.visit(default)

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name.split(".")[0] in WINDOWS_MODULES:
                self._hit(node, f"import {alias.name}")

    def visit_ImportFrom(self, node):
        module = (node.module or "").split(".")[0]
        if module in WINDOWS_MODULES:
            self._hit(node, f"from {node.module} import ...")
        for alias in node.names:
            if alias.name in WINDOWS_ATTRIBUTES.get(module, ()):
                self._hit(node, f"from {node.module} import {alias.name}")

    def visit_Attribute(self, node):
        if node.attr in WINDOWS_NAMES:
            base = ast.unparse(node.value).split(".")[-1]
            if node.attr in WINDOWS_ATTRIBUTES.get(base, ()):
                self._hit(node, ast.unparse(node))
        self.generic_visit(node)


def windows_only_at_module_level(source: str) -> list[str]:
    visitor = _ModuleLevel()
    for statement in ast.parse(source).body:
        visitor.visit(statement)
    return visitor.found


class ImportsEverywhere(unittest.TestCase):
    def test_no_module_uses_a_windows_only_name_where_importing_it_would_run_it(self):
        problems = []
        for path in sorted(JCC.glob("*.py")):
            for hit in windows_only_at_module_level(path.read_text("utf-8")):
                problems.append(f"{path.name} {hit}")
        self.assertEqual(problems, [], "Windows-only names run on import:\n" + "\n".join(problems))

    def test_the_check_finds_what_it_should_and_lets_through_what_is_guarded(self):
        self.assertTrue(windows_only_at_module_level("import ctypes\nuser32 = ctypes.windll.user32\n"))
        self.assertTrue(windows_only_at_module_level("import winreg\n"))
        self.assertTrue(windows_only_at_module_level("import subprocess\ndef f(flags=subprocess.CREATE_NO_WINDOW):\n    pass\n"))
        self.assertTrue(windows_only_at_module_level("import ctypes\nclass A:\n    CB = ctypes.WINFUNCTYPE(None)\n"))
        self.assertTrue(windows_only_at_module_level("import os\nif os.name != 'nt':\n    os.startfile('x')\n"))
        self.assertFalse(windows_only_at_module_level("import ctypes\ndef f():\n    return ctypes.windll.user32\n"))
        self.assertFalse(windows_only_at_module_level("import os, ctypes\nif os.name == 'nt':\n    import winreg\n    u = ctypes.windll.user32\n"))
        self.assertFalse(windows_only_at_module_level("import os, subprocess\nF = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0\n"))
        self.assertFalse(windows_only_at_module_level("import sys, ctypes\nif sys.platform != 'win32':\n    pass\nelse:\n    u = ctypes.windll\n"))


class EveryModuleImports(unittest.TestCase):
    def test_every_module_in_jcc_imports_here(self):
        import importlib
        failures = []
        for path in sorted(JCC.glob("*.py")):
            if path.stem in ("__main__",):
                continue
            try:
                importlib.import_module(f"jcc.{path.stem}")
            except Exception as e:  # noqa: BLE001 - every kind of failure is the finding
                failures.append(f"{path.stem}: {type(e).__name__}: {e}")
        self.assertEqual(failures, [])


class TestSystem(unittest.TestCase):
    def on(self, platform):
        patch = mock.patch.object(system, "PLATFORM", platform)
        patch.start()
        self.addCleanup(patch.stop)

    def test_each_system_has_its_plain_name(self):
        for platform, said in (("win32", "Windows"), ("darwin", "macOS"), ("linux", "Linux")):
            with mock.patch.object(system, "PLATFORM", platform):
                self.assertEqual(system.name(), said)

    def test_only_windows_has_a_console_window_to_hide(self):
        self.on("darwin")
        self.assertEqual(system.no_window(), 0)
        self.assertEqual(system.own_group(), {"start_new_session": True})
        self.on("win32")
        self.assertEqual(system.no_window(), getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(system.own_group(), {})

    def test_the_background_python_is_pythonw_on_windows_when_it_is_there(self):
        folder = Path(tempfile.mkdtemp(prefix="jcc-py-"))
        self.addCleanup(lambda: shutil.rmtree(folder, ignore_errors=True))
        python = folder / "python.exe"
        with mock.patch.object(sys, "executable", str(python)):
            self.on("win32")
            self.assertEqual(system.background_python(), str(python), "no pythonw beside it: this Python")
            (folder / "pythonw.exe").write_text("", "utf-8")
            self.assertEqual(system.background_python(), str(folder / "pythonw.exe"))
            self.on("darwin")
            self.assertEqual(system.background_python(), str(python), "a Mac has no console window to hide")

    def test_browsers_on_a_mac_are_found_in_the_app_folders_best_first(self):
        self.on("darwin")
        root = Path(tempfile.mkdtemp(prefix="jcc-apps-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        for tail in (system.MAC_BROWSERS[2], system.MAC_BROWSERS[0]):         # Brave and Chrome
            (root / tail).parent.mkdir(parents=True)
            (root / tail).write_text("", "utf-8")
        with mock.patch.object(system, "MAC_APP_ROOTS", (str(root),)):
            self.assertEqual(system.browsers(), [str(root / system.MAC_BROWSERS[0]), str(root / system.MAC_BROWSERS[2])])

    def test_browsers_on_linux_come_from_the_path(self):
        self.on("linux")
        with mock.patch("shutil.which", lambda name: "/usr/bin/" + name if name in ("chromium", "brave-browser") else None):
            self.assertEqual(system.browsers(), ["/usr/bin/chromium", "/usr/bin/brave-browser"])

    @unittest.skipUnless(sys.platform == "win32", "Windows' own folder names")
    def test_browsers_on_windows_are_edge_then_chrome_then_brave(self):
        self.on("win32")
        root = Path(tempfile.mkdtemp(prefix="jcc-pf-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        tails = (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe")
        for tail in reversed(tails):
            path = root / Path(*tail.split("\\"))
            path.parent.mkdir(parents=True)
            path.write_text("", "utf-8")
        with mock.patch.dict(os.environ, {"ProgramFiles(x86)": str(root), "ProgramFiles": str(root / "none"), "LOCALAPPDATA": ""}), \
                mock.patch("shutil.which", lambda name: None):
            found = system.browsers()
        self.assertEqual([Path(p).name for p in found], ["msedge.exe", "chrome.exe", "brave.exe"])

    def test_files_and_pages_open_with_the_systems_opener_never_through_a_shell(self):
        started = []
        self.on("darwin")
        system.open_path("-a Terminal", run=lambda argv, **kw: started.append(argv))
        self.assertEqual(started[-1][0], "open")
        self.assertTrue(Path(started[-1][1]).is_absolute(), "a path is made absolute, so it is never read as an option")
        system.open_url("https://example.com/?q=a b", run=lambda argv, **kw: started.append(argv))
        self.assertEqual(started[-1], ["open", "https://example.com/?q=a b"])
        self.on("linux")
        system.open_url("mailto:someone@example.com", run=lambda argv, **kw: started.append(argv))
        self.assertEqual(started[-1], ["xdg-open", "mailto:someone@example.com"])
        for address in ("file:///etc/passwd", "javascript:alert(1)", "-a Terminal", "x-apple.systempreferences:"):
            with self.assertRaises(ValueError):
                system.open_url(address, run=lambda argv, **kw: started.append(argv))

    def test_a_line_of_shell_is_one_argument_of_the_systems_shell(self):
        line = 'echo "hi"; ls ~'
        self.on("win32")
        self.assertEqual(system.shell_command(line), ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", line])
        self.on("darwin")
        with mock.patch("jcc.system.os.path.exists", lambda path: True):
            self.assertEqual(system.shell_command(line), ["/bin/zsh", "-lc", line])
        with mock.patch("jcc.system.os.path.exists", lambda path: False):
            self.assertEqual(system.shell_command(line), ["/bin/bash", "-lc", line], "no zsh: bash")
        self.on("linux")
        self.assertEqual(system.shell_command(line), ["/bin/bash", "-lc", line])
        self.assertEqual(system.shell_name(), "bash")

    def test_ending_a_program_ends_everything_it_started(self):
        ran = []
        self.on("win32")
        system.kill_tree(4321, run=lambda argv, **kw: ran.append(argv))
        self.assertEqual(ran, [["taskkill", "/PID", "4321", "/T", "/F"]])
        self.on("darwin")
        signals = []
        with mock.patch("os.getpgid", lambda pid: 4321, create=True), mock.patch("os.getpgrp", lambda: 100, create=True), \
                mock.patch("os.killpg", lambda group, sig: signals.append(("group", group)), create=True), \
                mock.patch("os.kill", lambda pid, sig: signals.append(("one", pid))), mock.patch("signal.SIGKILL", 9, create=True):
            system.kill_tree(4321)
            self.assertEqual(signals, [("group", 4321)], "a job in its own group: the whole group")
        signals.clear()
        with mock.patch("os.getpgid", lambda pid: 100, create=True), mock.patch("os.getpgrp", lambda: 100, create=True), \
                mock.patch("os.killpg", lambda group, sig: signals.append(("group", group)), create=True), \
                mock.patch("os.kill", lambda pid, sig: signals.append(("one", pid))), mock.patch("signal.SIGKILL", 9, create=True):
            system.kill_tree(4321)
            self.assertEqual(signals, [("one", 4321)], "a program in JARVIS's own group: only that program, never JARVIS")
        system.kill_tree(0)
        system.kill_tree("12")


class TestJobsOffWindows(unittest.TestCase):
    def test_a_project_python_follows_the_system_and_either_form_is_taken(self):
        from jcc.config import venv_python
        self.assertEqual(venv_python(None, windows=True), r".venv\Scripts\python.exe")
        self.assertEqual(venv_python(None, windows=False), ".venv/bin/python")
        self.assertEqual(venv_python(r".venv\Scripts\python.exe", windows=False), ".venv/bin/python")
        self.assertEqual(venv_python(".venv/bin/python", windows=True), r".venv\Scripts\python.exe")
        self.assertEqual(venv_python("env/Scripts/python.exe", windows=False), "env/bin/python")
        self.assertEqual(venv_python("/usr/bin/python3", windows=False), "/usr/bin/python3", "a full path is used as written")
        self.assertEqual(venv_python(r"C:\Python312\python.exe", windows=True), r"C:\Python312\python.exe")

    def test_coding_clis_are_found_in_the_usual_places(self):
        from jcc import agents
        folder = Path(tempfile.mkdtemp(prefix="jcc-bin-"))
        self.addCleanup(lambda: shutil.rmtree(folder, ignore_errors=True))
        (folder / "claude").write_text("", "utf-8")
        os.chmod(folder / "claude", 0o755)
        self.assertEqual(agents._usual_place("claude", (str(folder),)), str(folder / "claude"))
        self.assertIsNone(agents._usual_place("codex", (str(folder),)))
        self.assertIsNone(agents._usual_place("../claude", (str(folder / "x"),)), "only a plain name is looked for")

    def test_permission_rules_name_folders_from_the_root_of_the_disk(self):
        from jcc import agents
        here = Path(os.path.abspath("work")).as_posix()
        forms = agents._forms(Path("work"))
        if here.startswith("/"):
            self.assertEqual(forms, ["/" + here, here])
        else:
            self.assertEqual(forms, ["//" + here[0].lower() + here[2:], here])

    def test_a_jobs_process_is_known_by_when_it_started_where_there_is_no_proc(self):
        from jcc import resilience
        answer = subprocess.CompletedProcess([], 0, "Sat Nov 14 10:00:01 2026\n", "")
        self.assertEqual(resilience._started_by_ps(321, run=lambda argv, **kw: answer), "Sat Nov 14 10:00:01 2026")
        gone = subprocess.CompletedProcess([], 1, "", "")
        self.assertIsNone(resilience._started_by_ps(321, run=lambda argv, **kw: gone))

    def test_jobs_get_a_session_of_their_own_off_windows(self):
        from jcc import jobs
        seen = {}

        class Process:
            pid = 7

            def __init__(self, argv, **kw):
                seen.update(kw)
        with mock.patch("subprocess.Popen", Process):
            jobs.detached_spawn(["agent"], Path("."), {})
        self.assertEqual(seen["start_new_session"], os.name != "nt")


if __name__ == "__main__":
    unittest.main()
