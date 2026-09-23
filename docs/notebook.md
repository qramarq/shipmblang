# ShipMB Notebook

A local desktop diary and program notebook. Each dated entry has a title,
journal text, and a separate ShipMBLang program. No account is required.

From an installed copy of ShipMBLang, or the project directory:

```text
python -m shipmblang notebook
```

On Windows you can also double-click `notebook.cmd` in the project folder.
Python 3.11 or newer and Tkinter are required. Python's Windows installer offers
Tcl/Tk support; on many Linux distributions install `python3-tk`. A desktop
display is needed. This app is not a Colab or browser interface.

## Write, save, and run

1. Choose **New entry**, enter a title and date, and write in **Journal**.
2. Put executable English in **Program**, or choose **Example**.
3. Choose **Compile** to inspect bytecode or **Run program** to see output.
   Selecting text inside Program executes only that selection.
4. Choose **Save** or press Ctrl+S. Ctrl+N starts another entry. Leaving an
   unsaved entry prompts you to save, discard changes, or cancel.
5. Search titles, journal text, and programs using the entry list.

Example program:

```text
Pls show me the total of 2 and 3.
Present "A small idea, made real.".
```

The result is `5` followed by the quoted sentence. Journal prose is never sent
to the compiler. Program execution uses the existing general-profile runtime,
with model translation and compiler memory disabled. Unsupported wording shows
diagnostics instead of silently guessing. Execution runs in a separate process
with a 20-second timeout, keeping the diary responsive. Saving never runs code.

## Local data and backups

Entries are stored in SQLite outside the repository: on Windows,
`%LOCALAPPDATA%/ShipMBLang/notebook.sqlite3`; on other platforms,
`$XDG_DATA_HOME/ShipMBLang/notebook.sqlite3` (default `~/.local/share`).
This first version has manual saving and local storage; it has no cloud sync,
account login, or encryption. Compiler results are temporary and are not saved
as part of the entry. SQLite stores journal text as ordinary readable data.

**Back up notebook** copies saved entries to a SQLite file you choose. Open a
backup or choose a different notebook with:

```text
python -m shipmblang notebook --database "path/to/my-notebook.sqlite3"
```

Delete asks for confirmation and permanently removes the saved entry.
