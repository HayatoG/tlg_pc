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
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tlg_run  # noqa: E402

TEXT = {
    'journey': ('Journey', 'Jornada'),
    'setup': ('Game & language', 'Jogo e idioma'),
    'image': ('Image & display', 'Imagem e vídeo'),
    'journal': ('Session log', 'Registro da sessão'),
    'eyebrow': ('A BOND BEYOND WORDS', 'UM VÍNCULO ALÉM DAS PALAVRAS'),
    'hero_copy': ('A boy. A mysterious companion.\nAn extraordinary journey awaits.',
                  'Um menino. Um companheiro misterioso.\nUma jornada extraordinária espera por você.'),
    'edition': ('PC RECOMPILATION', 'RECOMPILAÇÃO PARA PC'),
    'home_note': ('Before the journey', 'Antes da jornada'),
    'home_help': ('Choose your game folder in Game & language. Fine-tune your experience in Image & display and Controls.',
                  'Selecione a pasta do jogo em Jogo e idioma. Ajuste sua experiência em Imagem e vídeo e Controles.'),
    'setup_hint': ('Your game, your language. Settings are saved automatically.',
                   'Seu jogo, seu idioma. As configurações são salvas automaticamente.'),
    'image_hint': ('Find the right balance for your journey.', 'Encontre o equilíbrio para sua jornada.'),
    'controls_hint': ('A little closer to Trico.', 'Um pouco mais perto de Trico.'),
    'journal_hint': ('Follow the game output and find details about your session.',
                     'Acompanhe a saída do jogo e os detalhes da sua sessão.'),
    'files': ('Files & maintenance', 'Arquivos e manutenção'),
    'automatic_save': ('Settings saved automatically', 'Configurações salvas automaticamente'),
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
    'mods': ('Mods / Cheats…', 'Mods / Cheats…'),
    'mods_title': ('Mods / Cheats', 'Mods / Cheats'),
    'mods_hint': ('Drop shadPS4/GoldHEN cheat XML files in the mods folder, then turn them on here. '
                  'Nothing here changes the game until you enable it.',
                  'Solte arquivos de cheat XML no formato shadPS4/GoldHEN na pasta de mods e ligue aqui. '
                  'Nada muda no jogo até você ativar.'),
    'mods_warning': ('A cheat can crash the game or behave oddly; if that happens, turn it off here.',
                     'Um cheat pode travar o jogo ou se comportar de forma estranha; se isso acontecer, desligue aqui.'),
    'mods_folder': ('Open mods folder', 'Abrir pasta de mods'),
    'mods_refresh': ('Refresh list', 'Atualizar lista'),
    'mods_empty': ('No cheat XML files found in the mods folder yet.',
                   'Nenhum arquivo de cheat XML encontrado na pasta de mods ainda.'),
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
    'sponsor': ('♥ Sponsor on GitHub', '♥ Apoie no GitHub'),
}
CHANNEL_URL = 'https://www.youtube.com/@hayatog-dev'
DISCORD_URL = 'https://discord.gg/UMkdMYZh9g'
SPONSOR_URL = 'https://github.com/sponsors/HayatoG'
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
    def configure_theme(self):
        """Stone, parchment and moss; all controls remain native Tk/ttk widgets."""
        self.colors = {'paper': '#eeeae0', 'card': '#f8f5ed', 'ink': '#283d35',
                       'muted': '#536158', 'line': '#d4d6c8', 'accent': '#48644f',
                       'control_border': '#7a8477', 'disabled': '#d5d9cc',
                       'dark': '#1a2420', 'light': '#f4f0e4'}
        c = self.colors
        families = set(tkfont.families(self.root))
        self.serif = next((f for f in ('Palatino Linotype', 'Book Antiqua', 'DejaVu Serif')
                           if f in families), 'Times')
        self.sans = next((f for f in ('Segoe UI', 'Noto Sans', 'DejaVu Sans')
                          if f in families), 'TkDefaultFont')
        self.root.configure(background=c['paper'])
        self.root.option_add('*TCombobox*Listbox.background', c['card'])
        self.root.option_add('*TCombobox*Listbox.foreground', c['ink'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', c['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', c['light'])
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=(self.sans, 10), background=c['paper'], foreground=c['ink'],
                        bordercolor=c['line'], lightcolor=c['line'], darkcolor=c['line'],
                        troughcolor=c['paper'], focuscolor=c['accent'])
        style.map('.', foreground=[('disabled', c['muted'])])
        style.configure('TFrame', background=c['paper'])
        style.configure('TLabel', background=c['paper'], foreground=c['ink'])
        style.configure('Muted.TLabel', foreground=c['muted'])
        style.configure('Heading.TLabel', font=(self.serif, 25), foreground=c['ink'])
        style.configure('Brand.TLabel', font=(self.serif, 17))
        style.configure('Eyebrow.TLabel', font=(self.sans, 8, 'bold'), foreground=c['accent'])
        style.configure('TLabelframe', background=c['card'], borderwidth=1, relief='solid')
        style.configure('TLabelframe.Label', background=c['paper'], foreground=c['accent'],
                        font=(self.sans, 10, 'bold'))
        style.configure('Card.TFrame', background=c['card'])
        style.configure('Card.TLabel', background=c['card'])
        style.configure('TButton', background=c['card'], foreground=c['ink'], padding=(14, 9),
                        borderwidth=1, relief='flat')
        style.map('TButton', background=[('active', '#e0e4d7'), ('pressed', '#d1daca')],
                  foreground=[('disabled', c['muted'])], bordercolor=[('focus', c['accent'])])
        style.configure('Nav.TButton', background=c['paper'], padding=(18, 12),
                        font=(self.sans, 10), borderwidth=0)
        style.configure('Selected.Nav.TButton', background=c['ink'], foreground=c['light'])
        style.map('Selected.Nav.TButton', background=[('active', c['accent'])],
                  foreground=[('active', c['light'])])
        style.configure('Play.TButton', background=c['ink'], foreground=c['light'],
                        font=(self.sans, 13, 'bold'), padding=(38, 14))
        style.map('Play.TButton', background=[('disabled', c['disabled']), ('active', '#42604d'),
                                            ('pressed', '#1a3026')],
                  foreground=[('disabled', c['muted']), ('active', c['light'])])
        style.configure('TEntry', fieldbackground=c['card'], padding=8, insertcolor=c['ink'])
        style.configure('TCombobox', fieldbackground=c['card'], background=c['card'],
                        foreground=c['ink'], arrowcolor=c['accent'], padding=7)
        style.configure('TSpinbox', fieldbackground=c['card'], background=c['card'],
                        arrowcolor=c['accent'], padding=6)
        # Clam makes readonly+focus combobox text white. Override the foreground
        # independently of text selection, including inactive selections in entries.
        for field_style in ('TEntry', 'TCombobox', 'TSpinbox'):
            style.configure(field_style, foreground=c['ink'], selectforeground=c['light'],
                            selectbackground=c['ink'], bordercolor=c['control_border'],
                            lightcolor=c['control_border'], darkcolor=c['control_border'])
            style.map(field_style,
                      foreground=[('disabled', c['muted']), ('!disabled', c['ink'])],
                      fieldbackground=[('disabled', c['disabled']), ('!disabled', c['card'])],
                      selectforeground=[('disabled', c['muted']), ('!disabled', c['light'])],
                      selectbackground=[('disabled', c['disabled']), ('!disabled', c['ink'])],
                      bordercolor=[('focus', c['ink']), ('!focus', c['control_border'])],
                      lightcolor=[('focus', c['ink']), ('!focus', c['control_border'])],
                      darkcolor=[('focus', c['ink']), ('!focus', c['control_border'])])
        style.configure('TCheckbutton', background=c['card'], padding=(0, 7),
                        indicatorbackground=c['paper'], indicatorforeground=c['ink'],
                        upperbordercolor=c['control_border'], lowerbordercolor=c['control_border'])
        style.map('TCheckbutton', background=[('active', c['card'])],
                  indicatorbackground=[('selected', c['accent'])],
                  indicatorforeground=[('selected', c['light'])])
        style.configure('Vertical.TScrollbar', background=c['control_border'], borderwidth=0,
                        arrowsize=12, troughcolor=c['paper'])
        style.configure('TSeparator', background=c['line'])

    def build(self):
        """Presentation only: existing settings, callbacks and launch path are reused."""
        old_log = self.log.get('1.0', 'end-1c') if getattr(self, 'log', None) else ''
        current_page = getattr(self, 'current_page', 'journey')
        for child in self.root.winfo_children():
            child.destroy()
        root = self.root
        root.title(self.t('title'))
        self.configure_theme()
        if not getattr(self, 'window_sized', False):
            root.geometry('1240x820')
            self.window_sized = True
        root.minsize(1040, 700)
        self.load_art()
        main = ttk.Frame(root)
        main.pack(fill='both', expand=True)

        header = ttk.Frame(main, padding=(28, 18))
        header.pack(fill='x')
        brand = ttk.Frame(header)
        brand.pack(side='left')
        ttk.Label(brand, text='THE LAST GUARDIAN', style='Brand.TLabel').pack(anchor='w')
        ttk.Label(brand, text=self.t('edition') + '   /   CUSA03627 · v1.03',
                  style='Eyebrow.TLabel').pack(anchor='w', pady=(3, 0))
        credits = ttk.Frame(header)
        credits.pack(side='right')
        ttk.Label(credits, text=self.t('port_by'), style='Muted.TLabel').pack(anchor='e')
        links = ttk.Frame(credits)
        links.pack(anchor='e', pady=(5, 0))
        for index, (key, url) in enumerate((('channel', CHANNEL_URL), ('discord', DISCORD_URL),
                                             ('sponsor', SPONSOR_URL))):
            link = ttk.Label(links, text=self.t(key), foreground=self.colors['accent'],
                             cursor='hand2', font=(self.sans, 9))
            link.pack(side='left', padx=(16 if index else 0, 0))
            link.bind('<Button-1>', lambda _, u=url: webbrowser.open(u))
        ttk.Separator(main).pack(fill='x', padx=28)
        navigation = ttk.Frame(main, padding=(28, 10))
        navigation.pack(fill='x')
        self.nav_buttons = {}
        for key in ('journey', 'setup', 'image', 'controls', 'journal'):
            button = ttk.Button(navigation, text=self.t(key), style='Nav.TButton',
                                command=lambda k=key: self.show_page(k))
            button.pack(side='left', padx=(0, 6))
            self.nav_buttons[key] = button
        self.content = ttk.Frame(main)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.pages = {}
        self.vars = {}
        self.build_journey()

        setup = self.settings_page('setup', 'setup_hint')
        game = self.card(setup, self.t('game'), 0, 0)
        for row, key in enumerate(('game_dir', 'system_lib_dir')):
            ttk.Label(game, text=self.t(key), style='Card.TLabel').grid(
                row=row * 2, column=0, columnspan=2, sticky='w', pady=(0, 6))
            var = tk.StringVar(value=self.settings[key])
            var.trace_add('write', lambda *_: self.changed())
            self.vars[key] = var
            ttk.Entry(game, textvariable=var, width=30).grid(
                row=row * 2 + 1, column=0, sticky='ew', pady=(0, 18))
            ttk.Button(game, text=self.t('browse'), command=lambda k=key: self.browse(k)).grid(
                row=row * 2 + 1, column=1, padx=(8, 0), pady=(0, 18))
        lang = self.card(setup, self.t('language'), 0, 1)
        self.game_lang_box = None
        self.build_game_language(lang)
        self.combo(lang, 1, 'ui_language', UI_LANGUAGES,
                   lambda k: self.t('auto') if k == 'auto' else UI_LANGUAGE_NAMES[k],
                   on_change=self.build)
        audio = self.card(setup, self.t('audio'), 1, 0, span=2)
        self.check(audio, 0, 'native_audio')

        image = self.settings_page('image', 'image_hint')
        video = self.card(image, self.t('video'), 0, 0)
        self.combo(video, 0, 'display_mode', DISPLAY_MODES, lambda k: self.t(k))
        self.check(video, 1, 'vsync')
        self.check(video, 2, 'show_fps')
        ttk.Label(video, text=self.t('vram'), wraplength=230, style='Card.TLabel').grid(
            row=3, column=0, sticky='w', pady=(12, 0))
        vram = tk.IntVar(value=int(self.settings['vram_budget_mb']))
        self.vars['vram_budget_mb'] = vram
        spin = ttk.Spinbox(video, from_=2000, to=24000, increment=200,
                           textvariable=vram, width=8, command=self.changed)
        spin.grid(row=3, column=1, sticky='e', pady=(12, 0))
        spin.bind('<FocusOut>', lambda _: self.changed())
        ttk.Label(video, text=self.t('vram_hint'), style='Card.TLabel',
                  foreground=self.colors['muted'], wraplength=420, justify='left').grid(
            row=4, column=0, columnspan=2, sticky='w', pady=(10, 18))
        self.combo(video, 5, 'frame_rate', tlg_run.FRAME_RATES, lambda k: self.t(f'fps_{k}'))
        ttk.Label(video, text=self.t('fps_hint'), style='Card.TLabel',
                  foreground=self.colors['muted'], wraplength=420, justify='left').grid(
            row=6, column=0, columnspan=2, sticky='w', pady=(8, 0))
        filters = self.card(image, self.t('image'), 0, 1)
        self.build_filters(filters, 0)

        control_page = self.settings_page('controls', 'controls_hint')
        controls = self.card(control_page, self.t('controls'), 0, 0, span=2)
        self.check(controls, 0, 'mouse_enabled')
        self.check(controls, 1, 'mouse_invert_y')
        ttk.Label(controls, text=self.t('mouse_sensitivity'), style='Card.TLabel').grid(
            row=2, column=0, sticky='w', pady=(12, 0))
        sens = tk.DoubleVar(value=float(self.settings.get('mouse_sensitivity', 1.0)))
        self.vars['mouse_sensitivity'] = sens
        sens_spin = ttk.Spinbox(controls, from_=0.1, to=5.0, increment=0.1, format='%.2f',
                                textvariable=sens, width=6, command=self.changed)
        sens_spin.grid(row=2, column=1, sticky='w', padx=12, pady=(12, 0))
        sens_spin.bind('<FocusOut>', lambda _: self.changed())
        ttk.Button(controls, text=self.t('remap'), command=self.remap_dialog).grid(
            row=2, column=2, sticky='e', pady=(12, 0))
        ttk.Label(controls, text=self.t('mouse_hint'), style='Card.TLabel',
                  foreground=self.colors['muted'], wraplength=760).grid(
            row=3, column=0, columnspan=3, sticky='w', pady=(18, 0))

        journal = self.settings_page('journal', 'journal_hint')
        tools = ttk.Frame(journal)
        tools.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 14))
        for key, command in (('saves', lambda: self.open(tlg_run.USER_DIR / 'savedata')),
                             ('logs', lambda: self.open(tlg_run.LOG_DIR)),
                             ('mods', self.mods_dialog)):
            ttk.Button(tools, text=self.t(key), command=command).pack(side='left', padx=(0, 8))
        self.cache_button = ttk.Button(tools, text=self.t('clear_cache'), command=self.clear_cache)
        self.cache_button.pack(side='right')
        log_frame = ttk.Frame(journal)
        log_frame.grid(row=1, column=0, columnspan=2, sticky='nsew')
        journal.rowconfigure(1, weight=1)
        self.log = tk.Text(log_frame, wrap='none', font=('TkFixedFont', 10),
                           background=self.colors['dark'], foreground='#d9e3d0',
                           insertbackground=self.colors['light'], selectbackground='#45634f',
                           selectforeground=self.colors['light'],
                           relief='flat', borderwidth=0, highlightthickness=0,
                           padx=18, pady=16, width=60, height=16)
        self.log.insert('1.0', old_log)
        self.log.configure(state='disabled')
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        horizontal = ttk.Scrollbar(log_frame, orient='horizontal', command=self.log.xview)
        self.log.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')

        footer = ttk.Frame(main, padding=(28, 16))
        footer.pack(side='bottom', fill='x')
        ttk.Separator(main).pack(side='bottom', fill='x')
        self.content.pack(fill='both', expand=True)
        self.play_button = ttk.Button(footer, text='▷  ' + self.t('play'),
                                      style='Play.TButton', command=self.play)
        self.play_button.pack(side='right', padx=(24, 0))
        ttk.Button(footer, text=self.t('quit'), command=self.quit).pack(side='right')
        status_frame = ttk.Frame(footer)
        status_frame.pack(side='left', fill='x', expand=True)
        ttk.Label(status_frame, text=self.t('automatic_save'), style='Eyebrow.TLabel').pack(anchor='w')
        self.status = ttk.Label(status_frame, text='', style='Muted.TLabel',
                                wraplength=690, justify='left')
        self.status.pack(anchor='w', pady=(5, 0))
        status_frame.bind('<Configure>', lambda event: self.status.configure(
            wraplength=max(240, event.width)))
        self.show_page(current_page)
        self.refresh_status()

    def show_page(self, key):
        self.current_page = key
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items():
            button.configure(style='Selected.Nav.TButton' if name == key else 'Nav.TButton')

    def settings_page(self, key, hint):
        """Scrollable pages keep every setting reachable at smaller window sizes."""
        page = ttk.Frame(self.content)
        page.grid(row=0, column=0, sticky='nsew')
        self.pages[key] = page
        heading = ttk.Frame(page, padding=(32, 18, 32, 20))
        heading.pack(fill='x')
        ttk.Label(heading, text=self.t(key), style='Heading.TLabel').pack(anchor='w')
        ttk.Label(heading, text=self.t(hint), style='Muted.TLabel').pack(anchor='w', pady=(5, 0))
        holder = ttk.Frame(page)
        holder.pack(fill='both', expand=True, padx=(24, 16), pady=(0, 24))
        canvas = tk.Canvas(holder, background=self.colors['paper'], highlightthickness=0)
        scroll = ttk.Scrollbar(holder, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=body, anchor='nw')
        body.columnconfigure((0, 1), weight=1, uniform='cards')
        body.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))

        def resized(event):
            canvas.itemconfigure(window, width=event.width)
            canvas.itemconfigure(window, height=max(event.height, body.winfo_reqheight()))
        canvas.bind('<Configure>', resized)
        # Bind only this page's descendants: comboboxes and spinboxes keep their own wheel behavior.
        def wheel(event):
            if canvas.winfo_height() < body.winfo_reqheight():
                delta = (-1 if event.num == 4 else 1) if event.num in (4, 5) else -int(event.delta / 120)
                canvas.yview_scroll(delta, 'units')
            return 'break'
        def bind_wheel():
            def visit(widget):
                if not isinstance(widget, (ttk.Combobox, ttk.Spinbox, tk.Text)):
                    for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                        widget.bind(sequence, wheel)
                for child in widget.winfo_children():
                    visit(child)
            visit(body)
        page.after_idle(bind_wheel)
        return body

    def card(self, parent, title, row, column, span=1):
        card = ttk.LabelFrame(parent, text='  ' + title + '  ', padding=20)
        card.grid(row=row, column=column, columnspan=span, sticky='new', padx=8, pady=(6, 18))
        card.columnconfigure(0, weight=1)
        return card

    def build_journey(self):
        page = ttk.Frame(self.content)
        page.grid(row=0, column=0, sticky='nsew')
        self.pages['journey'] = page
        canvas = tk.Canvas(page, background=self.colors['dark'], highlightthickness=0, height=430)
        canvas.pack(fill='both', expand=True)
        art = canvas.create_image(0, 0, image=self.banner, anchor='ne') if self.banner else None
        items = []
        items.append(canvas.create_text(56, 92, text=self.t('eyebrow'), fill='#c0ccab',
                                        font=(self.sans, 9, 'bold'), anchor='nw'))
        items.append(canvas.create_line(56, 123, 108, 123, fill='#a6b18f', width=2))
        items.append(canvas.create_text(52, 146, text='THE LAST\nGUARDIAN', fill='#f3efdf',
                                        font=(self.serif, 45), anchor='nw'))
        items.append(canvas.create_text(56, 318, text=self.t('hero_copy'), fill='#d4d9c9',
                                        font=(self.sans, 12), anchor='nw', width=420))
        items.append(canvas.create_text(56, 397, text=self.t('edition') + '   /   HAYATOG',
                                        fill=self.colors['light'], font=(self.sans, 8), anchor='nw'))
        def resized(event):
            if art:
                canvas.coords(art, event.width, 0)
            scale = min(1.0, event.height / 490)
            offset = max(0, (event.height - 490) / 2)
            canvas.itemconfigure(items[2], font=(self.serif, max(23, round(45 * scale))))
            canvas.itemconfigure(items[3], font=(self.sans, max(10, round(12 * scale))))
            for item, y in zip(items, (92, 123, 146, 318, 397)):
                coords = canvas.coords(item)
                if len(coords) == 4:
                    canvas.coords(item, 56, y * scale + offset, 108, y * scale + offset)
                else:
                    canvas.coords(item, 52 if y == 146 else 56, y * scale + offset)
        canvas.bind('<Configure>', resized)
        note = ttk.Frame(page, padding=(32, 18))
        note.pack(fill='x')
        ttk.Label(note, text=self.t('home_note'), font=(self.serif, 15)).pack(anchor='w')
        help_text = ttk.Label(note, text=self.t('home_help'), style='Muted.TLabel', wraplength=1080)
        help_text.pack(anchor='w', pady=(5, 0))
        note.bind('<Configure>', lambda event: help_text.configure(wraplength=max(400, event.width - 64)))

    def load_art(self):
        """Local presentation asset, with the user's dump as a fallback; no network at startup."""
        self.banner = getattr(self, 'banner', None)
        if getattr(self, 'art_loaded', False):
            return
        self.art_loaded = True
        icon = tlg_run.PORT_DIR / 'launcher' / 'tlg.png'
        try:
            if icon.is_file():
                self.icon = tk.PhotoImage(file=str(icon))
                self.root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        picture = tlg_run.PORT_DIR / 'launcher' / 'assets' / 'guardian-hero.png'
        if not picture.is_file():
            picture = art_path(self.settings, 'pic1.png') or art_path(self.settings, 'pic0.png')
        if picture:
            try:
                self.banner = tk.PhotoImage(file=str(picture))
            except tk.TclError:
                self.banner = None

    def build_filters(self, parent, row):
        """SMAA, sharpening and color adjustments, read from and written to tlg.ini right away."""
        ttk.Separator(parent).grid(row=row, column=0, columnspan=2, sticky='ew', pady=(8, 4))
        ttk.Label(parent, text=self.t('filters'), style='Card.TLabel',
                  foreground=self.colors['muted'], wraplength=360).grid(
            row=row + 1, column=0, columnspan=2, sticky='w')
        ini = dict(INI_DEFAULTS)
        ini.update({k: v for k, v in tlg_run.read_ini(tlg_run.USER_DIR / 'tlg.ini').items() if k in ini})
        self.ini_vars = {}
        for offset, key in ((2, 'smaa'), (4, 'color_adjust')):
            var = tk.BooleanVar(value=ini[key] not in ('0', ''))
            self.ini_vars[key] = var
            ttk.Checkbutton(parent, text=self.t(key), variable=var, command=self.filters_changed).grid(
                row=row + offset, column=0, columnspan=2, sticky='w', pady=2)
        ttk.Label(parent, text=self.t('sharpening'), style='Card.TLabel').grid(row=row + 3, column=0, sticky='w')
        self.sharpener = ttk.Combobox(parent, values=[self.t('sharpen_' + k) for k in SHARPENERS],
                                      state='readonly', width=16)
        self.sharpener.current(2 if ini['cas'] not in ('0', '') else 1 if ini['rcas'] not in ('0', '') else 0)
        self.sharpener.grid(row=row + 3, column=1, sticky='w', padx=6, pady=2)
        self.sharpener.bind('<<ComboboxSelected>>', lambda _: self.filters_changed())
        for index, key in enumerate(COLOR_RANGES):
            low, high = COLOR_RANGES[key]
            ttk.Label(parent, text=self.t(key), style='Card.TLabel', wraplength=230).grid(
                row=row + 5 + index, column=0, sticky='w', padx=(16, 0))
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
        ttk.Label(parent, text=self.t(key), style='Card.TLabel', wraplength=185).grid(
            row=row, column=0, sticky='w', pady=8)
        names = [label(v) for v in values]
        box = ttk.Combobox(parent, values=names, state='readonly', width=22)
        current = self.settings.get(key, values[0])
        box.current(values.index(current) if current in values else 0)
        box.grid(row=row, column=1, sticky='ew', padx=(12, 0), pady=8)

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
        ttk.Label(parent, text=self.t('game_language'), style='Card.TLabel', wraplength=185).grid(
            row=0, column=0, sticky='w', pady=8)
        self.game_lang_box = ttk.Combobox(parent, state='readonly', width=22)
        self.game_lang_box.grid(row=0, column=1, sticky='ew', padx=(12, 0), pady=8)
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
        win.configure(background=self.colors['paper'])
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
            ttk.Label(frame, text=tlg_run.DEFAULT_KEYS[button], foreground=self.colors['muted']).grid(
                row=row, column=column + 3, sticky='w', padx=(0, 18))
        ttk.Label(frame, text=self.t('remap_help'), foreground=self.colors['muted'], wraplength=760, justify='left').grid(
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

    def mods_dialog(self):
        """Mods/cheats (shadPS4/GoldHEN XML in tlg_run.mods_dir()); toggles write mods.json
        through tlg_run.set_mod_enabled. Nothing here is on unless the player turns it on."""
        if getattr(self, 'mods_window', None) and self.mods_window.winfo_exists():
            self.mods_window.lift()
            return
        win = self.mods_window = tk.Toplevel(self.root)
        win.configure(background=self.colors['paper'])
        win.title(self.t('mods_title'))
        win.transient(self.root)
        win.minsize(560, 360)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=self.t('mods_hint'), wraplength=520, justify='left').pack(anchor='w')
        ttk.Label(frame, text=self.t('mods_warning'), foreground='#a33', wraplength=520, justify='left').pack(
            anchor='w', pady=(4, 8))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill='both', expand=True)
        canvas = tk.Canvas(list_frame, background=self.colors['paper'], highlightthickness=0)
        scroll = ttk.Scrollbar(list_frame, orient='vertical', command=canvas.yview)
        rows = ttk.Frame(canvas)
        rows.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=rows, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        def toggle(key, var):
            tlg_run.set_mod_enabled(key, var.get())

        def populate():
            for child in rows.winfo_children():
                child.destroy()
            try:
                mods = tlg_run.list_mods(self.settings)
            except Exception as error:  # a malformed XML file is reported, never crashes the launcher
                mods = []
                ttk.Label(rows, text=str(error), foreground='#a33').pack(anchor='w')
            if not mods:
                ttk.Label(rows, text=self.t('mods_empty'), foreground=self.colors['muted']).pack(anchor='w', pady=8)
            for key, name, note, enabled in mods:
                row = ttk.Frame(rows)
                row.pack(fill='x', anchor='w', pady=2)
                var = tk.BooleanVar(value=enabled)
                ttk.Checkbutton(row, text=name or key, variable=var,
                                command=lambda k=key, v=var: toggle(k, v)).pack(anchor='w')
                if note:
                    ttk.Label(row, text=note, foreground=self.colors['muted'], wraplength=480, justify='left').pack(
                        anchor='w', padx=(22, 0))
        populate()

        bottom = ttk.Frame(frame)
        bottom.pack(fill='x', pady=(10, 0))
        ttk.Button(bottom, text=self.t('mods_folder'), command=lambda: self.open(tlg_run.mods_dir())).pack(side='left')
        ttk.Button(bottom, text=self.t('mods_refresh'), command=populate).pack(side='left', padx=6)
        ttk.Button(bottom, text=self.t('close'), command=win.destroy).pack(side='right')

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
