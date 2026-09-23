# ShipMB Notes

Small executable sticky notes. Type English directly on the note; the only
visible actions are **Run** and **Terminal**. Notes save automatically after
600 milliseconds without typing and when you close them.

```text
python -m shipmblang notebook
```

On Windows, double-click `notebook.cmd`. Python 3.11+ and Tkinter are required.
On many Linux distributions install `python3-tk`. A desktop display is needed.

## Two buttons

- **Run** compiles and executes the whole note, then shows its output. Selecting
  a fragment does not change what runs. Ctrl+Enter also runs the note.
- **Terminal** shows or hides output without clearing it. Ctrl+backtick also
  toggles it. This is program output, not an operating-system shell.

Try writing:

```text
Pls show me the total of 2 and 3.
Present "A thought, made real.".
```

The output is `5` followed by the quoted sentence. Saving and typing never run
code. The same local general-profile compiler is used, with model calls and
compiler memory disabled. Unsupported English shows diagnostics. Runs have a
20-second timeout and do not block typing. Editing during a run labels its
output as belonging to the earlier text.

## More notes

Right-click the note (or press Shift+F10) for:

- **New note** (Ctrl+N): another independent sticky window.
- **Open note** (Ctrl+O): search saved notes, then double-click or press Enter.
- **Back up notes**: save a copy of the notes database.
- **Delete note**: permanently remove a note after confirmation.

Ctrl+S immediately saves. Closing a note saves it; reopening the app opens the
most recently dated saved entry. Find other notes with Open note. A failed save
shows **Not saved**, and a failed save on close keeps the window open.

## Existing diary entries

Previous program text becomes the executable note. Earlier journal text is
preserved separately, available through **Previous journal** in the right-click
menu. It is not added to the runnable text. No database migration is required.

## Storage and backups

The existing SQLite file is reused: on Windows,
`%LOCALAPPDATA%/ShipMBLang/notebook.sqlite3`; elsewhere,
`$XDG_DATA_HOME/ShipMBLang/notebook.sqlite3` (default `~/.local/share`). Notes are
local, unencrypted text, without cloud sync. Output is temporary and is not
stored with the note. Open a backup or separate database with:

```text
python -m shipmblang notebook --database "path/to/my-notes.sqlite3"
```
