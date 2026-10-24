use ratatui::backend::TestBackend;
use ratatui::buffer::{Buffer, CellWidth};
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Paragraph, Wrap};
use ratatui::{Frame, Terminal};
use std::error::Error;
use std::fs;
use std::path::Path;

use crate::{App, ChatMessage, Focus, InputKind};

#[derive(Clone, Copy)]
pub(crate) struct Palette {
    pub(crate) bg: Color,
    pub(crate) sidebar: Color,
    pub(crate) text: Color,
    pub(crate) muted: Color,
    pub(crate) accent: Color,
    pub(crate) user_bg: Color,
    pub(crate) user_fg: Color,
    pub(crate) bot_bg: Color,
    pub(crate) bot_fg: Color,
    pub(crate) error_bg: Color,
    pub(crate) error_fg: Color,
    pub(crate) error_accent: Color,
    pub(crate) ok: Color,
    pub(crate) warn: Color,
    pub(crate) composer: Color,
    pub(crate) border: Color,
    pub(crate) chip: Color,
    pub(crate) header: Color,
}

#[derive(Clone, Copy)]
pub(crate) struct Glyphs {
    pub(crate) rounded: bool,
    pub(crate) ellipsis: &'static str,
    pub(crate) ok: &'static str,
    pub(crate) err: &'static str,
    pub(crate) ask: &'static str,
    pub(crate) draft: &'static str,
    pub(crate) pin: &'static str,
    pub(crate) unread: &'static str,
    pub(crate) collapse: &'static str,
    pub(crate) expand: &'static str,
    pub(crate) bar: &'static str,
    pub(crate) thread: &'static str,
}

#[derive(Clone)]
pub(crate) struct BuiltLine {
    pub(crate) spans: Vec<(String, Style)>,
    pub(crate) bytecode_for: Option<String>,
}

pub(crate) fn palette(light: bool) -> Palette {
    if light {
        Palette {
            bg: rgb(255, 255, 255), sidebar: rgb(242, 243, 245), text: rgb(26, 28, 32),
            muted: rgb(90, 96, 108), accent: rgb(51, 144, 236), user_bg: rgb(214, 228, 255),
            user_fg: rgb(18, 32, 56), bot_bg: rgb(240, 242, 245), bot_fg: rgb(26, 28, 32),
            error_bg: rgb(255, 226, 226), error_fg: rgb(120, 24, 24), error_accent: rgb(196, 48, 48),
            ok: rgb(18, 140, 80), warn: rgb(168, 110, 16), composer: rgb(248, 249, 251),
            border: rgb(198, 202, 210), chip: rgb(226, 232, 240), header: rgb(245, 247, 250),
        }
    } else {
        Palette {
            bg: rgb(30, 31, 36), sidebar: rgb(43, 45, 49), text: rgb(242, 243, 245),
            muted: rgb(148, 155, 164), accent: rgb(88, 101, 242), user_bg: rgb(43, 82, 120),
            user_fg: rgb(255, 255, 255), bot_bg: rgb(47, 49, 54), bot_fg: rgb(242, 243, 245),
            error_bg: rgb(82, 42, 46), error_fg: rgb(255, 228, 228), error_accent: rgb(237, 66, 69),
            ok: rgb(35, 165, 89), warn: rgb(240, 178, 50), composer: rgb(56, 58, 64),
            border: rgb(78, 80, 88), chip: rgb(64, 68, 82), header: rgb(35, 36, 40),
        }
    }
}

pub(crate) fn glyphs(ascii: bool) -> Glyphs {
    if ascii {
        Glyphs {
            rounded: false, ellipsis: "...", ok: "OK", err: "ERR", ask: "ASK", draft: "NEW",
            pin: "*", unread: "*", collapse: ">", expand: "v", bar: ">", thread: "|",
        }
    } else {
        Glyphs {
            rounded: true, ellipsis: "…", ok: "✓", err: "✕", ask: "?", draft: "·",
            pin: "◆", unread: "●", collapse: "▸", expand: "▾", bar: "▌", thread: "│",
        }
    }
}

pub(crate) fn render_text(app: &mut App, width: u16, height: u16) -> Result<String, Box<dyn Error>> {
    let backend = TestBackend::new(width, height);
    let mut terminal = Terminal::new(backend)?;
    terminal.draw(|frame| draw(frame, app))?;
    Ok(buffer_plain(terminal.backend().buffer()))
}

pub(crate) fn write_dump(app: &mut App, path: &Path, width: u16, height: u16) -> Result<(), Box<dyn Error>> {
    let backend = TestBackend::new(width, height);
    let mut terminal = Terminal::new(backend)?;
    terminal.draw(|frame| draw(frame, app))?;
    let buffer = terminal.backend().buffer();
    let text = buffer_plain(buffer);
    let json = buffer_json(buffer);
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)?;
        }
    }
    let stem = path.with_extension("");
    let base = if path.extension().is_some() { stem } else { path.to_path_buf() };
    fs::write(base.with_extension("txt"), text)?;
    fs::write(base.with_extension("json"), json)?;
    Ok(())
}

pub(crate) fn draw(frame: &mut Frame, app: &mut App) {
    let area = frame.area();
    frame.render_widget(Block::default().style(Style::default().bg(app.palette.bg)), area);
    app.hits.search = Rect::default();
    app.hits.rooms.clear();
    app.hits.timeline = Rect::default();
    app.hits.composer = Rect::default();
    app.hits.bytecode.clear();
    if area.width < 8 || area.height < 6 {
        let line = Line::from(Span::styled(" ShipMB ", Style::default().fg(app.palette.header).bg(app.palette.accent).add_modifier(Modifier::BOLD)));
        frame.render_widget(Paragraph::new(line), area);
        if !app.glyphs.rounded { flatten_ascii(frame); }
        return;
    }
    let footer_h = if area.height >= 20 { 3 } else if area.height >= 12 { 2 } else { 1 };
    let outer = Layout::default().direction(Direction::Vertical)
        .constraints([Constraint::Length(1), Constraint::Min(4), Constraint::Length(footer_h)])
        .split(area);
    draw_header(frame, app, outer[0]);
    let show_sidebar = area.width >= 56;
    let main = if show_sidebar {
        let sidebar_w = (area.width as u32 * 28 / 100).clamp(24, 36) as u16;
        let body = Layout::default().direction(Direction::Horizontal)
            .constraints([Constraint::Length(sidebar_w), Constraint::Length(1), Constraint::Min(20)]).split(outer[1]);
        draw_sidebar(frame, app, body[0]);
        body[2]
    } else {
        outer[1]
    };
    draw_main(frame, app, main);
    draw_footer(frame, app, outer[2]);
    if let Some(modal) = app.modal.clone() {
        draw_modal(frame, app, &modal);
    }
    if !app.glyphs.rounded { flatten_ascii(frame); }
}

fn flatten_ascii(frame: &mut Frame) {
    let buffer = frame.buffer_mut();
    for y in 0..buffer.area.height {
        for x in 0..buffer.area.width {
            let cell = &mut buffer[(x, y)];
            let next = match cell.symbol() {
                "╭" | "╮" | "╰" | "╯" | "┌" | "┐" | "└" | "┘" | "├" | "┤" | "┬" | "┴" | "┼" => "+",
                "─" | "━" => "-",
                "│" | "┃" => "|",
                _ => continue,
            };
            cell.set_symbol(next);
        }
    }
}

fn draw_header(frame: &mut Frame, app: &App, area: Rect) {
    frame.render_widget(Block::default().style(Style::default().bg(app.palette.header)), area);
    let badge = status_label(app.room_status(), &app.glyphs);
    let title = if app.room_title.is_empty() { "New chat".to_string() } else { app.room_title.clone() };
    let line = Line::from(vec![
        Span::styled(" ShipMB ", Style::default().fg(rgb(255, 255, 255)).bg(app.palette.accent).add_modifier(Modifier::BOLD)),
        Span::styled("  ", Style::default().bg(app.palette.header)),
        Span::styled(truncate(&title, 40, app.glyphs.ellipsis), Style::default().fg(app.palette.text).bg(app.palette.header).add_modifier(Modifier::BOLD)),
        Span::styled(format!("  {badge}  "), Style::default().fg(status_color(app.room_status(), &app.palette)).bg(app.palette.header)),
        Span::styled(if app.dirty { "draft  " } else { "" }, Style::default().fg(app.palette.warn).bg(app.palette.header)),
        Span::styled(truncate(&app.status, 28, app.glyphs.ellipsis), Style::default().fg(app.palette.muted).bg(app.palette.header)),
        Span::styled(format!("  {}", app.theme_label()), Style::default().fg(app.palette.muted).bg(app.palette.header)),
    ]);
    frame.render_widget(Paragraph::new(line).style(Style::default().bg(app.palette.header)), area);
}

fn draw_sidebar(frame: &mut Frame, app: &mut App, area: Rect) {
    let border = border_type(app.glyphs.rounded);
    let focused = matches!(app.focus, Focus::Rooms | Focus::Search);
    let block = Block::default().title(" Chats ").borders(Borders::ALL).border_type(border)
        .border_style(Style::default().fg(if focused { app.palette.accent } else { app.palette.border }))
        .style(Style::default().bg(app.palette.sidebar).fg(app.palette.text));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    if inner.height == 0 || inner.width == 0 {
        return;
    }
    let mut lines = Vec::new();
    let search_style = if app.focus == Focus::Search {
        Style::default().fg(app.palette.user_fg).bg(app.palette.user_bg)
    } else {
        Style::default().fg(app.palette.muted).bg(app.palette.composer)
    };
    let query = if app.search.is_empty() && app.focus != Focus::Search {
        "Search chats".to_string()
    } else {
        format!("{}{}", app.search, if app.focus == Focus::Search { " " } else { "" })
    };
    lines.push(pad_line(format!(" {query}"), inner.width as usize, search_style));
    app.hits.search = Rect { x: inner.x, y: inner.y, width: inner.width, height: 1 };
    let cards = 3usize;
    let room_height = inner.height.saturating_sub(1) as usize;
    let visible = room_height / cards;
    if app.selected > 0 && app.room_scroll > app.selected {
        app.room_scroll = app.selected;
    }
    if app.selected >= app.room_scroll + visible.max(1) {
        app.room_scroll = app.selected + 1 - visible.max(1);
    }
    let mut row = 1u16;
    for (offset, room) in app.rooms.iter().enumerate().skip(app.room_scroll).take(visible.max(1)) {
        if row + 2 >= inner.height {
            break;
        }
        let selected = offset == app.selected;
        let base = if selected {
            Style::default().fg(app.palette.user_fg).bg(app.palette.user_bg)
        } else {
            Style::default().fg(app.palette.text).bg(app.palette.sidebar)
        };
        let muted = if selected { base } else { Style::default().fg(app.palette.muted).bg(app.palette.sidebar) };
        let mark = if room.unread { format!("{} ", app.glyphs.unread) } else { "  ".to_string() };
        let pin = if room.pinned { format!("{} ", app.glyphs.pin) } else { String::new() };
        let title = format!("{mark}{pin}{}", room.title);
        lines.push(pad_line(truncate(&title, inner.width as usize, app.glyphs.ellipsis), inner.width as usize, base.add_modifier(Modifier::BOLD)));
        let preview = if room.preview.is_empty() { "No messages yet".to_string() } else { room.preview.clone() };
        lines.push(pad_line(format!("  {}", truncate(&preview, inner.width.saturating_sub(2) as usize, app.glyphs.ellipsis)), inner.width as usize, muted));
        let when = crate::activity_label(&room.last_activity, &app.now);
        let badge = status_label(&room.status, &app.glyphs);
        let meta = format!("  {when}  {badge}");
        lines.push(pad_line(truncate(&meta, inner.width as usize, ""), inner.width as usize, muted.fg(status_color(&room.status, &app.palette))));
        app.hits.rooms.push((Rect { x: inner.x, y: inner.y + row, width: inner.width, height: 3 }, offset));
        row += 3;
    }
    if app.rooms.is_empty() {
        lines.push(pad_line("  No chats yet".to_string(), inner.width as usize, Style::default().fg(app.palette.muted).bg(app.palette.sidebar)));
        lines.push(pad_line("  Ctrl+N starts one".to_string(), inner.width as usize, Style::default().fg(app.palette.muted).bg(app.palette.sidebar)));
    }
    frame.render_widget(Paragraph::new(to_lines(&lines)).style(Style::default().bg(app.palette.sidebar)), inner);
}

fn draw_main(frame: &mut Frame, app: &mut App, area: Rect) {
    let composer_h = if area.height >= 22 { 6 } else { 4 };
    let split = Layout::default().direction(Direction::Vertical)
        .constraints([Constraint::Min(3), Constraint::Length(composer_h)]).split(area);
    draw_timeline(frame, app, split[0]);
    draw_composer(frame, app, split[1]);
}

fn draw_timeline(frame: &mut Frame, app: &mut App, area: Rect) {
    let border = border_type(app.glyphs.rounded);
    let focused = app.focus == Focus::Timeline;
    let block = Block::default().title(" Conversation ").borders(Borders::ALL).border_type(border)
        .border_style(Style::default().fg(if focused { app.palette.accent } else { app.palette.border }))
        .style(Style::default().bg(app.palette.bg).fg(app.palette.text));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    app.hits.timeline = inner;
    if inner.width < 4 || inner.height == 0 {
        return;
    }
    let built = build_timeline(app, inner.width as usize);
    let height = inner.height as usize;
    let max_scroll = built.len().saturating_sub(height);
    if app.stick_to_bottom {
        app.timeline_scroll = max_scroll;
    } else if app.timeline_scroll > max_scroll {
        app.timeline_scroll = max_scroll;
    }
    if app.timeline_scroll == max_scroll {
        app.stick_to_bottom = true;
    }
    let mut rendered = Vec::new();
    for (index, line) in built.iter().skip(app.timeline_scroll).take(height).enumerate() {
        if let Some(id) = &line.bytecode_for {
            app.hits.bytecode.push((inner.y + index as u16, id.clone()));
        }
        rendered.push(Line::from(line.spans.iter().map(|(text, style)| Span::styled(text.clone(), *style)).collect::<Vec<_>>()));
    }
    frame.render_widget(Paragraph::new(rendered), inner);
}

fn draw_composer(frame: &mut Frame, app: &mut App, area: Rect) {
    let border = border_type(app.glyphs.rounded);
    let title = if app.awaiting.is_some() { " Reply to ShipMB " } else { " Message " };
    let focused = app.focus == Focus::Composer;
    let block = Block::default().title(title).borders(Borders::ALL).border_type(border)
        .border_style(Style::default().fg(if focused { app.palette.accent } else { app.palette.border }))
        .style(Style::default().bg(app.palette.composer).fg(app.palette.text));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    app.hits.composer = inner;
    if inner.height == 0 || inner.width == 0 {
        return;
    }
    let style = Style::default().fg(app.palette.text).bg(app.palette.composer);
    let mut rendered = Vec::new();
    if !app.images.is_empty() {
        let chips = app.images.iter().map(|image| format!("[{}]", image.caption)).collect::<Vec<_>>().join(" ");
        rendered.push(Line::from(Span::styled(truncate(&chips, inner.width as usize, app.glyphs.ellipsis), Style::default().fg(app.palette.accent).bg(app.palette.chip))));
    }
    let text_rows = inner.height.saturating_sub(rendered.len() as u16) as usize;
    if app.lines.iter().all(|line| line.is_empty()) && app.focus == Focus::Composer {
        let hint = if app.awaiting.is_some() { "Write the clarified program and press Enter" } else { "Write a program, then Enter" };
        let mut spans = vec![Span::styled(hint, Style::default().fg(app.palette.muted).bg(app.palette.composer))];
        spans.push(Span::styled(" ", Style::default().fg(app.palette.bg).bg(app.palette.accent)));
        rendered.push(Line::from(spans));
    } else {
        let width = inner.width as usize;
        if app.cursor_row < app.composer_scroll {
            app.composer_scroll = app.cursor_row;
        }
        if text_rows > 0 && app.cursor_row >= app.composer_scroll + text_rows {
            app.composer_scroll = app.cursor_row + 1 - text_rows;
        }
        for (index, line) in app.lines.iter().enumerate().skip(app.composer_scroll).take(text_rows) {
            rendered.push(composer_line(line, index == app.cursor_row, app.cursor_col, width, style, app.palette.accent, app.palette.bg, focused));
        }
    }
    frame.render_widget(Paragraph::new(rendered), inner);
}

fn draw_footer(frame: &mut Frame, app: &App, area: Rect) {
    let hint = " Enter run  Ctrl+Enter compile  Alt+C compile  Alt+Enter/Ctrl+J newline  Up edit last  Ctrl+I image  Ctrl+N new  Ctrl+O search  Ctrl+S save  Ctrl+B backup  Ctrl+D delete  Ctrl+R unplaced  Ctrl+P pin  Ctrl+E detail  Alt+T theme  F5 run  Ctrl+Q quit";
    let style = Style::default().fg(app.palette.muted).bg(app.palette.header);
    let lines = wrap_words(&hint, area.width as usize).into_iter().take(area.height as usize)
        .map(|line| Line::from(Span::styled(line, style))).collect::<Vec<_>>();
    frame.render_widget(Paragraph::new(lines).style(style), area);
}

fn draw_modal(frame: &mut Frame, app: &App, modal: &crate::Modal) {
    let area = centered(frame.area(), 72, 8);
    frame.render_widget(Clear, area);
    let (title, prompt) = match &modal.kind {
        InputKind::ImagePath => ("Attach image", "PNG, JPEG, GIF, WebP, or BMP path. Enter attaches it, Esc cancels.".to_string()),
        InputKind::UnplacedImages { ids, .. } => ("Remove unplaced images", format!("No marker for {}. Type REMOVE to detach them.", ids.join(", "))),
        InputKind::BackupPath => ("Back up chats", "Destination path for a SQLite backup.".to_string()),
        InputKind::Delete => ("Delete chat", "Type DELETE to remove this chat and its messages.".to_string()),
    };
    let content = vec![
        Line::from(Span::styled(prompt, Style::default().fg(app.palette.text))),
        Line::from(""),
        Line::from(Span::styled(format!("> {}", modal.value), Style::default().fg(app.palette.warn))),
    ];
    let block = Block::default().title(format!(" {title} ")).borders(Borders::ALL)
        .border_type(border_type(app.glyphs.rounded))
        .border_style(Style::default().fg(app.palette.accent))
        .style(Style::default().bg(app.palette.sidebar).fg(app.palette.text));
    frame.render_widget(Paragraph::new(content).wrap(Wrap { trim: true }).block(block), area);
}

fn build_timeline(app: &App, width: usize) -> Vec<BuiltLine> {
    let mut lines = Vec::new();
    if app.messages.is_empty() && !app.busy {
        lines.push(plain("Send a program with Enter. ShipMB answers here.", width, Style::default().fg(app.palette.muted).bg(app.palette.bg)));
        return lines;
    }
    let mut previous_day = String::new();
    let children = child_index(&app.messages);
    let roots: Vec<usize> = app.messages.iter().enumerate().filter(|(_, message)| message.parent_id.is_empty()).map(|(index, _)| index).collect();
    for index in roots {
        let message = app.messages[index].clone();
        let day = crate::day_label(&message.created_at, &app.now);
        if day != previous_day {
            lines.push(centered_line(&day, width, Style::default().fg(app.palette.muted).bg(app.palette.bg)));
            previous_day = day;
        }
        push_message(app, &mut lines, &message, width, 0, app.palette.bg);
        if let Some(kids) = children.get(&message.id) {
            for child in kids {
                push_message(app, &mut lines, child, width, 2, app.palette.bg);
                if let Some(nested) = children.get(&child.id) {
                    for answer in nested {
                        push_message(app, &mut lines, answer, width, 4, app.palette.bg);
                    }
                }
            }
        }
        lines.push(plain("", width, Style::default().bg(app.palette.bg)));
    }
    if app.busy {
        lines.push(plain("ShipMB is typing…", width, Style::default().fg(app.palette.accent).bg(app.palette.bg)));
    }
    lines
}

fn push_message(app: &App, lines: &mut Vec<BuiltLine>, message: &ChatMessage, width: usize, indent: usize, canvas: Color) {
    let user = message.role == "user";
    let tone = bubble_tone(message);
    let (fg, bg, accent) = match tone {
        Tone::User => (app.palette.user_fg, app.palette.user_bg, app.palette.accent),
        Tone::Error => (app.palette.error_fg, app.palette.error_bg, app.palette.error_accent),
        Tone::Ask => (app.palette.text, app.palette.bot_bg, app.palette.warn),
        Tone::Bot => (app.palette.bot_fg, app.palette.bot_bg, app.palette.accent),
    };
    let gutter = if indent == 0 { 0 } else { indent.min(width / 5) };
    let max_bubble = width.saturating_sub(gutter).saturating_sub(2).clamp(16, 46);
    let mut body = message.body.clone();
    if body.trim().is_empty() { body = "(empty)".to_string(); }
    let wrapped = wrap_words(&body, max_bubble.saturating_sub(2));
    let content = wrapped.iter().map(|row| row.chars().count()).max().unwrap_or(1);
    let bubble_width = content.saturating_add(2).clamp(8, max_bubble);
    let name = if user {
        "You".to_string()
    } else if message.kind == "journal" {
        "History".to_string()
    } else {
        "ShipMB".to_string()
    };
    let name_line = format!("{}{name}", if gutter > 0 { app.glyphs.thread.to_string() + " " } else { String::new() });
    lines.push(align_text(&name_line, width, user, Style::default().fg(accent).bg(canvas).add_modifier(Modifier::BOLD), gutter, canvas));
    for row in wrapped {
        let text = format!("{} {row}", app.glyphs.bar);
        lines.push(bubble_row(&text, width, bubble_width, user, gutter, Style::default().fg(fg).bg(bg), canvas));
    }
    if user {
        for chip in image_chips(message) {
            let text = format!("[{chip}]");
            lines.push(bubble_row(&text, width, bubble_width, true, gutter, Style::default().fg(app.palette.accent).bg(app.palette.chip), canvas));
        }
    }
    if !user {
        if let Some(detail) = bytecode_text(message) {
            let open = app.expanded.contains(&message.id);
            let marker = if open { app.glyphs.expand } else { app.glyphs.collapse };
            let label = format!("{marker} bytecode");
            let mut row = bubble_row(&label, width, bubble_width, false, gutter, Style::default().fg(app.palette.muted).bg(bg), canvas);
            row.bytecode_for = Some(message.id.clone());
            lines.push(row);
            if open {
                for piece in wrap_words(&detail, bubble_width.saturating_sub(2)).into_iter().take(12) {
                    lines.push(bubble_row(&piece, width, bubble_width, false, gutter, Style::default().fg(app.palette.muted).bg(bg), canvas));
                }
            }
        }
    }
    let stamp = crate::clock_label(&message.created_at);
    if !stamp.is_empty() {
        lines.push(align_text(&stamp, width, user, Style::default().fg(app.palette.muted).bg(canvas), gutter, canvas));
    }
}

fn image_chips(message: &ChatMessage) -> Vec<String> {
    let mut chips = Vec::new();
    if let Some(images) = message.detail.get("images").and_then(|value| value.as_array()) {
        for image in images {
            let caption = image.get("caption").and_then(|value| value.as_str()).unwrap_or("image");
            chips.push(caption.to_string());
        }
    }
    chips
}

fn bytecode_text(message: &ChatMessage) -> Option<String> {
    let text = message.detail.get("bytecode").and_then(|value| value.as_str()).unwrap_or("");
    if text.trim().is_empty() { None } else { Some(text.to_string()) }
}

#[derive(Clone, Copy, PartialEq)]
enum Tone { User, Bot, Error, Ask }

fn bubble_tone(message: &ChatMessage) -> Tone {
    if message.role == "user" {
        return Tone::User;
    }
    let status = message.detail.get("status").and_then(|value| value.as_str()).unwrap_or("");
    if message.kind == "clarification" || status == "needs_clarification" {
        return Tone::Ask;
    }
    if status == "compiled" || message.kind == "journal" || status.is_empty() {
        return Tone::Bot;
    }
    Tone::Error
}

fn child_index(messages: &[ChatMessage]) -> std::collections::HashMap<String, Vec<ChatMessage>> {
    let mut map: std::collections::HashMap<String, Vec<ChatMessage>> = std::collections::HashMap::new();
    for message in messages {
        if !message.parent_id.is_empty() {
            map.entry(message.parent_id.clone()).or_default().push(message.clone());
        }
    }
    map
}

fn composer_line(line: &[char], current: bool, cursor: usize, width: usize, style: Style, cursor_bg: Color, cursor_fg: Color, focused: bool) -> Line<'static> {
    let mut spans = Vec::new();
    let shown = line.iter().take(width).copied().collect::<String>();
    if !current || !focused {
        spans.push(Span::styled(format!("{shown:<width$}"), style));
        return Line::from(spans);
    }
    let chars: Vec<char> = line.iter().copied().collect();
    let mut column = 0usize;
    while column < width {
        if column == cursor {
            let symbol = chars.get(column).copied().filter(|ch| *ch != '\0').map(|ch| ch.to_string()).unwrap_or_else(|| " ".to_string());
            spans.push(Span::styled(symbol, Style::default().fg(cursor_fg).bg(cursor_bg).add_modifier(Modifier::BOLD)));
            column += 1;
            continue;
        }
        if column >= chars.len() {
            spans.push(Span::styled(" ".repeat(width - column), style));
            break;
        }
        spans.push(Span::styled(chars[column].to_string(), style));
        column += 1;
    }
    Line::from(spans)
}

fn bubble_row(text: &str, width: usize, bubble_width: usize, right: bool, gutter: usize, style: Style, canvas: Color) -> BuiltLine {
    let padded = format!("{text:<bubble_width$}");
    let trimmed = truncate(&padded, bubble_width, "");
    let gap = width.saturating_sub(gutter).saturating_sub(trimmed.chars().count());
    let mut spans = Vec::new();
    let canvas_style = Style::default().bg(canvas);
    if gutter > 0 {
        spans.push((" ".repeat(gutter), canvas_style));
    }
    if right {
        spans.push((" ".repeat(gap), canvas_style));
        spans.push((trimmed, style));
    } else {
        spans.push((trimmed, style));
        spans.push((" ".repeat(gap), canvas_style));
    }
    BuiltLine { spans, bytecode_for: None }
}

fn align_text(text: &str, width: usize, right: bool, style: Style, gutter: usize, canvas: Color) -> BuiltLine {
    let shown = truncate(text, width.saturating_sub(gutter), "");
    let gap = width.saturating_sub(gutter).saturating_sub(shown.chars().count());
    let canvas_style = Style::default().bg(canvas);
    let mut spans = Vec::new();
    if gutter > 0 {
        spans.push((" ".repeat(gutter), canvas_style));
    }
    if right {
        spans.push((" ".repeat(gap), canvas_style));
        spans.push((shown, style));
    } else {
        spans.push((shown, style));
        spans.push((" ".repeat(gap), canvas_style));
    }
    BuiltLine { spans, bytecode_for: None }
}

fn plain(text: &str, width: usize, style: Style) -> BuiltLine {
    BuiltLine { spans: vec![(format!("{text:<width$}"), style)], bytecode_for: None }
}

fn centered_line(text: &str, width: usize, style: Style) -> BuiltLine {
    let shown = truncate(text, width, "");
    let pad = width.saturating_sub(shown.chars().count()) / 2;
    let bg = Style::default().bg(style.bg.unwrap_or(Color::Reset));
    BuiltLine {
        spans: vec![(" ".repeat(pad), bg), (shown.clone(), style), (" ".repeat(width.saturating_sub(pad).saturating_sub(shown.chars().count())), bg)],
        bytecode_for: None,
    }
}

fn pad_line(text: String, width: usize, style: Style) -> BuiltLine {
    let shown = truncate(&text, width, "");
    let pad = width.saturating_sub(shown.chars().count());
    BuiltLine { spans: vec![(format!("{shown}{}", " ".repeat(pad)), style)], bytecode_for: None }
}

fn to_lines(lines: &[BuiltLine]) -> Vec<Line<'static>> {
    lines.iter().map(|line| {
        Line::from(line.spans.iter().map(|(text, style)| Span::styled(text.clone(), *style)).collect::<Vec<_>>())
    }).collect()
}

fn status_label(status: &str, glyphs: &Glyphs) -> String {
    match status {
        "ok" => glyphs.ok.to_string(),
        "err" => glyphs.err.to_string(),
        "ask" => glyphs.ask.to_string(),
        _ => glyphs.draft.to_string(),
    }
}

fn status_color(status: &str, palette: &Palette) -> Color {
    match status {
        "ok" => palette.ok,
        "err" => palette.error_accent,
        "ask" => palette.warn,
        _ => palette.muted,
    }
}

fn border_type(rounded: bool) -> BorderType {
    if rounded { BorderType::Rounded } else { BorderType::Plain }
}

fn rgb(r: u8, g: u8, b: u8) -> Color { Color::Rgb(r, g, b) }

pub(crate) fn truncate(text: &str, max: usize, ellipsis: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    if max == 0 { return String::new(); }
    if chars.len() <= max { return text.to_string(); }
    let extra = ellipsis.chars().count();
    if max <= extra { return chars.into_iter().take(max).collect(); }
    format!("{}{ellipsis}", chars.into_iter().take(max - extra).collect::<String>())
}

pub(crate) fn wrap_words(text: &str, width: usize) -> Vec<String> {
    let width = width.max(8);
    let mut lines = Vec::new();
    for paragraph in text.split('\n') {
        if paragraph.is_empty() {
            lines.push(String::new());
            continue;
        }
        let mut current = String::new();
        for word in paragraph.split(' ') {
            let word_len = word.chars().count();
            let current_len = current.chars().count();
            if current.is_empty() {
                if word_len <= width {
                    current = word.to_string();
                } else {
                    let chars: Vec<char> = word.chars().collect();
                    let mut start = 0;
                    while start < chars.len() {
                        let end = (start + width).min(chars.len());
                        lines.push(chars[start..end].iter().collect());
                        start = end;
                    }
                }
            } else if current_len + 1 + word_len <= width {
                current.push(' ');
                current.push_str(word);
            } else {
                lines.push(std::mem::take(&mut current));
                current = word.to_string();
            }
        }
        if !current.is_empty() {
            lines.push(current);
        }
    }
    if lines.is_empty() { lines.push(String::new()); }
    lines
}

fn centered(area: Rect, width: u16, height: u16) -> Rect {
    Rect {
        x: area.x + area.width.saturating_sub(width.min(area.width)) / 2,
        y: area.y + area.height.saturating_sub(height.min(area.height)) / 2,
        width: width.min(area.width),
        height: height.min(area.height),
    }
}

fn buffer_plain(buffer: &Buffer) -> String {
    let mut rows = Vec::new();
    for y in 0..buffer.area.height {
        let mut row = String::new();
        let mut skip = 0u16;
        for x in 0..buffer.area.width {
            let cell = &buffer[(x, y)];
            if skip > 0 {
                skip -= 1;
                continue;
            }
            row.push_str(cell.symbol());
            skip = cell.cell_width().saturating_sub(1);
        }
        rows.push(row.trim_end().to_string());
    }
    rows.join("\n")
}

fn buffer_json(buffer: &Buffer) -> String {
    let mut rows = Vec::new();
    for y in 0..buffer.area.height {
        let mut row = Vec::new();
        for x in 0..buffer.area.width {
            let cell = &buffer[(x, y)];
            row.push(serde_json::json!({
                "c": cell.symbol(),
                "fg": color_rgb(cell.fg),
                "bg": color_rgb(cell.bg),
            }));
        }
        rows.push(serde_json::Value::Array(row));
    }
    serde_json::to_string(&serde_json::json!({
        "width": buffer.area.width,
        "height": buffer.area.height,
        "cells": rows,
    })).unwrap_or_else(|_| "{}".to_string())
}

fn color_rgb(color: Color) -> [u8; 3] {
    match color {
        Color::Rgb(r, g, b) => [r, g, b],
        Color::Black => [0, 0, 0],
        Color::Red => [205, 49, 49],
        Color::Green => [13, 188, 121],
        Color::Yellow => [229, 229, 16],
        Color::Blue => [36, 114, 200],
        Color::Magenta => [188, 63, 188],
        Color::Cyan => [17, 168, 205],
        Color::Gray => [170, 170, 170],
        Color::DarkGray => [102, 102, 102],
        Color::LightRed => [255, 85, 85],
        Color::LightGreen => [85, 255, 85],
        Color::LightYellow => [255, 255, 85],
        Color::LightBlue => [85, 85, 255],
        Color::LightMagenta => [255, 85, 255],
        Color::LightCyan => [85, 255, 255],
        Color::White => [255, 255, 255],
        Color::Indexed(index) => [index, index, index],
        Color::Reset => [30, 31, 36],
    }
}

