"""Keeping a record safely: whole or not at all, one writer at a time,
checked against its schema, and saying which code made it.

Every JSON file a script keeps goes through write() or change():

- write() puts the record in NAME.part, flushes it to the disk and renames
  it over NAME, so a crash or a full disk leaves the old file whole, never
  half of the new one.
- change() holds a lock on the file while it reads, changes and writes it,
  so two processes changing it at once (the patrol adding a night while a
  person dismisses a candidate) cannot lose one another's change.
- With a schema (a name in schemas/), the record is checked before it
  replaces anything. One that does not match is kept beside the file as
  NAME.rejected.json for a person to look at, the old file stays as it was,
  and the write raises.
- With `stamp`, a copy carries "provenance": the telescopeyoke version, the
  git commit it ran from and whether that had changes not committed, the
  schema version, the record's own format version, the Python and the
  numerical libraries' versions, when it was made, and a fingerprint of the
  settings (the site and the Telegram bot are left out of it). Every
  scientific result is stamped, so a candidate found in six months' time
  says which difference.py found it.
"""
import contextlib
import functools
import hashlib
import json
import os
import platform
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMAS = ROOT / "schemas"
PRIVATE = ("site", "telegram", "horizon")   # left out of the settings' fingerprint


class Rejected(ValueError):
    """A record that does not match its schema: it was not written."""


@functools.cache
def version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


@functools.cache
def commit():
    """(commit, changed): the git commit this code is, and whether tracked
    files differ from it; (None, None) outside a git checkout, unless
    TY_CODE_COMMIT says (a copy restack.py --on HOST sent). Kept for the
    life of the process, which is right: a long-running process goes on
    running the code it started with, whatever is checked out later."""
    sent = os.environ.get("TY_CODE_COMMIT")   # a copy sent by remote.py, without its git history
    if sent:
        sha, _, changed = sent.partition("+")
        return sha, changed == "changed"

    def git(*args):
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10)
    try:
        head = git("rev-parse", "HEAD")
        if head.returncode:
            return None, None
        changed = git("status", "--porcelain", "--untracked-files=no")
        return head.stdout.strip(), bool(changed.stdout.strip()) if changed.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None, None


@functools.cache
def libraries():
    found = {}
    for name in ("numpy", "scipy", "astropy"):
        try:
            found[name] = __import__(name).__version__
        except ImportError:
            found[name] = None
    return found


def fingerprint():
    """A short hash of the settings that shape a result. The site, the
    Telegram bot and the skyline are left out: a record may be shared."""
    import config
    try:
        settings = config._read(config.FILE) if config.FILE.exists() else config.example()
    except Exception:   # a fingerprint is never worth failing a record over
        return None
    kept = {k: v for k, v in settings.items() if k not in PRIVATE}
    return hashlib.sha256(json.dumps(kept, sort_keys=True, default=str).encode()).hexdigest()[:16]


def code():
    """The code in a few characters, for a line in a record: 0.2.1+6bb014d."""
    sha, changed = commit()
    return version() + (f"+{sha[:7]}" if sha else "") + ("-changed" if changed else "")


def provenance(record_version=1):
    import interface
    sha, changed = commit()
    return {"telescopeyoke": version(), "git_commit": sha, "uncommitted_changes": changed,
            "schema_version": interface.SCHEMA_VERSION, "record_version": record_version,
            "python": platform.python_version(), "libraries": libraries(),
            "settings": fingerprint(),
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


@functools.cache
def schema(name):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def check(record, name):
    """Raise Rejected if the record does not match schemas/NAME, or a part
    of one: "reference#/$defs/version" is one version in reference's."""
    import jsonschema
    file, _, part = name.partition("#")
    whole = schema(file)
    against = {"$defs": whole.get("$defs", {}), "$ref": "#" + part} if part else whole
    try:
        jsonschema.validate(record, against)
    except jsonschema.ValidationError as problem:
        where = "/".join(str(p) for p in problem.absolute_path) or "the top"
        raise Rejected(f"{name} record does not match its schema at {where}: {problem.message}") from None


def write(path, record, schema=None, stamp=False, record_version=1, indent=1, default=None):
    """Keep `record` at `path` as JSON, whole or not at all. Returns what
    was written (the record, with its provenance when stamped)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if stamp and isinstance(record, dict):
        record = dict(record, provenance=provenance(record_version))
    text = json.dumps(record, indent=indent, default=default)
    if schema:
        try:
            check(json.loads(text), schema)
        except Rejected:
            path.with_name(path.stem + ".rejected.json").write_text(text, encoding="utf-8")
            raise
    partial = path.with_name(path.name + ".part")
    with open(partial, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    partial.replace(path)
    return record


@contextlib.contextmanager
def locked(path):
    """Hold NAME.lock while the block runs: one process at a time."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a+b") as f:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:   # LK_LOCK gives up after ten seconds; keep waiting
                    continue
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def read(path, empty=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty


def change(path, how, empty=None, **options):
    """Read the record at `path` (or `empty` if there is none yet), let
    how(record) change it in place, and write it, all
    under the file's lock, so nothing another process wrote meanwhile is
    lost. Returns (the record as written, what how returned)."""
    with locked(path):
        record = read(path, empty)
        result = how(record)
        written = write(path, record, **options)
    return written, result
