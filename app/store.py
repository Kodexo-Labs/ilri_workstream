"""Writing to the data folder.

The evidence folder is the input surface, and until now the only way to change
it was a text editor. That matters more than it sounds: the whole point of this
workflow is that someone can put new material in front of it and rerun, and if
that requires a terminal then the tool only works for the person who built it.

Everything here writes plain markdown to `DATA_DIR`. No database, no upload
store — the files stay exactly as readable and as diffable as they were when
someone dropped them in by hand.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

MARKDOWN_SUFFIXES = {".md", ".markdown", ".txt"}
# Large enough for a quarter's Teams export or a long minutes file. The
# browser posts multipart parts, and Starlette's default 1 MB cap used to
# refuse anything bigger before this store even saw it.
MAX_UPLOAD_BYTES = 10_000_000
MAX_UPLOAD_FILES = 500


class StoreError(ValueError):
    """Something the person can fix, phrased so they can fix it."""


def slugify(text: str) -> str:
    normalised = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalised).strip("-").lower()
    return slug[:60] or "document"


def safe_target(evidence_dir: Path, filename: str) -> Path:
    """Resolve a filename inside the evidence folder, or refuse.

    Anything with a path separator, a parent reference, or a resolved location
    outside the folder is rejected rather than sanitised — quietly rewriting a
    suspicious path is how a traversal bug survives review.
    """
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise StoreError(f"{filename!r} is not a valid document name")

    target = (evidence_dir / filename).resolve()
    if target.parent != evidence_dir.resolve():
        raise StoreError(f"{filename!r} is outside the evidence folder")
    if target.suffix.lower() not in MARKDOWN_SUFFIXES:
        raise StoreError(f"{target.suffix or 'that'} is not a markdown file")
    return target


def unique_path(evidence_dir: Path, slug: str) -> Path:
    candidate = evidence_dir / f"{slug}.md"
    counter = 2
    while candidate.exists():
        candidate = evidence_dir / f"{slug}-{counter}.md"
        counter += 1
    return candidate


_UNSAFE_FILENAME = re.compile(r'[<>:"|?*]')


def original_filename(filename: str) -> str:
    """The name the director chose, minus any path. Not a slug."""
    name = Path(filename).name
    if (
        not name
        or name in {".", ".."}
        or name.startswith(".")
        or "/" in name
        or "\\" in name
        or _UNSAFE_FILENAME.search(name)
    ):
        raise StoreError(f"{filename!r} is not a valid document name")
    suffix = Path(name).suffix.lower()
    if suffix not in MARKDOWN_SUFFIXES:
        raise StoreError(f"{filename} is not markdown or plain text.")
    if not Path(name).stem.strip():
        raise StoreError(f"{filename!r} is not a valid document name")
    return name


def unique_named(directory: Path, filename: str) -> Path:
    """Keep the original filename. Number it only when that name is taken."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def compose_markdown(title: str, body: str, date: str = "") -> str:
    """Build a document the loader can read back.

    The loader takes the date from the heading, falling back to an italic line
    just beneath it. Writing the date on its own line means a title does not
    have to be phrased in any particular way to be dated correctly.
    """
    title = title.strip()
    body = body.strip()
    lines = [f"# {title}", ""]
    if date.strip():
        lines += [f"*{date.strip()}*", ""]
    lines += [body, ""]
    return "\n".join(lines)


def add_pasted(evidence_dir: Path, title: str, body: str, date: str = "") -> Path:
    if not title.strip():
        raise StoreError("Give the document a title — it is what the reader sees first.")
    if not body.strip():
        raise StoreError("Paste the document text.")

    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = unique_path(evidence_dir, slugify(title))
    path.write_text(compose_markdown(title, body, date), encoding="utf-8")
    return path


def add_uploaded(evidence_dir: Path, filename: str, content: bytes) -> Path:
    if not content:
        raise StoreError(f"{filename} is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // 1_000_000
        raise StoreError(f"{filename} is larger than {limit_mb} MB.")

    suffix = Path(filename).suffix.lower()
    if suffix not in MARKDOWN_SUFFIXES:
        raise StoreError(f"{filename} is not markdown or plain text.")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StoreError(f"{filename} is not valid UTF-8 text.") from error

    evidence_dir.mkdir(parents=True, exist_ok=True)
    name = original_filename(filename)
    path = unique_named(evidence_dir, name)

    # Give it a heading if it has none, so the loader has a title to show.
    if not text.lstrip().startswith("#"):
        text = f"# {Path(name).stem}\n\n{text}"
    path.write_text(text, encoding="utf-8")
    return path


def remove(evidence_dir: Path, filename: str) -> None:
    target = safe_target(evidence_dir, filename)
    if not target.exists():
        raise StoreError(f"{filename} is not there.")
    target.unlink()


def remove_workspace(settings, filename: str) -> None:
    """Delete a named file wherever the workspace keeps it.

    The setup screen lists the objective record and the prior row beside the
    evidence files, so the same remove control has to work on all three.
    """
    path, _role = resolve_workspace_document(settings, filename)
    path.unlink()
    forget_role(settings, filename)


def clear_workspace(settings) -> list[str]:
    """Remove every document the setup screen can show.

    The demo pack is the way back in. Draft runs are left alone — they have
    their own delete — so clearing the input folder does not erase a review
    already in flight. Assigned roles go with the files; a later upload does
    not inherit them.
    """
    removed: list[str] = []
    for path in (settings.objective_file, settings.prior_update_file):
        if path.is_file():
            removed.append(path.name)
            path.unlink()
    evidence_dir = settings.evidence_dir
    if evidence_dir.is_dir():
        for path in sorted(evidence_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in MARKDOWN_SUFFIXES:
                removed.append(path.name)
                path.unlink()
    roles_path = _roles_path(settings)
    if roles_path.exists():
        roles_path.unlink()
    return removed


def read_document(evidence_dir: Path, filename: str) -> str:
    return safe_target(evidence_dir, filename).read_text(encoding="utf-8")


def write_document(evidence_dir: Path, filename: str, text: str) -> Path:
    if not text.strip():
        raise StoreError("A document cannot be empty. Delete it instead.")
    target = safe_target(evidence_dir, filename)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")
    return target


def resolve_workspace_document(settings, filename: str) -> tuple[Path, str]:
    """Find a named file wherever the workspace keeps it.

    Uploaded files keep their names in the evidence folder. The demo pack
    still writes the objective record and prior row beside that folder. The
    edit link is the same for every file on the setup screen.
    """
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise StoreError(f"{filename!r} is not a valid document name")

    roles = read_roles(settings)
    evidence_dir = settings.evidence_dir
    try:
        target = safe_target(evidence_dir, filename)
    except StoreError:
        target = None
    if target is not None and target.exists():
        if roles.get("objective") == filename:
            return target, "objective"
        if roles.get("prior") == filename:
            return target, "prior"
        return target, "evidence"

    named = {
        settings.objective_file.name: (settings.objective_file, "objective"),
        settings.prior_update_file.name: (settings.prior_update_file, "prior"),
    }
    special = named.get(filename)
    if special is not None and special[0].exists():
        return special

    raise StoreError(f"{filename} is not there.")


def write_workspace_document(path: Path, text: str) -> Path:
    if not text.strip():
        raise StoreError("A document cannot be empty. Delete it instead.")
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


# --- roles -------------------------------------------------------------------
# A file's role is a label the director sets, not a rename and not a guess.
# Uploaded documents stay in the evidence folder under the name they arrived
# with. `roles.json` records which of those names is the objective record and
# which is the previous quarter row. The demo pack still writes the two
# reference files beside the folder; those are used only when nothing has
# been assigned yet.


def _roles_path(settings) -> Path:
    return settings.data_dir / "roles.json"


def read_roles(settings) -> dict[str, str]:
    path = _roles_path(settings)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: name
        for key, name in data.items()
        if key in ("objective", "prior") and isinstance(name, str) and name
    }


def write_roles(settings, roles: dict[str, str]) -> None:
    path = _roles_path(settings)
    cleaned = {
        key: name
        for key, name in roles.items()
        if key in ("objective", "prior") and name
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")


def forget_role(settings, filename: str) -> None:
    roles = read_roles(settings)
    changed = False
    for key in ("objective", "prior"):
        if roles.get(key) == filename:
            del roles[key]
            changed = True
    if changed:
        write_roles(settings, roles)


def _existing(path: Path) -> Path | None:
    try:
        if path.is_file():
            return path
    except OSError:
        return None
    return None


def _path_for_role(settings, role: str) -> Path | None:
    """The file marked as `role`, if any.

    Once the director has used the role dropdown, `roles.json` is the only
    source — leftover demo files are not silently adopted. Until then the
    demo pack's copies beside the evidence folder still count.
    """
    slot = settings.objective_file if role == "objective" else settings.prior_update_file
    roles_exist = _roles_path(settings).is_file()
    name = read_roles(settings).get(role)
    if name:
        try:
            path = safe_target(settings.evidence_dir, name)
            if path.exists():
                return path
        except StoreError:
            pass
        if name == settings.objective_file.name and settings.objective_file.exists():
            return settings.objective_file
        if name == settings.prior_update_file.name and settings.prior_update_file.exists():
            return settings.prior_update_file
        return None
    if roles_exist:
        return None
    return _existing(slot)


def objective_path(settings) -> Path | None:
    """The file marked as the objective record, or the demo pack's copy."""
    return _path_for_role(settings, "objective")


def prior_path(settings) -> Path | None:
    """The file marked as the previous quarter row, or the demo pack's copy."""
    return _path_for_role(settings, "prior")


def assigned_paths(settings) -> set[Path]:
    """Resolved paths the pipeline must not also read as evidence."""
    found: set[Path] = set()
    for path in (objective_path(settings), prior_path(settings)):
        if path is None:
            continue
        try:
            found.add(path.resolve())
        except OSError:
            found.add(path)
    return found


def set_role(settings, filename: str, role: str, from_role: str = "") -> str:
    """Assign a file as evidence, the objective record or the prior row.

    The file is not moved and not renamed. Changing the dropdown only
    updates which name is recorded as that role. `from_role` is accepted
    so the form can post it; lookup is by filename.
    """
    del from_role
    path, current = resolve_workspace_document(settings, filename)
    if role not in ("evidence", "objective", "prior"):
        raise StoreError(f"{role!r} is not a role.")

    if role == current:
        if role == "evidence":
            return f"{filename} is already evidence."
        label = "objective record" if role == "objective" else "previous quarter row"
        return f"{filename} is already the {label}."

    roles = read_roles(settings)
    displaced = ""

    if role == "evidence":
        if path in (settings.objective_file, settings.prior_update_file):
            settings.evidence_dir.mkdir(parents=True, exist_ok=True)
            dest = unique_named(settings.evidence_dir, path.name)
            dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            path.unlink()
            forget_role(settings, filename)
            if dest.name != filename:
                return f"{filename} is now evidence, as {dest.name}."
            return f"{filename} is now evidence."
        forget_role(settings, filename)
        return f"{filename} is now evidence."

    previous = roles.get(role)
    if previous and previous != filename:
        displaced = f" {previous} is evidence again."

    other = "prior" if role == "objective" else "objective"
    if roles.get(other) == filename:
        del roles[other]

    # A file sitting in the demo pack's slot keeps that name; uploaded
    # files keep theirs. Either way the assignment is the name, not a copy.
    roles[role] = path.name
    write_roles(settings, roles)

    label = "objective record" if role == "objective" else "previous quarter row"
    return f"{filename} is now the {label}.{displaced}"


# --- the objective record ----------------------------------------------------


def write_field_table(path: Path, title: str, fields: dict[str, str]) -> None:
    """Write a `| Field | Value |` table, the shape the loader reads."""
    rows = "\n".join(f"| `{key}` | {value or '—'} |" for key, value in fields.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {title}\n\n| Field | Value |\n|---|---|\n{rows}\n", encoding="utf-8"
    )


def update_objective(path: Path, existing: dict[str, str], changes: dict[str, str]) -> None:
    """Apply changes, keeping every field the form did not carry.

    A form that shows four fields must not silently drop the ten it does not.
    """
    merged = dict(existing)
    merged.update({k: v for k, v in changes.items() if v is not None})
    merged["Last_Modified"] = dt.date.today().isoformat()
    write_field_table(path, f"Level2_Objectives — {merged.get('Objective_ID', 'record')}", merged)
