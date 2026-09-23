"""A local notebook/diary with an explicit ShipMBLang program workspace."""
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
    def __init__(self, root, store):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText

        self.tk, self.ttk = tk, ttk
        self.root, self.store = root, store
        self.entry_id = None
        self.dirty = False
        self.loading = False
        self.busy = False
        self.revision = 0
        self.results = queue.Queue()
        self.title = tk.StringVar()
        self.day = tk.StringVar(value=date.today().isoformat())
        self.search = tk.StringVar()
        self.status = tk.StringVar(value="New entry · saved locally when you press Save")
        root.title("ShipMB Notebook")
        root.geometry("1180x820")
        root.minsize(860, 640)
        root.configure(bg="#f6f3eb")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f6f3eb")
        style.configure("TLabel", background="#f6f3eb", foreground="#253e39", font=("Segoe UI", 10))
        style.configure("Heading.TLabel", font=("Georgia", 23))
        style.configure("TButton", padding=(12, 7), font=("Segoe UI", 10))
        style.configure("Accent.TButton", background="#245e50", foreground="white")
        style.map("Accent.TButton", background=[("active", "#194b40")])
        style.configure("Treeview", rowheight=34, font=("Segoe UI", 10), background="#fffdf7", fieldbackground="#fffdf7")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        header = ttk.Frame(root, padding=(22, 16))
        header.pack(fill="x")
        ttk.Label(header, text="ShipMB Notebook", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, text="A diary for thoughts. A workspace for programs.").pack(side="left", padx=24)
        ttk.Button(header, text="Back up notebook", command=self.backup).pack(side="right")
        body = ttk.Panedwindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=18)
        sidebar = ttk.Frame(body, padding=(0, 0, 12, 0))
        body.add(sidebar, weight=1)
        ttk.Button(sidebar, text="+ New entry", command=self.new_entry, style="Accent.TButton").pack(fill="x", pady=(0, 14))
        ttk.Label(sidebar, text="Search entries").pack(anchor="w")
        search_box = ttk.Entry(sidebar, textvariable=self.search, width=29)
        search_box.pack(fill="x", pady=(4, 10))
        self.entries = ttk.Treeview(sidebar, columns=("date",), show="tree headings", selectmode="browse")
        self.entries.heading("#0", text="ENTRY")
        self.entries.heading("date", text="DATE")
        self.entries.column("#0", width=160, minwidth=90)
        self.entries.column("date", width=90, minwidth=85, stretch=False)
        self.entries.pack(fill="both", expand=True)
        self.entries.bind("<<TreeviewSelect>>", self.select_entry)
        ttk.Button(sidebar, text="Delete entry…", command=self.delete_entry).pack(fill="x", pady=(10, 0))

        editor = ttk.Frame(body, padding=(12, 0, 0, 0))
        body.add(editor, weight=4)
        fields = ttk.Frame(editor)
        fields.pack(fill="x")
        ttk.Label(fields, text="Entry title").grid(row=0, column=0, sticky="w")
        ttk.Label(fields, text="Date · YYYY-MM-DD").grid(row=0, column=1, sticky="w", padx=10)
        self.title_input = ttk.Entry(fields, textvariable=self.title, font=("Georgia", 17))
        self.title_input.grid(row=1, column=0, sticky="ew", pady=5)
        ttk.Entry(fields, textvariable=self.day, width=13).grid(row=1, column=1, padx=10)
        ttk.Button(fields, text="Save", command=self.save, style="Accent.TButton").grid(row=1, column=2)
        fields.columnconfigure(0, weight=1)
        ttk.Label(editor, text="JOURNAL · your notes stay here").pack(anchor="w", pady=(12, 5))
        self.journal = ScrolledText(editor, height=9, wrap="word", undo=True, font=("Georgia", 12),
                                    bg="#fffdf7", fg="#273e39", relief="flat", padx=14, pady=12)
        self.journal.pack(fill="both", expand=True)
        toolbar = ttk.Frame(editor)
        toolbar.pack(fill="x", pady=(14, 6))
        ttk.Label(toolbar, text="PROGRAM · compile a selection or the whole program").pack(side="left")
        ttk.Button(toolbar, text="Example", command=self.example).pack(side="right")
        self.program = ScrolledText(editor, height=6, wrap="word", undo=True, font=("Consolas", 11),
                                    bg="#edf3ee", fg="#183e32", relief="flat", padx=14, pady=10)
        self.program.pack(fill="both", expand=True)
        actions = ttk.Frame(editor)
        actions.pack(fill="x", pady=8)
        self.compile_button = ttk.Button(actions, text="Compile", command=lambda: self.execute("compile"))
        self.compile_button.pack(side="left")
        self.run_button = ttk.Button(actions, text="Run program", command=lambda: self.execute("run"), style="Accent.TButton")
        self.run_button.pack(side="left", padx=8)
        ttk.Label(actions, text="Offline grammar · no model calls").pack(side="right")
        self.output = ScrolledText(editor, height=7, wrap="word", font=("Consolas", 10),
                                   bg="#223c35", fg="#e2f0e6", relief="flat", padx=12, pady=10, state="disabled")
        self.output.pack(fill="both", expand=True)
        ttk.Label(root, textvariable=self.status, padding=(22, 10)).pack(fill="x")

        self.title.trace_add("write", self.changed)
        self.day.trace_add("write", self.changed)
        self.search.trace_add("write", lambda *_: self.refresh())
        for widget in (self.journal, self.program):
            widget.bind("<<Modified>>", self.text_changed)
        root.bind("<Control-s>", lambda _: self.save())
        root.bind("<Control-n>", lambda _: self.new_entry())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self.write_output("Write a program, or choose Example to try English instructions.")
        self.poll_id = root.after(100, self.poll)

    def changed(self, *_):
        if not self.loading:
            self.dirty = True
            self.revision += 1
            self.status.set("Unsaved changes · Ctrl+S to save")

    def text_changed(self, event):
        if event.widget.edit_modified():
            self.changed()
            event.widget.edit_modified(False)

    def refresh(self):
        self.entries.delete(*self.entries.get_children())
        for entry in self.store.list(self.search.get()):
            self.entries.insert("", "end", iid=entry["id"], text=entry["title"], values=(entry["entry_date"],))
        if self.entry_id and self.entries.exists(self.entry_id):
            self.entries.selection_set(self.entry_id)

    def save(self):
        from tkinter import messagebox
        try:
            self.entry_id = self.store.save(
                entry_id=self.entry_id, title=self.title.get(), entry_date=self.day.get(),
                journal=self.journal.get("1.0", "end-1c"), program=self.program.get("1.0", "end-1c"))
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Could not save", str(error), parent=self.root)
            return False
        self.dirty = False
        self.status.set(f"Saved locally · {self.store.path}")
        self.refresh()
        return True

    def may_leave(self):
        from tkinter import messagebox
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Save entry?", "Save your changes before leaving this entry?", parent=self.root)
        return self.save() if answer else answer is False

    def load(self, entry=None):
        self.loading = True
        self.entry_id = entry["id"] if entry else None
        self.title.set(entry["title"] if entry else "")
        self.day.set(entry["entry_date"] if entry else date.today().isoformat())
        for widget, key in ((self.journal, "journal"), (self.program, "program")):
            widget.delete("1.0", "end")
            widget.insert("1.0", entry[key] if entry else "")
            widget.edit_reset()
            widget.edit_modified(False)
        self.loading = False
        self.dirty = False
        self.revision += 1
        self.status.set("Entry opened" if entry else "New entry · Ctrl+S to save")
        self.write_output("Results appear here after you compile or run a program.")
        self.title_input.focus_set()

    def new_entry(self):
        if self.may_leave():
            self.load()
            self.entries.selection_remove(self.entries.selection())

    def select_entry(self, _=None):
        selected = self.entries.selection()
        if not selected or selected[0] == self.entry_id:
            return
        target = selected[0]
        if self.may_leave():
            self.load(self.store.get(target))
            if self.entries.exists(target):
                self.entries.selection_set(target)
        elif self.entry_id and self.entries.exists(self.entry_id):
            self.entries.selection_set(self.entry_id)
        else:
            self.entries.selection_remove(self.entries.selection())

    def delete_entry(self):
        from tkinter import messagebox
        if self.entry_id and messagebox.askyesno("Delete entry?", "Permanently delete this saved entry and any unsaved edits?", parent=self.root):
            try:
                self.store.delete(self.entry_id)
            except sqlite3.Error as error:
                messagebox.showerror("Could not delete", str(error), parent=self.root)
                return
            self.load()
            self.refresh()

    def backup(self):
        from tkinter import filedialog, messagebox
        if not self.may_leave():
            return
        destination = filedialog.asksaveasfilename(parent=self.root, title="Back up saved entries",
            defaultextension=".sqlite3", initialfile=f"shipmb-notebook-{date.today()}.sqlite3",
            filetypes=[("Notebook database", "*.sqlite3")])
        if destination:
            try:
                self.store.backup(destination)
                self.status.set(f"Notebook backed up to {destination}")
            except (OSError, ValueError, sqlite3.Error) as error:
                messagebox.showerror("Backup failed", str(error), parent=self.root)

    def example(self):
        self.program.insert("end", ('\n' if self.program.get("1.0", "end-1c") else '') +
                            'Pls show me the total of 2 and 3.\nPresent "A small idea, made real.".\n')
        self.program.focus_set()

    def write_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def execute(self, mode):
        if self.busy:
            return
        selected = bool(self.program.tag_ranges("sel"))
        source = self.program.get("sel.first", "sel.last") if selected else self.program.get("1.0", "end-1c")
        if not source.strip():
            self.write_output("Write a program first, or choose Example.")
            return
        self.busy = True
        self.compile_button.state(["disabled"])
        self.run_button.state(["disabled"])
        self.write_output(f"{mode.title()} · {'selected text' if selected else 'whole program'}…")
        revision = self.revision

        def work():
            try:
                code, result = execute_program(source, mode)
                if code:
                    text = "Needs attention\n\n" + json.dumps(result, indent=2, ensure_ascii=False)
                elif mode == "compile":
                    text = "Compiled successfully\n\n" + json.dumps(result.get("target_code"), indent=2, ensure_ascii=False)
                else:
                    text = result.get("runtime", {}).get("stdout", "") or "Program finished with no printed output."
            except subprocess.TimeoutExpired:
                text = "Program stopped after 20 seconds. Simplify it and try again."
            except Exception as error:
                text = f"Could not {mode}: {error}"
            self.results.put((revision, text))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            revision, text = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.compile_button.state(["!disabled"])
            self.run_button.state(["!disabled"])
            if revision == self.revision:
                self.write_output(text)
            else:
                self.write_output("Entry changed during execution. Compile or run again for current results.")
        self.poll_id = self.root.after(100, self.poll)

    def close(self):
        if self.may_leave():
            self.root.after_cancel(self.poll_id)
            self.store.close()
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Open the local ShipMB notebook and diary.")
    parser.add_argument("--database", type=Path, default=default_database(), help="Notebook SQLite file (also opens a backup).")
    args = parser.parse_args()
    try:
        import tkinter as tk
    except ImportError:
        parser.exit(2, "ShipMB Notebook needs Tkinter. Install Python's Tk support (python3-tk on many Linux systems).\n")
    try:
        root = tk.Tk()
    except tk.TclError as error:
        parser.exit(2, f"ShipMB Notebook needs a desktop display: {error}\n")
    try:
        store = NotebookStore(args.database)
    except (OSError, sqlite3.Error) as error:
        root.destroy()
        parser.exit(2, f"Could not open notebook: {error}\n")
    NotebookApp(root, store)
    root.mainloop()


if __name__ == "__main__":
    main()
