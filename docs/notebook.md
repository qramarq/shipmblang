# ShipMBLang chat-room notebook

The notebook opens as a Ratatui terminal room, closer to a Discord or Telegram
chat than a document editor. Saved notes are rooms in a sidebar. The center is
a conversation with ShipMB. The bottom is a multiline composer. Existing SQLite
notes are kept and opened as rooms.

```text
python -m shipmblang editor
```

`python -m shipmblang notebook`, `notebook.cmd`, and the standalone
`shipmblang notebook` command open the same UI. Rust and Cargo are required for
a source install; the first launch builds the bundled UI in the local
ShipMBLang data directory. Python 3.11 or newer is also required. The
[standalone executable](standalone.md) includes a prebuilt editor, so that
build does not need Rust, Cargo, or Python at launch.

Check the packed editor without a terminal:

```text
shipmblang editor --version
shipmblang editor --smoke --demo
shipmblang notebook --smoke --database /tmp/notes.sqlite3
```

`--smoke` prints `shipmblang editor smoke ok` and one rendered frame, then
exits. `--theme dark` or `--theme light` selects the palette. `--ascii` draws
plain borders and badges. `Alt+T` toggles the theme inside a live session and
stores the choice in the notebook database.

## Rooms

The left sidebar lists each saved note as a chat: title, last-activity time, a
one-line preview, and a status badge. The badges are compiled ok, error, needs
clarification, and draft. A pin mark and an unread dot sit on the room. Search
is the field at the top of the sidebar. Ctrl+O focuses it. Ctrl+N starts a new
chat. Click a room, or move with the arrow keys while the room list is focused,
then press Enter.

On a narrow terminal the sidebar hides and the conversation uses the full
width. The layout follows the terminal size.

## Conversation

Enter in the composer compiles and runs the draft, the same action as F5. The
program appears as your message, with a timestamp. ShipMB replies on the left
with stdout, diagnostics (including line spans), or a clarification question.
Errors use a red accent. Clarification questions are indented under the message
that raised them. Answer from the composer; Enter sends the clarified program.
Image attachments stay in the bubble as chips, and the `[[image:N]]` markers
stay in the program text.

Ctrl+E collapses or expands the bytecode detail on the latest ShipMB reply.
Click that line to do the same. Ctrl+P pins or unpins the open room. Date lines
read Today or Yesterday when the message timestamp falls on those days.

## Composer

The composer is multiline. Enter sends (compile and run). Ctrl+Enter compiles
without running where the terminal delivers that key. Alt+C is the compile-only
fallback when Ctrl+Enter arrives as a plain Enter. Alt+Enter and Shift+Enter
insert a newline. Ctrl+J inserts a newline when the terminal does not turn it
into Enter. Up-arrow in an empty composer loads the last program you sent, so
you can edit and send it again. Ctrl+I attaches an image at the cursor.

The footer lists these keys. Tab and Shift+Tab move among search, the room
list, the timeline, and the composer. The mouse clicks those areas and scrolls
the timeline.

## Images

Put the cursor where an image belongs and press Ctrl+I. Enter a local image
path. The composer inserts a visible `[[image:N]]` marker and the bubble shows
an attachment chip. Markers and files are renumbered from their order in the
program, so moving a marker changes which text it is next to. The editor
accepts PNG, JPEG, GIF, WebP, and BMP files, up to 8 MB each and 16 MB total,
with no more than four references. Each attachment needs one marker; duplicate
or unplaced markers stop compilation instead of dropping an image silently.
Ctrl+R removes unplaced attachments after you type REMOVE. To use the same file
twice, insert it twice so each position has its own marker. Images remain at
their local file paths; moving a file breaks its attachment.

Compiler memory is disabled for editor requests. Image interpretation requires
a configured image-capable provider. Text inside an image is treated as data by
the compiler. Configure one as described in the [MiniCPM-V guide](minicpmv.md).

## Notes and shortcuts

| Key | Action |
| --- | --- |
| Enter | Compile and run (same as F5) |
| Ctrl+Enter, Alt+C | Compile only |
| Alt+Enter, Shift+Enter, Ctrl+J | New line in the composer |
| Up | Edit the last sent program when the composer is empty |
| Ctrl+S | Save the current draft |
| Ctrl+N | Start a new chat |
| Ctrl+O | Focus chat search |
| Ctrl+I | Attach an image at the cursor |
| Ctrl+R | Remove attachments whose markers were deleted |
| Ctrl+B | Back up the notes database to a path you enter |
| Ctrl+D | Delete the open chat after you type DELETE |
| Ctrl+E | Show or hide bytecode on the latest reply |
| Ctrl+P | Pin or unpin the open chat |
| Alt+T | Toggle dark and light theme |
| F5 | Compile and run |
| Ctrl+Q | Save and quit |

Drafts autosave after a short pause. The first nonempty line of a new chat
becomes its title.

The database is `%LOCALAPPDATA%/ShipMBLang/notebook.sqlite3` on Windows or
`$XDG_DATA_HOME/ShipMBLang/notebook.sqlite3` elsewhere (default
`~/.local/share`). Open a backup or another database with:

```text
python -m shipmblang editor --database "path/to/my-notes.sqlite3"
```

The standalone executable accepts the same `--database` flag.

## What happens to older notes

Opening a database written by an earlier notebook does not delete or rewrite
the original note text. Each existing note becomes a room. Its program text
stays the current draft and is also copied once into the timeline as the
opening message, with the saved image document attached when one exists. A
journal that already contains dated lines (`YYYY-MM-DD HH:MM`) becomes separate
history replies. Any other journal text becomes one history reply. Later saves
update the draft and the sidebar preview. They do not add another timeline
copy. Sending from the composer appends the user message and the ShipMB reply.
Delete still removes that note, its messages, and its room state. Backup copies
the whole SQLite file, including the new tables.
