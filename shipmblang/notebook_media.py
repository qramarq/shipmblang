"""Optional media panel for a note; keeps writing and storage independent."""
import hashlib
from pathlib import Path
import shutil
import zipfile

from .media_jobs import MediaJobs, new_request_id, TERMINAL
from .media_workspace import tool_status, conversion_starter, composition_starter, TITLE_STARTER
from .media_preview import Preview


class MediaPanel:
    def __init__(self, app):
        import tkinter as tk
        from tkinter import ttk
        self.app = app
        self.preview = None
        self.job = None
        self.revision = None
        self.poll_id = None
        self.rendered_outputs = None
        if not app.entry_id:
            app.dirty = True
        if not app.save(notify=True):
            return
        if not hasattr(app.owner, 'media_jobs'):
            app.owner.media_jobs = MediaJobs(app.store.path.parent / 'media')
        self.jobs = app.owner.media_jobs
        self.project = app.entry_id
        self.workspace = self.jobs.workspace(self.project)
        self.window = tk.Toplevel(app.root)
        self.window.title('Media · ShipMB Notes')
        self.window.geometry('660x720')
        self.window.minsize(620, 620)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.frame = ttk.Frame(self.window, padding=18)
        self.frame.pack(fill='both', expand=True)
        ttk.Label(self.frame, text='Make something with your media', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        self.mode = tk.StringVar(value=self.workspace.mode())
        modes = ttk.Frame(self.frame); modes.pack(fill='x', pady=10)
        for label, value in [('Program', 'program'), ('Video composition', 'composition')]:
            ttk.Radiobutton(modes, text=label, value=value, variable=self.mode, command=lambda: self.workspace.mode(self.mode.get())).pack(side='left', padx=4)
        actions = ttk.Frame(self.frame); actions.pack(fill='x')
        for label, command in [('Add media', self.import_file), ('Media setup', self.setup), ('Export note + media', self.backup)]:
            ttk.Button(actions, text=label, command=command).pack(side='left', padx=(0, 6))
        self.assets = tk.Listbox(self.frame, height=4, exportselection=False, font=('Segoe UI', 11))
        self.assets.pack(fill='x', pady=10)
        starter = ttk.Frame(self.frame); starter.pack(fill='x')
        for label, command in [('Conversion starter', self.conversion), ('Composition starter', self.composition), ('Title-card starter', self.title), ('Play selected', self.play_asset)]:
            ttk.Button(starter, text=label, command=command).pack(side='left', padx=(0, 6))
        self.surface = tk.Frame(self.frame, background='#18231d', height=200)
        self.surface.pack(fill='both', expand=True, pady=10)
        self.surface.pack_propagate(False)
        controls = ttk.Frame(self.frame); controls.pack(fill='x')
        for label, op in [('Play', 'resume'), ('Pause', 'pause'), ('Stop playback', 'stop')]:
            ttk.Button(controls, text=label, command=lambda operation=op: self.player_command(operation)).pack(side='left', padx=3)
        self.position = tk.DoubleVar(value=0)
        self.seek = ttk.Scale(self.frame, from_=0, to=1000, variable=self.position)
        self.seek.pack(fill='x')
        self.seek.bind('<ButtonRelease-1>', lambda _: self.player_command('seek', [int(self.position.get())]))
        volume = ttk.Frame(self.frame); volume.pack(fill='x')
        ttk.Label(volume, text='Volume').pack(side='left')
        self.volume = tk.DoubleVar(value=80)
        slider = ttk.Scale(volume, from_=0, to=100, variable=self.volume)
        slider.pack(side='left', fill='x', expand=True)
        slider.bind('<ButtonRelease-1>', lambda _: self.player_command('volume', [int(self.volume.get())]))
        self.message = tk.StringVar(value='Choose a file or a title-card starter. Nothing runs automatically.')
        ttk.Label(self.frame, textvariable=self.message, wraplength=590).pack(fill='x', pady=8)
        self.job_message = tk.StringVar()
        ttk.Label(self.frame, textvariable=self.job_message, wraplength=590).pack(fill='x')
        self.results = tk.Listbox(self.frame, height=3, exportselection=False)
        self.results.pack(fill='x')
        buttons = ttk.Frame(self.frame); buttons.pack(fill='x', pady=10)
        for label, command in [('Check', lambda: self.run(True)), ('Run', self.run), ('Stop job', self.stop), ('Play result', self.play_result), ('Save as', self.export)]:
            ttk.Button(buttons, text=label, command=command).pack(side='left', padx=3)
        self.refresh_assets()
        self.job = self.jobs.latest(self.project)
        self.poll()

    def guard(self, action):
        try:
            return action()
        except Exception as error:
            self.message.set(str(error))

    def refresh_assets(self):
        self.items = self.workspace.read()['assets']
        self.assets.delete(0, 'end')
        for asset in self.items:
            self.assets.insert('end', f'{asset["name"]} · {asset["size"] // 1024} KiB')

    def selected(self):
        selection = self.assets.curselection()
        if not selection:
            raise ValueError('Select an imported asset first.')
        return self.items[selection[0]]

    def import_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.window, title='Import media into this note')
        if path:
            def add():
                self.workspace.import_file(path)
                self.refresh_assets()
                self.assets.selection_set(len(self.items)-1)
                self.message.set('Imported a copy. Choose a conversion starter or Play selected.')
            self.guard(add)

    def insert(self, source, mode):
        # Insert into a NEW note so the current user's writing is never replaced.
        note = self.app.start_note({'source': source})
        note.save()
        workspace = self.jobs.workspace(note.entry_id)
        for asset in self.items:
            destination = workspace.root / asset['path']
            shutil.copyfile(self.workspace.input_path(asset['path']), destination)
        from .media_workspace import write_json
        write_json(workspace.manifest, {'mode': mode, 'assets': list(self.items)})
        note.open_media()

    def conversion(self):
        self.guard(lambda: self.insert(conversion_starter(self.selected()), 'program'))

    def composition(self):
        self.guard(lambda: self.insert(composition_starter(self.selected()), "composition"))

    def title(self):
        self.guard(lambda: self.insert(TITLE_STARTER, 'composition'))

    def run(self, check=False):
        def submit():
            if not self.app.save(notify=True):
                return
            self.revision = self.app.text()
            self.job = self.jobs.submit(self.project, self.revision, self.mode.get(), new_request_id(), check=check)
            self.message.set('')
        self.guard(submit)

    def stop(self):
        if self.job:
            self.guard(lambda: self.jobs.cancel(self.project, self.job['id']))

    def poll(self):
        if self.job:
            self.job = self.jobs.get(self.project, self.job['id'])
            stale = hashlib.sha256(self.app.text().encode()).hexdigest() != self.job['source_revision']
            message = ('Earlier text · ' if stale else '') + self.job['message']
            if self.job.get('stdout'):
                message += '\n' + self.job['stdout'][:1000]
            for diagnostic in self.job.get('diagnostics', []):
                message += '\n' + diagnostic.get('message', '')
            self.job_message.set(message)
            if self.rendered_outputs != self.job["outputs"]:
                self.rendered_outputs = self.job["outputs"]
                self.results.delete(0, "end")
                for output in self.job["outputs"]:
                    self.results.insert("end", f'{output["name"]} · {output.get("duration", "?")} s')
        if self.preview:
            state = self.preview.state()
            self.seek.configure(to=max(1, state['duration']))
            self.position.set(state['position'])
            if state['state'] == 'error':
                self.message.set(state.get('error', 'Playback failed.'))
        self.poll_id = self.window.after(500, self.poll)

    def result_path(self):
        selected = self.results.curselection()
        if not self.job or not selected:
            raise ValueError('Select a completed result first.')
        return self.jobs.output(self.project, self.job['id'], self.job['outputs'][selected[0]]['id'])

    def play(self, path):
        if self.preview:
            self.preview.close()
        self.surface.update_idletasks()
        self.preview = Preview(path, self.surface.winfo_id(), self.jobs.root)

    def play_asset(self):
        self.guard(lambda: self.play(self.workspace.input_path(self.selected()['path'])))

    def play_result(self):
        self.guard(lambda: self.play(self.result_path()))

    def player_command(self, op, values=None):
        if self.preview:
            self.guard(lambda: self.preview.send(op, values))

    def export(self):
        from tkinter import filedialog
        def save():
            source = self.result_path()
            path = filedialog.asksaveasfilename(parent=self.window, initialfile=source.name)
            if path:
                with Path(path).open('xb') as target, source.open('rb') as stream:
                    shutil.copyfileobj(stream, target)
                self.message.set('Saved a copy of the result.')
        self.guard(save)

    def backup(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self.window, initialfile='note-and-media.zip', defaultextension='.zip')
        if path:
            def save():
                if self.project in self.jobs.active:
                    raise ValueError('Finish or stop the job before exporting the note.')
                with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('note.shipmb', self.app.text())
                    for file in self.workspace.root.rglob('*'):
                        if file.is_file() and file.resolve() != Path(path).resolve():
                            archive.write(file, 'media/' + file.relative_to(self.workspace.root).as_posix())
                self.message.set('Exported note source and media together.')
            self.guard(save)

    def setup(self):
        from tkinter import messagebox
        status = tool_status(self.jobs.root)
        messagebox.showinfo('Media setup', '\n'.join(f'{name.title()}: {"Ready" if status[name] else "Needs setup"}' for name in ('conversion', 'playback', 'rendering')) + '\n\n' + status['help'] + '\n\nMedia root: ' + str(self.jobs.root), parent=self.window)

    def close(self):
        if self.job and self.job['state'] not in TERMINAL:
            self.stop()
        if self.preview:
            self.preview.close()
        if self.poll_id:
            self.window.after_cancel(self.poll_id)
        self.app.media_panel = None
        self.window.destroy()
