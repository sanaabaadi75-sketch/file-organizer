"""Core logic: read a file, decide which project it belongs to, move it, and log the move.

Nothing in here is Windows specific, so it can be tested on any computer.
Every function has exactly one return statement.
"""
import json
import os
import re
import shutil
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# Files that should never be moved automatically
SKIP_SUFFIXES = {".lnk", ".url", ".ini", ".tmp", ".crdownload", ".part", ".partial", ".download", ".opdownload"}
SKIP_NAME_STARTS = ("~$", ".", "New Text Document", "New Microsoft", "New Rich Text", "New Bitmap")

# Files whose text we can read directly
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".cs", ".cpp", ".c", ".h", ".hpp",
                 ".php", ".html", ".sql", ".r", ".ino", ".java", ".xml", ".log", ".ipynb"}
MAX_TEXT = 3000
HIDDEN_FLAG = 2


# ---------------------------------------------------------------- places we keep our own data

def data_folder():
    """Folder for the move log and the ignore list (outside the Projects folder so it stays clean)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    folder = Path(base) / "FileOrganizer"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def ensure_config(config_path):
    """On first run, start your own config.json from config.example.json."""
    example = config_path.with_name("config.example.json")
    created = not config_path.exists() and example.exists()
    if created:
        shutil.copyfile(example, config_path)
    return created


def load_config(config_path):
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)
    return config


# ---------------------------------------------------------------- which files to leave alone

def load_ignored():
    """Files the user moved back with Undo. We never auto sort these again."""
    ignore_file = data_folder() / "ignored.json"
    ignored = set()
    if ignore_file.exists():
        try:
            ignored = set(json.loads(ignore_file.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            ignored = set()
    return ignored


def save_ignored(ignored):
    ignore_file = data_folder() / "ignored.json"
    ignore_file.write_text(json.dumps(sorted(ignored), indent=2), encoding="utf-8")
    return len(ignored)


def is_open_in_office(path):
    """Word and Excel create a '~$name' file next to a document while it is open."""
    lock_name = "~$" + path.name[2:]
    return (path.parent / lock_name).exists()


def is_hidden(path):
    attributes = getattr(path.stat(), "st_file_attributes", 0)
    return bool(attributes & HIDDEN_FLAG)


def is_sortable(path, automatic=True):
    """True when a file is safe to move. Folders, shortcuts, hidden and half downloaded files are skipped."""
    sortable = False
    try:
        sortable = (path.is_file()
                    and path.suffix.lower() not in SKIP_SUFFIXES
                    and not path.name.startswith(SKIP_NAME_STARTS)
                    and not is_hidden(path)
                    and not is_open_in_office(path))
        if sortable and automatic:
            sortable = str(path) not in load_ignored()
    except OSError:
        sortable = False
    return sortable


# ---------------------------------------------------------------- reading what is inside a file

def extract_text(path):
    """Return the first few thousand characters of text inside the file, or an empty string."""
    suffix = path.suffix.lower()
    text = ""
    try:
        if suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
        elif suffix == ".docx":
            import docx
            document = docx.Document(str(path))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        elif suffix == ".pptx":
            from pptx import Presentation
            deck = Presentation(str(path))
            text = "\n".join(shape.text for slide in deck.slides for shape in slide.shapes if hasattr(shape, "text"))
    except Exception:
        text = ""
    return text[:MAX_TEXT]


# ---------------------------------------------------------------- choosing a project with simple rules

def keyword_pattern(keyword):
    """Match a keyword as its own word, so 'lab' matches 'lab3' but not 'label'."""
    return re.compile(r"(?<![a-z])" + re.escape(keyword.lower()) + r"(?![a-z])")


def keyword_scores(file_name, suffix, text, projects):
    """Give every project points: 3 per keyword in the file name, 1 per keyword in the text (max 5), 3 for a matching file type."""
    name_lower = file_name.lower()
    text_lower = text.lower()
    scores = {}
    for project, info in projects.items():
        score = 0
        for keyword in info.get("keywords", []):
            pattern = keyword_pattern(keyword)
            score += 3 * len(pattern.findall(name_lower))
            score += min(len(pattern.findall(text_lower)), 5)
        if suffix.lower() in [ext.lower() for ext in info.get("extensions", [])]:
            score += 3
        if score > 0:
            scores[project] = score
    return scores


def pick_by_rules(scores, min_score):
    """Pick the top project only if it scored enough and clearly beat the runner up."""
    choice = None
    if scores:
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_project, best_score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        if best_score >= min_score and best_score > runner_up:
            choice = best_project
    return choice


# ---------------------------------------------------------------- choosing a project with AI

def match_project_name(answer, project_names):
    """Turn the AI's reply into one of our project names, or None."""
    cleaned = answer.strip().strip(".\"'*` ").lower()
    choice = None
    for name in project_names:
        if cleaned == name.lower():
            choice = name
    if choice is None and "none" not in cleaned.split():
        for name in sorted(project_names, key=len, reverse=True):
            if choice is None and name.lower() in cleaned:
                choice = name
    return choice


def build_prompt(file_name, text, projects):
    project_lines = "\n".join(f"{name}: {info.get('description', '')}" for name, info in projects.items())
    content = text.strip() or "(no readable text, decide from the file name)"
    prompt = (
        "You are sorting a file from someone's computer into one of their project folders.\n\n"
        f"Projects:\n{project_lines}\n\n"
        f"File name: {file_name}\n"
        f"Start of the file's content:\n\"\"\"\n{content[:2000]}\n\"\"\"\n\n"
        "Reply with only the project name exactly as written above. "
        "If no project clearly fits, reply NONE."
    )
    return prompt


def ask_ai(file_name, text, projects, ai_settings):
    """Ask a local Ollama model. Returns a project name, or None if AI is off, unavailable, or unsure."""
    choice = None
    if ai_settings.get("enabled"):
        body = json.dumps({
            "model": ai_settings.get("model", "llama3.2:3b"),
            "prompt": build_prompt(file_name, text, projects),
            "stream": False,
            "options": {"temperature": 0},
        }).encode("utf-8")
        url = ai_settings.get("url", "http://localhost:11434").rstrip("/") + "/api/generate"
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=ai_settings.get("timeout_seconds", 60)) as response:
                answer = json.loads(response.read().decode("utf-8")).get("response", "")
            choice = match_project_name(answer, list(projects))
        except Exception:
            choice = None
    return choice


def classify(path, config):
    """Rules first, AI second, To Review if neither is sure. Returns (project, how it was decided)."""
    projects = config["projects"]
    text = extract_text(path)
    scores = keyword_scores(path.stem, path.suffix, text, projects)
    project = pick_by_rules(scores, config.get("min_keyword_score", 2))
    method = "rules"
    if project is None:
        project = ask_ai(path.name, text, projects, config.get("ai", {}))
        method = "ai"
    if project is None:
        project = config.get("review_folder", "To Review")
        method = "review"
    return project, method


# ---------------------------------------------------------------- moving and logging

def unique_path(target):
    """If a file with that name already exists, add (2), (3), and so on."""
    candidate = target
    counter = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
        counter += 1
    return candidate


def destination_for(path, project, root):
    """Projects/<Project>/<Year>/<Month>/file, based on when the file was last changed (To Review too)."""
    when = datetime.fromtimestamp(path.stat().st_mtime)
    folder = root / project / f"{when:%Y}" / f"{when:%m}"
    return unique_path(folder / path.name)


def log_move(source, target, project, method):
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "from": str(source),
             "to": str(target), "project": project, "method": method}
    with open(data_folder() / "moves.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def sort_file(path, config, root, forced_project=None):
    """Move one file into its project. Returns a small summary dict."""
    if forced_project:
        project, method = forced_project, "manual"
        ignored = load_ignored()
        ignored.discard(str(path))
        save_ignored(ignored)
    else:
        project, method = classify(path, config)
    target = destination_for(path, project, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    entry = log_move(path, target, project, method)
    return entry


# ---------------------------------------------------------------- undo

def read_log():
    log_file = data_folder() / "moves.jsonl"
    entries = []
    if log_file.exists():
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


def undo_last(count=1):
    """Put the last few moved files back where they were, and stop auto sorting them."""
    entries = read_log()
    count = max(0, min(count, len(entries)))
    to_undo = entries[len(entries) - count:]
    kept = entries[:len(entries) - count]
    ignored = load_ignored()
    restored = []
    for entry in reversed(to_undo):
        source, target = Path(entry["from"]), Path(entry["to"])
        if target.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(source))
            ignored.add(str(source))
            restored.append(source)
    save_ignored(ignored)
    with open(data_folder() / "moves.jsonl", "w", encoding="utf-8") as handle:
        handle.writelines(json.dumps(entry) + "\n" for entry in kept)
    return restored


# ---------------------------------------------------------------- recent work

def recent_files(root, project_names, days, per_project):
    """For each project, the files changed most recently (newest first)."""
    cutoff = time.time() - days * 86400
    result = {}
    for name in project_names:
        folder = root / name
        files = []
        if folder.exists():
            for path in folder.rglob("*"):
                try:
                    if path.is_file() and is_sortable(path, automatic=False) and path.stat().st_mtime >= cutoff:
                        files.append(path)
                except OSError:
                    pass
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        if files:
            result[name] = files[:per_project]
    return result
