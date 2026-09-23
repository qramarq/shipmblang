"""Executable sticky notes using the shared ShipMBLang runtime."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading

from .notebook_store import NotebookStore, default_database


def execute_program(source, mode, *, timeout=20):
    """Isolate execution from the UI; disable model calls and compiler memory."""
    if mode not in {"compile", "run"}:
        raise ValueError("Expected compile or run.")
    if not source.strip():
        raise ValueError("Write or select a program first.")
    command = [sys.executable, "-X", "utf8", "-m", "shipmblang", mode,
               "--file", "-", "--format", "json", "--memory", "off", "--no-english-model"]
    completed = subprocess.run(
        command, input=source, capture_output=True, encoding="utf-8", timeout=timeout,
        cwd=Path(__file__).resolve().parents[1],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(completed.stderr.strip() or "The compiler returned no readable result.") from error
    return completed.returncode, result


class NotebookApp:
    """One sticky window; the first window owns the store and other notes."""
    def __init__(self, root, store, *, owner=None, entry=None):
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText

        self.tk, self.root, self.store = tk, root, store
        self.owner = owner or self
        if owner is None:
            self.windows = []
        self.owner.windows.append(self)
        self.entry_id = entry["id"] if entry else None
        self.entry_date = entry["entry_date"] if entry else date.today().isoformat()
        self.legacy_journal = entry["journal"] if entry else ""
        self.dirty = False
        self.busy = False
        self.save_id = None
        self.results = queue.Queue()
        self.terminal_visible = False
        self.status = tk.StringVar(value="Saved" if entry else "New note")
        paper, ink = "#fff0ac", "#423820"
        root.title("ShipMB Notes")
        root.geometry("410x380")
        root.minsize(300, 260)
        root.configure(bg=paper)
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(0, weight=1)
        self.program = tk.Text(root, wrap="word", undo=True, font=("Segoe UI", 14),
                               bg=paper, fg=ink, insertbackground=ink, relief="flat",
                               borderwidth=0, highlightthickness=0, padx=20, pady=18)
        self.program.grid(row=0, column=0, sticky="nsew")
        if entry:
            self.program.insert("1.0", entry["program"])
        self.program.edit_modified(False)
        self.program.bind("<<Modified>>", self.changed)
        self.footer = tk.Frame(root, bg=paper, padx=14, pady=10)
        self.footer.grid(row=1, column=0, sticky="ew")
        button_style = dict(font=("Segoe UI", 10), relief="flat", borderwidth=0,
                            cursor="hand2", padx=14, pady=6)
        self.run_button = tk.Button(self.footer, text="Run", command=self.execute,
                                    bg=ink, fg=paper, activebackground="#605032", activeforeground=paper, **button_style)
        self.run_button.pack(side="left")
        self.terminal_button = tk.Button(self.footer, text="Terminal", command=self.toggle_terminal,
                                         bg=paper, fg=ink, activebackground="#efdf97", **button_style)
        self.terminal_button.pack(side="left", padx=6)
        tk.Label(self.footer, textvariable=self.status, bg=paper, fg="#776c47",
                 font=("Segoe UI", 9)).pack(side="right")
        self.terminal = tk.Frame(root, bg="#252721")
        self.output = ScrolledText(self.terminal, height=8, wrap="word", font=("Consolas", 10),
                                   bg="#252721", fg="#f6efce", relief="flat", borderwidth=0,
                                   highlightthickness=0, padx=14, pady=12, state="disabled")
        self.output.pack(fill="both", expand=True)
        self.write_output("Ready. Press Run to execute this note.")

        self.menu = tk.Menu(root, tearoff=False)
        self.menu.add_command(label="New note", accelerator="Ctrl+N", command=self.new_note)
        self.menu.add_command(label="Open noteâ€¦", accelerator="Ctrl+O", command=self.open_notes)
        self.menu.add_separator()
        for label in ("Undo", "Cut", "Copy", "Paste"):
            self.menu.add_command(label=label, command=lambda value=label: self.program.event_generate(f"<<{value}>>"))
        self.menu.add_separator()
        self.menu.add_command(label="Back up notesâ€¦", command=self.backup)
        if self.legacy_journal:
            self.menu.add_command(label="Previous journalâ€¦", command=self.show_journal)
        self.menu.add_command(label="Delete noteâ€¦", command=self.delete_note)
        for widget in (self.program, self.footer):
            widget.bind("<Button-3>", self.context_menu)
        for key, action in (("<Control-n>", self.new_note), ("<Control-o>", self.open_notes),
                            ("<Control-s>", self.save), ("<Control-Return>", self.execute),
                            ("<Control-grave>", self.toggle_terminal)):
            root.bind(key, lambda _, action=action: self.shortcut(action))
        root.bind("<Shift-F10>", self.keyboard_menu)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(100, self.poll)
        self.program.focus_set()

    @staticmethod
    def shortcut(action):
        action()
        return "break"

    def keyboard_menu(self, _=None):
        try:
            self.menu.tk_popup(self.root.winfo_rootx()+25, self.root.winfo_rooty()+45)
        finally:
            self.menu.grab_release()
        return "break"

    def context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    def text(self):
        return self.program.get("1.0", "end-1c")

    def changed(self, _=None):
        if not self.program.edit_modified():
            return
        self.program.edit_modified(False)
        self.dirty = True
        self.status.set("Savingâ€¦")
        if self.save_id is not None:
            self.root.after_cancel(self.save_id)
        self.save_id = self.root.after(600, self.save)

    def save(self, *, notify=False):
        from tkinter import messagebox
        if self.save_id is not None:
            self.root.after_cancel(self.save_id)
            self.save_id = None
        if self.program.edit_modified():
            self.dirty = True
            self.program.edit_modified(False)
        if not self.dirty:
            return True
        source = self.text()
        title = next((line.strip() for line in source.splitlines() if line.strip()), "Untitled note")[:60]
        try:
            self.entry_id = self.store.save(entry_id=self.entry_id, title=title,
                entry_date=self.entry_date, journal=self.legacy_journal, program=source)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.status.set("Not saved")
            if notify:
                messagebox.showerror("Could not save note", str(error), parent=self.root)
            return False
        self.dirty = False
        self.status.set("Saved")
        return True

    def new_note(self, entry=None):
        if entry:
            for window in self.owner.windows:
                if window.entry_id == entry["id"]:
                    window.root.deiconify()
                    window.root.lift()
                    return window
        window = self.tk.Toplevel(self.owner.root)
        app = NotebookApp(window, self.store, owner=self.owner, entry=entry)
        window.geometry(f"+{self.root.winfo_x()+32}+{self.root.winfo_y()+32}")
        return app

    def open_notes(self):
        from tkinter import ttk
        window = self.tk.Toplevel(self.root)
        window.title("Open a note Â· double-click to open")
        window.geometry("420x320")
        search = self.tk.StringVar()
        ttk.Label(window, text="Search notes").pack(anchor="w", padx=12, pady=(10, 0))
        field = ttk.Entry(window, textvariable=search)
        field.pack(fill="x", padx=12, pady=8)
        entries = ttk.Treeview(window, columns=("date",), show="tree", selectmode="browse")
        entries.column("#0", width=280)
        entries.column("date", width=90, stretch=False)
        entries.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        def refresh(*_):
            entries.delete(*entries.get_children())
            for entry in self.store.list(search.get()):
                entries.insert("", "end", iid=entry["id"], text=entry["title"], values=(entry["entry_date"],))

        def open_selected(_=None):
            selected = entries.selection()
            if selected:
                entry = self.store.get(selected[0])
                if entry:
                    self.new_note(entry)
                    window.destroy()

        search.trace_add("write", refresh)
        entries.bind("<Double-1>", open_selected)
        entries.bind("<Return>", open_selected)
        refresh()
        field.focus_set()

    def show_journal(self):
        from tkinter.scrolledtext import ScrolledText
        window = self.tk.Toplevel(self.root)
        window.title("Previous journal Â· preserved")
        text = ScrolledText(window, wrap="word", font=("Segoe UI", 12))
        text.pack(fill="both", expand=True)
        text.insert("1.0", self.legacy_journal)
        text.configure(state="disabled")

    def delete_note(self):
        from tkinter import messagebox
        if not messagebox.askyesno("Delete note?", "Permanently delete this note?", parent=self.root):
            return
        try:
            if self.entry_id:
                self.store.delete(self.entry_id)
        except sqlite3.Error as error:
            messagebox.showerror("Could not delete", str(error), parent=self.root)
            return
        if self.save_id is not None:
            self.root.after_cancel(self.save_id)
            self.save_id = None
        self.entry_id = None
        self.entry_date = date.today().isoformat()
        self.legacy_journal = ""
        self.program.delete("1.0", "end")
        self.program.edit_reset()
        self.program.edit_modified(False)
        self.dirty = False
        self.status.set("New note")
        self.write_output("Ready.")

    def backup(self):
        from tkinter import filedialog, messagebox
        if not all(window.save(notify=True) for window in self.owner.windows):
            return
        destination = filedialog.asksaveasfilename(parent=self.root, title="Back up notes",
            defaultextension=".sqlite3", initialfile=f"shipmb-notes-{date.today()}.sqlite3",
            filetypes=[("Notes database", "*.sqlite3")])
        if destination:
            try:
                self.store.backup(destination)
                self.status.set("Backed up")
            except (OSError, ValueError, sqlite3.Error) as error:
                messagebox.showerror("Backup failed", str(error), parent=self.root)

    def toggle_terminal(self):
        self.terminal_visible = not self.terminal_visible
        if self.terminal_visible:
            self.terminal.grid(row=2, column=0, sticky="ew")
        else:
            self.terminal.grid_remove()
        self.terminal_button.configure(relief="sunken" if self.terminal_visible else "flat")

    def write_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def execute(self):
        if self.busy:
            return
        if not self.terminal_visible:
            self.toggle_terminal()
        source = self.text()
        if not source.strip():
            self.write_output("Write English instructions first. Try: Show the sum of 2 and 3.")
            return
        self.busy = True
        self.run_button.configure(state="disabled")
        self.write_output("Runningâ€¦")

        def work():
            try:
                code, result = execute_program(source, "run")
                if code:
                    messages = [d.get("message", "") for d in result.get("diagnostics", [])]
                    text = "Needs attention\n\n" + ("\n".join(filter(None, messages)) or json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    text = result.get("runtime", {}).get("stdout", "") or "Finished. No printed output."
            except subprocess.TimeoutExpired:
                text = "Stopped after 20 seconds. Simplify the program and try again."
            except Exception as error:
                text = f"Could not run: {error}"
            self.results.put((source, text))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            source, text = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.run_button.configure(state="normal")
            if source != self.text():
                text = "Result from before your latest edit:\n\n" + text
            self.write_output(text)
        self.poll_id = self.root.after(100, self.poll)

    def dispose(self):
        if self.save_id is not None:
            self.root.after_cancel(self.save_id)
        self.root.after_cancel(self.poll_id)
        self.owner.windows.remove(self)
        self.root.destroy()

    def close(self):
        if not self.save(notify=True):
            return
        if self is self.owner:
            if len(self.windows) > 1:
                self.root.withdraw()
                return
            self.store.close()
            self.dispose()
        else:
            self.dispose()
            if len(self.owner.windows) == 1 and self.owner.root.state() == "withdrawn":
                self.owner.close()


def main():
    parser = argparse.ArgumentParser(description="Open executable ShipMB sticky notes.")
    parser.add_argument("--database", type=Path, default=default_database(), help="Notes SQLite file (also opens a backup).")
    args = parser.parse_args()
    try:
        import tkinter as tk
    except ImportError:
        parser.exit(2, "ShipMB Notes needs Tkinter. Install Python's Tk support (python3-tk on many Linux systems).\n")
    try:
        root = tk.Tk()
    except tk.TclError as error:
        parser.exit(2, f"ShipMB Notes needs a desktop display: {error}\n")
    try:
        store = NotebookStore(args.database)
        entries = store.list()
    except (OSError, sqlite3.Error) as error:
        root.destroy()
        parser.exit(2, f"Could not open notes: {error}\n")
    NotebookApp(root, store, entry=store.get(entries[0]["id"]) if entries else None)
    root.mainloop()


if __name__ == "__main__":
    main()
