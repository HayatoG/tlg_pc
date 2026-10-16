#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Last Guardian launcher (Tkinter, Linux and Windows), in pt_BR and en_US.

Game folder, game and interface language, display, FPS overlay, VRAM budget and native audio;
Play starts the game through tlg_run.py (the same code path as run_tlg.sh) and shows its log.
Settings live in ~/.config/tlg-launcher/settings.json (%APPDATA% on Windows).
"""
import locale
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tlg_run  # noqa: E402

TEXT = {
    'title': ('The Last Guardian — PC', 'The Last Guardian — PC'),
    'game': ('Game', 'Jogo'),
    'game_dir': ('Game folder', 'Pasta do jogo'),
    'system_lib_dir': ('Console system modules', 'Módulos do sistema do console'),
    'browse': ('Browse…', 'Procurar…'),
    'language': ('Language', 'Idioma'),
    'game_language': ('Game language (voice and text)', 'Idioma do jogo (voz e texto)'),
    'ui_language': ('Interface language', 'Idioma da interface'),
    'auto': ('Automatic (system)', 'Automático (sistema)'),
    'video': ('Video', 'Vídeo'),
    'display_mode': ('Display mode', 'Modo de exibição'),
    'Windowed': ('Windowed', 'Janela'),
    'Borderless': ('Borderless window', 'Janela sem borda'),
    'Fullscreen': ('Fullscreen', 'Tela cheia'),
    'vsync': ('VSync', 'VSync'),
    'frame_rate': ('Frame rate (experimental)', 'Taxa de quadros (experimental)'),
    'fps_30': ('30 FPS (as on PS4)', '30 FPS (como no PS4)'),
    'fps_60': ('60 FPS', '60 FPS'),
    'fps_unlocked': ('Unlocked (up to the display)', 'Livre (até a taxa do monitor)'),
    'fps_hint': ('60/unlocked patch eboot 1.03 in memory; see docs/60fps.md',
                 '60/livre alteram o eboot 1.03 na memória; ver docs/60fps.md'),
    'show_fps': ('Show FPS overlay at start (F10 toggles)', 'Mostrar overlay de FPS ao iniciar (F10 alterna)'),
    'vram': ('Texture cache budget (MB of VRAM)', 'Orçamento do cache de texturas (MB de VRAM)'),
    'vram_hint': ('6 GB card: 5600 · 8 GB: 7000 · 12 GB: 10500 · 16 GB: 14000 · 24 GB: 21500. This is video card memory (VRAM), not RAM; never above your card\'s VRAM.',
                  'Placa de 6 GB: 5600 · 8 GB: 7000 · 12 GB: 10500 · 16 GB: 14000 · 24 GB: 21500. É a memória da placa de vídeo (VRAM), não a RAM; nunca acima da VRAM da placa.'),
    'filters': ('Image filters (live in the in-game menu too, Insert → Image)',
                'Filtros de imagem (também no menu do jogo, Insert → Imagem)'),
    'smaa': ('SMAA anti-aliasing (smooths edges; the HUD too)', 'Anti-aliasing SMAA (suaviza bordas; o HUD também)'),
    'sharpening': ('Sharpening', 'Nitidez'),
    'sharpen_off': ('Off', 'Desligada'),
    'sharpen_rcas': ('RCAS (FSR 1)', 'RCAS (FSR 1)'),
    'sharpen_cas': ('CAS (AMD)', 'CAS (AMD)'),
    'color_adjust': ('Color adjustments', 'Ajustes de cor'),
    'color_brightness': ('Brightness (0 = unchanged)', 'Brilho (0 = sem alteração)'),
    'color_contrast': ('Contrast (1 = unchanged)', 'Contraste (1 = sem alteração)'),
    'color_saturation': ('Saturation (1 = unchanged)', 'Saturação (1 = sem alteração)'),
    'color_gamma': ('Gamma (1 = unchanged)', 'Gama (1 = sem alteração)'),
    'audio': ('Audio', 'Áudio'),
    'native_audio': ('Native audio (libSceNgs2.sprx from your console)', 'Áudio nativo (libSceNgs2.sprx do seu console)'),
    'controls': ('Controls', 'Controles'),
    'mouse_enabled': ('Mouse turns the camera', 'Mouse gira a câmera'),
    'mouse_invert_y': ('Invert mouse Y axis', 'Inverter eixo Y do mouse'),
    'mouse_sensitivity': ('Mouse sensitivity', 'Sensibilidade do mouse'),
    'mouse_hint': ('Esc releases the mouse; a click in the game window takes it back.',
                   'Esc solta o mouse; um clique na janela do jogo prende de novo.'),
    'remap': ('Keyboard and mouse buttons…', 'Teclas e botões do mouse…'),
    'remap_title': ('Keyboard and mouse buttons', 'Teclas e botões do mouse'),
    'remap_help': ('Click Set and press a key or mouse button, or type SDL names (Space, Left Shift, '
                   'Mouse Left, Mouse X1, Wheel Up…). "|" gives several: Q|Mouse Left. "none": no key. '
                   'Empty: the default (grey). Applies at the next start.',
                   'Clique em Definir e aperte uma tecla ou botão do mouse, ou digite nomes do SDL (Space, Left Shift, '
                   'Mouse Left, Mouse X1, Wheel Up…). "|" junta vários: Q|Mouse Left. "none": nenhuma tecla. '
                   'Vazio: o padrão (cinza). Vale na próxima vez que o jogo abrir.'),
    'button': ('PS4 button', 'Botão do PS4'),
    'keys': ('Keys / mouse', 'Teclas / mouse'),
    'default': ('Default', 'Padrão'),
    'set': ('Set', 'Definir'),
    'press': ('Press a key…', 'Aperte uma tecla…'),
    'reset': ('Reset all', 'Restaurar tudo'),
    'close': ('Close', 'Fechar'),
    'play': ('Play', 'Jogar'),
    'saves': ('Saves folder', 'Pasta de saves'),
    'logs': ('Logs folder', 'Pasta de logs'),
    'clear_cache': ('Clear shader cache', 'Limpar cache de shaders'),
    'clear_cache_ask': ('This deletes the compiled shaders ({size}); the next start takes longer to load and '
                        'may stutter at first. Continue?',
                        'Isso apaga os shaders compilados ({size}); a próxima partida demora mais para carregar e '
                        'pode engasgar no começo. Continuar?'),
    'clear_cache_empty': ('The shader cache is already empty.', 'O cache de shaders já está vazio.'),
    'clear_cache_done': ('Shader cache cleared: {size} freed.', 'Cache de shaders limpo: {size} liberados.'),
    'clear_cache_failed': ('{size} freed, but {count} file(s) could not be deleted (in use? Close the game '
                           'and try again).',
                           '{size} liberados, mas {count} arquivo(s) não puderam ser apagados (em uso? Feche o '
                           'jogo e tente de novo).'),
    'quit': ('Quit', 'Sair'),
    'ready': ('Ready to play.', 'Pronto para jogar.'),
    'audio_native': ('Audio: native (console module found).', 'Áudio: nativo (módulo do console encontrado).'),
    'audio_builtin': ('Audio: built-in mixer, experimental (libSceNgs2.sprx not found or not selected).',
                      'Áudio: mixer próprio, experimental (libSceNgs2.sprx não encontrado ou desmarcado).'),
    'missing': ('Missing', 'Faltando'),
    'not_built': ('Port not built (run build.sh)', 'Port não compilado (rode o build.sh)'),
    'preparing': ('Preparing the game…', 'Preparando o jogo…'),
    'running': ('Playing — log:', 'Jogando — log:'),
    'ended': ('Game closed (exit code {code}).', 'Jogo fechado (código {code}).'),
    'crashed': ('The game closed with an error (code {code}). The log has the details.',
                'O jogo fechou com erro (código {code}). Os detalhes estão no log.'),
    'already': ('The game is already running.', 'O jogo já está rodando.'),
    'error': ('Error', 'Erro'),
    'port_by': ('PC port by HayatoG', 'Port para PC por HayatoG'),
    'channel': ('YouTube channel: @hayatog-dev', 'Canal no YouTube: @hayatog-dev'),
    'discord': ('Discord community', 'Comunidade no Discord'),
}
CHANNEL_URL = 'https://www.youtube.com/@hayatog-dev'
DISCORD_URL = 'https://discord.gg/UMkdMYZh9g'
GAME_LANGUAGE_NAMES = {'en': 'English', 'fr': 'Français', 'es_ES': 'Español (España)',
                       'de': 'Deutsch', 'it': 'Italiano', 'nl': 'Nederlands',
                       'pt_PT': 'Português (Portugal)', 'ru': 'Русский', 'fi': 'Suomi',
                       'sv': 'Svenska', 'da': 'Dansk', 'no': 'Norsk', 'pl': 'Polski',
                       'tr': 'Türkçe', 'ar': 'العربية',
                       'pt_BR': 'Português (Brasil)', 'es_LA': 'Español (Latinoamérica)',
                       'fr_CA': 'Français (Canada)'}
UI_LANGUAGES = ['auto', 'pt_BR', 'en_US']
UI_LANGUAGE_NAMES = {'pt_BR': 'Português (Brasil)', 'en_US': 'English (US)'}
DISPLAY_MODES = ['Windowed', 'Borderless', 'Fullscreen']
# The PS4 buttons the remap dialog lists, with what they do in The Last Guardian when known.
PS4_BUTTONS = [
    ('cross', 'Cross (X)', ('jump', 'pular')), ('circle', 'Circle', None), ('square', 'Square', None),
    ('triangle', 'Triangle', ('grab, hold on', 'agarrar, segurar')), ('l1', 'L1', None),
    ('r1', 'R1', ('call Trico', 'chamar o Trico')), ('l2', 'L2', None), ('r2', 'R2', None), ('l3', 'L3', None),
    ('r3', 'R3', None), ('options', 'Options', ('menu', 'menu')),
    ('touchpad_left', 'Touchpad (left)', ('photo mode', 'modo foto')),
    ('touchpad_right', 'Touchpad (right)', ('pause', 'pausa')),
    ('up', 'D-pad up', None), ('down', 'D-pad down', None), ('left', 'D-pad left', None), ('right', 'D-pad right', None),
]
# Tk key names -> SDL key names (src/runtime_pad.c reads SDL names); letters and digits are the same.
TK_TO_SDL = {
    'space': 'Space', 'Shift_L': 'Left Shift', 'Shift_R': 'Right Shift', 'Control_L': 'Left Ctrl',
    'Control_R': 'Right Ctrl', 'Alt_L': 'Left Alt', 'Alt_R': 'Right Alt', 'Return': 'Return', 'Tab': 'Tab',
    'BackSpace': 'Backspace', 'Up': 'Up', 'Down': 'Down', 'Left': 'Left', 'Right': 'Right', 'Delete': 'Delete',
    'Insert': 'Insert', 'Home': 'Home', 'End': 'End', 'Prior': 'PageUp', 'Next': 'PageDown',
    'Caps_Lock': 'CapsLock', 'comma': ',', 'period': '.', 'minus': '-', 'equal': '=', 'slash': '/',
    'semicolon': ';', 'apostrophe': "'", 'bracketleft': '[', 'bracketright': ']', 'backslash': '\\',
    'grave': '`', 'KP_Enter': 'Keypad Enter',
}
TK_MOUSE = {1: 'Mouse Left', 2: 'Mouse Middle', 3: 'Mouse Right', 8: 'Mouse X1', 9: 'Mouse X2'}


def sdl_key_name(keysym):
    """The SDL name of a Tk key, or None (Esc releases the mouse in game; F-keys are the port's)."""
    if keysym in TK_TO_SDL:
        return TK_TO_SDL[keysym]
    if len(keysym) == 1 and keysym.isalnum():
        return keysym.upper()
    if keysym.startswith('KP_') and keysym[3:].isdigit():
        return f'Keypad {keysym[3:]}'
    return None

SHARPENERS = ['off', 'rcas', 'cas']
# Image filters: kept in tlg.ini only (the in-game menu writes the same keys), with their
# defaults and ranges (tlg_graphics.h).
INI_DEFAULTS = {'smaa': '0', 'rcas': '1', 'cas': '0', 'color_adjust': '0', 'color_brightness': '0.00',
                'color_contrast': '1.00', 'color_saturation': '1.00', 'color_gamma': '1.00'}
COLOR_RANGES = {'color_brightness': (-0.5, 0.5), 'color_contrast': (0.5, 1.5),
                'color_saturation': (0.0, 2.0), 'color_gamma': (0.5, 2.0)}


def art_path(settings, name):
    """Official art from the user's own dump (sce_sys); never shipped with the port."""
    for folder in (Path(settings['game_dir']) / 'sce_sys', tlg_run.REPO_DIR / 'dump' / 'sce_sys'):
        if (folder / name).is_file():
            return folder / name
    return None


def system_is_portuguese():
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = os.environ.get(name)
        if value:
            return value.lower().startswith('pt')
    try:
        return (locale.getlocale()[0] or '').lower().startswith('pt')
    except ValueError:
        return False


class Launcher:
    def __init__(self, root):
        self.root = root
        self.settings = tlg_run.load_settings()
        self.process = None
        self.lines = queue.Queue()
        self.build()
        self.root.after(100, self.pump)

    # -- language ---------------------------------------------------------------------------
    def pt(self):
        choice = self.settings.get('ui_language', 'auto')
        return system_is_portuguese() if choice == 'auto' else choice == 'pt_BR'

    def t(self, key, **fmt):
        en, pt = TEXT[key]
        return (pt if self.pt() else en).format(**fmt)

    # -- window -----------------------------------------------------------------------------
    def build(self):
        """Horizontal layout: banner on top; Game + Audio | Language + Video | game log; buttons below."""
        for child in self.root.winfo_children():
            child.destroy()
        root = self.root
        root.title(self.t('title'))
        root.minsize(1120, 680)
        pad = {'padx': 6, 'pady': 4}
        main = ttk.Frame(root, padding=12)
        main.pack(fill='both', expand=True)
        for column, weight in enumerate((3, 3, 4)):
            main.columnconfigure(column, weight=weight, uniform='cols' if column < 2 else '')
        main.rowconfigure(2, weight=1)

        header = ttk.Frame(main)
        header.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 8))
        self.load_art()
        if self.banner:
            ttk.Label(header, image=self.banner).pack(side='left', padx=(0, 14))
        titles = ttk.Frame(header)
        titles.pack(side='left', fill='y')
        ttk.Label(titles, text='The Last Guardian', font=('TkDefaultFont', 22, 'bold')).pack(anchor='w')
        ttk.Label(titles, text='PC — CUSA03627 v1.03', foreground='#777').pack(anchor='w')
        credits = ttk.Frame(header)
        credits.pack(side='right', anchor='ne')
        ttk.Label(credits, text=self.t('port_by'), foreground='#777').pack(anchor='e')
        for key, url in (('channel', CHANNEL_URL), ('discord', DISCORD_URL)):
            link = ttk.Label(credits, text=self.t(key), foreground='#2a6fdb', cursor='hand2',
                             font=('TkDefaultFont', 10, 'underline'))
            link.pack(anchor='e')
            link.bind('<Button-1>', lambda _, u=url: webbrowser.open(u))
        self.status = ttk.Label(titles, text='', foreground='#555', wraplength=420, justify='left')
        self.status.pack(anchor='w', pady=(10, 0))

        self.vars = {}
        left = ttk.Frame(main)
        left.grid(row=2, column=0, sticky='nsew', **pad)
        left.columnconfigure(0, weight=1)
        game = ttk.LabelFrame(left, text=self.t('game'), padding=8)
        game.grid(sticky='ew', pady=(0, 8))
        game.columnconfigure(0, weight=1)
        for row, key in enumerate(('game_dir', 'system_lib_dir')):
            ttk.Label(game, text=self.t(key)).grid(row=row * 2, column=0, columnspan=2, sticky='w')
            var = tk.StringVar(value=self.settings[key])
            var.trace_add('write', lambda *_: self.changed())
            self.vars[key] = var
            ttk.Entry(game, textvariable=var).grid(row=row * 2 + 1, column=0, sticky='ew', pady=(0, 6))
            ttk.Button(game, text=self.t('browse'), command=lambda k=key: self.browse(k)).grid(
                row=row * 2 + 1, column=1, padx=(6, 0), pady=(0, 6))
        audio = ttk.LabelFrame(left, text=self.t('audio'), padding=8)
        audio.grid(sticky='ew', pady=(0, 8))
        self.check(audio, 0, 'native_audio')
        controls = ttk.LabelFrame(left, text=self.t('controls'), padding=8)
        controls.grid(sticky='ew')
        controls.columnconfigure(1, weight=1)
        self.check(controls, 0, 'mouse_enabled')
        self.check(controls, 1, 'mouse_invert_y')
        ttk.Label(controls, text=self.t('mouse_sensitivity')).grid(row=2, column=0, sticky='w', pady=(4, 0))
        sens = tk.DoubleVar(value=float(self.settings.get('mouse_sensitivity', 1.0)))
        self.vars['mouse_sensitivity'] = sens
        sens_spin = ttk.Spinbox(controls, from_=0.1, to=5.0, increment=0.1, format='%.2f', textvariable=sens,
                                width=6, command=self.changed)
        sens_spin.grid(row=2, column=1, sticky='w', padx=6, pady=(4, 0))
        sens_spin.bind('<FocusOut>', lambda _: self.changed())
        ttk.Button(controls, text=self.t('remap'), command=self.remap_dialog).grid(row=2, column=2, sticky='e', pady=(4, 0))
        ttk.Label(controls, text=self.t('mouse_hint'), foreground='#777', wraplength=420, justify='left').grid(
            row=3, column=0, columnspan=3, sticky='w', pady=(2, 0))

        middle = ttk.Frame(main)
        middle.grid(row=2, column=1, sticky='nsew', **pad)
        middle.columnconfigure(0, weight=1)
        lang = ttk.LabelFrame(middle, text=self.t('language'), padding=8)
        lang.grid(sticky='ew', pady=(0, 8))
        lang.columnconfigure(1, weight=1)
        self.game_lang_box = None
        self.build_game_language(lang)
        self.combo(lang, 1, 'ui_language', UI_LANGUAGES,
                   lambda k: self.t('auto') if k == 'auto' else UI_LANGUAGE_NAMES[k], on_change=self.build)
        video = ttk.LabelFrame(middle, text=self.t('video'), padding=8)
        video.grid(sticky='ew')
        video.columnconfigure(1, weight=1)
        self.combo(video, 0, 'display_mode', DISPLAY_MODES, lambda k: self.t(k))
        self.check(video, 1, 'vsync')
        self.check(video, 2, 'show_fps')
        self.combo(video, 5, 'frame_rate', tlg_run.FRAME_RATES, lambda k: self.t(f'fps_{k}'))
        ttk.Label(video, text=self.t('fps_hint'), foreground='#777', wraplength=320).grid(
            row=6, column=0, columnspan=2, sticky='w')
        ttk.Label(video, text=self.t('vram'), wraplength=220).grid(row=3, column=0, sticky='w', pady=(6, 0))
        vram = tk.IntVar(value=int(self.settings['vram_budget_mb']))
        self.vars['vram_budget_mb'] = vram
        spin = ttk.Spinbox(video, from_=2000, to=24000, increment=200, textvariable=vram, width=8,
                           command=self.changed)
        spin.grid(row=3, column=1, sticky='w', padx=6, pady=(6, 0))
        spin.bind('<FocusOut>', lambda _: self.changed())
        ttk.Label(video, text=self.t('vram_hint'), foreground='#777', wraplength=360).grid(row=4, column=0, columnspan=2, sticky='w')
        self.build_filters(video, 7)

        log_frame = ttk.LabelFrame(main, text='Log', padding=4)
        log_frame.grid(row=2, column=2, sticky='nsew', **pad)
        self.log = tk.Text(log_frame, wrap='none', font=('TkFixedFont', 9), state='disabled', width=60)
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        buttons = ttk.Frame(main)
        buttons.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        ttk.Button(buttons, text=self.t('quit'), command=self.quit).pack(side='left')
        style = ttk.Style()
        style.configure('Play.TButton', font=('TkDefaultFont', 13, 'bold'))
        self.play_button = ttk.Button(buttons, text=self.t('play'), style='Play.TButton', command=self.play)
        self.play_button.pack(side='right', ipadx=30, ipady=8)
        ttk.Button(buttons, text=self.t('logs'), command=lambda: self.open(tlg_run.LOG_DIR)).pack(side='right', padx=6)
        ttk.Button(buttons, text=self.t('saves'), command=lambda: self.open(tlg_run.USER_DIR / 'savedata')).pack(side='right')
        self.cache_button = ttk.Button(buttons, text=self.t('clear_cache'), command=self.clear_cache)
        self.cache_button.pack(side='right', padx=(0, 6))
        self.refresh_status()

    def load_art(self):
        """Window icon (the port's tlg.png) and a 480x135 banner (a band of pic1.png from the dump, when present)."""
        self.banner = getattr(self, 'banner', None)
        if getattr(self, 'art_loaded', False):
            return
        self.art_loaded = True
        try:
            icon = tlg_run.PORT_DIR / 'launcher' / 'tlg.png'  # the port's own icon
            if icon.is_file():
                self.icon = tk.PhotoImage(file=str(icon))
                self.root.iconphoto(True, self.icon)
            picture = art_path(self.settings, 'pic1.png') or art_path(self.settings, 'pic0.png')
            if picture:
                full = tk.PhotoImage(file=str(picture))
                band = full.width() * 9 // 32           # a 32:9 band from the middle of the image
                top = (full.height() - band) // 2
                self.banner = tk.PhotoImage()
                self.banner.tk.call(self.banner, 'copy', full, '-from', 0, top, full.width(), top + band,
                                    '-subsample', 4, 4)  # Tk command: same on every Python version
        except tk.TclError:
            self.banner = None

    def build_filters(self, parent, row):
        """SMAA, sharpening and color adjustments, read from and written to tlg.ini right away."""
        ttk.Separator(parent).grid(row=row, column=0, columnspan=2, sticky='ew', pady=(8, 4))
        ttk.Label(parent, text=self.t('filters'), foreground='#555', wraplength=360).grid(
            row=row + 1, column=0, columnspan=2, sticky='w')
        ini = dict(INI_DEFAULTS)
        ini.update({k: v for k, v in tlg_run.read_ini(tlg_run.USER_DIR / 'tlg.ini').items() if k in ini})
        self.ini_vars = {}
        for offset, key in ((2, 'smaa'), (4, 'color_adjust')):
            var = tk.BooleanVar(value=ini[key] not in ('0', ''))
            self.ini_vars[key] = var
            ttk.Checkbutton(parent, text=self.t(key), variable=var, command=self.filters_changed).grid(
                row=row + offset, column=0, columnspan=2, sticky='w', pady=2)
        ttk.Label(parent, text=self.t('sharpening')).grid(row=row + 3, column=0, sticky='w')
        self.sharpener = ttk.Combobox(parent, values=[self.t('sharpen_' + k) for k in SHARPENERS],
                                      state='readonly', width=16)
        self.sharpener.current(2 if ini['cas'] not in ('0', '') else 1 if ini['rcas'] not in ('0', '') else 0)
        self.sharpener.grid(row=row + 3, column=1, sticky='w', padx=6, pady=2)
        self.sharpener.bind('<<ComboboxSelected>>', lambda _: self.filters_changed())
        for index, key in enumerate(COLOR_RANGES):
            low, high = COLOR_RANGES[key]
            ttk.Label(parent, text=self.t(key)).grid(row=row + 5 + index, column=0, sticky='w', padx=(16, 0))
            var = tk.StringVar(value=ini[key])
            self.ini_vars[key] = var
            spin = ttk.Spinbox(parent, from_=low, to=high, increment=0.05, format='%.2f', textvariable=var,
                               width=6, command=self.filters_changed)
            spin.grid(row=row + 5 + index, column=1, sticky='w', padx=6, pady=1)
            spin.bind('<FocusOut>', lambda _: self.filters_changed())

    def filters_changed(self):
        values = {'smaa': int(self.ini_vars['smaa'].get()), 'color_adjust': int(self.ini_vars['color_adjust'].get()),
                  'rcas': int(self.sharpener.current() == 1), 'cas': int(self.sharpener.current() == 2)}
        for key, (low, high) in COLOR_RANGES.items():
            try:
                value = min(max(float(self.ini_vars[key].get().replace(',', '.')), low), high)
            except ValueError:
                continue  # while typing
            values[key] = f'{value:.2f}'
        tlg_run.USER_DIR.mkdir(parents=True, exist_ok=True)
        tlg_run.update_ini(tlg_run.USER_DIR / 'tlg.ini', values)

    def combo(self, parent, row, key, values, label, on_change=None):
        ttk.Label(parent, text=self.t(key)).grid(row=row, column=0, sticky='w')
        names = [label(v) for v in values]
        box = ttk.Combobox(parent, values=names, state='readonly', width=28)
        current = self.settings.get(key, values[0])
        box.current(values.index(current) if current in values else 0)
        box.grid(row=row, column=1, sticky='w', padx=6, pady=2)

        def picked(_):
            self.settings[key] = values[box.current()]
            tlg_run.save_settings(self.settings)
            if on_change:
                on_change()
            else:
                self.refresh_status()
        box.bind('<<ComboboxSelected>>', picked)
        return box

    # -- game language (depends on the loaded CUSA) ---------------------------------------------
    def build_game_language(self, parent):
        """Game language: the ones the loaded CUSA ships (by its title id), US by default."""
        ttk.Label(parent, text=self.t('game_language')).grid(row=0, column=0, sticky='w')
        self.game_lang_box = ttk.Combobox(parent, state='readonly', width=28)
        self.game_lang_box.grid(row=0, column=1, sticky='w', padx=6, pady=2)
        self.game_lang_box.bind('<<ComboboxSelected>>', self.picked_language)
        self.refresh_language_choices()

    def picked_language(self, _=None):
        values = self.game_lang_values
        self.settings['game_language'] = values[self.game_lang_box.current()]
        tlg_run.save_settings(self.settings)
        self.refresh_status()

    def refresh_language_choices(self):
        """Reload the combo for the game folder: another CUSA ships another set of languages."""
        if getattr(self, 'game_lang_box', None) is None:
            return
        values = list(tlg_run.game_languages(self.settings.get('game_dir')))
        self.game_lang_values = values
        self.game_lang_box.configure(values=[GAME_LANGUAGE_NAMES.get(v, v) for v in values])
        current = self.settings.get('game_language')
        if current not in values:
            current = tlg_run.default_language(self.settings.get('game_dir'))
        if current not in values:
            current = values[0]
        self.game_lang_box.current(values.index(current))
        if current != self.settings.get('game_language'):
            self.settings['game_language'] = current
            tlg_run.save_settings(self.settings)

    def remap_dialog(self):
        """PS4 button -> keys and mouse buttons (tlg.ini key_map through tlg_run.launch)."""
        if getattr(self, 'remap_window', None) and self.remap_window.winfo_exists():
            self.remap_window.lift()
            return
        win = self.remap_window = tk.Toplevel(self.root)
        win.title(self.t('remap_title'))
        win.transient(self.root)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill='both', expand=True)
        mapping = dict(self.settings.get('key_map') or {})
        entries = {}
        half = (len(PS4_BUTTONS) + 1) // 2
        for column in (0, 4):
            ttk.Label(frame, text=self.t('button'), font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=column, sticky='w')
            ttk.Label(frame, text=self.t('keys'), font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=column + 1, sticky='w')
            ttk.Label(frame, text=self.t('default'), font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=column + 3, sticky='w')

        def save(*_):
            self.settings['key_map'] = {b: e.get().strip() for b, e in entries.items() if e.get().strip()}
            tlg_run.save_settings(self.settings)

        def capture(button, entry, set_button):
            set_button.configure(text=self.t('press'))
            win.focus_set()

            def done(name):
                for sequence in ('<KeyPress>', '<ButtonPress>'):
                    win.unbind(sequence)
                set_button.configure(text=self.t('set'))
                if name:
                    entry.delete(0, 'end')
                    entry.insert(0, name)
                    save()

            def key(event):
                if event.keysym == 'Escape':
                    done(None)
                else:
                    done(sdl_key_name(event.keysym))
                return 'break'

            def mouse(event):
                done(TK_MOUSE.get(event.num))
                return 'break'
            win.after(150, lambda: (win.bind('<KeyPress>', key), win.bind('<ButtonPress>', mouse)))

        for index, (button, name, action) in enumerate(PS4_BUTTONS):
            row, column = index % half + 1, 0 if index < half else 4
            label = name if not action else f'{name} — {action[1] if self.pt() else action[0]}'
            ttk.Label(frame, text=label).grid(row=row, column=column, sticky='w', padx=(0, 6), pady=1)
            entry = ttk.Entry(frame, width=20)
            entry.insert(0, mapping.get(button, ''))
            entry.grid(row=row, column=column + 1, sticky='ew', pady=1)
            entry.bind('<FocusOut>', save)
            entry.bind('<Return>', save)
            entries[button] = entry
            set_button = ttk.Button(frame, text=self.t('set'), width=10)
            set_button.configure(command=lambda b=button, e=entry, s=set_button: capture(b, e, s))
            set_button.grid(row=row, column=column + 2, padx=4, pady=1)
            ttk.Label(frame, text=tlg_run.DEFAULT_KEYS[button], foreground='#888').grid(
                row=row, column=column + 3, sticky='w', padx=(0, 18))
        ttk.Label(frame, text=self.t('remap_help'), foreground='#555', wraplength=760, justify='left').grid(
            row=half + 1, column=0, columnspan=8, sticky='w', pady=(10, 6))
        bottom = ttk.Frame(frame)
        bottom.grid(row=half + 2, column=0, columnspan=8, sticky='ew')

        def reset():
            for entry in entries.values():
                entry.delete(0, 'end')
            save()

        def close():
            save()
            win.destroy()
        ttk.Button(bottom, text=self.t('reset'), command=reset).pack(side='left')
        ttk.Button(bottom, text=self.t('close'), command=close).pack(side='right')
        win.protocol('WM_DELETE_WINDOW', close)

    def check(self, parent, row, key):
        var = tk.BooleanVar(value=bool(self.settings[key]))
        self.vars[key] = var
        ttk.Checkbutton(parent, text=self.t(key), variable=var, command=self.changed).grid(
            row=row, column=0, columnspan=3, sticky='w', pady=2)

    # -- actions ----------------------------------------------------------------------------
    def changed(self):
        for key, var in self.vars.items():
            try:
                self.settings[key] = var.get()
            except tk.TclError:
                pass  # spinbox while typing
        tlg_run.save_settings(self.settings)
        self.refresh_language_choices()
        self.refresh_status()

    def refresh_status(self):
        problems = tlg_run.check_game(self.settings['game_dir'])
        if problems:
            text = '; '.join(self.t('not_built') if k == 'not_built' else f"{self.t('missing')}: {d}"
                             for k, d in problems)
        else:
            text = self.t('ready')
        audio = self.t('audio_native') if tlg_run.ngs2_module(self.settings) else self.t('audio_builtin')
        self.status.configure(text=f'{text}  {audio}')
        self.play_button.configure(state='disabled' if problems or self.process else 'normal')
        self.cache_button.configure(state='disabled' if self.process else 'normal')

    def browse(self, key):
        path = filedialog.askdirectory(initialdir=self.vars[key].get() or str(Path.home()))
        if path:
            self.vars[key].set(path)

    def open(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(path)  # noqa: S606 (local folder)
        else:
            subprocess.Popen(['xdg-open', str(path)])

    def clear_cache(self):
        """Clear shader cache: asks first, never while the game runs; shows how much was freed."""
        if self.process:
            messagebox.showinfo(self.t('title'), self.t('already'))
            return
        size = tlg_run.shader_cache_size(self.settings)
        if not size:
            messagebox.showinfo(self.t('clear_cache'), self.t('clear_cache_empty'))
            return
        if not messagebox.askyesno(self.t('clear_cache'),
                                   self.t('clear_cache_ask', size=tlg_run.shader_cache.human_size(size))):
            return
        try:
            freed, failures = tlg_run.clear_shader_cache(self.settings)
        except Exception as error:  # shown to the user, the launcher keeps running
            messagebox.showerror(self.t('error'), str(error))
            return
        freed = tlg_run.shader_cache.human_size(freed)
        if failures:
            message = self.t('clear_cache_failed', size=freed, count=len(failures))
            messagebox.showwarning(self.t('clear_cache'), message)
        else:
            message = self.t('clear_cache_done', size=freed)
            messagebox.showinfo(self.t('clear_cache'), message)
        self.append(message)

    def append(self, line):
        self.log.configure(state='normal')
        self.log.insert('end', line if line.endswith('\n') else line + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 2000:
            self.log.delete('1.0', '500.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def play(self):
        if self.process:
            messagebox.showinfo(self.t('title'), self.t('already'))
            return
        self.changed()
        self.append(self.t('preparing'))
        self.play_button.configure(state='disabled')
        self.cache_button.configure(state='disabled')
        threading.Thread(target=self.run_game, daemon=True).start()

    def run_game(self):
        try:
            tlg_run.prepare(self.settings, log=lambda line: self.lines.put(line))
            self.process, log = tlg_run.launch(self.settings)
        except Exception as error:  # shown to the user, the launcher keeps running
            self.lines.put(('error', str(error)))
            return
        self.lines.put(f"{self.t('running')} {log}")
        with open(log, 'w', encoding='utf-8') as out:
            out.write(f'Frame rate: requested {tlg_run.frame_rate(self.settings)}, applied {tlg_run.applied_frame_rate}\n')
            for line in self.process.stdout:
                out.write(line)
                out.flush()
                self.lines.put(line.rstrip('\n'))
        code = self.process.wait()
        self.process = None
        self.lines.put(('ended', code))

    def pump(self):
        try:
            while True:
                item = self.lines.get_nowait()
                if isinstance(item, tuple):
                    kind, value = item
                    if kind == 'error':
                        messagebox.showerror(self.t('error'), value)
                    else:
                        message = self.t('ended' if value in (0, -15) else 'crashed', code=value)
                        self.append(message)
                        if value not in (0, -15):
                            messagebox.showwarning(self.t('title'), message)
                    self.refresh_status()
                else:
                    self.append(item)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def quit(self):
        if self.process:
            self.process.terminate()
        self.root.destroy()


def main():
    # Packaged executable roles: --script <file> runs a preparation script, --play starts the
    # game with the saved settings and no launcher window (shortcuts, Steam).
    args = sys.argv[1:]
    if args[:1] == ['--script'] and len(args) > 1:
        sys.exit(tlg_run.run_script(args[1:]))
    if args[:1] == ['--clear-shader-cache']:
        sys.exit(tlg_run.main(args))
    if args[:1] == ['--play']:
        sys.exit(tlg_run.main(args[1:]))
    root = tk.Tk(className='tlg-pc')  # matches StartupWMClass in the desktop entry
    try:
        ttk.Style().theme_use('clam')
    except tk.TclError:
        pass
    Launcher(root)
    root.mainloop()


if __name__ == '__main__':
    main()
