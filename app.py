#!/usr/bin/env python3
"""TelescopeYoke, the application: one window, no terminal and no browser.

    ./app.py            the application
    ./app.py --demo     the same with a simulated mount and a made-up run

It is what the launcher in the applications menu starts (install.sh puts it
there; on Windows, install.ps1 makes the Start Menu shortcut). It starts the
console's server inside this program, on a free port of this computer only,
and shows its page in a window of its own. Closing the window ends whatever
is running and tells the mount to stop.

The window is made with whatever the system already has: GTK and WebKit on
Ubuntu, the WebView2 control through pywebview on Windows, and failing those
the installed Chrome, Chromium or Edge in its application mode. Only if none
of them is there does it fall back to a tab in the ordinary browser.
"""
import os
import sys

if "--demo" in sys.argv[1:]:
    os.environ["TY_DEMO"] = "1"      # before anything is imported: the demo keeps its own files

import argparse
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from pathlib import Path

import config
import console
import host

ROOT = Path(__file__).parent
TITLE = "TelescopeYoke"
ICON = ROOT / "console" / "telescopeyoke.png"
SIZE = (1400, 860)


def gtk_window(url, title, busy, self_test=False):
    """A GTK window holding a WebKit view: what Ubuntu has without installing
    anything. Returns False if this system has no GTK or WebKit."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import GLib, Gtk, WebKit2
    except (ImportError, ValueError):
        return False
    GLib.set_prgname("telescopeyoke")       # matches telescopeyoke.desktop, for the icon in the dock
    GLib.set_application_name(title)
    window = Gtk.Window(title=title)
    window.set_default_size(*SIZE)
    if ICON.exists():
        window.set_icon_from_file(str(ICON))
    view = WebKit2.WebView()
    view.get_settings().set_enable_developer_extras(False)
    view.connect("context-menu", lambda *a: True)     # no "Back / Reload" menu: it is not a browser
    window.add(view)

    def closing(*_):
        doing = busy()
        if doing and not self_test:
            ask = Gtk.MessageDialog(transient_for=window, modal=True, message_type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.OK_CANCEL, text=f"{doing} is still running.")
            ask.format_secondary_text("Closing TelescopeYoke ends it and stops the mount.")
            answer = ask.run()
            ask.destroy()
            if answer != Gtk.ResponseType.OK:
                return True      # stay open
        return False

    window.connect("delete-event", closing)
    window.connect("destroy", Gtk.main_quit)
    if self_test:
        def loaded(_, event):
            if event == WebKit2.LoadEvent.FINISHED:
                print(f"window: GTK with WebKit; page title: {view.get_title()}", flush=True)
                GLib.timeout_add(1500, window.destroy)
        view.connect("load-changed", loaded)
    view.load_uri(url)
    window.show_all()
    Gtk.main()
    return True


def webview_window(url, title, busy, self_test=False):
    """pywebview: on Windows this is the system's WebView2 control in a
    window of its own. Returns False if pywebview is not installed."""
    try:
        import webview
    except ImportError:
        return False
    window = webview.create_window(title, url, width=SIZE[0], height=SIZE[1], confirm_close=bool(busy()))
    if self_test:
        def loaded():
            print(f"window: pywebview; page title: {window.title}", flush=True)
            window.destroy()
        window.events.loaded += loaded
    webview.start()
    return True


def browser_program():
    """An installed browser that can show one page as an application window."""
    names = ["msedge", "chrome", "google-chrome", "chromium", "chromium-browser"]
    places = [Path(base) / tail for base in (r"C:\Program Files (x86)", r"C:\Program Files")
              for tail in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe")]
    return next((found for found in map(shutil.which, names) if found),
                next((str(p) for p in places if host.WINDOWS and p.exists()), None))


def app_mode_command(program, url, profile):
    """The browser's application mode: one window, no tabs, no address bar,
    and a profile of its own so that it is a separate program that ends when
    the window is closed."""
    return [program, f"--app={url}", f"--user-data-dir={profile}", f"--window-size={SIZE[0]},{SIZE[1]}",
            "--no-first-run", "--no-default-browser-check", f"--class={TITLE}"]


def browser_window(url, title, busy, self_test=False):
    program = browser_program()
    if not program or self_test:
        return False
    with tempfile.TemporaryDirectory(prefix="telescopeyoke-window-") as profile:
        subprocess.run(app_mode_command(program, url, profile), **host.QUIET)
    return True


def tab(url, title, busy, self_test=False):
    """Last resort: a tab in the ordinary browser, and this program waits."""
    if self_test:
        return False
    webbrowser.open(url)
    print(f"{title} is open in your browser. Press Ctrl+C here to close it.", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return True


def run(demo=False, self_test=False, ways=(gtk_window, webview_window, browser_window, tab)):
    server, key = console.serve(port=0, demo=demo, mode="app")
    jobs = server.RequestHandlerClass.jobs
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/?key={key}"
    busy = lambda: jobs.current["label"] if jobs.current else None
    try:
        shown = any(way(url, TITLE + (" (demo)" if demo else ""), busy, self_test) for way in ways)
    finally:
        # Closing the application ends its job and always tells the mount to stop.
        if not self_test:
            jobs.close()
        server.shutdown()
        server.server_close()
    return shown


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo", action="store_true",
                    help="a simulated mount and a made-up imaging run; needs no telescope")
    ap.add_argument("--self-test", action="store_true",
                    help="open the window, say how it was made, and close it again")
    ap.add_argument("--install-launcher", action="store_true",
                    help="put TelescopeYoke in the applications menu (the Start Menu on Windows)")
    args = ap.parse_args()
    if args.install_launcher:
        for written in host.install_launcher(ROOT):
            print(f"added {written}")
        return
    shown = run(args.demo or config.DEMO, args.self_test)
    if args.self_test and not shown:
        print("window: none of GTK with WebKit or pywebview is available here", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
