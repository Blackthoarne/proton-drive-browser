"""Thin wrapper around the Proton Drive CLI.

Every Drive operation runs the `proton-drive` executable as a subprocess.
Nothing here talks to the Proton API directly.

Command shapes come from the CLI source (ProtonDriveApps/sdk, cli/, v0.9.0).
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime

CLI_ENV = "PROTON_DRIVE_CLI"
CLI_NAME = "proton-drive"

MY_FILES = "/my-files"
SHARED_WITH_ME = "/shared-with-me"
DEVICES = "/devices"
TRASH = "/trash"

LIST_TIMEOUT = 180


class CliError(Exception):
    """The CLI ran and failed. `message` is short, `details` is everything it printed."""

    def __init__(self, message, details=""):
        super().__init__(message)
        self.message = message
        self.details = details


class CliMissingError(CliError):
    pass


class AuthRequiredError(CliError):
    pass


class CancelledError(CliError):
    pass


@dataclass
class Node:
    uid: str
    name: str
    is_folder: bool
    size: int | None
    modified: datetime | None
    media_type: str | None


def find_cli():
    candidates = [os.environ.get(CLI_ENV), shutil.which(CLI_NAME), os.path.expanduser(f"~/.local/bin/{CLI_NAME}")]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def escape_name(name):
    # The CLI splits paths on "/" and accepts "\/" for a literal slash in a name.
    return name.replace("/", "\\/")


def item_ref(section, node):
    """Remote path for one item. The CLI resolves a node UID used as a path part."""
    if section == TRASH:
        # Trashed items resolve by name only.
        return f"{TRASH}/{escape_name(node.name)}"
    return f"{section}/{node.uid}"


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _result_value(result, fallback):
    """Read the SDK's Result<T, Error> shape: {"ok": true, "value": ...}."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if result.get("ok") and isinstance(result.get("value"), str):
            return result["value"]
        error = result.get("error")
        if isinstance(error, dict) and isinstance(error.get("name"), str):
            return error["name"]
    return fallback


def node_from_json(data):
    if "rootFolderUid" in data:
        # A device entry from `filesystem list /devices`.
        uid = data["rootFolderUid"]
        return Node(uid, _result_value(data.get("name"), uid), True, None, None, None)

    uid = data.get("uid", "")
    revision = data.get("activeRevision") or {}
    folder = data.get("folder") or {}
    is_folder = data.get("type") != "file"
    modified = (
        _parse_date(revision.get("claimedModificationTime"))
        or _parse_date(folder.get("claimedModificationTime"))
        or _parse_date(data.get("modificationTime"))
    )
    size = None if is_folder else revision.get("claimedSize")
    return Node(uid, _result_value(data.get("name"), uid), is_folder, size, modified, data.get("mediaType"))


def _short_message(stderr, stdout):
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip() and not line.startswith("====")]
    if lines:
        return lines[0]
    failed = [line.strip() for line in (stdout or "").splitlines() if line.strip().startswith("❌")]
    if failed:
        return failed[0].lstrip("❌ ")
    return "The Proton Drive CLI failed without an error message."


def _raise_for(returncode, stdout, stderr):
    message = _short_message(stderr, stdout)
    details = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)
    if "You need to login first" in message:
        raise AuthRequiredError("You are not signed in to Proton Drive.", details)
    raise CliError(message, details or f"Exit code {returncode}")


class Process:
    """One running CLI command. `cancel()` may be called from another thread."""

    def __init__(self, args):
        cli = find_cli()
        if not cli:
            raise CliMissingError(
                f"The Proton Drive CLI ({CLI_NAME}) was not found.",
                f"Install it to ~/.local/bin/{CLI_NAME}, put it on PATH, or set {CLI_ENV}.",
            )
        self.args = [cli, *args]
        self.cancelled = False
        self._proc = subprocess.Popen(
            self.args,
            stdin=subprocess.DEVNULL,  # never block on an interactive prompt
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def wait(self, timeout=None):
        try:
            stdout, stderr = self._proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            stdout, stderr = self._proc.communicate()
            raise CliError(f"The Proton Drive CLI did not answer within {timeout} seconds.", stderr + stdout)
        if self.cancelled:
            raise CancelledError("Cancelled.", stderr + stdout)
        if self._proc.returncode != 0:
            _raise_for(self._proc.returncode, stdout, stderr)
        return stdout

    def cancel(self):
        self.cancelled = True
        if self._proc.poll() is None:
            self._proc.terminate()


def run(args, timeout=None):
    return Process(args).wait(timeout)


def list_folder(path, folders_only=False):
    args = ["filesystem", "list", "--json"]
    if folders_only:
        args += ["--type", "folder"]
    stdout = run([*args, "--", path], timeout=LIST_TIMEOUT)
    try:
        items = json.loads(stdout or "[]")
    except json.JSONDecodeError as error:
        raise CliError("The Proton Drive CLI returned output this app cannot read.", f"{error}\n\n{stdout}")
    return [node_from_json(item) for item in items if isinstance(item, dict)]


# Each builder returns the CLI arguments. The GUI runs them through Process so it can cancel.
# Uploads add a new revision when a file exists (Proton keeps the old one); downloads never
# overwrite a local file. Folders merge in both directions.


def upload_args(local_paths, parent_path):
    return ["filesystem", "upload", "--json", "-f", "create-new-revision", "-d", "merge", "--", *local_paths, parent_path]


def download_args(refs, local_folder):
    return ["filesystem", "download", "--json", "-f", "rename", "-d", "merge", "--", *refs, local_folder]


def open_download_args(ref, local_folder):
    # A private cache folder: replace any earlier copy.
    return ["filesystem", "download", "--json", "-f", "remove", "-d", "merge", "--", ref, local_folder]


def create_folder_args(parent_path, name):
    return ["filesystem", "create-folder", "--json", "--", parent_path, name]


def rename_args(ref, new_name):
    return ["filesystem", "rename", "--json", "--", ref, new_name]


# Batch commands print one "✅ name" or "❌ name: reason" line per item. The --json form
# loses the reason (the error serialises as {}), so these use the readable output.


def move_args(refs, target_path):
    return ["filesystem", "move", "--", *refs, target_path]


def trash_args(refs):
    return ["filesystem", "trash", "--", *refs]


def restore_args(refs):
    return ["filesystem", "restore", "--", *refs]


def delete_args(refs):
    return ["filesystem", "delete", "--", *refs]


def empty_trash_args():
    return ["filesystem", "empty-trash"]


def batch_failures(stdout):
    """Lines for items that failed in a move, trash, restore or delete."""
    return [line.strip()[1:].strip() for line in stdout.splitlines() if line.strip().startswith("❌")]
