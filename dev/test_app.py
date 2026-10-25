#!/usr/bin/env python3
"""End-to-end test of Drive Browser against dev/fake-proton-drive (not the real CLI).

Runs the real window, drives it through its actions and dialogs, and checks the
fake drive folder after each step. Usage: python3 -I dev/test_app.py [--screenshots DIR]
"""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
PROJECT = os.path.dirname(HERE)
ROOT = tempfile.mkdtemp(prefix="fake-drive-")
LOCAL = tempfile.mkdtemp(prefix="local-files-")
SHOTS = sys.argv[sys.argv.index("--screenshots") + 1] if "--screenshots" in sys.argv else None

os.environ["PROTON_DRIVE_CLI"] = os.path.join(HERE, "fake-proton-drive")
os.environ["FAKE_DRIVE_ROOT"] = ROOT


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


# Fixtures: a small drive and some local files to upload.
write(f"{ROOT}/my-files/Documents/notes.txt", "notes")
write(f"{ROOT}/my-files/Documents/Budget 2027.xlsx", "x" * 20480)
write(f"{ROOT}/my-files/Pictures/beach.jpg", "jpg")
write(f"{ROOT}/my-files/Storyspire/Itinerary.pdf", "pdf" * 5000)
write(f"{ROOT}/my-files/readme.md", "# readme")
write(f"{LOCAL}/upload-me.txt", "uploaded file")
write(f"{LOCAL}/Upload Folder/inner/deep.txt", "deep")
os.makedirs(f"{ROOT}/trash", exist_ok=True)

loader = importlib.machinery.SourceFileLoader("drive_browser", os.path.join(PROJECT, "drive-browser"))
spec = importlib.util.spec_from_loader("drive_browser", loader)
app_module = importlib.util.module_from_spec(spec)
loader.exec_module(app_module)

# This test writes, moves and deletes. Never let it reach the real CLI and a real account.
FAKE = os.environ["PROTON_DRIVE_CLI"]
if app_module.cli.find_cli() != FAKE:
    sys.exit(f"ABORT: the app would use {app_module.cli.find_cli()}, not the fake CLI {FAKE}.")
app_module.cli.find_cli = lambda: FAKE

from gi.repository import Adw, GLib, Gtk  # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition)))
    print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""), flush=True)


def pump(seconds=0.05):
    end = time.time() + seconds
    ctx = GLib.MainContext.default()
    while time.time() < end:
        ctx.iteration(False)
        time.sleep(0.005)


def wait_until(condition, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        pump(0.05)
        if condition():
            return True
    return False


def names(win):
    return sorted(win.store.get_item(i).node.name for i in range(win.store.get_n_items()))


def loaded(win):
    return win.state_stack.get_visible_child_name() != "loading" and not win.operations


def idle(win):
    start = time.time()
    ok = wait_until(lambda: loaded(win))
    if not ok:
        import threading

        print(f"   TIMEOUT after {time.time() - start:.1f}s: state={win.state_stack.get_visible_child_name()} "
              f"ops={[o.label for o in win.operations]} threads={[t.name for t in threading.enumerate()]}", flush=True)
        subprocess.run(["ps", "-o", "pid,stat,etime,args", "--ppid", str(os.getpid())])
    return ok


def select(win, *wanted):
    win.selection.unselect_all()
    for pos in range(win.selection.get_n_items()):
        if win.selection.get_item(pos).node.name in wanted:
            win.selection.select_item(pos, False)
    pump()


def position(win, name):
    return next(p for p in range(win.selection.get_n_items()) if win.selection.get_item(p).node.name == name)


def dialog(win):
    wait_until(lambda: win.get_visible_dialog() is not None, 3)
    return win.get_visible_dialog()


def answer(win, response, text=None):
    d = dialog(win)
    if d is None:
        return None
    if text is not None:
        row = find(d.get_extra_child(), Adw.EntryRow)
        row.set_text(text)
    enabled = d.get_response_enabled(response) if response in ("ok",) else True
    d.emit("response", response)
    d.force_close()
    pump(0.2)
    return enabled


def find(widget, cls):
    if widget is None:
        return None
    if isinstance(widget, cls):
        return widget
    child = widget.get_first_child()
    while child:
        found = find(child, cls)
        if found:
            return found
        child = child.get_next_sibling()
    return None


def shot(win, name):
    if not SHOTS:
        return
    pump(0.6)
    out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout
    import json

    for c in json.loads(out):
        if c.get("pid") == os.getpid():
            x, y = c["at"]
            w, h = c["size"]
            subprocess.run(["grim", "-g", f"{x},{y} {w}x{h}", os.path.join(SHOTS, f"{name}.png")])


def run_tests(win):
    # Browse
    check("loads My Files", idle(win) and names(win) == ["Documents", "Pictures", "Storyspire", "readme.md"], names(win))
    check("folders sort first", [win.sort_model.get_item(i).node.name for i in range(3)] == ["Documents", "Pictures", "Storyspire"])
    shot(win, "1-my-files")
    win._on_activate(None, position(win, "Documents"))
    check("opens a folder", idle(win) and names(win) == ["Budget 2027.xlsx", "notes.txt"], names(win))
    check("breadcrumb shows path", win.location.display_path() == "/my-files/Documents")
    win.go_back()
    check("back goes to parent", idle(win) and win.location.crumbs == ())
    win.go_forward()
    check("forward returns", idle(win) and win.location.title == "Documents")
    win.path_entry.set_text("/my-files/Pictures")
    win._on_path_entry_activate(win.path_entry)
    check("typed path opens folder", idle(win) and names(win) == ["beach.jpg"], names(win))
    win.navigate(app_module.Location("/my-files"))
    idle(win)

    # Search filters the current folder
    win.toggle_search()
    win.search_entry.set_text("story")
    wait_until(lambda: win.filter_model.get_n_items() == 1, 3)
    check("search filters", win.filter_model.get_n_items() == 1)
    win.toggle_search()
    pump(0.3)

    # New folder, with name validation
    win.activate_action("win.new-folder")
    check("new-folder rejects '/'", answer(win, "cancel", "bad/name") is not None and not dialog_enabled_after(win, "bad/name"))
    win.activate_action("win.new-folder")
    answer(win, "ok", "Client Files")
    check("creates a folder", idle(win) and os.path.isdir(f"{ROOT}/my-files/Client Files"))

    # Upload a file and a folder
    win.upload([f"{LOCAL}/upload-me.txt", f"{LOCAL}/Upload Folder"])
    check("uploads file and folder", idle(win) and os.path.isfile(f"{ROOT}/my-files/upload-me.txt") and os.path.isfile(f"{ROOT}/my-files/Upload Folder/inner/deep.txt"))
    shot(win, "2-after-upload")

    # Download a file and a folder (the folder chooser itself is a portal dialog, so call the CLI step directly)
    select(win, "readme.md", "Storyspire")
    dest = tempfile.mkdtemp(prefix="downloads-")
    win.run_operation("Downloading", app_module.cli.download_args(win._refs(win.selected_nodes()), dest), refresh=False)
    check("downloads file and folder", idle(win) and os.path.isfile(f"{dest}/readme.md") and os.path.isfile(f"{dest}/Storyspire/Itinerary.pdf"))

    # Rename
    select(win, "readme.md")
    win.activate_action("win.rename")
    answer(win, "ok", "README.md")
    check("renames", idle(win) and os.path.isfile(f"{ROOT}/my-files/README.md"))

    # Move with Move To dialog
    select(win, "upload-me.txt")
    win.activate_action("win.move-to")
    d = dialog(win)
    wait_until(lambda: d.stack.get_visible_child_name() == "list", 5)
    d.go(d.location.child(next(r.node for r in rows(d.listbox) if r.node.name == "Client Files")))
    wait_until(lambda: d.stack.get_visible_child_name() != "loading", 5)
    d._on_move(None)
    check("Move To moves", idle(win) and os.path.isfile(f"{ROOT}/my-files/Client Files/upload-me.txt"))

    # Move with Cut and Paste
    select(win, "README.md")
    win.activate_action("win.cut")
    win._on_activate(None, position(win, "Documents"))
    idle(win)
    win.activate_action("win.paste")
    check("Cut and Paste moves", idle(win) and os.path.isfile(f"{ROOT}/my-files/Documents/README.md"))

    # Trash asks first; Cancel keeps the item
    select(win, "notes.txt")
    win.activate_action("win.delete-key")
    d = dialog(win)
    check("trash asks for confirmation", d is not None and "Trash" in d.get_heading())
    answer(win, "cancel")
    check("cancel keeps item", os.path.isfile(f"{ROOT}/my-files/Documents/notes.txt"))
    win.activate_action("win.delete-key")
    answer(win, "ok")
    check("trash moves item", idle(win) and os.path.isfile(f"{ROOT}/trash/notes.txt"))

    # Trash view: restore, permanent delete (confirmed), empty trash
    win.navigate(app_module.Location("/trash"))
    check("trash lists item", idle(win) and names(win) == ["notes.txt"], names(win))
    select(win, "notes.txt")
    win.activate_action("win.restore")
    check("restores item", idle(win) and os.path.isfile(f"{ROOT}/my-files/notes.txt"))
    win.navigate(app_module.Location("/my-files"))
    idle(win)
    select(win, "notes.txt")
    win.activate_action("win.trash")
    answer(win, "ok")
    idle(win)
    win.navigate(app_module.Location("/trash"))
    idle(win)
    select(win, "notes.txt")
    win.activate_action("win.delete-key")
    d = dialog(win)
    check("permanent delete asks", d is not None and "Permanently" in d.get_heading())
    answer(win, "ok")
    check("deletes permanently", idle(win) and not os.path.exists(f"{ROOT}/trash/notes.txt"))
    shot(win, "3-trash-empty")

    # Errors are shown
    win.navigate(app_module.Location("/my-files"))
    idle(win)
    os.environ["FAKE_FAIL"] = "create-folder"
    win.activate_action("win.new-folder")
    answer(win, "ok", "Will Fail")
    idle(win)
    d = dialog(win)
    check("CLI error opens a dialog", d is not None and "Simulated failure" in d.get_body(), d and d.get_body())
    shot(win, "4-error-dialog")
    answer(win, "close")
    del os.environ["FAKE_FAIL"]

    os.environ["FAKE_FAIL_ITEM"] = "Pictures"
    select(win, "Pictures", "Storyspire")
    win.activate_action("win.move-to")
    d = dialog(win)
    wait_until(lambda: d.stack.get_visible_child_name() != "loading", 5)
    d.go(d.location.child(next(r.node for r in rows(d.listbox) if r.node.name == "Client Files")))
    wait_until(lambda: d.stack.get_visible_child_name() != "loading", 5)
    d._on_move(None)
    idle(win)
    d = dialog(win)
    check("per-item failure is reported", d is not None and "1 item failed" in d.get_body(), d and d.get_body())
    answer(win, "close")
    check("other item still moved", os.path.isdir(f"{ROOT}/my-files/Client Files/Storyspire"))
    del os.environ["FAKE_FAIL_ITEM"]

    os.environ["FAKE_LOGGED_OUT"] = "1"
    win.refresh()
    idle(win)
    check("signed-out page", win.status_page.get_title() == "Sign In to Proton Drive")
    shot(win, "5-signed-out")
    del os.environ["FAKE_LOGGED_OUT"]

    os.environ["PROTON_DRIVE_CLI"] = "/nonexistent/proton-drive"
    path_backup = os.environ["PATH"]
    os.environ["PATH"] = "/usr/bin"
    app_module.cli.find_cli = lambda: None
    win.refresh()
    idle(win)
    check("missing-CLI page", win.status_page.get_title() == "Proton Drive CLI Not Found")
    app_module.cli.find_cli = lambda: FAKE
    os.environ["PATH"] = path_backup


def dialog_enabled_after(win, text):
    win.activate_action("win.new-folder")
    d = dialog(win)
    find(d.get_extra_child(), Adw.EntryRow).set_text(text)
    pump()
    enabled = d.get_response_enabled("ok")
    d.force_close()
    pump(0.2)
    return enabled


def rows(listbox):
    child = listbox.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


def main():
    app = app_module.DriveApp()
    app.set_application_id("local.DriveBrowser.Test")

    def activate(_app):
        win = app_module.DriveWindow(app)
        win.present()
        try:
            run_tests(win)
        except Exception as error:  # report, then stop
            import traceback

            traceback.print_exc()
            check(f"no exception ({error})", False)
        win.operations.clear()
        win.destroy()
        app.quit()

    app.connect("activate", activate)
    app.run([])
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
