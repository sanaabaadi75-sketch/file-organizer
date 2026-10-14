"""The Windows specific parts: finding the real Desktop, making shortcuts, pinning to Quick Access, opening Explorer.

On other systems these fall back to simple behaviour so the rest of the program can still be tested.
Every function has exactly one return statement.
"""
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = 0x08000000  # stops a black console window from flashing

# Windows' own IDs for special folders (works even if OneDrive moved your Desktop)
KNOWN_FOLDER_IDS = {
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
}


def known_folder(name):
    """Real location of Desktop, Downloads or Documents."""
    folder = Path.home() / name
    if IS_WINDOWS and name in KNOWN_FOLDER_IDS:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        raw = uuid.UUID(KNOWN_FOLDER_IDS[name]).bytes_le
        guid = GUID.from_buffer_copy(raw)
        pointer = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer))
        if result == 0:
            folder = Path(pointer.value)
            ctypes.windll.ole32.CoTaskMemFree(pointer)
    return folder


def projects_root(config):
    """Where the Projects folder lives. 'auto' means inside OneDrive if you have it, so it syncs to your phone."""
    setting = config.get("projects_folder", "auto")
    if setting and setting != "auto":
        root = Path(os.path.expandvars(os.path.expanduser(setting)))
    elif os.environ.get("OneDrive"):
        root = Path(os.environ["OneDrive"]) / "Projects"
    else:
        root = known_folder("Documents") / "Projects"
    return root


def ps_quote(value):
    """Wrap text in single quotes for PowerShell."""
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script):
    """Run a PowerShell script quietly. Returns True if it worked."""
    worked = False
    if IS_WINDOWS:
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as handle:
            handle.write(script)
            script_path = handle.name
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True, creationflags=NO_WINDOW)
        os.remove(script_path)
        worked = completed.returncode == 0
    return worked


def create_shortcuts(shortcuts):
    """shortcuts is a list of (link_path, target, arguments, working_folder). All made in one PowerShell call."""
    lines = ["$shell = New-Object -ComObject WScript.Shell"]
    for link, target, arguments, working in shortcuts:
        lines.append(
            f"$s = $shell.CreateShortcut({ps_quote(link)}); $s.TargetPath = {ps_quote(target)}; "
            f"$s.Arguments = {ps_quote(arguments)}; $s.WorkingDirectory = {ps_quote(working)}; $s.Save()")
    if IS_WINDOWS:
        worked = run_powershell("\n".join(lines)) if shortcuts else True
    else:
        # Outside Windows (for testing) write a tiny text file that names the target instead
        for link, target, arguments, working in shortcuts:
            Path(link).write_text(str(target), encoding="utf-8")
        worked = True
    return worked


_mutex_handle = None


def already_running(name="FileOrganizerSingleInstance"):
    """True if another copy of the background app is already running."""
    global _mutex_handle
    running = False
    if IS_WINDOWS:
        import ctypes
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
        running = ctypes.windll.kernel32.GetLastError() == 183
    return running


def pin_to_quick_access(folder):
    """Adds a folder to the left sidebar of File Explorer."""
    script = f"(New-Object -ComObject Shell.Application).Namespace({ps_quote(folder)}).Self.InvokeVerb('pintohome')"
    return run_powershell(script)


def open_folder(folder):
    opened = False
    if IS_WINDOWS:
        os.startfile(str(folder))
        opened = True
    return opened


def show_in_explorer(path):
    """Open the folder containing a file with that file highlighted."""
    shown = False
    if IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", str(path)])
        shown = True
    return shown


def pythonw_path():
    """The windowless Python, so the background app has no console window."""
    windowless = Path(sys.executable).with_name("pythonw.exe")
    return str(windowless if windowless.exists() else Path(sys.executable))


def startup_folder():
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
