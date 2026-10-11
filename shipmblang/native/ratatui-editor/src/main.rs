use crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use crossterm::execute;
use crossterm::terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen};
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Alignment, Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use ratatui::{Frame, Terminal};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::env;
use std::error::Error;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::Duration;

const MAX_IMAGES: usize = 4;
const MAX_IMAGE_BYTES: u64 = 8_000_000;
const MAX_TOTAL_IMAGE_BYTES: u64 = 16_000_000;

#[derive(Clone)]
struct NoteSummary {
    id: String,
    title: String,
    date: String,
}

#[derive(Clone)]
struct ImageAttachment {
    id: String,
    path: PathBuf,
    caption: String,
}

#[derive(Clone, Copy, PartialEq)]
enum Focus {
    Notes,
    Document,
}

#[derive(Clone, Copy)]
enum Operation {
    Compile,
    Run,
}

#[derive(Clone)]
struct CompileContext {
    operation: Operation,
    source: String,
    images: Vec<PathBuf>,
    interpretation: Option<String>,
    clarification_rounds: usize,
}

struct WorkerResult {
    context: CompileContext,
    result: Result<Value, String>,
}

enum InputKind {
    Search,
    ImagePath,
    Clarification(String),
    UnplacedImages { operation: Option<Operation>, ids: Vec<String> },
    BackupPath,
    Delete,
}

struct Modal {
    kind: InputKind,
    value: String,
}

struct Args {
    database: PathBuf,
    python: PathBuf,
    workdir: PathBuf,
    startdir: PathBuf,
}

struct App {
    database: PathBuf,
    python: PathBuf,
    workdir: PathBuf,
    startdir: PathBuf,
    notes: Vec<NoteSummary>,
    selected_note: usize,
    focus: Focus,
    entry_id: Option<String>,
    entry_date: String,
    journal: String,
    lines: Vec<Vec<char>>,
    cursor_row: usize,
    cursor_col: usize,
    scroll_y: usize,
    scroll_x: usize,
    images: Vec<ImageAttachment>,
    next_image_id: u64,
    dirty: bool,
    dirty_since: Option<std::time::Instant>,
    busy: bool,
    modal: Option<Modal>,
    status: String,
    output: Vec<String>,
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
        let mut values = env::args().skip(1);
        while let Some(arg) = values.next() {
            let value = values.next().ok_or_else(|| format!("Missing value after {arg}"))?;
            match arg.as_str() {
                "--database" => database = Some(PathBuf::from(value)),
                "--python" => python = Some(PathBuf::from(value)),
                "--workdir" => workdir = Some(PathBuf::from(value)),
                "--startdir" => startdir = Some(PathBuf::from(value)),
                _ => return Err(format!("Unknown editor option: {arg}")),
            }
        }
        Ok(Self {
            database: database.ok_or_else(|| "Missing --database".to_string())?,
            python: python.ok_or_else(|| "Missing --python".to_string())?,
            workdir: workdir.ok_or_else(|| "Missing --workdir".to_string())?,
            startdir: startdir.ok_or_else(|| "Missing --startdir".to_string())?,
        })
    }
}

impl App {
    fn new(args: Args) -> Result<Self, Box<dyn Error>> {
        let (tx, rx) = mpsc::channel();
        let mut app = Self {
            database: args.database,
            python: args.python,
            workdir: args.workdir,
            startdir: args.startdir,
            notes: Vec::new(),
            selected_note: 0,
            focus: Focus::Document,
            entry_id: None,
            entry_date: String::new(),
            journal: String::new(),
            lines: vec![Vec::new()],
            cursor_row: 0,
            cursor_col: 0,
            scroll_y: 0,
            scroll_x: 0,
            images: Vec::new(),
            next_image_id: 1,
            dirty: false,
            dirty_since: None,
            busy: false,
            modal: None,
            status: "Opening notebook…".to_string(),
            output: vec![
                "Write a ShipMBLang program as a document, add images inline, and compile.".to_string(),
                "Image anchors are passed to the compiler in the order they appear in the text.".to_string(),
            ],
            tx,
            rx,
            pending: None,
            quitting: false,
        };
        app.refresh_notes("")?;
        if !app.notes.is_empty() {
            app.open_note(0)?;
        } else {
            app.status = "New document".to_string();
        }
        Ok(app)
    }

    fn bridge(&self, request: Value) -> Result<Value, String> {
        let mut child = Command::new(&self.python)
            .args(["-X", "utf8", "-m", "shipmblang.editor_bridge", "--database"])
            .arg(&self.database)
            .current_dir(&self.workdir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("Could not start Python: {error}"))?;
        if let Some(mut input) = child.stdin.take() {
            serde_json::to_writer(&mut input, &request).map_err(|error| error.to_string())?;
            input.flush().map_err(|error| error.to_string())?;
        }
        let output = child.wait_with_output().map_err(|error| error.to_string())?;
        if !output.status.success() {
            let detail = String::from_utf8_lossy(&output.stderr);
            return Err(if detail.trim().is_empty() {
                "Could not access the notes database.".to_string()
            } else {
                detail.trim().to_string()
            });
        }
        let value: Value = serde_json::from_slice(&output.stdout).map_err(|error| {
            format!("The notes database returned an unreadable response: {error}")
        })?;
        if value.get("ok").and_then(Value::as_bool) != Some(true) {
            return Err(value.get("error").and_then(Value::as_str).unwrap_or("Notes operation failed.").to_string());
        }
        Ok(value)
    }

    fn refresh_notes(&mut self, query: &str) -> Result<(), String> {
        let response = self.bridge(json!({"action":"list", "query":query}))?;
        self.notes = response.get("entries").and_then(Value::as_array).into_iter().flatten()
            .map(|entry| NoteSummary {
                id: text(entry, "id"), title: text(entry, "title"), date: text(entry, "entry_date"),
            }).collect();
        self.selected_note = self.selected_note.min(self.notes.len().saturating_sub(1));
        Ok(())
    }

    fn open_note(&mut self, index: usize) -> Result<(), String> {
        let summary = self.notes.get(index).ok_or("Choose a note first.")?.clone();
        if self.dirty {
            self.save()?;
        }
        let response = self.bridge(json!({"action":"get", "id":summary.id}))?;
        let entry = response.get("entry").and_then(Value::as_object).ok_or("Note was not found.")?;
        self.entry_id = entry.get("id").and_then(Value::as_str).map(str::to_string);
        self.entry_date = entry.get("entry_date").and_then(Value::as_str).unwrap_or("").to_string();
        self.journal = entry.get("journal").and_then(Value::as_str).unwrap_or("").to_string();
        let program = entry.get("program").and_then(Value::as_str).unwrap_or("").to_string();
        self.lines = split_lines(&program);
        self.images = parse_images(entry.get("document").and_then(Value::as_str).unwrap_or(""), &program);
        self.next_image_id = self.images.iter().filter_map(|image| image.id.parse::<u64>().ok()).max().unwrap_or(0) + 1;
        self.cursor_row = 0;
        self.cursor_col = 0;
        self.scroll_x = 0;
        self.scroll_y = 0;
        self.dirty = false;
        self.dirty_since = None;
        self.selected_note = index;
        self.focus = Focus::Document;
        self.status = "Saved".to_string();
        self.output = vec![format!("Opened {}", summary.title)];
        Ok(())
    }

    fn new_note(&mut self) {
        if self.dirty {
            if let Err(error) = self.save() {
                self.status = "Save failed".to_string();
                self.output = vec![error];
                return;
            }
        }
        self.entry_id = None;
        self.entry_date.clear();
        self.journal.clear();
        self.lines = vec![Vec::new()];
        self.images.clear();
        self.next_image_id = 1;
        self.cursor_row = 0;
        self.cursor_col = 0;
        self.scroll_x = 0;
        self.scroll_y = 0;
        self.dirty = false;
        self.status = "New document".to_string();
        self.output = vec!["New document. Start typing or press Ctrl+I to add an image.".to_string()];
        self.focus = Focus::Document;
    }

    fn save(&mut self) -> Result<(), String> {
        let source = self.source();
        let title = source.lines().find(|line| !line.trim().is_empty()).unwrap_or("Untitled note").trim();
        let document = json!({
            "version": 2,
            "images": self.images.iter().map(|image| json!({
                "id": image.id, "path": image.path.to_string_lossy(), "caption": image.caption,
            })).collect::<Vec<_>>(),
        });
        let response = self.bridge(json!({
            "action":"save", "id":self.entry_id, "entry_date":self.entry_date,
            "title":title.chars().take(60).collect::<String>(), "journal":self.journal,
            "program":source, "document":document.to_string(),
        }))?;
        let entry = response.get("entry").and_then(Value::as_object).ok_or("Note was saved but could not be reloaded.")?;
        self.entry_id = entry.get("id").and_then(Value::as_str).map(str::to_string);
        self.entry_date = entry.get("entry_date").and_then(Value::as_str).unwrap_or("").to_string();
        self.dirty = false;
        self.dirty_since = None;
        self.refresh_notes("")?;
        if let Some(id) = &self.entry_id {
            if let Some(index) = self.notes.iter().position(|note| &note.id == id) {
                self.selected_note = index;
            }
        }
        self.status = "Saved".to_string();
        Ok(())
    }

    fn mark_dirty(&mut self) {
        self.dirty = true;
        self.dirty_since = Some(std::time::Instant::now());
        self.status = "Editing…".to_string();
    }

    fn source(&self) -> String {
        self.lines.iter().map(|line| line.iter().collect::<String>()).collect::<Vec<_>>().join("\n")
    }

    fn title(&self) -> String {
        self.source().lines().find(|line| !line.trim().is_empty()).unwrap_or("Untitled note").trim().chars().take(60).collect()
    }

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

    fn delete(&mut self) {
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
        self.images.push(ImageAttachment { id, path, caption });
        self.output = vec![format!("Inserted {caption} at the cursor."), "The numbered image reference follows the document order.".to_string()];
        Ok(())
    }

    fn active_image_stats(&self) -> (usize, u64) {
        let total = self.images.iter()
            .filter_map(|image| fs::metadata(&image.path).ok())
            .fold(0_u64, |sum, metadata| sum.saturating_add(metadata.len()));
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
                    if known.contains_key(id.as_str()) {
                        *used.entry(id).or_insert(0) += 1;
                    }
                    index = end + 2;
                    continue;
                }
            }
            index += 1;
        }
        self.images.iter().filter(|image| !used.contains_key(&image.id))
            .map(|image| image.id.clone()).collect()
    }

    fn ordered_submission(&self, source: &str) -> Result<(String, Vec<PathBuf>), String> {
        if self.images.len() > MAX_IMAGES {
            return Err(format!("A document can use at most {MAX_IMAGES} image attachments. Remove extras with Ctrl+R."));
        }
        let mut total_bytes = 0_u64;
        for image in &self.images {
            let metadata = fs::metadata(&image.path)
                .map_err(|error| format!("Cannot read attached image {}: {error}", image.caption))?;
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
                    return Err(format!("Image attachment {} is referenced more than once. Keep one marker or insert a separate attachment with Ctrl+I.", id));
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
            return Err(format!("Attached image {} has no marker in the document. Restore [[image:{}]] or remove unplaced images with Ctrl+R.", image.caption, image.id));
        }
        Ok((output, paths))
    }

    fn prompt_remove_unplaced(&mut self, operation: Option<Operation>) {
        let ids = self.unplaced_image_ids(&self.source());
        if ids.is_empty() {
            if operation.is_none() {
                self.status = "No unplaced images".to_string();
            }
            return;
        }
        self.modal = Some(Modal { kind: InputKind::UnplacedImages { operation, ids }, value: String::new() });
    }

    fn ordered_image_ids(&self) -> Vec<String> {
        let source: Vec<char> = self.source().chars().collect();
        let known: HashMap<&str, ()> = self.images.iter().map(|image| (image.id.as_str(), ())).collect();
        let mut ids = Vec::new();
        let mut index = 0;
        while index + 8 <= source.len() {
            if source[index..index + 8].iter().collect::<String>() == "[[image:" {
                if let Some(end_rel) = source[index + 8..].windows(2).position(|pair| pair == [']', ']']) {
                    let end = index + 8 + end_rel;
                    let id = source[index + 8..end].iter().collect::<String>();
                    if known.contains_key(id.as_str()) {
                        ids.push(id);
                        index = end + 2;
                        continue;
                    }
                }
            }
            index += 1;
        }
        ids
    }

    fn begin_compile(&mut self, operation: Operation) {
        if self.busy { return; }
        let source = self.source();
        if source.trim().is_empty() {
            self.output = vec!["Write a program before compiling.".to_string()];
            self.status = "Empty document".to_string();
            return;
        }
        if let Err(error) = self.save() {
            self.output = vec![format!("Save before compiling: {error}")];
            self.status = "Save failed".to_string();
            return;
        }
        let (source, images) = match self.ordered_submission(&source) {
            Ok(result) => result,
            Err(error) => {
                self.output = vec![error];
                self.status = "Image reference needs attention".to_string();
                self.prompt_remove_unplaced(Some(operation));
                return;
            }
        };
        self.start_worker(CompileContext { operation, source, images, interpretation: None, clarification_rounds: 0 });
    }

    fn start_worker(&mut self, context: CompileContext) {
        self.busy = true;
        self.pending = Some(context.clone());
        self.status = match context.operation { Operation::Compile => "Compiling…", Operation::Run => "Running…" }.to_string();
        self.output = vec![self.status.clone(), "The editor remains available while the compiler works.".to_string()];
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
        match message.result {
            Err(error) => { self.output = vec![format!("Could not compile: {error}")]; self.status = "Compiler error".to_string(); }
            Ok(result) => {
                let stale = self.ordered_submission(&self.source()).map(|(source, paths)| source != message.context.source || paths != message.context.images).unwrap_or(true);
                self.output = format_result(&result, message.context.operation);
                if stale {
                    self.output.insert(0, "Result is from before the latest document edit.".to_string());
                    self.status = "Older document result".to_string();
                    return;
                }
                if result.get("status").and_then(Value::as_str) == Some("needs_clarification") {
                    let question = result.get("clarifications").and_then(Value::as_array).and_then(|items| items.first());
                    let id = question.and_then(|item| item.get("id")).and_then(Value::as_str).unwrap_or("");
                    let text = question.and_then(|item| item.get("question")).and_then(Value::as_str).unwrap_or("");
                    if id == "image-model" {
                        self.status = "Image-capable model required".to_string();
                    } else if !text.is_empty() {
                        let mut context = message.context;
                        if context.clarification_rounds < 4 {
                            self.modal = Some(Modal { kind: InputKind::Clarification(text.to_string()), value: String::new() });
                            self.pending = Some(context);
                            self.status = "Compiler needs clarification".to_string();
                        } else {
                            self.status = "Clarification limit reached".to_string();
                        }
                    } else {
                        self.status = "Compiler needs clarification".to_string();
                    }
                } else if result.get("status").and_then(Value::as_str) == Some("compiled") {
                    self.status = match message.context.operation { Operation::Compile => "Compiled", Operation::Run => "Finished" }.to_string();
                } else {
                    self.status = "Could not compile".to_string();
                }
            }
        }
    }

    fn handle_key(&mut self, key: KeyEvent) {
        if key.kind == KeyEventKind::Release { return; }
        if self.modal.is_some() {
            self.handle_modal_key(key);
            return;
        }
        let control = key.modifiers.contains(KeyModifiers::CONTROL);
        if control {
            match key.code {
                KeyCode::Char('s') => { if let Err(error) = self.save() { self.output = vec![error]; self.status = "Save failed".to_string(); } }
                KeyCode::Char('n') => self.new_note(),
                KeyCode::Char('o') => self.modal = Some(Modal { kind: InputKind::Search, value: String::new() }),
                KeyCode::Char('i') => self.modal = Some(Modal { kind: InputKind::ImagePath, value: String::new() }),
                KeyCode::Char('b') => self.modal = Some(Modal { kind: InputKind::BackupPath, value: String::new() }),
                KeyCode::Char('r') => self.prompt_remove_unplaced(None),
                KeyCode::Enter => self.begin_compile(Operation::Compile),
                KeyCode::Char('q') => {
                    if self.dirty {
                        if let Err(error) = self.save() {
                            self.output = vec![format!("Could not save before quitting: {error}")];
                            self.status = "Not saved".to_string();
                            return;
                        }
                    }
                    self.quitting = true;
                }
                KeyCode::Char('d') => self.modal = Some(Modal { kind: InputKind::Delete, value: String::new() }),
                _ => {}
            }
            return;
        }
        if key.code == KeyCode::F(5) { self.begin_compile(Operation::Run); return; }
        if key.code == KeyCode::Tab { self.focus = if self.focus == Focus::Notes { Focus::Document } else { Focus::Notes }; return; }
        if self.focus == Focus::Notes {
            match key.code {
                KeyCode::Up | KeyCode::Char('k') => self.selected_note = self.selected_note.saturating_sub(1),
                KeyCode::Down | KeyCode::Char('j') => self.selected_note = (self.selected_note + 1).min(self.notes.len().saturating_sub(1)),
                KeyCode::Enter => { let result = self.open_note(self.selected_note); if let Err(error) = result { self.output = vec![error]; } }
                KeyCode::Char('i') => self.modal = Some(Modal { kind: InputKind::ImagePath, value: String::new() }),
                _ => self.focus = Focus::Document,
            }
        } else {
            match key.code {
                KeyCode::Char(ch) => self.insert_char(ch),
                KeyCode::Enter => self.insert_char('\n'),
                KeyCode::Backspace => self.backspace(),
                KeyCode::Delete => self.delete(),
                code @ (KeyCode::Left | KeyCode::Right | KeyCode::Up | KeyCode::Down | KeyCode::Home | KeyCode::End) => self.move_cursor(code),
                KeyCode::Esc => self.focus = Focus::Notes,
                _ => {}
            }
        }
    }

    fn handle_modal_key(&mut self, key: KeyEvent) {
        if key.kind == KeyEventKind::Release { return; }
        if key.code == KeyCode::Esc { self.modal = None; self.pending = None; return; }
        if key.code == KeyCode::Enter {
            let Some(modal) = self.modal.take() else { return; };
            match modal.kind {
                InputKind::Search => {
                    if let Err(error) = self.refresh_notes(&modal.value) { self.output = vec![error]; }
                    self.selected_note = 0;
                    self.focus = Focus::Notes;
                    self.status = format!("{} notes", self.notes.len());
                }
                InputKind::ImagePath => match self.insert_image(&modal.value) {
                    Ok(()) => { self.focus = Focus::Document; }
                    Err(error) => { self.output = vec![error]; self.status = "Image not added".to_string(); }
                },
                InputKind::Clarification(question) => {
                    let answer = modal.value.trim().to_string();
                    if answer.is_empty() { self.status = "Clarification skipped".to_string(); return; }
                    if let Some(mut context) = self.pending.take() {
                        context.interpretation = Some(answer);
                        context.clarification_rounds += 1;
                        self.start_worker(context);
                    }
                }
                InputKind::UnplacedImages { operation, ids } => {
                    if modal.value.trim().eq_ignore_ascii_case("remove") {
                        let before = self.images.len();
                        self.images.retain(|image| !ids.contains(&image.id));
                        let removed = before - self.images.len();
                        self.mark_dirty();
                        self.output = vec![format!("Removed {removed} unplaced image attachment(s).")];
                        if let Some(operation) = operation {
                            self.begin_compile(operation);
                        }
                    } else {
                        self.status = "Image removal cancelled".to_string();
                    }
                }
                InputKind::BackupPath => {
                    let input = PathBuf::from(modal.value.trim().trim_matches('"'));
                    let destination = if input.is_absolute() { input } else { self.startdir.join(input) };
                    match self.bridge(json!({"action":"backup", "destination":destination})) {
                        Ok(_) => { self.status = "Backup saved".to_string(); self.output = vec![format!("Notes backed up to {}", destination.display())]; }
                        Err(error) => { self.status = "Backup failed".to_string(); self.output = vec![error]; }
                    }
                }
                InputKind::Delete => {
                    if modal.value.trim().eq_ignore_ascii_case("delete") {
                        if let Some(id) = self.entry_id.clone() {
                            match self.bridge(json!({"action":"delete", "id":id})) {
                                Ok(_) => { self.dirty = false; self.entry_id = None; self.new_note(); let _ = self.refresh_notes(""); self.status = "Note deleted".to_string(); }
                                Err(error) => { self.output = vec![error]; self.status = "Delete failed".to_string(); }
                            }
                        } else { self.new_note(); }
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

    fn auto_save(&mut self) {
        if self.dirty && self.dirty_since.map(|time| time.elapsed() >= Duration::from_millis(800)).unwrap_or(false) {
            if let Err(error) = self.save() {
                self.output = vec![format!("Could not save: {error}")];
                self.status = "Not saved".to_string();
                self.dirty_since = Some(std::time::Instant::now());
            }
        }
    }
}

fn text(value: &Value, key: &str) -> String {
    value.get(key).and_then(Value::as_str).unwrap_or("").to_string()
}

fn split_lines(source: &str) -> Vec<Vec<char>> {
    source.split('\n').map(|line| line.chars().collect()).collect()
}

fn parse_images(document: &str, program: &str) -> Vec<ImageAttachment> {
    let parsed = serde_json::from_str::<Value>(document).unwrap_or(Value::Null);
    let mut images = Vec::new();
    if parsed.get("version").and_then(Value::as_u64) == Some(2) {
        if let Some(items) = parsed.get("images").and_then(Value::as_array) {
            for item in items {
                let path = item.get("path").and_then(Value::as_str).unwrap_or("");
                if path.is_empty() { continue; }
                let id = item.get("id").and_then(Value::as_str).unwrap_or("").to_string();
                if id.is_empty() { continue; }
                images.push(ImageAttachment {
                    id,
                    path: PathBuf::from(path),
                    caption: item.get("caption").and_then(Value::as_str).unwrap_or("Image").to_string(),
                });
            }
        }
    } else if parsed.get("version").and_then(Value::as_u64) == Some(1) {
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
    }
    let _ = program;
    images
}

fn invoke_compiler(python: &Path, workdir: &Path, context: &CompileContext) -> Result<Value, String> {
    let command = match context.operation { Operation::Compile => "compile", Operation::Run => "run" };
    let mut process = Command::new(python);
    process.args(["-X", "utf8", "-m", "shipmblang", command, "--file", "-", "--pipeline", "direct", "--memory", "off", "--format", "json"]);
    for image in &context.images { process.arg("--image").arg(image); }
    if let Some(interpretation) = &context.interpretation {
        process.arg("--interpretation").arg(interpretation);
    }
    let mut child = process.current_dir(workdir).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|error| format!("Could not start ShipMBLang: {error}"))?;
    if let Some(mut input) = child.stdin.take() {
        input.write_all(context.source.as_bytes()).map_err(|error| error.to_string())?;
    }
    let output = child.wait_with_output().map_err(|error| error.to_string())?;
    let parsed = serde_json::from_slice::<Value>(&output.stdout);
    match parsed {
        Ok(result) => Ok(result),
        Err(error) => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            Err(if stderr.trim().is_empty() { format!("Compiler returned unreadable output: {error}") } else { stderr.trim().to_string() })
        }
    }
}

fn format_result(result: &Value, operation: Operation) -> Vec<String> {
    let mut lines = Vec::new();
    let status = result.get("status").and_then(Value::as_str).unwrap_or("unsupported");
    if status == "compiled" {
        lines.push(match operation { Operation::Compile => "Compiled successfully.".to_string(), Operation::Run => "Ran successfully.".to_string() });
        if let Some(interpretation) = result.get("interpretation_source").and_then(Value::as_str) {
            lines.push(String::new());
            lines.push("Compiler interpretation:".to_string());
            lines.extend(interpretation.lines().map(str::to_string));
        }
        if matches!(operation, Operation::Run) {
            let stdout = result.get("runtime").and_then(|runtime| runtime.get("stdout")).and_then(Value::as_str).unwrap_or("");
            lines.push(String::new());
            lines.push(if stdout.is_empty() { "Program finished with no printed output.".to_string() } else { format!("Output: {stdout}") });
        }
        if let Some(target) = result.get("target_code") {
            lines.push(String::new());
            lines.push("Bytecode:".to_string());
            lines.extend(serde_json::to_string_pretty(target).unwrap_or_default().lines().map(str::to_string));
        }
    } else {
        lines.push(if status == "needs_clarification" { "The compiler needs clarification.".to_string() } else { "Could not compile this document.".to_string() });
        if let Some(questions) = result.get("clarifications").and_then(Value::as_array) {
            for question in questions {
                if let Some(text) = question.get("question").and_then(Value::as_str) { lines.push(format!("? {text}")); }
            }
        }
        if let Some(diagnostics) = result.get("diagnostics").and_then(Value::as_array) {
            for diagnostic in diagnostics {
                if let Some(text) = diagnostic.get("message").and_then(Value::as_str) { lines.push(format!("• {text}")); }
            }
        }
    }
    if lines.is_empty() { lines.push(serde_json::to_string_pretty(result).unwrap_or_else(|_| "No compiler output.".to_string())); }
    lines
}

fn editor_area(frame: &mut Frame, area: Rect, app: &mut App) {
    let block = Block::default().title(format!(" Document  ·  {} ", app.title())).borders(Borders::ALL)
        .border_style(if app.focus == Focus::Document { Style::default().fg(Color::Cyan) } else { Style::default().fg(Color::DarkGray) });
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let height = inner.height as usize;
    let text_width = inner.width.saturating_sub(7) as usize;
    if height == 0 || text_width == 0 { return; }
    if app.cursor_row < app.scroll_y { app.scroll_y = app.cursor_row; }
    if app.cursor_row >= app.scroll_y + height { app.scroll_y = app.cursor_row + 1 - height; }
    if app.cursor_col < app.scroll_x { app.scroll_x = app.cursor_col; }
    if app.cursor_col >= app.scroll_x + text_width { app.scroll_x = app.cursor_col + 1 - text_width; }
    let mut rendered = Vec::new();
    for index in app.scroll_y..(app.scroll_y + height).min(app.lines.len()) {
        let line = &app.lines[index];
        let mut spans = vec![Span::styled(format!("{:>4} ", index + 1), Style::default().fg(Color::DarkGray))];
        let visible = &line[app.scroll_x.min(line.len())..];
        let visible = &visible[..visible.len().min(text_width)];
        let mut position = 0;
        while position < visible.len() {
            let global = app.scroll_x + position;
            if position + 8 <= visible.len() && visible[position..position + 8].iter().collect::<String>() == "[[image:" {
                if let Some(end_rel) = visible[position + 8..].windows(2).position(|pair| pair == [']', ']']) {
                    let end = position + 8 + end_rel + 2;
                    let token = visible[position..end].iter().collect::<String>();
                    spans.push(Span::styled(token, Style::default().fg(Color::LightCyan).bg(Color::Rgb(25, 49, 61))));
                    position = end;
                    continue;
                }
            }
            let ch = visible[position];
            let style = if app.focus == Focus::Document && index == app.cursor_row && global == app.cursor_col {
                Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD)
            } else if app.focus == Focus::Document && index == app.cursor_row && global + 1 == app.cursor_col {
                Style::default().fg(Color::White).bg(Color::Rgb(40, 48, 56))
            } else { Style::default().fg(Color::White) };
            spans.push(Span::styled(ch.to_string(), style));
            position += 1;
        }
        if app.focus == Focus::Document && index == app.cursor_row && app.cursor_col >= app.scroll_x + visible.len() {
            spans.push(Span::styled(" ", Style::default().fg(Color::Black).bg(Color::Cyan)));
        }
        rendered.push(Line::from(spans));
    }
    frame.render_widget(Paragraph::new(rendered), inner);
}

fn draw(frame: &mut Frame, app: &mut App) {
    let outer = Layout::default().direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(8), Constraint::Length(8), Constraint::Length(2)]).split(frame.area());
    let header = Line::from(vec![
        Span::styled(" ShipMBLang ", Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD)),
        Span::styled("  Documents  /  ", Style::default().fg(Color::Gray)),
        Span::styled(app.title(), Style::default().fg(Color::White).add_modifier(Modifier::BOLD)),
        Span::styled("    ", Style::default()),
        Span::styled(if app.dirty { "Unsaved" } else { app.status.as_str() }, Style::default().fg(if app.dirty { Color::Yellow } else { Color::Green })),
    ]);
    frame.render_widget(Paragraph::new(header).block(Block::default().borders(Borders::BOTTOM).border_style(Style::default().fg(Color::DarkGray))), outer[0]);
    let middle = Layout::default().direction(Direction::Horizontal).constraints([Constraint::Percentage(24), Constraint::Percentage(76)]).split(outer[1]);
    let mut note_lines = vec![Line::from(Span::styled("Your documents", Style::default().fg(Color::Gray)))];
    let visible_notes = middle[0].height.saturating_sub(3) as usize;
    for (index, note) in app.notes.iter().enumerate().skip(app.selected_note.saturating_sub(visible_notes.saturating_sub(1))).take(visible_notes) {
        let style = if index == app.selected_note { Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD) } else { Style::default().fg(Color::White) };
        note_lines.push(Line::from(Span::styled(truncate(&note.title, middle[0].width.saturating_sub(4) as usize), style)));
        if middle[0].width > 14 { note_lines.push(Line::from(Span::styled(format!("  {}", note.date), Style::default().fg(Color::DarkGray)))); }
    }
    frame.render_widget(Paragraph::new(note_lines).block(Block::default().title(" Notes ").borders(Borders::ALL)
        .border_style(if app.focus == Focus::Notes { Style::default().fg(Color::Cyan) } else { Style::default().fg(Color::DarkGray) })), middle[0]);
    editor_area(frame, middle[1], app);

    let lower = Layout::default().direction(Direction::Horizontal).constraints([Constraint::Percentage(24), Constraint::Percentage(76)]).split(outer[2]);
    let mut image_lines = vec![Line::from(Span::styled("Inline image cards", Style::default().fg(Color::Gray)))];
    let mut seen = HashMap::<String, usize>::new();
    for (order, id) in app.ordered_image_ids().iter().enumerate() {
        if let Some(attachment) = app.images.iter().find(|image| &image.id == id) {
            let references = seen.entry(id.clone()).or_insert(0);
            *references += 1;
            let duplicate = if *references > 1 { " · duplicate marker" } else { "" };
            image_lines.push(Line::from(Span::styled(format!("{}. {}{}", order + 1, truncate(&attachment.caption, lower[0].width.saturating_sub(5) as usize), duplicate), Style::default().fg(if *references > 1 { Color::Yellow } else { Color::LightCyan }))));
            image_lines.push(Line::from(Span::styled(truncate(&attachment.path.to_string_lossy(), lower[0].width.saturating_sub(5) as usize), Style::default().fg(Color::DarkGray))));
        }
    }
    for attachment in &app.images {
        if !seen.contains_key(&attachment.id) {
            image_lines.push(Line::from(Span::styled(format!("Unplaced · {}", truncate(&attachment.caption, lower[0].width.saturating_sub(5) as usize)), Style::default().fg(Color::Yellow))));
            image_lines.push(Line::from(Span::styled(format!("{} · Ctrl+R to remove", truncate(&attachment.path.to_string_lossy(), lower[0].width.saturating_sub(5) as usize)), Style::default().fg(Color::DarkGray))));
        }
    }
    if app.images.is_empty() { image_lines.push(Line::from(Span::styled("Ctrl+I to insert an image", Style::default().fg(Color::DarkGray)))); }
    frame.render_widget(Paragraph::new(image_lines).wrap(Wrap { trim: true }).block(Block::default().title(" Images ").borders(Borders::ALL).border_style(Style::default().fg(Color::DarkGray))), lower[0]);
    let output_lines = app.output.iter().map(|line| Line::from(line.as_str())).collect::<Vec<_>>();
    frame.render_widget(Paragraph::new(output_lines).wrap(Wrap { trim: false }).block(Block::default().title(" Compiler / Output ").borders(Borders::ALL).border_style(Style::default().fg(Color::DarkGray))), lower[1]);
    let footer = Line::from(vec![
        Span::styled(" Ctrl+S ", Style::default().fg(Color::Cyan)), Span::raw("Save  "),
        Span::styled("Ctrl+N ", Style::default().fg(Color::Cyan)), Span::raw("New  "),
        Span::styled("Ctrl+O ", Style::default().fg(Color::Cyan)), Span::raw("Search  "),
        Span::styled("Ctrl+I ", Style::default().fg(Color::Cyan)), Span::raw("Image  "),
        Span::styled("Ctrl+R ", Style::default().fg(Color::Cyan)), Span::raw("Remove unplaced  "),
        Span::styled("Ctrl+B ", Style::default().fg(Color::Cyan)), Span::raw("Backup  "),
        Span::styled("Ctrl+Enter ", Style::default().fg(Color::Cyan)), Span::raw("Compile  "),
        Span::styled("F5 ", Style::default().fg(Color::Cyan)), Span::raw("Run  "),
        Span::styled("Tab ", Style::default().fg(Color::Cyan)), Span::raw("Switch panel  "),
        Span::styled("Ctrl+Q ", Style::default().fg(Color::Cyan)), Span::raw("Quit"),
    ]);
    frame.render_widget(Paragraph::new(footer).alignment(Alignment::Center), outer[3]);
    if let Some(modal) = &app.modal { draw_modal(frame, modal); }
}

fn draw_modal(frame: &mut Frame, modal: &Modal) {
    let area = centered(frame.area(), 76, 7);
    frame.render_widget(Clear, area);
    let (title, prompt) = match &modal.kind {
        InputKind::Search => ("Find a document", "Search title or text; Enter to filter, Esc to cancel".to_string()),
        InputKind::ImagePath => ("Insert image", "Enter a local PNG, JPEG, GIF, WebP or BMP path".to_string()),
        InputKind::Clarification(question) => ("Compiler clarification", format!("{question}\nEnter the complete clarified program in English.")),
        InputKind::UnplacedImages { ids, .. } => ("Remove unplaced images", format!("Attachments without markers: {}. Type REMOVE to detach them; Esc cancels.", ids.join(", "))),
        InputKind::BackupPath => ("Back up notes", "Enter a destination path for a SQLite backup".to_string()),
        InputKind::Delete => ("Delete document", "Type DELETE and press Enter to permanently delete this note".to_string()),
    };
    let content = vec![Line::from(prompt), Line::from(""), Line::from(Span::styled(format!("› {}", modal.value), Style::default().fg(Color::Yellow)))];
    frame.render_widget(Paragraph::new(content).wrap(Wrap { trim: true }).block(Block::default().title(format!(" {title} ")).borders(Borders::ALL).border_style(Style::default().fg(Color::Cyan))), area);
}

fn centered(area: Rect, width: u16, height: u16) -> Rect {
    Rect { x: area.x + area.width.saturating_sub(width) / 2, y: area.y + area.height.saturating_sub(height) / 2, width: width.min(area.width), height: height.min(area.height) }
}

fn truncate(text: &str, max: usize) -> String {
    let chars: Vec<char> = text.chars().collect();
    if chars.len() <= max { text.to_string() } else if max > 1 { format!("{}…", chars[..max - 1].iter().collect::<String>()) } else { "…".to_string() }
}

fn run_tui(mut terminal: Terminal<CrosstermBackend<io::Stdout>>, mut app: App) -> Result<(), Box<dyn Error>> {
    loop {
        terminal.draw(|frame| draw(frame, &mut app))?;
        app.receive_worker();
        app.auto_save();
        if app.quitting { break; }
        if event::poll(Duration::from_millis(100))? {
            if let Event::Key(key) = event::read()? { app.handle_key(key); }
        }
    }
    if app.dirty { let _ = app.save(); }
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = Args::parse().map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
    let app = App::new(args).map_err(|error| io::Error::new(io::ErrorKind::Other, error.to_string()))?;
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let terminal = Terminal::new(CrosstermBackend::new(stdout))?;
    let result = run_tui(terminal, app);
    disable_raw_mode()?;
    execute!(io::stdout(), LeaveAlternateScreen)?;
    result
}
