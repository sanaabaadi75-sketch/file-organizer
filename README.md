# File Organizer

A small program that keeps your Windows computer tidy on its own. It quietly files the loose files in your personal folders (Desktop, Downloads, Documents, Pictures, Videos and Music) into a Projects folder, sorted by subject and then by year and month, and it keeps a Recent Work folder on your Desktop that shows what you changed most recently in each project. You never have to search or remember names.

## What you will see after installing

Your Desktop will show a **Projects** shortcut and a **Recent Work** folder. Inside Recent Work there is one folder per project, holding shortcuts to your five most recently changed files in that project, newest first (numbered 1, 2, 3...). It refreshes every time the computer starts and every 30 minutes.

Your Projects folder looks like this:

```
Projects
  School
    2026
      10
        lab4.cpp
  Finances
  Photos
    2026
      09
        IMG_0412.jpg
  Job Search
  ...
  To Review      (files it was not sure about, also by year and month)
```

A small yellow folder icon sits near the clock (it may be hidden under the ^ arrow). Clicking it lets you open Projects, tidy up immediately, undo the last move, pause, or open the settings.

When you right click any file you get an **Organize** menu with "Sort for me" and "Move to School", "Move to Finances", and so on. On Windows 11 this menu is inside **Show more options** at the bottom of the right click menu.

Projects and Recent Work are also pinned to the left sidebar of File Explorer, so they appear in every Open and Save window too.

## How it decides where a file goes

First it checks simple rules: words in the file's name and inside the file (for example "assignment" means School, "receipt" or "bank" means Finances) and the file type (a .jpg goes to Photos, an .mp3 to Music). If the rules are clearly sure, that decides it.

If the rules are not sure and you have installed the free Ollama program, it asks a small AI model running on your own laptop, which reads the start of the file and picks a project. Nothing is sent to the internet.

If neither is sure, the file goes into **To Review** so nothing ever gets lost.

It waits two minutes after a file was last changed before moving it, so it will not snatch something you are still working on. It never touches shortcuts, hidden files, files that are still downloading, Word or Excel files that are open, or new files still called "New Text Document".

## Files inside folders

It also tidies files inside everyday subfolders of the watched folders (up to three levels deep), and removes a subfolder once it is empty. It leaves these folders exactly as they are, without looking inside:

- **Programming projects**: any folder with signs of code, such as `.git`, `package.json`, `requirements.txt`, `Makefile`, a Visual Studio `.sln`, or mostly code files.
- **Program folders**: anything holding files a program needs, such as `.dll` files or Outlook data files.
- Folders that programs keep in Documents for themselves (Zoom, Custom Office Templates, My Games and so on), hidden folders, and any folder you add to `"leave_folders_alone"` in `config.json`.

To keep the old behaviour (loose files only), set `"sort_inside_folders": false`.

## Files that belong together

Files that depend on each other are moved together into one folder named after the main file, so nothing breaks:

- Files with the same name and different types: `movie.mp4` and `movie.srt`, `trip.part1.rar` and `trip.part2.rar`.
- A saved web page and its `_files` folder.
- A page, note or playlist and the files it mentions: an `.html` page and its `style.css` and `pics` folder, a `.md` note and its pictures, a `.cue` and its `.bin`, an `.m3u` playlist and its songs.

The files themselves are never renamed, because a page or playlist would stop finding them. Undo puts back the whole group at once.

## Installing

1. Install Python from python.org (tick **Add Python to PATH** during setup).
2. Put this File Organizer folder somewhere permanent, such as `Documents\File Organizer`. Do not leave it in Downloads, because the organizer would try to file itself.
3. Double click **install.bat**. On the first run it creates your own `config.json` from `config.example.json`.

That is all. It starts now and every time Windows starts.

**Important:** the first run files away every loose file already sitting in the watched folders (except folders and shortcuts). To watch fewer folders, copy `config.example.json` to `config.json` and shorten `"watch_folders"` before installing, for example `["Desktop", "Downloads"]`. The folders you can list are Desktop, Downloads, Documents, Pictures, Videos and Music.

### Optional: turn on the AI

1. Install Ollama from ollama.com.
2. Open Command Prompt and run `ollama pull qwen3.5:4b`
3. In `config.json`, set `"enabled": true` under `"ai"`.

The AI is off by default. Without it, everything still works using the rules and the To Review folder, and sorting is much faster.

## Changing your projects

Click the tray icon and choose **Settings**, which opens `config.json`. Each project has a description (what the AI reads), keywords (what the rules look for), and optional file extensions. Add, rename, or remove projects there and save. The running program picks up the changes automatically. After changing the list of projects, double click **install.bat** once more so the right click menu matches.

`projects_folder` is `"auto"`, which puts Projects inside OneDrive if you use it (so it also appears on your phone in the OneDrive app), otherwise inside Documents. You can type any folder path instead, for example `"G:\\My Drive\\Projects"` for Google Drive.

## Undo and safety

The organizer only ever moves files, never deletes them. Every move is written to a log. **Undo last move** in the tray menu puts the file back exactly where it was, and from then on the organizer leaves that file alone. To undo several moves at once, open Command Prompt in this folder and run `py organizer.py --undo 10`.

## Removing it

Double click **uninstall.bat**, then right click the tray icon and choose Quit. Your Projects folder and every file in it stay exactly as they are.

## The code

| File | What it does |
|---|---|
| `sorter.py` | Reads files, scores them against your rules, asks the AI, moves files, keeps the log and undo |
| `organizer.py` | The background app: checks the watched folders every 30 seconds, builds Recent Work, tray icon |
| `winutils.py` | Windows specific parts: finding your real Desktop, making shortcuts, pinning to the sidebar |
| `windows_setup.py` | Install and uninstall: startup entry, right click menu, Desktop shortcut |
| `config.example.json` | Starting projects and settings, copied to `config.json` (your own, not tracked by git) on first run |

Every function has exactly one return statement.
