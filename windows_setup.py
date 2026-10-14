"""Connects File Organizer to Windows, or disconnects it.

    py windows_setup.py install     (run again any time you change your project list)
    py windows_setup.py uninstall   (your files are never touched)

Every function has exactly one return statement.
"""
import re
import subprocess
import sys
from pathlib import Path

import sorter
import winutils

APP_FOLDER = Path(__file__).resolve().parent
SCRIPT = APP_FOLDER / "organizer.py"
MENU_KEY = r"Software\Classes\*\shell\FileOrganizer"
STARTUP_LINK = "File Organizer.lnk"


def add_right_click_menu(project_names):
    """Adds an 'Organize' menu to every file's right click menu, with 'Sort for me' and one item per project."""
    import winreg
    pythonw = winutils.pythonw_path()
    hkcu = winreg.HKEY_CURRENT_USER
    with winreg.CreateKey(hkcu, MENU_KEY) as key:
        winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Organize")
        winreg.SetValueEx(key, "SubCommands", 0, winreg.REG_SZ, "")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, "imageres.dll,-3")
    entries = [("00Auto", "Sort for me", f'"{pythonw}" "{SCRIPT}" --sort "%1"')]
    for number, name in enumerate(project_names, start=1):
        safe = re.sub(r"[^A-Za-z0-9]", "", name)
        entries.append((f"{number:02d}{safe}", f"Move to {name}", f'"{pythonw}" "{SCRIPT}" --move-to "%1" "{name}"'))
    for key_name, label, command in entries:
        item_path = MENU_KEY + "\\shell\\" + key_name
        with winreg.CreateKey(hkcu, item_path) as key:
            winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, label)
        with winreg.CreateKey(hkcu, item_path + "\\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    return len(entries)


def delete_key_tree(root, path):
    """Registry keys must be emptied before they can be deleted."""
    import winreg
    removed = False
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
            children = []
            index = 0
            while True:
                try:
                    children.append(winreg.EnumKey(key, index))
                    index += 1
                except OSError:
                    break
        for child in children:
            delete_key_tree(root, path + "\\" + child)
        winreg.DeleteKey(root, path)
        removed = True
    except FileNotFoundError:
        removed = False
    return removed


def install():
    sorter.ensure_config(APP_FOLDER / "config.json")
    config = sorter.load_config(APP_FOLDER / "config.json")
    root = winutils.projects_root(config)
    desktop = winutils.known_folder("Desktop")
    recent = desktop / "Recent Work"

    print(f"Projects folder: {root}")
    for name in list(config["projects"]) + [config.get("review_folder", "To Review")]:
        (root / name).mkdir(parents=True, exist_ok=True)
    recent.mkdir(exist_ok=True)

    pythonw = winutils.pythonw_path()
    winutils.create_shortcuts([
        (desktop / "Projects.lnk", root, "", root),
        (winutils.startup_folder() / STARTUP_LINK, pythonw, f'"{SCRIPT}"', APP_FOLDER),
    ])
    print("Added a Projects shortcut to your Desktop and set File Organizer to start with Windows")

    winutils.pin_to_quick_access(root)
    winutils.pin_to_quick_access(recent)
    print("Pinned Projects and Recent Work to the File Explorer sidebar")

    count = add_right_click_menu(list(config["projects"]))
    print(f"Added the Organize right click menu ({count} items)")

    subprocess.Popen([pythonw, str(SCRIPT)], cwd=str(APP_FOLDER))
    print("File Organizer is running. Look for the folder icon near the clock (it may be under the ^ arrow).")
    return True


def uninstall():
    import winreg
    delete_key_tree(winreg.HKEY_CURRENT_USER, MENU_KEY)
    (winutils.startup_folder() / STARTUP_LINK).unlink(missing_ok=True)
    (winutils.known_folder("Desktop") / "Projects.lnk").unlink(missing_ok=True)
    print("Removed the right click menu, the startup entry and the Desktop shortcut.")
    print("Your Projects folder and every file in it were left exactly as they are.")
    print("To stop the running app, right click its icon near the clock and choose Quit.")
    return True


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    done = False
    if not winutils.IS_WINDOWS:
        print("This setup is for Windows.")
    elif action == "install":
        done = install()
    elif action == "uninstall":
        done = uninstall()
    else:
        print(__doc__)
    return done


if __name__ == "__main__":
    main()
