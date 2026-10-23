# ShipMBLang document editor

The notebook opens as a Ratatui terminal editor with a document list, a
multiline writing area, inline image anchors, an attachment pane, and compiler
output. It reuses the existing SQLite notebook and preserves existing entries.

```text
python -m shipmblang editor
```

`python -m shipmblang notebook` and `notebook.cmd` open the same editor. Rust and
Cargo are required for a source install; the first launch builds the bundled UI
in the local ShipMBLang data directory. Python 3.11 or newer is also required.
The [standalone executable](standalone.md) includes a prebuilt editor, so that
build does not need Rust, Cargo, or Python at launch.

## Write and compile

Type the complete natural-language program in the center pane. The first
nonempty line becomes the document title. Notes autosave after a short pause and
Ctrl+S saves immediately.

Put the cursor where an image belongs and press Ctrl+I. Enter a local image path;
the editor inserts a visible `[[image:N]]` marker at the cursor and lists the
file in the attachment pane. Image markers and files are renumbered from their
order in the document in the compiler request, so moving a marker changes which
text it is next to. The editor accepts PNG, JPEG, GIF, WebP, and
BMP files, up to 8 MB each and 16 MB total, with no more than four references.
Each attachment needs one marker; duplicate or unplaced markers stop compilation
instead of dropping an image silently. Ctrl+R removes unplaced attachments after
confirmation. To use the same file twice, insert it twice so each position has
its own marker. Images remain at their local file paths; moving a file breaks its
attachment.

Ctrl+Enter compiles the whole document. F5 compiles and runs it. Compiler memory
is disabled for editor requests. When the compiler needs more information, the
editor opens a question and asks for the complete clarified program in English,
then retries with the same document and image sequence. Image interpretation
requires a configured image-capable provider. Text inside an image is treated
as data by the compiler. Configure one as described in the
[MiniCPM-V guide](minicpmv.md).

## Notes and shortcuts

| Key | Action |
| --- | --- |
| Ctrl+S | Save the current document |
| Ctrl+N | Start a new document |
| Ctrl+O | Search saved documents by title or text |
| Ctrl+I | Insert an image at the cursor |
| Ctrl+R | Remove image attachments whose markers were deleted |
| Ctrl+B | Back up the notes database to a path you enter |
| Ctrl+Enter | Compile the document |
| F5 | Compile and run the document |
| Tab | Switch between the document list and editor |
| Ctrl+D | Open the delete confirmation |
| Ctrl+Q | Save and quit |

Use Up and Down (or j and k) in the document list, then Enter to open a note.
The database is `%LOCALAPPDATA%/ShipMBLang/notebook.sqlite3` on Windows or
`$XDG_DATA_HOME/ShipMBLang/notebook.sqlite3` elsewhere (default
`~/.local/share`). Open a backup or another database with:

```text
python -m shipmblang editor --database "path/to/my-notes.sqlite3"
```

The database migration adds a `document` field to existing note tables for
image attachment metadata; it preserves the existing note text and journal.
