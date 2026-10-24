mod ui;

use crossterm::event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent, MouseEventKind};
use crossterm::execute;
use crossterm::terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen};
use ratatui::backend::CrosstermBackend;
use ratatui::layout::Rect;
use ratatui::Terminal;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::env;
use std::error::Error;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use ui::{glyphs, palette, Glyphs, Palette};

const MAX_IMAGES: usize = 4;
const MAX_IMAGE_BYTES: u64 = 8_000_000;
const MAX_TOTAL_IMAGE_BYTES: u64 = 16_000_000;
const EDITOR_VERSION: &str = "0.1.0";

#[derive(Clone)]
pub(crate) struct Room {
    pub(crate) id: String,
    pub(crate) title: String,
    pub(crate) preview: String,
    pub(crate) status: String,
    pub(crate) last_activity: String,
    pub(crate) unread: bool,
    pub(crate) pinned: bool,
}

#[derive(Clone)]
pub(crate) struct ChatMessage {
    pub(crate) id: String,
    pub(crate) role: String,
    pub(crate) kind: String,
    pub(crate) body: String,
    pub(crate) detail: Value,
    pub(crate) created_at: String,
    pub(crate) parent_id: String,
}

#[derive(Clone)]
struct ImageAttachment {
    id: String,
    path: PathBuf,
    caption: String,
}

#[derive(Clone, Copy, PartialEq)]
pub(crate) enum Focus { Rooms, Search, Timeline, Composer }

#[derive(Clone, Copy)]
enum Operation { Compile, Run }

#[derive(Clone)]
struct CompileContext {
    entry_id: String,
    operation: Operation,
    source: String,
    images: Vec<PathBuf>,
    interpretation: Option<String>,
    clarification_rounds: usize,
    user_message_id: String,
}

struct WorkerResult {
    context: CompileContext,
    result: Result<Value, String>,
}

#[derive(Clone)]
pub(crate) enum InputKind {
    ImagePath,
    UnplacedImages { operation: Option<Operation>, ids: Vec<String> },
    BackupPath,
    Delete,
}

#[derive(Clone)]
pub(crate) struct Modal {
    pub(crate) kind: InputKind,
    pub(crate) value: String,
}

#[derive(Clone)]
struct Awaiting {
    context: CompileContext,
    parent_id: String,
}

pub(crate) struct Hits {
    pub(crate) search: Rect,
    pub(crate) rooms: Vec<(Rect, usize)>,
    pub(crate) timeline: Rect,
    pub(crate) composer: Rect,
    pub(crate) bytecode: Vec<(u16, String)>,
}

struct Args {
    database: PathBuf,
    python: PathBuf,
    workdir: PathBuf,
    startdir: PathBuf,
    theme: Option<String>,
    smoke: bool,
    demo: bool,
    version: bool,
    ascii: bool,
    dump: Option<PathBuf>,
    select: Option<usize>,
}

pub(crate) struct App {
    database: PathBuf,
    python: PathBuf,
    workdir: PathBuf,
    startdir: PathBuf,
    offline: bool,
    pub(crate) rooms: Vec<Room>,
    pub(crate) selected: usize,
    pub(crate) room_scroll: usize,
    pub(crate) focus: Focus,
    entry_id: Option<String>,
    entry_date: String,
    journal: String,
    pub(crate) room_title: String,
    room_status_text: String,
    pub(crate) lines: Vec<Vec<char>>,
    pub(crate) cursor_row: usize,
    pub(crate) cursor_col: usize,
    pub(crate) composer_scroll: usize,
    pub(crate) messages: Vec<ChatMessage>,
    pub(crate) timeline_scroll: usize,
    pub(crate) stick_to_bottom: bool,
    images: Vec<ImageAttachment>,
    next_image_id: u64,
    pub(crate) dirty: bool,
    dirty_since: Option<Instant>,
    pub(crate) busy: bool,
    pub(crate) modal: Option<Modal>,
    pub(crate) status: String,
    pub(crate) search: String,
    light: bool,
    pub(crate) palette: Palette,
    pub(crate) glyphs: Glyphs,
    pub(crate) now: String,
    pub(crate) expanded: HashSet<String>,
    pub(crate) awaiting: Option<Awaiting>,
    pub(crate) hits: Hits,
    demo_threads: HashMap<String, Vec<ChatMessage>>,
    tx: Sender<WorkerResult>,
    rx: Receiver<WorkerResult>,
    pending: Option<CompileContext>,
    quitting: bool,
}

impl Args {
    fn parse() -> Result<Self, String> {
        let mut database = None;
        let mut python = None;
        let mut workdir = None;
        let mut startdir = None;
        let mut theme = None;
        let mut dump = None;
        let mut select = None;
        let mut smoke = false;
        let mut demo = false;
        let mut version = false;
        let mut ascii = false;
        let mut values = env::args().skip(1);
        while let Some(arg) = values.next() {
            match arg.as_str() {
                "--version" => version = true,
                "--smoke" => smoke = true,
                "--demo" => demo = true,
                "--ascii" => ascii = true,
                "--database" => database = Some(required(&mut values, &arg)?),
                "--python" => python = Some(required(&mut values, &arg)?),
                "--workdir" => workdir = Some(required(&mut values, &arg)?),
                "--startdir" => startdir = Some(required(&mut values, &arg)?),
                "--theme" => theme = Some(required(&mut values, &arg)?),
                "--dump" => dump = Some(PathBuf::from(required(&mut values, &arg)?)),
                "--select" => {
                    let raw = required(&mut values, &arg)?;
                    select = Some(raw.parse::<usize>().map_err(|_| format!("Expected a room number after {arg}"))?);
                }
                other => return Err(format!("Unknown editor option: {other}")),
            }
        }
        if !version && !demo && database.is_none() {
            return Err("Missing --database".to_string());
        }
        Ok(Self {
            database: database.map(PathBuf::from).unwrap_or_default(),
            python: python.map(PathBuf::from).unwrap_or_default(),
            workdir: workdir.map(PathBuf::from).unwrap_or_else(|| env::current_dir().unwrap_or_default()),
            startdir: startdir.map(PathBuf::from).unwrap_or_else(|| env::current_dir().unwrap_or_default()),
            theme, smoke, demo, version, ascii, dump, select,
        })
    }
}

fn required(values: &mut impl Iterator<Item = String>, arg: &str) -> Result<String, String> {
    values.next().ok_or_else(|| format!("Missing value after {arg}"))
}

impl App {
    fn new(args: &Args) -> Result<Self, Box<dyn Error>> {
        let (tx, rx) = mpsc::channel();
        let light = args.theme.as_deref() == Some("light");
        let mut app = Self::blank(args, tx, rx, light);
        app.refresh_notes("")?;
        if args.theme.is_none() {
            if let Ok(value) = app.bridge(json!({"action": "list", "query": ""})) {
                if value.get("theme").and_then(Value::as_str) == Some("light") {
                    app.light = true;
                    app.palette = palette(true);
                }
                if let Some(now) = value.get("now").and_then(Value::as_str) {
                    app.now = now.to_string();
                }
            }
        }
        if !app.rooms.is_empty() {
            let index = args.select.unwrap_or(0).min(app.rooms.len() - 1);
            app.open_room(index)?;
        } else {
            app.status = "New chat".to_string();
            app.room_title = "New chat".to_string();
        }
        Ok(app)
    }

    fn demo(theme: &str, ascii: bool, select: usize) -> Self {
        let (tx, rx) = mpsc::channel();
        let args = Args {
            database: PathBuf::new(), python: PathBuf::new(), workdir: PathBuf::new(), startdir: PathBuf::new(),
            theme: Some(theme.to_string()), smoke: true, demo: true, version: false, ascii, dump: None, select: Some(select),
        };
        let mut app = Self::blank(&args, tx, rx, theme == "light");
        app.offline = true;
        app.glyphs = glyphs(ascii);
        let now = utc_now_iso();
        let today = date_prefix(&now).to_string();
        let yday = yesterday(&today);
        app.now = now;
        let sum_user = message("u1", "user", "message", "Show the sum of 2 and 3.", json!({}), &format!("{today}T09:14:00+00:00"), "");
        let sum_bot = message("b1", "bot", "reply", "Ran successfully.\n5", json!({
            "status": "compiled", "bytecode": "const 2\nconst 3\nbinary add\nshow",
        }), &format!("{today}T09:14:02+00:00"), "");
        let follow = message("u2", "user", "message", "Present it.", json!({}), &format!("{today}T09:16:00+00:00"), "");
        let question = message("b2", "bot", "clarification", "Which declared value does this reference mean? Use its name.", json!({"status": "needs_clarification"}), &format!("{today}T09:16:01+00:00"), "u2");
        let cafe_user = message("c1", "user", "opening", "Present \"café\".", json!({}), &format!("{today}T08:02:00+00:00"), "");
        let cafe_bot = message("c2", "bot", "reply", "Ran successfully.\ncafé", json!({"status": "compiled", "bytecode": "const café\nshow"}), &format!("{today}T08:02:01+00:00"), "");
        let park_user = message("p1", "user", "message", "Describe [[image:1]] and count the trees.", json!({
            "images": [{"id": "1", "path": "/photos/park.png", "caption": "park.png"}],
        }), &format!("{yday}T18:02:00+00:00"), "");
        let park_bot = message("p2", "bot", "reply", "Could not compile this program.\nline 1:1 (chars 0-12) Image interpretation needs an image-capable model.", json!({"status": "unsupported"}), &format!("{yday}T18:02:03+00:00"), "");
        app.demo_threads.insert("sum".into(), vec![sum_user, sum_bot, follow, question]);
        app.demo_threads.insert("cafe".into(), vec![cafe_user, cafe_bot]);
        app.demo_threads.insert("park".into(), vec![park_user, park_bot]);
        app.rooms = vec![
            Room { id: "sum".into(), title: "Sum of 2 and 3".into(), preview: "Which declared value does this reference mean?".into(), status: "ask".into(), last_activity: format!("{today}T09:16:01+00:00"), unread: false, pinned: true },
            Room { id: "cafe".into(), title: "Café receipt".into(), preview: "café".into(), status: "ok".into(), last_activity: format!("{today}T08:02:01+00:00"), unread: true, pinned: false },
            Room { id: "park".into(), title: "Park photo".into(), preview: "Could not compile this program.".into(), status: "err".into(), last_activity: format!("{yday}T18:02:03+00:00"), unread: false, pinned: false },
        ];
        let index = select.min(app.rooms.len() - 1);
        let _ = app.open_room(index);
        app.focus = Focus::Composer;
        app
    }

    fn blank(args: &Args, tx: Sender<WorkerResult>, rx: Receiver<WorkerResult>, light: bool) -> Self {
        let ascii = args.ascii || env::var("SHIPMB_ASCII").ok().as_deref() == Some("1") || env::var("TERM").ok().as_deref() == Some("dumb");
        Self {
            database: args.database.clone(), python: args.python.clone(), workdir: args.workdir.clone(), startdir: args.startdir.clone(),
            offline: args.demo, rooms: Vec::new(), selected: 0, room_scroll: 0, focus: Focus::Composer,
            entry_id: None, entry_date: String::new(), journal: String::new(), room_title: String::new(), room_status_text: "draft".into(),
            lines: vec![Vec::new()], cursor_row: 0, cursor_col: 0, composer_scroll: 0, messages: Vec::new(),
            timeline_scroll: 0, stick_to_bottom: true, images: Vec::new(), next_image_id: 1, dirty: false, dirty_since: None,
            busy: false, modal: None, status: "Ready".into(), search: String::new(), light, palette: palette(light), glyphs: glyphs(ascii),
            now: utc_now_iso(), expanded: HashSet::new(), awaiting: None,
            hits: Hits { search: Rect::default(), rooms: Vec::new(), timeline: Rect::default(), composer: Rect::default(), bytecode: Vec::new() },
            demo_threads: HashMap::new(), tx, rx, pending: None, quitting: false,
        }
    }

    pub(crate) fn room_status(&self) -> &str { &self.room_status_text }

    pub(crate) fn theme_label(&self) -> &'static str { if self.light { "light" } else { "dark" } }

    fn bridge(&self, request: Value) -> Result<Value, String> {
        if self.offline {
            return Err("Sample chat rooms are not connected to a notebook.".to_string());
        }
        let mut child = Command::new(&self.python)
            .args(["-X", "utf8", "-m", "shipmblang.editor_bridge", "--database"])
            .arg(&self.database)
            .current_dir(&self.workdir)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
            .spawn().map_err(|error| format!("Could not start Python: {error}"))?;
        if let Some(mut input) = child.stdin.take() {
            serde_json::to_writer(&mut input, &request).map_err(|error| error.to_string())?;
            input.flush().map_err(|error| error.to_string())?;
        }
        let output = child.wait_with_output().map_err(|error| error.to_string())?;
        if !output.status.success() {
            let detail = String::from_utf8_lossy(&output.stderr);
            return Err(if detail.trim().is_empty() { "Could not access the notes database.".to_string() } else { detail.trim().to_string() });
        }
        let value: Value = serde_json::from_slice(&output.stdout).map_err(|error| format!("The notes database returned an unreadable response: {error}"))?;
        if value.get("ok").and_then(Value::as_bool) != Some(true) {
            return Err(value.get("error").and_then(Value::as_str).unwrap_or("Notes operation failed.").to_string());
        }
        if let Some(now) = value.get("now").and_then(Value::as_str) {
            let _ = now;
        }
        Ok(value)
    }

    fn refresh_notes(&mut self, query: &str) -> Result<(), String> {
        if self.offline {
            return Ok(());
        }
        let response = self.bridge(json!({"action": "list", "query": query}))?;
        if let Some(now) = response.get("now").and_then(Value::as_str) {
            self.now = now.to_string();
        }
        let current = self.entry_id.clone();
        self.rooms = response.get("entries").and_then(Value::as_array).into_iter().flatten().map(room_from_value).collect();
        if let Some(id) = current {
            if let Some(index) = self.rooms.iter().position(|room| room.id == id) {
                self.selected = index;
            }
        }
        self.selected = self.selected.min(self.rooms.len().saturating_sub(1));
        Ok(())
    }

    fn open_room(&mut self, index: usize) -> Result<(), String> {
        if self.rooms.is_empty() {
            return Ok(());
        }
        if self.dirty && !self.offline {
            self.save()?;
        }
        let room = self.rooms.get(index).ok_or("Choose a chat first.")?.clone();
        if self.offline {
            self.messages = self.demo_threads.get(&room.id).cloned().unwrap_or_default();
            self.entry_id = Some(room.id.clone());
            self.room_title = room.title.clone();
            self.room_status_text = room.status.clone();
            self.lines = vec![Vec::new()];
            self.cursor_row = 0;
            self.cursor_col = 0;
            self.images.clear();
            self.selected = index;
            self.stick_to_bottom = true;
            self.sync_awaiting();
            self.status = "Ready".to_string();
            return Ok(());
        }
        let response = self.bridge(json!({"action": "get", "id": room.id}))?;
        let entry = response.get("entry").and_then(Value::as_object).ok_or("Chat was not found.")?;
        self.entry_id = entry.get("id").and_then(Value::as_str).map(str::to_string);
        self.entry_date = entry.get("entry_date").and_then(Value::as_str).unwrap_or("").to_string();
        self.journal = entry.get("journal").and_then(Value::as_str).unwrap_or("").to_string();
        let program = entry.get("program").and_then(Value::as_str).unwrap_or("").to_string();
        self.lines = split_lines(&program);
        self.images = parse_images(entry.get("document").and_then(Value::as_str).unwrap_or(""));
        self.next_image_id = self.images.iter().filter_map(|image| image.id.parse::<u64>().ok()).max().unwrap_or(0) + 1;
        let timeline = self.bridge(json!({"action": "timeline", "id": room.id}))?;
        if let Some(now) = timeline.get("now").and_then(Value::as_str) {
            self.now = now.to_string();
        }
        self.messages = timeline.get("messages").and_then(Value::as_array).into_iter().flatten().map(message_from_value).collect();
        let _ = self.bridge(json!({"action": "read", "id": room.id}));
        self.cursor_row = self.lines.len().saturating_sub(1);
        self.cursor_col = self.lines.last().map(|line| line.len()).unwrap_or(0);
        self.composer_scroll = 0;
        self.dirty = false;
        self.dirty_since = None;
        self.selected = index;
        self.room_title = entry.get("title").and_then(Value::as_str).unwrap_or(&room.title).to_string();
        self.room_status_text = room.status.clone();
        self.focus = Focus::Composer;
        self.stick_to_bottom = true;
        self.sync_awaiting();
        self.status = "Opened".to_string();
        let query = self.search.clone();
        let _ = self.refresh_notes(&query);
        Ok(())
    }

    fn sync_awaiting(&mut self) {
        self.awaiting = None;
        let Some(question) = self.messages.iter().rev().find(|message| message.kind == "clarification" || message.detail.get("status").and_then(Value::as_str) == Some("needs_clarification")) else { return; };
        let answered = self.messages.iter().any(|message| message.parent_id == question.id && message.role == "user");
        if answered { return; }
        let parent = self.messages.iter().find(|message| message.id == question.parent_id && message.role == "user");
        let Some(parent) = parent else { return; };
        let rounds = self.messages.iter().filter(|message| message.kind == "answer").count();
        if rounds >= 4 { return; }
        self.awaiting = Some(Awaiting {
            parent_id: question.id.clone(),
            context: CompileContext {
                entry_id: self.entry_id.clone().unwrap_or_default(),
                operation: Operation::Run,
                source: parent.body.clone(),
                images: paths_from_detail(&parent.detail),
                interpretation: None,
                clarification_rounds: rounds,
                user_message_id: parent.id.clone(),
            },
        });
    }

    fn new_chat(&mut self) {
        if self.offline { self.status = "Sample chat".to_string(); return; }
        if self.dirty {
            if let Err(error) = self.save() {
                self.status = error;
                return;
            }
        }
        self.entry_id = None;
        self.entry_date.clear();
        self.journal.clear();
        self.room_title = "New chat".to_string();
        self.room_status_text = "draft".to_string();
        self.lines = vec![Vec::new()];
        self.cursor_row = 0;
        self.cursor_col = 0;
        self.messages.clear();
        self.images.clear();
        self.next_image_id = 1;
        self.awaiting = None;
        self.dirty = false;
        self.focus = Focus::Composer;
        if let Err(error) = self.save() {
            self.status = error;
            return;
        }
        self.status = "New chat".to_string();
    }

    fn save(&mut self) -> Result<(), String> {
        if self.offline { return Ok(()); }
        let source = self.source();
        let document = json!({
            "version": 2,
            "images": self.images.iter().map(|image| json!({
                "id": image.id, "path": image.path.to_string_lossy(), "caption": image.caption,
            })).collect::<Vec<_>>(),
        });
        let response = self.bridge(json!({
            "action": "save", "id": self.entry_id, "entry_date": self.entry_date,
            "title": self.title_for_save(), "journal": self.journal,
            "program": source, "document": document.to_string(),
        }))?;
        let entry = response.get("entry").and_then(Value::as_object).ok_or("Chat was saved but could not be reloaded.")?;
        self.entry_id = entry.get("id").and_then(Value::as_str).map(str::to_string);
        self.entry_date = entry.get("entry_date").and_then(Value::as_str).unwrap_or("").to_string();
        if let Some(title) = entry.get("title").and_then(Value::as_str) {
            self.room_title = title.to_string();
        }
        self.dirty = false;
        self.dirty_since = None;
        let query = self.search.clone();
        self.refresh_notes(&query)?;
        self.status = "Saved".to_string();
        Ok(())
    }

    fn title_for_save(&self) -> String {
        let drafted = self.source().lines().find(|line| !line.trim().is_empty()).unwrap_or("").trim().to_string();
        if !drafted.is_empty() {
            return drafted.chars().take(60).collect();
        }
        if !self.room_title.trim().is_empty() {
            return self.room_title.chars().take(60).collect();
        }
        "New chat".to_string()
    }

    fn mark_dirty(&mut self) {
        self.dirty = true;
        self.dirty_since = Some(Instant::now());
        self.status = "Editing…".to_string();
    }

    fn source(&self) -> String {
        self.lines.iter().map(|line| line.iter().collect::<String>()).collect::<Vec<_>>().join("\n")
    }

    fn composer_empty(&self) -> bool { self.lines.iter().all(|line| line.is_empty()) }

    fn insert_char(&mut self, ch: char) {
        if ch == '\n' {
            let tail = self.lines[self.cursor_row].split_off(self.cursor_col);
            self.cursor_row += 1;
            self.cursor_col = 0;
            self.lines.insert(self.cursor_row, tail);
        } else if ch == '\t' {
            for _ in 0..4 { self.lines[self.cursor_row].insert(self.cursor_col, ' '); self.cursor_col += 1; }
        } else if !ch.is_control() {
            self.lines[self.cursor_row].insert(self.cursor_col, ch);
            self.cursor_col += 1;
        } else {
            return;
        }
        self.mark_dirty();
    }

    fn backspace(&mut self) {
        if self.cursor_col > 0 {
            self.cursor_col -= 1;
            self.lines[self.cursor_row].remove(self.cursor_col);
        } else if self.cursor_row > 0 {
            let current = self.lines.remove(self.cursor_row);
            self.cursor_row -= 1;
            self.cursor_col = self.lines[self.cursor_row].len();
            self.lines[self.cursor_row].extend(current);
        } else { return; }
        self.mark_dirty();
    }

    fn delete_char(&mut self) {
        if self.cursor_col < self.lines[self.cursor_row].len() {
            self.lines[self.cursor_row].remove(self.cursor_col);
        } else if self.cursor_row + 1 < self.lines.len() {
            let next = self.lines.remove(self.cursor_row + 1);
            self.lines[self.cursor_row].extend(next);
        } else { return; }
        self.mark_dirty();
    }

    fn move_cursor(&mut self, code: KeyCode) {
        match code {
            KeyCode::Left if self.cursor_col > 0 => self.cursor_col -= 1,
            KeyCode::Left if self.cursor_row > 0 => { self.cursor_row -= 1; self.cursor_col = self.lines[self.cursor_row].len(); }
            KeyCode::Right if self.cursor_col < self.lines[self.cursor_row].len() => self.cursor_col += 1,
            KeyCode::Right if self.cursor_row + 1 < self.lines.len() => { self.cursor_row += 1; self.cursor_col = 0; }
            KeyCode::Up if self.cursor_row > 0 => { self.cursor_row -= 1; self.cursor_col = self.cursor_col.min(self.lines[self.cursor_row].len()); }
            KeyCode::Down if self.cursor_row + 1 < self.lines.len() => { self.cursor_row += 1; self.cursor_col = self.cursor_col.min(self.lines[self.cursor_row].len()); }
            KeyCode::Home => self.cursor_col = 0,
            KeyCode::End => self.cursor_col = self.lines[self.cursor_row].len(),
            _ => {}
        }
    }

    fn edit_last_sent(&mut self) {
        let Some(message) = self.messages.iter().rev().find(|message| message.role == "user" && message.kind != "answer").cloned() else {
            self.status = "No sent program yet".to_string();
            return;
        };
        self.lines = split_lines(&message.body);
        self.cursor_row = self.lines.len().saturating_sub(1);
        self.cursor_col = self.lines.last().map(|line| line.len()).unwrap_or(0);
        self.images = images_from_detail(&message.detail);
        self.next_image_id = self.images.iter().filter_map(|image| image.id.parse::<u64>().ok()).max().unwrap_or(0) + 1;
        self.mark_dirty();
        self.focus = Focus::Composer;
        self.status = "Editing the last sent program".to_string();
    }

    fn insert_image(&mut self, raw_path: &str) -> Result<(), String> {
        let input = PathBuf::from(raw_path.trim().trim_matches('"'));
        let candidate = if input.is_absolute() { input } else { self.startdir.join(input) };
        if candidate.as_os_str().is_empty() { return Err("Enter a local image path.".to_string()); }
        let path = candidate.canonicalize().map_err(|error| format!("Cannot open image path: {error}"))?;
        let metadata = fs::metadata(&path).map_err(|error| error.to_string())?;
        if !metadata.is_file() { return Err("Choose a local image file.".to_string()); }
        if metadata.len() == 0 || metadata.len() > MAX_IMAGE_BYTES {
            return Err("Each image must be nonempty and 8 MB or smaller.".to_string());
        }
        let (active, total) = self.active_image_stats();
        if active >= MAX_IMAGES { return Err(format!("A document can use at most {MAX_IMAGES} images.")); }
        if total + metadata.len() > MAX_TOTAL_IMAGE_BYTES {
            return Err("All images together must be 16 MB or smaller.".to_string());
        }
        let mut signature = [0_u8; 12];
        let bytes_read = fs::File::open(&path).and_then(|mut file| file.read(&mut signature)).map_err(|error| error.to_string())?;
        let valid_image = signature.starts_with(b"\x89PNG\r\n\x1a\n")
            || signature.starts_with(b"\xff\xd8\xff")
            || signature.starts_with(b"GIF87a")
            || signature.starts_with(b"GIF89a")
            || (bytes_read >= 12 && &signature[..4] == b"RIFF" && &signature[8..12] == b"WEBP")
            || signature.starts_with(b"BM");
        if !valid_image { return Err("Choose a PNG, JPEG, GIF, WebP, or BMP image.".to_string()); }
        let id = self.next_image_id.to_string();
        self.next_image_id += 1;
        let caption = path.file_name().and_then(|name| name.to_str()).unwrap_or("Image").to_string();
        let marker = format!("[[image:{id}]]");
        for ch in marker.chars() { self.insert_char(ch); }
        self.images.push(ImageAttachment { id, path, caption: caption.clone() });
        self.status = format!("Attached {caption}");
        Ok(())
    }

    fn active_image_stats(&self) -> (usize, u64) {
        let total = self.images.iter().filter_map(|image| fs::metadata(&image.path).ok()).fold(0_u64, |sum, metadata| sum.saturating_add(metadata.len()));
        (self.images.len(), total)
    }

    fn unplaced_image_ids(&self, source: &str) -> Vec<String> {
        let known: HashMap<&str, ()> = self.images.iter().map(|image| (image.id.as_str(), ())).collect();
        let chars: Vec<char> = source.chars().collect();
        let mut used = HashMap::<String, usize>::new();
        let mut index = 0;
        while index + 8 <= chars.len() {
            if chars[index..index + 8].iter().collect::<String>() == "[[image:" {
                if let Some(end_rel) = chars[index + 8..].windows(2).position(|pair| pair == [']', ']']) {
                    let end = index + 8 + end_rel;
                    let id: String = chars[index + 8..end].iter().collect();
                    if known.contains_key(id.as_str()) { *used.entry(id).or_insert(0) += 1; }
                    index = end + 2;
                    continue;
                }
            }
            index += 1;
        }
        self.images.iter().filter(|image| !used.contains_key(&image.id)).map(|image| image.id.clone()).collect()
    }

    fn ordered_submission(&self, source: &str) -> Result<(String, Vec<PathBuf>), String> {
        if self.images.len() > MAX_IMAGES {
            return Err(format!("A document can use at most {MAX_IMAGES} image attachments. Remove extras with Ctrl+R."));
        }
        let mut total_bytes = 0_u64;
        for image in &self.images {
            let metadata = fs::metadata(&image.path).map_err(|error| format!("Cannot read attached image {}: {error}", image.caption))?;
            if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_IMAGE_BYTES {
                return Err(format!("Attached image {} must be a nonempty regular image file of 8 MB or less.", image.caption));
            }
            total_bytes = total_bytes.saturating_add(metadata.len());
        }
        if total_bytes > MAX_TOTAL_IMAGE_BYTES {
            return Err("All image attachments together must be 16 MB or smaller. Remove extras with Ctrl+R.".to_string());
        }
        let mapping: HashMap<&str, &PathBuf> = self.images.iter().map(|image| (image.id.as_str(), &image.path)).collect();
        if mapping.len() != self.images.len() {
            return Err("The saved image attachment list contains duplicate IDs. Remove and reinsert the affected images.".to_string());
        }
        let chars: Vec<char> = source.chars().collect();
        let mut output = String::new();
        let mut paths = Vec::new();
        let mut used = HashMap::<String, usize>::new();
        let mut index = 0;
        while index < chars.len() {
            if index + 8 <= chars.len() && chars[index..index + 8].iter().collect::<String>() == "[[image:" {
                let Some(end_rel) = chars[index + 8..].windows(2).position(|pair| pair == [']', ']']) else {
                    return Err("An image marker is incomplete. Restore its closing `]]` or remove the marker.".to_string());
                };
                let end = index + 8 + end_rel;
                let id = chars[index + 8..end].iter().collect::<String>();
                let Some(path) = mapping.get(id.as_str()) else {
                    return Err(format!("Image marker [[image:{id}]] has no attached file. Add the image again with Ctrl+I."));
                };
                let uses = used.entry(id.clone()).or_insert(0);
                *uses += 1;
                if *uses > 1 {
                    return Err(format!("Image attachment {id} is referenced more than once. Keep one marker or insert a separate attachment with Ctrl+I."));
                }
                paths.push((*path).clone());
                output.push_str(&format!("[[image:{}]]", paths.len()));
                index = end + 2;
                continue;
            }
            output.push(chars[index]);
            index += 1;
        }
        if let Some(image) = self.images.iter().find(|image| !used.contains_key(&image.id)) {
            return Err(format!("Attached image {} has no marker in the message. Restore [[image:{}]] or remove unplaced images with Ctrl+R.", image.caption, image.id));
        }
        Ok((output, paths))
    }

    fn prompt_remove_unplaced(&mut self, operation: Option<Operation>) {
        let ids = self.unplaced_image_ids(&self.source());
        if ids.is_empty() {
            if operation.is_none() { self.status = "No unplaced images".to_string(); }
            return;
        }
        self.modal = Some(Modal { kind: InputKind::UnplacedImages { operation, ids }, value: String::new() });
    }

    fn begin_compile(&mut self, operation: Operation) {
        if self.busy || self.offline { return; }
        if self.awaiting.is_some() && matches!(operation, Operation::Run) {
            self.answer_clarification();
            return;
        }
        let draft = self.source();
        if draft.trim().is_empty() {
            self.status = "Write a program before sending.".to_string();
            return;
        }
        let (source, images) = match self.ordered_submission(&draft) {
            Ok(result) => result,
            Err(error) => {
                self.status = error;
                self.prompt_remove_unplaced(Some(operation));
                return;
            }
        };
        if let Err(error) = self.save() {
            self.status = format!("Save before compiling: {error}");
            return;
        }
        let entry_id = match self.entry_id.clone() {
            Some(id) => id,
            None => { self.status = "Could not open a chat for this message.".to_string(); return; }
        };
        let detail = json!({
            "images": self.images.iter().map(|image| json!({"id": image.id, "path": image.path.to_string_lossy(), "caption": image.caption})).collect::<Vec<_>>(),
        });
        let appended = self.bridge(json!({
            "action": "append", "id": entry_id, "role": "user", "kind": "message",
            "body": source, "detail": detail,
        }));
        let message = match appended {
            Ok(value) => value.get("message").cloned().unwrap_or(Value::Null),
            Err(error) => { self.status = error; return; }
        };
        let user_message_id = message.get("id").and_then(Value::as_str).unwrap_or("").to_string();
        self.lines = vec![Vec::new()];
        self.cursor_row = 0;
        self.cursor_col = 0;
        self.images.clear();
        self.next_image_id = 1;
        self.dirty = true;
        if let Err(error) = self.save() {
            self.status = format!("Saved the message, but not the empty draft: {error}");
        }
        self.load_timeline();
        self.stick_to_bottom = true;
        self.start_worker(CompileContext { entry_id, operation, source, images, interpretation: None, clarification_rounds: 0, user_message_id });
    }

    fn answer_clarification(&mut self) {
        let Some(awaiting) = self.awaiting.clone() else { return; };
        let answer = self.source();
        if answer.trim().is_empty() {
            self.status = "Write the clarified program in the composer.".to_string();
            return;
        }
        if let Err(error) = self.bridge(json!({
            "action": "append", "id": awaiting.context.entry_id, "role": "user", "kind": "answer",
            "body": answer, "parent_id": awaiting.parent_id, "detail": {},
        })) {
            self.status = error;
            return;
        }
        self.lines = vec![Vec::new()];
        self.cursor_row = 0;
        self.cursor_col = 0;
        self.dirty = true;
        let _ = self.save();
        self.load_timeline();
        let mut context = awaiting.context;
        context.interpretation = Some(answer);
        context.clarification_rounds += 1;
        self.awaiting = None;
        self.start_worker(context);
    }

    fn load_timeline(&mut self) {
        let Some(id) = self.entry_id.clone() else { return; };
        if let Ok(timeline) = self.bridge(json!({"action": "timeline", "id": id})) {
            if let Some(now) = timeline.get("now").and_then(Value::as_str) { self.now = now.to_string(); }
            self.messages = timeline.get("messages").and_then(Value::as_array).into_iter().flatten().map(message_from_value).collect();
        }
        let query = self.search.clone();
        let _ = self.refresh_notes(&query);
        if let Some(room) = self.rooms.iter().find(|room| Some(&room.id) == self.entry_id.as_ref()) {
            self.room_status_text = room.status.clone();
            self.room_title = room.title.clone();
        }
    }

    fn start_worker(&mut self, context: CompileContext) {
        self.busy = true;
        self.pending = Some(context.clone());
        self.status = match context.operation { Operation::Compile => "Compiling…", Operation::Run => "Running…" }.to_string();
        self.stick_to_bottom = true;
        let tx = self.tx.clone();
        let python = self.python.clone();
        let workdir = self.workdir.clone();
        thread::spawn(move || {
            let result = invoke_compiler(&python, &workdir, &context);
            let _ = tx.send(WorkerResult { context, result });
        });
    }

    fn receive_worker(&mut self) {
        let Ok(message) = self.rx.try_recv() else { return; };
        self.busy = false;
        self.pending = None;
        let entry_id = message.context.entry_id.clone();
        let user_message_id = message.context.user_message_id.clone();
        match message.result {
            Err(error) => {
                let detail = json!({"status": "error"});
                let _ = self.bridge(json!({"action": "append", "id": entry_id, "role": "bot", "kind": "reply", "body": format!("Could not compile: {error}"), "detail": detail, "parent_id": user_message_id}));
                self.status = "Compiler error".to_string();
            }
            Ok(result) => {
                let (body, detail, status_name) = bot_from_result(&result, &message.context.source, message.context.operation);
                let kind = if status_name == "needs_clarification" { "clarification" } else { "reply" };
                let _ = self.bridge(json!({
                    "action": "append", "id": entry_id, "role": "bot", "kind": kind,
                    "body": body, "detail": detail, "parent_id": user_message_id,
                }));
                if status_name == "needs_clarification" {
                    let question = result.get("clarifications").and_then(Value::as_array).and_then(|items| items.first());
                    let id = question.and_then(|item| item.get("id")).and_then(Value::as_str).unwrap_or("");
                    let text = question.and_then(|item| item.get("question")).and_then(Value::as_str).unwrap_or("");
                    if id == "image-model" {
                        self.status = "Image-capable model required".to_string();
                    } else if !text.is_empty() && message.context.clarification_rounds < 4 {
                        self.status = "Reply to ShipMB in the composer".to_string();
                    } else if message.context.clarification_rounds >= 4 {
                        self.status = "Clarification limit reached".to_string();
                    } else {
                        self.status = "Compiler needs clarification".to_string();
                    }
                } else if status_name == "compiled" {
                    self.status = match message.context.operation { Operation::Compile => "Compiled", Operation::Run => "Finished" }.to_string();
                } else {
                    self.status = "Could not compile".to_string();
                }
            }
        }
        if self.entry_id.as_deref() == Some(entry_id.as_str()) {
            self.load_timeline();
            let _ = self.bridge(json!({"action": "read", "id": entry_id}));
            self.sync_awaiting();
            self.stick_to_bottom = true;
        } else {
            let query = self.search.clone();
        let _ = self.refresh_notes(&query);
        }
    }

    fn toggle_theme(&mut self) {
        self.light = !self.light;
        self.palette = palette(self.light);
        if !self.offline {
            let name = if self.light { "light" } else { "dark" };
            let _ = self.bridge(json!({"action": "preference", "key": "theme", "value": name}));
        }
        self.status = format!("Theme: {}", self.theme_label());
    }

    fn toggle_pin(&mut self) {
        if self.offline { self.status = "Sample chat".to_string(); return; }
        let Some(id) = self.entry_id.clone() else { return; };
        let pinned = self.rooms.iter().find(|room| room.id == id).map(|room| room.pinned).unwrap_or(false);
        match self.bridge(json!({"action": "pin", "id": id, "pinned": !pinned})) {
            Ok(_) => {
                let query = self.search.clone();
                let _ = self.refresh_notes(&query);
                self.status = if pinned { "Unpinned".into() } else { "Pinned".into() };
            }
            Err(error) => self.status = error,
        }
    }

    fn toggle_bytecode(&mut self) {
        let id = self.messages.iter().rev().find(|message| message.role == "bot" && message.detail.get("bytecode").and_then(Value::as_str).map(|text| !text.is_empty()).unwrap_or(false)).map(|message| message.id.clone());
        if let Some(id) = id {
            if !self.expanded.insert(id.clone()) { self.expanded.remove(&id); }
        }
    }

    fn handle_key(&mut self, key: KeyEvent) {
        if key.kind == KeyEventKind::Release { return; }
        if self.modal.is_some() { self.handle_modal_key(key); return; }
        let control = key.modifiers.contains(KeyModifiers::CONTROL);
        let alt = key.modifiers.contains(KeyModifiers::ALT);
        if key.code == KeyCode::F(5) { self.begin_compile(Operation::Run); return; }
        if alt && matches!(key.code, KeyCode::Char('t') | KeyCode::Char('T')) { self.toggle_theme(); return; }
        if alt && matches!(key.code, KeyCode::Char('c') | KeyCode::Char('C')) { self.begin_compile(Operation::Compile); return; }
        if control {
            match key.code {
                KeyCode::Char('s') => { if let Err(error) = self.save() { self.status = error; } }
                KeyCode::Char('n') => self.new_chat(),
                KeyCode::Char('o') => { self.focus = Focus::Search; self.status = "Search chats".into(); }
                KeyCode::Char('i') => self.modal = Some(Modal { kind: InputKind::ImagePath, value: String::new() }),
                KeyCode::Char('b') => self.modal = Some(Modal { kind: InputKind::BackupPath, value: String::new() }),
                KeyCode::Char('r') => self.prompt_remove_unplaced(None),
                KeyCode::Char('p') => self.toggle_pin(),
                KeyCode::Char('e') => self.toggle_bytecode(),
                KeyCode::Char('j') => { if self.focus == Focus::Composer { self.insert_char('\n'); } }
                KeyCode::Enter => self.begin_compile(Operation::Compile),
                KeyCode::Char('q') => self.quit(),
                KeyCode::Char('d') => self.modal = Some(Modal { kind: InputKind::Delete, value: String::new() }),
                _ => {}
            }
            return;
        }
        if matches!(key.code, KeyCode::Enter) && (alt || key.modifiers.contains(KeyModifiers::SHIFT)) {
            if self.focus != Focus::Composer { self.focus = Focus::Composer; }
            self.insert_char('\n');
            return;
        }
        if key.code == KeyCode::Tab {
            self.focus = match self.focus {
                Focus::Search => Focus::Rooms,
                Focus::Rooms => Focus::Timeline,
                Focus::Timeline => Focus::Composer,
                Focus::Composer => Focus::Rooms,
            };
            return;
        }
        if key.code == KeyCode::BackTab {
            self.focus = match self.focus {
                Focus::Composer => Focus::Timeline,
                Focus::Timeline => Focus::Rooms,
                Focus::Rooms => Focus::Search,
                Focus::Search => Focus::Composer,
            };
            return;
        }
        match self.focus {
            Focus::Search => self.handle_search_key(key),
            Focus::Rooms => self.handle_room_key(key),
            Focus::Timeline => self.handle_timeline_key(key),
            Focus::Composer => self.handle_composer_key(key),
        }
    }

    fn handle_search_key(&mut self, key: KeyEvent) {
        match key.code {
            KeyCode::Esc => { self.search.clear(); let _ = self.refresh_notes(""); self.focus = Focus::Composer; }
            KeyCode::Enter => { self.focus = Focus::Rooms; self.status = format!("{} chats", self.rooms.len()); }
            KeyCode::Up => { self.focus = Focus::Rooms; self.selected = self.selected.saturating_sub(1); }
            KeyCode::Down => { self.focus = Focus::Rooms; if !self.rooms.is_empty() { self.selected = (self.selected + 1).min(self.rooms.len() - 1); } }
            KeyCode::Backspace => { self.search.pop(); let _ = self.refresh_notes(&self.search.clone()); }
            KeyCode::Char(ch) => { self.search.push(ch); let _ = self.refresh_notes(&self.search.clone()); }
            _ => {}
        }
    }

    fn handle_room_key(&mut self, key: KeyEvent) {
        match key.code {
            KeyCode::Up | KeyCode::Char('k') => self.selected = self.selected.saturating_sub(1),
            KeyCode::Down | KeyCode::Char('j') => if !self.rooms.is_empty() { self.selected = (self.selected + 1).min(self.rooms.len() - 1); },
            KeyCode::Enter => { let index = self.selected; if let Err(error) = self.open_room(index) { self.status = error; } }
            KeyCode::Esc => self.focus = Focus::Composer,
            _ => self.focus = Focus::Composer,
        }
    }

    fn handle_timeline_key(&mut self, key: KeyEvent) {
        match key.code {
            KeyCode::Up | KeyCode::Char('k') => { self.stick_to_bottom = false; self.timeline_scroll = self.timeline_scroll.saturating_sub(1); }
            KeyCode::Down | KeyCode::Char('j') => { self.timeline_scroll = self.timeline_scroll.saturating_add(1); }
            KeyCode::PageUp => { self.stick_to_bottom = false; self.timeline_scroll = self.timeline_scroll.saturating_sub(8); }
            KeyCode::PageDown => self.timeline_scroll = self.timeline_scroll.saturating_add(8),
            KeyCode::Enter | KeyCode::Esc => self.focus = Focus::Composer,
            KeyCode::Char('e') => self.toggle_bytecode(),
            _ => self.focus = Focus::Composer,
        }
    }

    fn handle_composer_key(&mut self, key: KeyEvent) {
        match key.code {
            KeyCode::Enter => self.begin_compile(Operation::Run),
            KeyCode::Char(ch) => self.insert_char(ch),
            KeyCode::Backspace => self.backspace(),
            KeyCode::Delete => self.delete_char(),
            KeyCode::Up if self.composer_empty() && self.cursor_row == 0 && self.cursor_col == 0 => self.edit_last_sent(),
            code @ (KeyCode::Left | KeyCode::Right | KeyCode::Up | KeyCode::Down | KeyCode::Home | KeyCode::End) => self.move_cursor(code),
            KeyCode::Esc => self.focus = Focus::Rooms,
            _ => {}
        }
    }

    fn handle_modal_key(&mut self, key: KeyEvent) {
        if key.kind == KeyEventKind::Release { return; }
        if key.code == KeyCode::Esc { self.modal = None; return; }
        if key.code == KeyCode::Enter {
            let Some(modal) = self.modal.take() else { return; };
            match modal.kind {
                InputKind::ImagePath => match self.insert_image(&modal.value) {
                    Ok(()) => self.focus = Focus::Composer,
                    Err(error) => self.status = error,
                },
                InputKind::UnplacedImages { operation, ids } => {
                    if modal.value.trim().eq_ignore_ascii_case("remove") {
                        let before = self.images.len();
                        self.images.retain(|image| !ids.contains(&image.id));
                        let removed = before - self.images.len();
                        self.mark_dirty();
                        self.status = format!("Removed {removed} unplaced image attachment(s).");
                        if let Some(operation) = operation { self.begin_compile(operation); }
                    } else { self.status = "Image removal cancelled".to_string(); }
                }
                InputKind::BackupPath => {
                    let input = PathBuf::from(modal.value.trim().trim_matches('"'));
                    let destination = if input.is_absolute() { input } else { self.startdir.join(input) };
                    match self.bridge(json!({"action": "backup", "destination": destination})) {
                        Ok(_) => self.status = format!("Notes backed up to {}", destination.display()),
                        Err(error) => self.status = error,
                    }
                }
                InputKind::Delete => {
                    if modal.value.trim().eq_ignore_ascii_case("delete") {
                        if let Some(id) = self.entry_id.clone() {
                            match self.bridge(json!({"action": "delete", "id": id})) {
                                Ok(_) => {
                                    self.dirty = false;
                                    self.entry_id = None;
                                    self.messages.clear();
                                    self.lines = vec![Vec::new()];
                                    let _ = self.refresh_notes("");
                                    if self.rooms.is_empty() { self.new_chat(); } else if let Err(error) = self.open_room(0) { self.status = error; }
                                    self.status = "Chat deleted".to_string();
                                }
                                Err(error) => self.status = error,
                            }
                        } else { self.new_chat(); }
                    } else { self.status = "Delete cancelled".to_string(); }
                }
            }
            return;
        }
        match key.code {
            KeyCode::Backspace => { if let Some(modal) = &mut self.modal { modal.value.pop(); } }
            KeyCode::Char(ch) if !key.modifiers.contains(KeyModifiers::CONTROL) => { if let Some(modal) = &mut self.modal { modal.value.push(ch); } }
            _ => {}
        }
    }

    fn handle_mouse(&mut self, mouse: MouseEvent) {
        match mouse.kind {
            MouseEventKind::ScrollUp => self.scroll_at(mouse.column, mouse.row, -3),
            MouseEventKind::ScrollDown => self.scroll_at(mouse.column, mouse.row, 3),
            MouseEventKind::Down(MouseButton::Left) => self.click(mouse.column, mouse.row),
            _ => {}
        }
    }

    fn scroll_at(&mut self, column: u16, row: u16, delta: i32) {
        if contains(self.hits.timeline, column, row) || contains(self.hits.composer, column, row) {
            if delta < 0 { self.stick_to_bottom = false; self.timeline_scroll = self.timeline_scroll.saturating_sub(delta.unsigned_abs() as usize); }
            else { self.timeline_scroll = self.timeline_scroll.saturating_add(delta as usize); }
            self.focus = Focus::Timeline;
        } else if self.hits.rooms.iter().any(|(rect, _)| contains(*rect, column, row)) || contains(self.hits.search, column, row) {
            if delta < 0 { self.room_scroll = self.room_scroll.saturating_sub(1); }
            else { self.room_scroll = self.room_scroll.saturating_add(1); }
        }
    }

    fn click(&mut self, column: u16, row: u16) {
        if let Some((_, id)) = self.hits.bytecode.iter().find(|(y, _)| *y == row) {
            let id = id.clone();
            if !self.expanded.insert(id.clone()) { self.expanded.remove(&id); }
            self.focus = Focus::Timeline;
            return;
        }
        if let Some((_, index)) = self.hits.rooms.iter().find(|(rect, _)| contains(*rect, column, row)).cloned() {
            self.selected = index;
            if let Err(error) = self.open_room(index) { self.status = error; }
            return;
        }
        if contains(self.hits.search, column, row) { self.focus = Focus::Search; return; }
        if contains(self.hits.composer, column, row) { self.focus = Focus::Composer; return; }
        if contains(self.hits.timeline, column, row) { self.focus = Focus::Timeline; }
    }

    fn quit(&mut self) {
        if self.dirty {
            if let Err(error) = self.save() {
                self.status = format!("Could not save before quitting: {error}");
                return;
            }
        }
        self.quitting = true;
    }

    fn auto_save(&mut self) {
        if self.offline { return; }
        if self.dirty && self.dirty_since.map(|time| time.elapsed() >= Duration::from_millis(800)).unwrap_or(false) {
            if let Err(error) = self.save() {
                self.status = format!("Could not save: {error}");
                self.dirty_since = Some(Instant::now());
            }
        }
    }
}

fn contains(rect: Rect, column: u16, row: u16) -> bool {
    column >= rect.x && column < rect.x.saturating_add(rect.width) && row >= rect.y && row < rect.y.saturating_add(rect.height)
}

fn room_from_value(entry: &Value) -> Room {
    Room {
        id: text(entry, "id"), title: text(entry, "title"), preview: text(entry, "preview"),
        status: { let status = text(entry, "status"); if status.is_empty() { "draft".into() } else { status } },
        last_activity: { let stamp = text(entry, "last_activity"); if stamp.is_empty() { text(entry, "updated_at") } else { stamp } },
        unread: entry.get("unread").and_then(Value::as_i64).unwrap_or(0) != 0,
        pinned: entry.get("pinned").and_then(Value::as_i64).unwrap_or(0) != 0,
    }
}

fn message_from_value(entry: &Value) -> ChatMessage {
    ChatMessage {
        id: text(entry, "id"), role: text(entry, "role"), kind: text(entry, "kind"), body: text(entry, "body"),
        detail: entry.get("detail").cloned().unwrap_or(json!({})),
        created_at: text(entry, "created_at"),
        parent_id: entry.get("parent_id").and_then(Value::as_str).unwrap_or("").to_string(),
    }
}

fn message(id: &str, role: &str, kind: &str, body: &str, detail: Value, created_at: &str, parent: &str) -> ChatMessage {
    ChatMessage { id: id.into(), role: role.into(), kind: kind.into(), body: body.into(), detail, created_at: created_at.into(), parent_id: parent.into() }
}

fn text(value: &Value, key: &str) -> String { value.get(key).and_then(Value::as_str).unwrap_or("").to_string() }

fn split_lines(source: &str) -> Vec<Vec<char>> {
    if source.is_empty() { return vec![Vec::new()]; }
    source.split('\n').map(|line| line.chars().collect()).collect()
}

fn parse_images(document: &str) -> Vec<ImageAttachment> {
    let parsed = serde_json::from_str::<Value>(document).unwrap_or(Value::Null);
    if parsed.get("version").and_then(Value::as_u64) == Some(1) {
        let mut images = Vec::new();
        if let Some(blocks) = parsed.get("blocks").and_then(Value::as_array) {
            let mut id = 0_u64;
            for block in blocks {
                if block.get("type").and_then(Value::as_str) == Some("image") {
                    if let Some(path) = block.get("path").and_then(Value::as_str) {
                        id += 1;
                        images.push(ImageAttachment {
                            id: id.to_string(), path: PathBuf::from(path),
                            caption: block.get("caption").and_then(Value::as_str).unwrap_or("Image").to_string(),
                        });
                    }
                }
            }
        }
        return images;
    }
    images_from_detail(&parsed)
}

fn images_from_detail(detail: &Value) -> Vec<ImageAttachment> {
    let mut images = Vec::new();
    let items = detail.get("images").and_then(Value::as_array).or_else(|| {
        if detail.get("version").and_then(Value::as_u64) == Some(2) { detail.get("images").and_then(Value::as_array) } else { None }
    });
    if let Some(items) = items {
        for item in items {
            let path = item.get("path").and_then(Value::as_str).unwrap_or("");
            let id = item.get("id").and_then(Value::as_str).unwrap_or("");
            if path.is_empty() || id.is_empty() { continue; }
            images.push(ImageAttachment { id: id.to_string(), path: PathBuf::from(path), caption: item.get("caption").and_then(Value::as_str).unwrap_or("Image").to_string() });
        }
    }
    images
}

fn paths_from_detail(detail: &Value) -> Vec<PathBuf> {
    images_from_detail(detail).into_iter().map(|image| image.path).collect()
}

fn bot_from_result(result: &Value, source: &str, operation: Operation) -> (String, Value, String) {
    let status = result.get("status").and_then(Value::as_str).unwrap_or("unsupported").to_string();
    let mut lines = Vec::new();
    if status == "compiled" {
        lines.push(match operation { Operation::Compile => "Compiled successfully.".to_string(), Operation::Run => "Ran successfully.".to_string() });
        if let Some(text) = result.get("interpretation_source").and_then(Value::as_str) {
            if !text.is_empty() { lines.push(format!("Interpretation:\n{text}")); }
        }
        if matches!(operation, Operation::Run) {
            let stdout = result.get("runtime").and_then(|runtime| runtime.get("stdout")).and_then(Value::as_str).unwrap_or("");
            lines.push(if stdout.is_empty() { "Program finished with no printed output.".to_string() } else { stdout.trim_end().to_string() });
        }
    } else if status == "needs_clarification" {
        if let Some(questions) = result.get("clarifications").and_then(Value::as_array) {
            for question in questions {
                if let Some(text) = question.get("question").and_then(Value::as_str) { lines.push(text.to_string()); }
            }
        }
        if lines.is_empty() { lines.push("The compiler needs clarification.".to_string()); }
    } else {
        lines.push("Could not compile this program.".to_string());
        if let Some(diagnostics) = result.get("diagnostics").and_then(Value::as_array) {
            for diagnostic in diagnostics {
                if let Some(text) = diagnostic.get("message").and_then(Value::as_str) {
                    let prefix = diagnostic.get("span").map(|span| span_label(source, span)).unwrap_or_default();
                    lines.push(if prefix.is_empty() { text.to_string() } else { format!("{prefix} {text}") });
                }
            }
        }
    }
    let bytecode = result.get("target_code").map(|value| serde_json::to_string_pretty(value).unwrap_or_default()).unwrap_or_default();
    let detail = json!({
        "status": status,
        "operation": match operation { Operation::Compile => "compile", Operation::Run => "run" },
        "stdout": result.get("runtime").and_then(|runtime| runtime.get("stdout")).and_then(Value::as_str).unwrap_or(""),
        "diagnostics": result.get("diagnostics").cloned().unwrap_or(json!([])),
        "clarifications": result.get("clarifications").cloned().unwrap_or(json!([])),
        "bytecode": bytecode,
    });
    (lines.join("\n"), detail, status)
}

fn span_label(source: &str, span: &Value) -> String {
    let start = span.get("start").and_then(Value::as_u64).unwrap_or(0) as usize;
    let end = span.get("end").and_then(Value::as_u64).unwrap_or(start as u64) as usize;
    let chars: Vec<char> = source.chars().collect();
    let start = start.min(chars.len());
    let line = chars.iter().take(start).filter(|ch| **ch == '\n').count() + 1;
    let column = chars.iter().take(start).rev().take_while(|ch| **ch != '\n').count() + 1;
    format!("line {line}:{column} (chars {start}-{end})")
}

fn invoke_compiler(python: &Path, workdir: &Path, context: &CompileContext) -> Result<Value, String> {
    let command = match context.operation { Operation::Compile => "compile", Operation::Run => "run" };
    let mut process = Command::new(python);
    process.args(["-X", "utf8", "-m", "shipmblang", command, "--file", "-", "--pipeline", "direct", "--memory", "off", "--format", "json"]);
    for image in &context.images { process.arg("--image").arg(image); }
    if let Some(interpretation) = &context.interpretation { process.arg("--interpretation").arg(interpretation); }
    let mut child = process.current_dir(workdir).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()
        .map_err(|error| format!("Could not start ShipMBLang: {error}"))?;
    if let Some(mut input) = child.stdin.take() { input.write_all(context.source.as_bytes()).map_err(|error| error.to_string())?; }
    let output = child.wait_with_output().map_err(|error| error.to_string())?;
    match serde_json::from_slice::<Value>(&output.stdout) {
        Ok(result) => Ok(result),
        Err(error) => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            Err(if stderr.trim().is_empty() { format!("Compiler returned unreadable output: {error}") } else { stderr.trim().to_string() })
        }
    }
}

pub(crate) fn activity_label(stamp: &str, now: &str) -> String {
    let day = date_prefix(stamp);
    let today = date_prefix(now);
    let clock = clock_label(stamp);
    if day == today {
        if clock.is_empty() { "Today".into() } else { clock }
    } else if day == yesterday(&today) {
        if clock.is_empty() { "Yesterday".into() } else { format!("Yesterday {clock}") }
    } else if day.is_empty() {
        String::new()
    } else if clock.is_empty() { day } else { format!("{day} {clock}") }
}

pub(crate) fn day_label(stamp: &str, now: &str) -> String {
    let day = date_prefix(stamp);
    let today = date_prefix(now);
    if day.is_empty() { return String::new(); }
    if day == today { "Today".into() } else if day == yesterday(&today) { "Yesterday".into() } else { day }
}

pub(crate) fn clock_label(stamp: &str) -> String {
    if stamp.len() >= 16 && stamp.as_bytes().get(10) == Some(&b'T') { stamp[11..16].to_string() } else { String::new() }
}

pub(crate) fn date_prefix(stamp: &str) -> String {
    if stamp.len() >= 10 && stamp.as_bytes()[4] == b'-' && stamp.as_bytes()[7] == b'-' { stamp[..10].to_string() } else { String::new() }
}

pub(crate) fn yesterday(ymd: &str) -> String {
    let parts: Vec<i64> = ymd.split('-').filter_map(|part| part.parse().ok()).collect();
    if parts.len() != 3 { return String::new(); }
    let days = days_from_civil(parts[0], parts[1] as u32, parts[2] as u32);
    let (year, month, day) = civil_from_days(days - 1);
    format!("{year:04}-{month:02}-{day:02}")
}

fn utc_now_iso() -> String {
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() as i64;
    let days = secs.div_euclid(86_400);
    let tod = secs.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    format!("{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}+00:00", tod / 3600, (tod % 3600) / 60, tod % 60)
}

fn days_from_civil(year: i64, month: u32, day: u32) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let yoe = (year - era * 400) as u64;
    let month_index = if month > 2 { month as u64 - 3 } else { month as u64 + 9 };
    let doy = (153 * month_index + 2) / 5 + day as u64 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe as i64 - 719468
}

fn civil_from_days(mut z: i64) -> (i32, u32, u32) {
    z += 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let year = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let month_index = (5 * doy + 2) / 153;
    let day = (doy - (153 * month_index + 2) / 5 + 1) as u32;
    let month = if month_index < 10 { month_index + 3 } else { month_index - 9 };
    let year = if month <= 2 { year + 1 } else { year };
    (year as i32, month as u32, day)
}

fn run_tui(mut terminal: Terminal<CrosstermBackend<io::Stdout>>, mut app: App) -> Result<(), Box<dyn Error>> {
    loop {
        terminal.draw(|frame| ui::draw(frame, &mut app))?;
        app.receive_worker();
        app.auto_save();
        if app.quitting { break; }
        if event::poll(Duration::from_millis(100))? {
            match event::read()? {
                Event::Key(key) => app.handle_key(key),
                Event::Mouse(mouse) => app.handle_mouse(mouse),
                Event::Resize(_, _) => {}
                _ => {}
            }
        }
    }
    if app.dirty { let _ = app.save(); }
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = Args::parse().map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
    if args.version {
        println!("shipmblang-editor {EDITOR_VERSION}");
        return Ok(());
    }
    let mut app = if args.demo { App::demo(args.theme.as_deref().unwrap_or("dark"), args.ascii, args.select.unwrap_or(0)) } else { App::new(&args)? };
    if args.ascii { app.glyphs = glyphs(true); }
    if let Some(theme) = args.theme.as_deref() {
        app.light = theme == "light";
        app.palette = palette(app.light);
    }
    if args.smoke || args.dump.is_some() {
        if let Some(path) = &args.dump { ui::write_dump(&mut app, path, 100, 36)?; }
        let text = ui::render_text(&mut app, 100, 36)?;
        if args.smoke { println!("shipmblang editor smoke ok"); }
        println!("{text}");
        return Ok(());
    }
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let terminal = Terminal::new(CrosstermBackend::new(stdout))?;
    let result = run_tui(terminal, app);
    disable_raw_mode()?;
    execute!(io::stdout(), LeaveAlternateScreen, DisableMouseCapture)?;
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame(theme: &str, ascii: bool, select: usize) -> String {
        let mut app = App::demo(theme, ascii, select);
        ui::render_text(&mut app, 100, 36).unwrap()
    }

    #[test]
    fn dark_chat_frame_shows_the_conversation() {
        let text = frame("dark", false, 0);
        assert!(text.contains("ShipMB"), "{text}");
        assert!(text.contains("Today"), "{text}");
        assert!(text.contains("Show the sum"), "{text}");
        assert!(text.contains("Which declared"), "{text}");
        assert!(text.contains("Enter"), "{text}");
        assert!(text.contains("bytecode"), "{text}");
        assert!(text.contains("Yesterday"), "{text}");
    }

    #[test]
    fn light_frame_shows_the_image_attachment() {
        let text = frame("light", false, 2);
        assert!(text.contains("[[image:1]]"), "{text}");
        assert!(text.contains("park.png"), "{text}");
        assert!(text.contains("ShipMB"), "{text}");
        assert!(text.contains("Yesterday"), "{text}");
    }

    #[test]
    fn ascii_frame_uses_plain_badges_and_borders() {
        let text = frame("dark", true, 0);
        assert!(text.contains("ASK"), "{text}");
        assert!(text.contains("OK"), "{text}");
        assert!(text.contains('+'), "{text}");
        assert!(!text.contains('▸'), "{text}");
    }

    #[test]
    fn yesterday_crosses_month_and_leap_day() {
        assert_eq!(yesterday("2026-10-23"), "2026-10-22");
        assert_eq!(yesterday("2026-03-01"), "2026-02-28");
        assert_eq!(yesterday("2024-03-01"), "2024-02-29");
        assert_eq!(civil_from_days(0), (1970, 1, 1));
    }
}
