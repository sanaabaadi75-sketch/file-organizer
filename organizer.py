"""File Organizer: the background app.

Run with no options and it sits near the clock, tidies your personal folders into your
Projects folder, and keeps a Recent Work folder on your Desktop up to date.

Other ways to run it (the right click menu uses these):
    organizer.py --sort "C:\\path\\file.pdf"                 let it decide the project
    organizer.py --move-to "C:\\path\\file.pdf" "School"     put it in a project you choose
    organizer.py --once                                      tidy once and exit
    organizer.py --undo 3                                    put the last 3 moved files back

Every function has exactly one return statement.
"""
import argparse
import json
import threading
import time
from collections import Counter
from pathlib import Path

import sorter
import winutils

APP_FOLDER = Path(__file__).resolve().parent
CONFIG_PATH = APP_FOLDER / "config.json"
TICK_SECONDS = 2


def notices_folder():
    folder = sorter.data_folder() / "notices"
    folder.mkdir(exist_ok=True)
    return folder


def heartbeat_file():
    return sorter.data_folder() / "heartbeat"


def background_app_alive():
    """The background app touches a heartbeat file every few seconds."""
    beat = heartbeat_file()
    alive = beat.exists() and time.time() - beat.stat().st_mtime < 15
    return alive


def describe_moves(moves):
    """Short notification text for a list of moves."""
    if len(moves) == 1:
        entry = moves[0]
        text = f"{Path(entry['to']).name} moved to {entry['project']}"
    else:
        counts = Counter(entry["project"] for entry in moves)
        text = f"Sorted {len(moves)} files: " + ", ".join(f"{n} to {p}" for p, n in counts.most_common())
    return text


def make_icon_image():
    """Draw a small folder icon so no image file is needed."""
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 14, 30, 24), radius=3, fill=(240, 180, 40))
    draw.rounded_rectangle((6, 20, 58, 54), radius=5, fill=(250, 200, 60))
    draw.line((16, 34, 48, 34), fill=(150, 100, 20), width=3)
    draw.line((16, 42, 40, 42), fill=(150, 100, 20), width=3)
    return image


class Organizer:
    def __init__(self):
        sorter.ensure_config(CONFIG_PATH)
        self.config_mtime = 0
        self.config = {}
        self.reload_config()
        self.desktop = winutils.known_folder("Desktop")
        self.paused = False
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.icon = None

    # ------------------------------------------------------------ settings

    def reload_config(self):
        """Pick up changes to config.json without restarting."""
        mtime = CONFIG_PATH.stat().st_mtime
        changed = mtime != self.config_mtime
        if changed:
            self.config = sorter.load_config(CONFIG_PATH)
            self.config_mtime = mtime
            self.root = winutils.projects_root(self.config)
            self.watch_folders = [winutils.known_folder(name) for name in self.config.get("watch_folders", [])]
        return changed

    # ------------------------------------------------------------ sorting

    def try_sort(self, path, ignore_age):
        """Sort one file if it has been left alone long enough. Returns the move summary or None."""
        result = None
        try:
            wait = self.config.get("wait_before_sorting_seconds", 120)
            settled = ignore_age or time.time() - path.stat().st_mtime >= wait
            if settled and sorter.is_sortable(path, automatic=True):
                result = sorter.sort_file(path, self.config, self.root)
        except OSError:
            result = None  # file vanished or is in use; we will try again next round
        return result

    def sweep(self, ignore_age=False):
        """Look through the watched folders once (loose files only, never inside subfolders)."""
        moves = []
        with self.lock:
            for folder in self.watch_folders:
                paths = sorted(folder.iterdir()) if folder.exists() else []
                for path in paths:
                    result = self.try_sort(path, ignore_age)
                    if result:
                        moves.append(result)
        return moves

    def sort_one(self, path, project=None):
        """Used by the right click menu. Returns the move summary, or None if the file could not be moved."""
        entry = None
        try:
            entry = sorter.sort_file(path, self.config, self.root, forced_project=project)
        except OSError as error:
            print(f"Could not move {path}: {error}")
        if entry and background_app_alive():
            notice = notices_folder() / f"{time.time_ns()}.json"
            notice.write_text(json.dumps(entry), encoding="utf-8")
        elif entry:
            winutils.show_in_explorer(entry["to"])
        return entry

    # ------------------------------------------------------------ recent work

    def refresh_recent_work(self):
        """Rebuild Desktop\\Recent Work with shortcuts to what you changed last, grouped by project."""
        recent_dir = self.desktop / "Recent Work"
        recent_dir.mkdir(parents=True, exist_ok=True)
        for old in list(recent_dir.rglob("*.lnk")):
            old.unlink(missing_ok=True)
        for folder in sorted((p for p in recent_dir.rglob("*") if p.is_dir()), reverse=True):
            if not any(folder.iterdir()):
                folder.rmdir()
        settings = self.config.get("recent_work", {})
        groups = sorter.recent_files(self.root, list(self.config["projects"]),
                                     settings.get("days", 14), settings.get("files_per_project", 5))
        shortcuts = []
        for project, files in groups.items():
            folder = recent_dir / project
            folder.mkdir(exist_ok=True)
            for number, path in enumerate(files, start=1):
                shortcuts.append((folder / f"{number} {path.name}.lnk", path, "", path.parent))
        winutils.create_shortcuts(shortcuts)
        return len(shortcuts)

    # ------------------------------------------------------------ messages from the right click menu

    def collect_notices(self):
        entries = []
        for notice in sorted(notices_folder().glob("*.json")):
            try:
                entries.append(json.loads(notice.read_text(encoding="utf-8")))
                notice.unlink()
            except (OSError, ValueError):
                pass
        return entries

    def notify(self, text):
        shown = False
        if self.icon is not None and text:
            try:
                self.icon.notify(text, "File Organizer")
                shown = True
            except Exception:
                shown = False
        return shown

    # ------------------------------------------------------------ the main loop

    def loop(self, icon=None):
        if icon is not None:
            icon.visible = True
        last_sweep = 0
        last_refresh = 0
        while not self.stop_event.is_set():
            heartbeat_file().touch()
            self.reload_config()
            moves = self.collect_notices()
            if not self.paused and time.time() - last_sweep >= self.config.get("check_every_seconds", 30):
                moves += self.sweep()
                last_sweep = time.time()
            refresh_every = self.config.get("recent_work", {}).get("refresh_minutes", 30) * 60
            if moves or time.time() - last_refresh >= refresh_every:
                self.refresh_recent_work()
                last_refresh = time.time()
            if moves:
                self.notify(describe_moves(moves))
            self.stop_event.wait(TICK_SECONDS)
        return None

    # ------------------------------------------------------------ tray menu actions

    def on_open_projects(self):
        self.root.mkdir(parents=True, exist_ok=True)
        return winutils.open_folder(self.root)

    def on_open_recent(self):
        return winutils.open_folder(self.desktop / "Recent Work")

    def on_tidy_now(self):
        moves = self.sweep(ignore_age=True)
        self.refresh_recent_work()
        return self.notify(describe_moves(moves) if moves else "Everything is already tidy")

    def on_toggle_pause(self):
        self.paused = not self.paused
        return self.notify("Paused" if self.paused else "Running again")

    def on_undo(self):
        with self.lock:
            restored = sorter.undo_last(1)
        self.refresh_recent_work()
        return self.notify(f"Put {restored[0].name} back" if restored else "Nothing to undo")

    def on_settings(self):
        return winutils.open_folder(CONFIG_PATH)

    def on_quit(self):
        self.stop_event.set()
        if self.icon is not None:
            self.icon.stop()
        return None

    def start(self):
        """Show the icon near the clock and run the loop in the background."""
        import pystray
        from pystray import Menu, MenuItem as Item
        menu = Menu(
            Item("Open Projects", self.on_open_projects, default=True),
            Item("Open Recent Work", self.on_open_recent),
            Menu.SEPARATOR,
            Item("Tidy up now", self.on_tidy_now),
            Item("Undo last move", self.on_undo),
            Item("Pause", self.on_toggle_pause, checked=lambda item: self.paused),
            Item("Settings", self.on_settings),
            Menu.SEPARATOR,
            Item("Quit", self.on_quit),
        )
        self.icon = pystray.Icon("FileOrganizer", make_icon_image(), "File Organizer", menu)
        self.icon.run(setup=self.loop)
        return None


def main():
    parser = argparse.ArgumentParser(description="Keeps your files organized by project and date.")
    parser.add_argument("--sort", metavar="FILE", help="sort one file, letting the organizer choose")
    parser.add_argument("--move-to", nargs=2, metavar=("FILE", "PROJECT"), help="move one file into a project")
    parser.add_argument("--once", action="store_true", help="tidy once and refresh Recent Work, then exit")
    parser.add_argument("--undo", type=int, metavar="N", help="put the last N moved files back")
    args = parser.parse_args()
    organizer = Organizer()
    if args.sort:
        organizer.sort_one(Path(args.sort))
    elif args.move_to:
        organizer.sort_one(Path(args.move_to[0]), args.move_to[1])
    elif args.once:
        moves = organizer.sweep(ignore_age=True)
        organizer.refresh_recent_work()
        print(describe_moves(moves) if moves else "Nothing to sort")
    elif args.undo:
        for path in sorter.undo_last(args.undo):
            print(f"Put back: {path}")
    elif not winutils.already_running():
        organizer.start()
    return None


if __name__ == "__main__":
    main()
