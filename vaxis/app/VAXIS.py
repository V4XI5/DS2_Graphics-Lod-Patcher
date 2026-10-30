import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import game_fonts
import vaxis_core as core

TITLE = 'Death Stranding 2 - Graphics&LOD Patcher'

BG = '#050505'
PANEL = '#101010'
PANEL_HI = '#1a130c'
LINE = '#2a2a2a'
TEXT = '#f2f2f2'
MUTED = '#8c8c8c'
ACCENT = '#ff8a1f'
ACCENT_HOVER = '#ffa54f'
ACCENT_OFF = '#3a240f'
ACCENT_OFF_TEXT = '#8a5a2c'
INK = '#050505'
OK = ACCENT
WARN = '#ffd166'
BAD = '#ff5a4d'

FONT_ROLES = {
    'title': ('neon', 24),
    'card_title': ('neon', 19),
    'list': ('mono', 10),
    'small': ('neon', 10),
    'label': ('mono', 9),
    'button': ('mono', 11),
    'mono': ('mono', 9),
}
FALLBACK = {'neon': 'Segoe UI', 'mono': 'Consolas'}


def enable_dpi_awareness():
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


class PresetCard(tk.Frame):
    def __init__(self, master, app, index, preset):
        super().__init__(master, bg=PANEL, highlightthickness=2, highlightbackground=LINE, cursor='hand2')
        self.app, self.preset = app, preset
        self.selected = self.hover = False
        px = app.px
        self.wrapped = []
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill='x', padx=px(16), pady=(px(14), 0))
        self.number = tk.Label(head, text=f'0{index + 1}', font=app.fonts['label'], fg=MUTED, bg=PANEL)
        self.number.pack(side='left')
        tk.Label(head, text=preset['tag'], font=app.fonts['label'], fg=ACCENT, bg=PANEL).pack(side='right')
        tk.Label(self, text=preset['name'].upper(), font=app.fonts['card_title'], fg=TEXT, bg=PANEL,
                 anchor='w').pack(fill='x', padx=px(16), pady=(px(4), 0))
        self.rule = tk.Frame(self, bg=LINE, height=1)
        self.rule.pack(fill='x', padx=px(16), pady=(px(6), px(10)))
        if preset['intro']:
            intro = tk.Label(self, text=preset['intro'], font=app.fonts['list'], fg=MUTED, bg=PANEL, anchor='w',
                             justify='left', bd=0, pady=0)
            intro.pack(fill='x', padx=px(16), pady=(0, px(8)))
            self.wrapped.append((intro, 0))
        for text in preset['bullets']:
            row = tk.Frame(self, bg=PANEL)
            row.pack(fill='x', padx=px(16), pady=(0, px(9)))
            mark = tk.Frame(row, bg=ACCENT, width=px(5), height=px(5))
            mark.keep_bg = True
            mark.pack(side='left', anchor='n', pady=(px(6), 0), padx=(0, px(9)))
            label = tk.Label(row, text=text, font=app.fonts['list'], fg=TEXT, bg=PANEL, anchor='w',
                             justify='left', bd=0, pady=0)
            label.pack(side='left', fill='x')
            self.wrapped.append((label, px(14)))
        tk.Frame(self, bg=PANEL).pack(fill='both', expand=True)
        badge = tk.Frame(self, bg=PANEL)
        badge.pack(fill='x', padx=px(16), pady=(px(6), px(14)))
        self.badge_mark = tk.Frame(badge, bg=PANEL, width=px(7), height=px(7))
        self.badge_mark.pack(side='left', padx=(0, px(8)))
        self.badge = tk.Label(badge, text='', font=app.fonts['label'], fg=OK, bg=PANEL, anchor='w')
        self.badge.pack(side='left')
        self.bind('<Configure>', self.rewrap)
        for w in self.walk():
            w.bind('<Button-1>', lambda e: app.select(self.preset['id']))
            w.bind('<Enter>', lambda e: self.set_hover(True))
            w.bind('<Leave>', lambda e: self.set_hover(False))

    def rewrap(self, event):
        inner = event.width - 2 * int(self['highlightthickness']) - self.app.px(32)
        for label, indent in self.wrapped:
            label.config(wraplength=max(inner - indent, 40))

    def walk(self):
        stack = [self]
        while stack:
            w = stack.pop()
            yield w
            stack.extend(w.winfo_children())

    def set_hover(self, on):
        self.hover = on
        self.paint()

    def set_selected(self, on):
        self.selected = on
        self.paint()

    def set_installed(self, on):
        self.installed = on
        self.badge.config(text='INSTALLED' if on else '')
        self.paint()

    def paint(self):
        bg = PANEL_HI if self.selected or (self.hover and self.app.enabled) else PANEL
        self.config(bg=bg, highlightbackground=ACCENT if self.selected else LINE)
        for w in self.walk():
            if w is not self and not getattr(w, 'keep_bg', False):
                w.config(bg=bg)
        self.rule.config(bg=ACCENT if self.selected else LINE)
        self.badge_mark.config(bg=OK if getattr(self, 'installed', False) else bg)
        self.number.config(fg=ACCENT if self.selected else MUTED)


class App:
    def __init__(self, root, selftest=None):
        self.root = root
        self.selftest = selftest
        self.events = queue.Queue()
        self.worker = None
        self.enabled = True
        self.game = None
        self.code, self.current = 'none', None
        self.choice = 'ultra'

        scale = root.winfo_fpixels('1i') / 96.0
        self.px = lambda v: int(round(v * scale))
        game = core.find_game()
        self.font_families = game_fonts.load(game)
        self.fonts = {role: tkfont.Font(root, family=FALLBACK[kind], size=size)
                      for role, (kind, size) in FONT_ROLES.items()}
        self.apply_fonts()

        root.title(f'{TITLE}  v{core.VERSION}  |  made by VAXIS')
        root.configure(bg=BG)
        root.minsize(self.px(940), self.px(740))
        try:
            root.iconbitmap(core.resource_path('vaxis.ico'))
        except tk.TclError:
            pass
        root.protocol('WM_DELETE_WINDOW', self.close)

        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Vaxis.Horizontal.TProgressbar', troughcolor=PANEL, background=ACCENT,
                        bordercolor=LINE, lightcolor=ACCENT, darkcolor=ACCENT, thickness=self.px(6))

        self.build()
        self.dark_title_bar()
        self.log('Ready. Pick a preset and click Install. Close the game first.')
        self.set_game(game)
        self.root.after(50, self.pump)
        if selftest:
            self.root.attributes('-topmost', True)
            self.root.after(1500, self.run_selftest)

    def apply_fonts(self):
        for role, (kind, size) in FONT_ROLES.items():
            self.fonts[role].configure(family=self.font_families.get(kind, FALLBACK[kind]))

    def build(self):
        pad = self.px(26)
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill='both', expand=True, padx=pad, pady=(self.px(20), self.px(14)))

        head = tk.Frame(outer, bg=BG)
        head.pack(fill='x')
        tk.Label(head, text=TITLE, font=self.fonts['title'], fg=ACCENT, bg=BG).pack(side='left')
        tk.Label(head, text=f'v{core.VERSION}', font=self.fonts['label'], fg=MUTED, bg=BG).pack(
            side='right', anchor='s', pady=(0, self.px(8)))
        tk.Frame(outer, bg=ACCENT, height=self.px(2)).pack(fill='x', pady=(self.px(6), self.px(18)))

        self.section(outer, 'GAME FOLDER')
        row = tk.Frame(outer, bg=BG)
        row.pack(fill='x')
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(row, textvariable=self.path_var, font=self.fonts['mono'], bg=PANEL, fg=TEXT,
                                   readonlybackground=PANEL, relief='flat', state='readonly',
                                   highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE)
        self.path_entry.pack(side='left', fill='x', expand=True, ipady=self.px(8), ipadx=self.px(6))
        self.browse_btn = self.button(row, 'BROWSE', self.browse, primary=False)
        self.browse_btn.pack(side='left', padx=(self.px(10), 0))
        status = tk.Frame(outer, bg=BG)
        status.pack(fill='x', pady=(self.px(10), self.px(18)))
        self.status_mark = tk.Frame(status, bg=MUTED, width=self.px(7), height=self.px(7))
        self.status_mark.pack(side='left', padx=(0, self.px(9)))
        self.status_line = tk.Label(status, text='', font=self.fonts['list'], fg=MUTED, bg=BG, anchor='w')
        self.status_line.pack(side='left', fill='x')

        self.section(outer, 'CHOOSE A PRESET')
        cards = tk.Frame(outer, bg=BG)
        cards.pack(fill='both', expand=True)
        self.cards = {}
        for i, p in enumerate(core.PRESETS):
            card = PresetCard(cards, self, i, p)
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else self.px(12), 0))
            cards.columnconfigure(i, weight=1, uniform='card')
            self.cards[p['id']] = card
        cards.rowconfigure(0, weight=1)

        actions = tk.Frame(outer, bg=BG)
        actions.pack(fill='x', pady=(self.px(18), 0))
        self.install_btn = self.button(actions, 'INSTALL', self.install, primary=True)
        self.install_btn.pack(side='left')
        self.uninstall_btn = self.button(actions, 'UNINSTALL', self.uninstall, primary=False)
        self.uninstall_btn.pack(side='left', padx=(self.px(10), 0))
        self.step_label = tk.Label(actions, text='', font=self.fonts['small'], fg=MUTED, bg=BG, anchor='e')
        self.step_label.pack(side='right')

        self.progress = ttk.Progressbar(outer, style='Vaxis.Horizontal.TProgressbar', maximum=1000)
        self.progress.pack(fill='x', pady=(self.px(12), self.px(10)))

        logbox = tk.Frame(outer, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        logbox.pack(fill='x')
        self.log_text = tk.Text(logbox, height=6, font=self.fonts['mono'], bg=PANEL, fg=MUTED, relief='flat',
                                wrap='word', padx=self.px(10), pady=self.px(8), state='disabled',
                                insertbackground=TEXT, selectbackground=ACCENT_OFF)
        self.log_text.pack(fill='x')

        foot = tk.Frame(outer, bg=BG)
        foot.pack(fill='x', pady=(self.px(10), 0))
        tk.Label(foot, text=f'Close the game before installing. Original data is backed up in '
                            f'{core.BACKUP_DIR} inside the game folder.',
                 font=self.fonts['small'], fg=MUTED, bg=BG, anchor='w').pack(side='left')
        tk.Label(foot, text='made by VAXIS', font=self.fonts['label'], fg=ACCENT, bg=BG).pack(side='right')

        self.select(self.choice)

    def dark_title_bar(self):
        if os.name != 'nt':
            return
        try:
            import ctypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            colorref = lambda c: int(c[5:7] + c[3:5] + c[1:3], 16)
            for attribute, value in ((20, 1), (35, colorref(BG)), (34, colorref(LINE)), (36, colorref(MUTED))):
                v = ctypes.c_int(value)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(v), ctypes.sizeof(v))
        except (AttributeError, OSError):
            pass

    def section(self, parent, text):
        tk.Label(parent, text=text, font=self.fonts['label'], fg=MUTED, bg=BG, anchor='w').pack(
            fill='x', pady=(0, self.px(7)))

    def button(self, parent, text, command, primary):
        b = tk.Button(parent, text=text, command=command, font=self.fonts['button'], relief='flat', bd=0,
                      cursor='hand2', padx=self.px(22), pady=self.px(9), highlightthickness=0 if primary else 1,
                      highlightbackground=LINE)
        b.primary = primary
        b.bind('<Enter>', lambda e: self.paint_button(b, hover=True))
        b.bind('<Leave>', lambda e: self.paint_button(b))
        self.paint_button(b)
        return b

    def paint_button(self, b, hover=False):
        on = str(b['state']) != 'disabled'
        if b.primary:
            bg = (ACCENT_HOVER if hover else ACCENT) if on else ACCENT_OFF
            b.config(bg=bg, fg=INK, activebackground=ACCENT_HOVER, activeforeground=INK,
                     disabledforeground=ACCENT_OFF_TEXT)
        else:
            bg = PANEL_HI if hover and on else PANEL
            b.config(bg=bg, fg=TEXT, activebackground=PANEL_HI, activeforeground=ACCENT,
                     disabledforeground='#4a4a4a', highlightbackground=ACCENT if hover and on else LINE)

    def set_button(self, b, on, text=None):
        b.config(state='normal' if on else 'disabled')
        if text:
            b.config(text=text)
        self.paint_button(b)

    def set_game(self, path):
        self.game = path
        self.path_var.set(path or 'Not found. Click BROWSE and pick the Death Stranding 2 folder.')
        if path and len(self.font_families) < len(game_fonts.FONTS):
            self.font_families = game_fonts.load(path, self.font_families)
            self.apply_fonts()
        self.refresh()

    def refresh(self):
        if not self.game:
            self.code, self.current = 'none', None
            self.status('Game folder not found.', BAD)
        else:
            try:
                self.code, self.current, message = core.status(self.game)
            except core.PatchError as e:
                self.code, self.current, message = 'partial', None, str(e)
            color = {'installed': OK, 'none': MUTED}.get(self.code, WARN)
            self.status(message, color)
        for pid, card in self.cards.items():
            card.set_installed(self.code == 'installed' and pid == self.current)
        if self.code == 'installed' and self.current:
            self.select(self.current)
        self.update_buttons()

    def status(self, text, color):
        self.status_mark.config(bg=color)
        self.status_line.config(text=text, fg=TEXT if color == MUTED else color)

    def select(self, pid):
        if not self.enabled:
            return
        self.choice = pid
        for k, card in self.cards.items():
            card.set_selected(k == pid)
        self.update_buttons()

    def update_buttons(self):
        name = core.preset(self.choice)['name'].upper()
        same = self.code == 'installed' and self.current == self.choice
        self.set_button(self.install_btn, self.enabled and bool(self.game) and not same,
                        f'{name} INSTALLED' if same else f'INSTALL {name}')
        self.set_button(self.uninstall_btn, self.enabled and bool(self.game) and self.code != 'none')
        self.set_button(self.browse_btn, self.enabled)

    def set_enabled(self, on):
        self.enabled = on
        self.root.config(cursor='' if on else 'watch')
        for card in self.cards.values():
            card.paint()
        self.update_buttons()

    def browse(self):
        path = filedialog.askdirectory(title='Select the Death Stranding 2 game folder',
                                       initialdir=self.game or None)
        if not path:
            return
        path = os.path.realpath(path)
        if not core.is_game_dir(path):
            messagebox.showerror('VAXIS', 'That folder does not contain Death Stranding 2.\n\n'
                                          'Pick the folder that contains DS2.exe.')
            return
        self.set_game(path)

    def install(self):
        name = core.preset(self.choice)['name']
        self.run(f'Installing {name}', core.install, self.game, self.choice,
                 done=f'{name} is installed. Start the game and enjoy.')

    def uninstall(self):
        if not messagebox.askyesno('VAXIS', 'Restore the original game files?'):
            return
        self.run('Uninstalling', core.uninstall, self.game, done='The original game files are restored.')

    def run(self, title, fn, *args, done):
        self.set_enabled(False)
        self.progress['value'] = 0
        self.step_label.config(text=title + '...')
        self.log(f'--- {title}')

        def work():
            try:
                fn(*args, log=lambda m: self.events.put(('log', m)),
                   report=lambda f, t: self.events.put(('progress', (f, t))))
                self.events.put(('done', done))
            except core.PatchError as e:
                self.events.put(('error', str(e)))
            except Exception as e:
                self.events.put(('log', traceback.format_exc()))
                self.events.put(('error', f'Unexpected error: {e}'))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def pump(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log':
                    self.log(value)
                elif kind == 'progress':
                    fraction, text = value
                    self.progress['value'] = int(fraction * 1000)
                    self.step_label.config(text=text)
                elif kind in ('done', 'error'):
                    self.worker = None
                    self.set_enabled(True)
                    self.refresh()
                    if kind == 'done':
                        self.progress['value'] = 1000
                        self.step_label.config(text='Done')
                        self.log(value)
                        messagebox.showinfo('VAXIS', value)
                    else:
                        self.progress['value'] = 0
                        self.step_label.config(text='Failed')
                        self.log('ERROR: ' + value)
                        messagebox.showerror('VAXIS', value)
        except queue.Empty:
            pass
        self.root.after(50, self.pump)

    def log(self, text):
        self.log_text.config(state='normal')
        self.log_text.insert('end', text.rstrip() + '\n')
        self.log_text.see('end')
        self.log_text.config(state='disabled')

    def close(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning('VAXIS', 'Please wait until the patcher has finished.\n\n'
                                            'Closing now could leave the game files half patched.')
            return
        self.root.destroy()

    def run_selftest(self):
        lines = [f'game: {self.game}', f'status: {self.code} {self.current}']
        try:
            for p in core.PRESETS:
                files = core.load_preset(p['id'])
                lines.append(f'{p["id"]}: {sum(len(v) for v in files.values())} values in {len(files)} files')
            import lz4.block
            data = b'vaxis' * 1000
            assert lz4.block.decompress(lz4.block.compress(data, store_size=False), uncompressed_size=len(data)) == data
            lines.append('lz4: ok')
            for role, f in self.fonts.items():
                lines.append(f'font {role}: {f.actual("family")} {f.actual("size")}')
            lines.append('result: ok')
        except Exception as e:
            lines.append(f'result: failed {e!r}')
        with open(self.selftest, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        self.root.after(2500, self.root.destroy)


def main():
    selftest = None
    if len(sys.argv) >= 3 and sys.argv[1] == '--selftest':
        selftest = sys.argv[2]
    enable_dpi_awareness()
    root = tk.Tk()
    App(root, selftest)
    root.mainloop()


if __name__ == '__main__':
    main()
