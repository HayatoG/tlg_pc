#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare and run The Last Guardian (CUSA03627 v1.03) through the native loader.

Shared by the command line (run_tlg.sh -> `tlg_run.py [seconds]`) and the launcher window
(tlg_launcher.py), so both start the game the same way:
  1. prepare.py / link_modules.py / content_profile.py build out/boot-linked.bin from the game
     folder (eboot 1.03 + the game's libc/Fios2, and libSceNgs2.sprx from the console firmware
     when present: native audio; otherwise the built-in mixer, runtime_ngs2.c); on a CPU without
     the PS4's MOVBE/BMI1/LZCNT/SSE4A, and on Windows for the red-zone protection, isa_rewrite.py
     writes out/isa-rewrite.bin, the instruction sites tlg-probe rewrites;
  2. the TLG defaults below become TLG_* environment variables (each one validated in play);
  3. tlg-probe runs with its output in out/logs/run-<date>.log (last_run.log points to it).
"""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import backports_table
import logtail
import shader_cache
import userdata

# A packaged build (PyInstaller) keeps its folders next to the executable: scripts/, out/, user/.
FROZEN = bool(getattr(sys, 'frozen', False))
PORT_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PORT_DIR / 'scripts'))
import mod_patches  # noqa: E402
REPO_DIR = PORT_DIR.parent
OUT_DIR = PORT_DIR / 'out'


def user_dir():
    """The folder of saves, tlg.ini, mods, backups and GPU caches: TLG_USER_DIR, else the per-user
    pointer file (survives reinstalling; the Qt launcher's Saves screen sets it), else
    <port folder>/user (userdata.py has the rules). Always call this instead of caching it."""
    return userdata.user_dir(PORT_DIR)


def __getattr__(name):  # USER_DIR (the Tk launcher, older code) is the current folder
    if name == 'USER_DIR':
        return user_dir()
    raise AttributeError(name)


LOG_DIR = OUT_DIR / 'logs'
PROBE = OUT_DIR / ('tlg-probe.exe' if os.name == 'nt' else 'tlg-probe')
KEEP_LOGS = 30

# Game language: the engine's own ids (NOT the PS4 system ones), looked up through
# sceSystemServiceParamGetInt(LANG). Each CUSA ships a subset of them; an id it does not ship
# falls back to English (1). Tables swept from the loaded trico_<lang>.psarc.
LANGUAGES_US = {'en': 1, 'pt_BR': 17, 'es_LA': 20, 'fr_CA': 22}
LANGUAGES_EU = {'en': 1, 'fr': 2, 'es_ES': 3, 'de': 4, 'it': 5, 'nl': 6, 'pt_PT': 7, 'ru': 8,
                'fi': 12, 'sv': 13, 'da': 14, 'no': 15, 'pl': 16, 'tr': 19, 'ar': 21}
LANGUAGES_BY_TITLE = {'CUSA03627': LANGUAGES_US, 'CUSA03745': LANGUAGES_EU}
DEFAULT_LANGUAGE_BY_TITLE = {'CUSA03627': 'es_LA', 'CUSA03745': 'es_ES'}


def game_languages(game_dir=''):
    """The language table (engine ids) the CUSA in game_dir ships; the US one when it is unknown."""
    title = shader_cache.title_id(game_dir) if game_dir else None
    return LANGUAGES_BY_TITLE.get(title, LANGUAGES_US)


def default_language(game_dir=''):
    """The game language the launcher starts with for the CUSA in game_dir (US by default)."""
    title = shader_cache.title_id(game_dir) if game_dir else None
    return DEFAULT_LANGUAGE_BY_TITLE.get(title, 'es_LA')


# Every language key either disc has (the Qt launcher's names table covers them all).
GAME_LANGUAGES = {**LANGUAGES_US, **LANGUAGES_EU}
# The closest choice when the system's language is missing from the disc.
_LANGUAGE_SIBLING = {'pt_BR': 'pt_PT', 'pt_PT': 'pt_BR', 'es_LA': 'es_ES', 'es_ES': 'es_LA',
                     'fr_CA': 'fr', 'fr': 'fr_CA'}
_LANGUAGE_PREFIX = {'en': 'en', 'pt': 'pt_BR', 'es': 'es_LA', 'fr': 'fr', 'de': 'de', 'it': 'it', 'nl': 'nl',
                    'pl': 'pl', 'tr': 'tr', 'ru': 'ru', 'fi': 'fi', 'sv': 'sv', 'da': 'da', 'no': 'no', 'nb': 'no',
                    'nn': 'no', 'ar': 'ar'}


def system_game_language(environ=None):
    """The game language that follows the system one (LC_ALL, LC_MESSAGES, LANG, then the locale):
    pt_PT/pt_BR, es_ES/es_LA and fr_CA/fr by region; English when this game has no such language."""
    environ = os.environ if environ is None else environ
    code = next((environ[name] for name in ('LC_ALL', 'LC_MESSAGES', 'LANG') if environ.get(name)), '')
    if not code:
        try:
            import locale
            code = locale.getlocale()[0] or ''
        except Exception:
            code = ''
    parts = re.split(r'[_\-.@]', code.strip().lower())
    windows = {'english': 'en', 'portuguese': 'pt', 'spanish': 'es', 'french': 'fr', 'german': 'de',
               'italian': 'it', 'dutch': 'nl', 'polish': 'pl', 'turkish': 'tr', 'russian': 'ru'}
    language = windows.get(parts[0], parts[0])
    region = parts[1] if len(parts) > 1 else ''
    if language == 'pt':
        return 'pt_PT' if region in ('pt', 'portugal') else 'pt_BR'
    if language == 'es':
        return 'es_ES' if region in ('es', 'spain') else 'es_LA'
    if language == 'fr':
        return 'fr_CA' if region in ('ca', 'canada') else 'fr'
    return _LANGUAGE_PREFIX.get(language, 'en')


def game_language_choices(settings):
    """The game language box of the Qt launcher: 'auto', the languages the disc has and the saved
    choice even when the disc lacks it (never changed behind the player's back)."""
    keys = ['auto'] + list(game_languages(settings.get('game_dir', '')))
    choice = settings.get('game_language', 'auto')
    return keys + [choice] if choice in GAME_LANGUAGES and choice not in keys else keys


def resolve_game_language(settings, environ=None):
    """The language key the game gets: the saved choice when the disc has it; 'auto' follows the
    system (or its closest variant); anything else is English, as before."""
    table = game_languages(settings.get('game_dir', ''))
    choice = settings.get('game_language', 'auto')
    if choice in table:
        return choice
    if choice == 'auto':
        system = system_game_language(environ)
        for key in (system, _LANGUAGE_SIBLING.get(system)):
            if key in table:
                return key
    return 'en'

# TLG defaults (see README "Opções" and the reasons in each comment).
DEFAULT_ENV = {
    'TLG_PIPELINE_BINARIES': '0',  # VK_KHR_pipeline_binary crashes on the NVIDIA 595 driver
    'TLG_READBACKS': '2',          # the game reads GPU compute results on the CPU (AsyncMap)
    'TLG_READBACK_LINEAR': '1',    # small/linear render targets back to the CPU: auto exposure (#38, #40)
    'TLG_GC_BUDGET_MB': '5600',    # texture cache budget for 6 GB of VRAM
    'TLG_UPSCALER': 'off',         # native image: GoW3's temporal upscalers made it shake
    'TLG_JITTER': '0',
    'TLG_OBJECT_MOTION': '0',
    'TLG_FRAME_STATS': '1',        # FPS in the log every 5 s (scripts/watch_session.sh heartbeat)
}

DEFAULT_SETTINGS = {
    # Source tree: the merged game view and the console modules of ~/decomp. Package: the player
    # picks the game folder; libSceNgs2.sprx goes in system_lib/ next to the executable.
    'game_dir': '' if FROZEN else str(REPO_DIR / 'game' / 'CUSA03627'),
    'system_lib_dir': str(PORT_DIR / 'system_lib') if FROZEN else str(REPO_DIR / 'dump' / 'system_lib'),
    'game_language': 'pt_BR',
    'ui_language': 'auto',         # auto | pt_BR | en_US
    'show_fps': False,
    'display_mode': 'Windowed',    # Windowed | Borderless | Fullscreen (tlg.ini)
    'vsync': True,
    'vram_budget_mb': 5600,
    'native_audio': True,
    # Mouse and keyboard (tlg.ini; the in-game menu's Controls tab changes the mouse ones too).
    'mouse_enabled': True,
    'mouse_sensitivity': 1.0,
    'mouse_invert_y': False,
    'key_map': {},                 # PS4 button -> 'Key|Mouse Left' (empty: the default)
    'frame_rate': '30',            # 30 | 60 | unlocked (scripts/tlg_patches.py; TLG_FPS wins)
    'gpu_readbacks': '2',          # TLG_READBACKS: 2 precise (the game reads GPU compute results), 0 fast
    'stick_deadzone': 10,          # percent; runtime_pad.c TLG_STICK_DEADZONE
    'close_on_play': True,         # Qt launcher: close about 2 s after the game starts
    'reopen_launcher': True,       # ... and open again when the game exits
}
FRAME_RATES = ['30', '60', 'unlocked']
# The frame rate mode prepare() really applied (another eboot build stays at 30).
applied_frame_rate = '30'

# Keyboard and mouse defaults of src/runtime_pad.c, in its key_map syntax ('|': several).
DEFAULT_KEYS = {
    'cross': 'Space', 'circle': 'Left Shift', 'square': 'E|Mouse Middle', 'triangle': 'Q|Mouse Left',
    'l1': '1', 'r1': '3|Mouse Right', 'l2': 'R', 'r2': 'F', 'l3': 'Z', 'r3': 'C', 'options': 'Return',
    'touchpad_left': 'Tab', 'touchpad_right': 'Backspace', 'up': 'I', 'down': 'K', 'left': 'J', 'right': 'L',
}
# Synced with tlg.ini both ways: the in-game menu saves them there.
INI_KEYS = ('mouse_enabled', 'mouse_sensitivity', 'mouse_invert_y', 'key_map')


def key_map_spec(mapping):
    """The tlg.ini key_map value: only the buttons that differ from the defaults."""
    return ','.join(f'{button}={value.strip()}' for button, value in mapping.items()
                    if button in DEFAULT_KEYS and value.strip() and value.strip() != DEFAULT_KEYS[button])


def parse_key_map(spec):
    mapping = {}
    for entry in (spec or '').split(','):
        button, eq, value = entry.partition('=')
        if eq and button.strip().lower() in DEFAULT_KEYS:
            mapping[button.strip().lower()] = value.strip()
    return mapping


def read_ini(path):
    values = {}
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            key, eq, value = line.partition('=')
            if eq and not key.startswith('#'):
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def config_path():
    base = Path(os.environ.get('APPDATA') or os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'tlg-launcher' / 'settings.json'


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        settings.update(json.loads(config_path().read_text(encoding='utf-8')))
    except (OSError, ValueError):
        pass
    # The in-game menu may have changed the mouse since: tlg.ini wins for those keys.
    ini = read_ini(user_dir() / 'tlg.ini')
    try:
        if 'mouse_enabled' in ini:
            settings['mouse_enabled'] = ini['mouse_enabled'] != '0'
        if 'mouse_invert_y' in ini:
            settings['mouse_invert_y'] = ini['mouse_invert_y'] != '0'
        if 'mouse_sensitivity' in ini:
            settings['mouse_sensitivity'] = min(5.0, max(0.1, float(ini['mouse_sensitivity'])))
    except ValueError:
        pass
    if 'key_map' in ini:
        settings['key_map'] = parse_key_map(ini['key_map'])
    return settings


def save_settings(settings):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


# Messages about the player's game folder (en, pt) the Qt launcher can show; none blocks only as a
# warning in this port (check_game reports missing files and the unbuilt probe).
TEXT = {}
WARNINGS = set()


def message(key, portuguese=None, **fmt):
    en, pt = TEXT[key]
    if portuguese is None:
        return f'{pt.format(**fmt)}\n{en.format(**fmt)}'
    return (pt if portuguese else en).format(**fmt)


class GameError(RuntimeError):
    """A problem with the player's game files (TEXT key + detail)."""

    def __init__(self, key, detail):
        super().__init__(f'{key}: {detail}')
        self.key, self.detail = key, detail


def blocking(problems):
    """The problems of check_game that keep Play disabled (all but the warnings)."""
    return [problem for problem in problems if problem[0] not in WARNINGS]


def experimental_states(settings):
    """The player's choices of the Qt launcher's Graphics/Fixes switches (tlg.ini + settings)."""
    return backports_table.read_states(read_ini(user_dir() / 'tlg.ini'), settings)


def save_experimental(settings, states):
    """Writes the switches: tlg.ini keys (the in-game menu's own file) and the start-up switches
    kept in settings.json."""
    user_dir().mkdir(parents=True, exist_ok=True)
    backports_table.write_ini(user_dir() / 'tlg.ini', backports_table.ini_updates(states))
    for item in backports_table.ITEMS:
        if item.store == 'launcher':
            settings[item.key] = backports_table.effective(item, states) != '0'
    save_settings(settings)


def check_game(game_dir):
    """Problems that keep the game from starting, as (key, detail) pairs; empty means ready."""
    game = Path(game_dir)
    problems = []
    if not (game / 'eboot.bin').is_file():
        problems.append(('missing', 'eboot.bin'))
    for module in ('libc.prx', 'libSceFios2.prx'):
        if not (game / 'sce_module' / module).is_file():
            problems.append(('missing', f'sce_module/{module}'))
    for archive in ('trico_boot.psarc', 'trico_001.psarc', 'trico_002.psarc', 'trico_003.psarc'):
        if not (game / archive).is_file():
            problems.append(('missing', archive))
    if not PROBE.is_file():
        problems.append(('not_built', str(PROBE)))
    return problems


def ngs2_module(settings):
    path = Path(settings['system_lib_dir']) / 'libSceNgs2.sprx'
    return path if settings.get('native_audio', True) and path.is_file() else None


def read_ini(path):
    """The key=value pairs of tlg.ini (empty when the file does not exist yet)."""
    values = {}
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def update_ini(path, values):
    """Sets keys in tlg.ini (the in-game menu's file), keeping every other line."""
    lines = path.read_text(encoding='utf-8').splitlines() if path.is_file() else ['# tlg settings']
    seen = set()
    for i, line in enumerate(lines):
        key = line.split('=', 1)[0].strip()
        if key in values:
            lines[i] = f'{key}={values[key]}'
            seen.add(key)
    lines += [f'{k}={v}' for k, v in values.items() if k not in seen]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


# The serial the GPU backend names this game's shader cache after (another region's copy: its
# param.sfo TITLE_ID, read from the game folder).
SHADER_CACHE_SERIALS = ('CUSA03627',)


def shader_cache_serials(settings):
    serial = shader_cache.title_id(settings['game_dir']) if settings.get('game_dir') else None
    return sorted({*SHADER_CACHE_SERIALS, *([serial] if serial else [])})


def gpu_user_dir():
    """Where the GPU backend keeps its caches (shaders, pipelines): the saves folder, on every OS.
    TLG_GPU_USER_DIR moves it."""
    return Path(os.environ.get('TLG_GPU_USER_DIR') or user_dir())


def shader_cache_size(settings):
    """Bytes of compiled shaders this game has on disk (launcher/shader_cache.py has the paths)."""
    return shader_cache.size(shader_cache_serials(settings), gpu_user_dir())


def clear_shader_cache(settings):
    """Deletes this game's compiled shaders: the next start rebuilds them (longer load, some
    stutter at first). Saves, settings and logs stay. Returns (bytes freed, [(path, error)])."""
    return shader_cache.clear(shader_cache_serials(settings), gpu_user_dir())


def python_command(script):
    """How to run one of scripts/*.py: the packaged executable runs them itself (--script)."""
    if FROZEN:
        return [sys.executable, '--script', str(script)]
    return [sys.executable, str(script)]


def attach_stdio():
    """A windowed Windows executable starts without sys.stdout; inherited pipes still exist."""
    if os.name != 'nt':
        return
    import ctypes
    import msvcrt
    for name, std in (('stdout', -11), ('stderr', -12)):
        if getattr(sys, name) is not None:
            continue
        stream = None
        handle = ctypes.windll.kernel32.GetStdHandle(std)
        if handle and handle != ctypes.c_void_p(-1).value:
            try:
                stream = open(msvcrt.open_osfhandle(handle, os.O_WRONLY), 'w', encoding='utf-8',
                              errors='replace', buffering=1)
            except OSError:
                stream = None
        setattr(sys, name, stream or open(os.devnull, 'w'))


NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)  # no console flashing for the scripts


def run_script(argv):
    """--script <path> [args]: runs a preparation script inside the packaged executable."""
    import runpy
    attach_stdio()
    script = Path(argv[0])
    sys.argv = [str(script), *argv[1:]]
    sys.path.insert(0, str(script.parent))
    try:
        runpy.run_path(str(script), run_name='__main__')
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    except Exception as error:  # noqa: BLE001  never PyInstaller's "unhandled exception" dialog
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(f'{script.name}: {error}', file=sys.stderr, flush=True)  # last line: the reason
        return 1
    return 0


def frame_rate(settings):
    """The requested frame rate mode: TLG_FPS, else the launcher's setting."""
    return os.environ.get('TLG_FPS') or str(settings.get('frame_rate', '30'))


def mods_dir():
    """TLG_MODS_DIR, else user_dir()/mods (created empty on first use so the player sees where
    to drop shadPS4/GoldHEN cheat XML files)."""
    directory = Path(os.environ.get('TLG_MODS_DIR') or user_dir() / 'mods')
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def mods_config():
    return Path(os.environ.get('TLG_MODS_CONFIG') or user_dir() / 'mods.json')


def list_mods(settings):
    """[(key, name, note, enabled)] for the Mods tab: every shadPS4/GoldHEN cheat XML found in
    the mods folder for this game's version, with its current enabled state (the file's own
    isEnabled, unless mods.json overrides it). An untouched mods folder lists nothing selected."""
    from tlg_patches import TITLE_IDS
    app_version = mod_patches.game_app_version(settings['game_dir'])
    found = mod_patches.external_patches(mods_dir(), app_version, TITLE_IDS)
    selected = {key for key, _, _ in mod_patches.external_selection(found, mods_config())}
    return [(key, meta.get('Name'), meta.get('Note', ''), key in selected) for key, _, meta in found]


def set_mod_enabled(key, enabled):
    """Updates mods.json: moves key into enabled/disabled, out of the other list."""
    path = mods_config()
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    on, off = set(data.get('enabled', [])), set(data.get('disabled', []))
    (on if enabled else off).add(key)
    (off if enabled else on).discard(key)
    path.write_text(json.dumps({'enabled': sorted(on), 'disabled': sorted(off)}, indent=2))


def prepare(settings, log=print):
    """Builds out/boot-linked.bin, out/content.bin and out/patches.bin (frame rate patches and
    any enabled mod); returns the module list that was linked."""
    global applied_frame_rate
    game = settings['game_dir']
    scripts = PORT_DIR / 'scripts'
    modules = ['libc.prx', 'libSceFios2.prx']
    ngs2 = ngs2_module(settings)
    if ngs2:
        modules.append(str(ngs2))
    steps = [
        [*python_command(scripts / 'prepare.py'), game, '--out', str(OUT_DIR)],
        [*python_command(scripts / 'link_modules.py'), game, '--out', str(OUT_DIR), '--modules', *modules],
        [*python_command(scripts / 'content_profile.py'), game, '--out', str(OUT_DIR)],
        [*python_command(scripts / 'tlg_patches.py'), game, '--out', str(OUT_DIR), '--mode', frame_rate(settings),
         '--mods-dir', str(mods_dir()), '--mods-config', str(mods_config())],
    ]
    for step in steps:
        result = subprocess.run(step, cwd=str(scripts), capture_output=True, text=True,
                                creationflags=NO_WINDOW)
        if result.returncode:
            name = next(Path(arg).name for arg in step if arg.endswith('.py'))
            raise RuntimeError(f'{name}: {result.stderr.strip() or result.stdout.strip()}')
        for line in result.stdout.splitlines():
            log(line)
            if line.startswith('Frame rate: ') and line.endswith(' patch writes'):
                applied_frame_rate = line.split()[2]
    isa_table(log)
    return modules


ISA_TABLE = OUT_DIR / 'isa-rewrite.bin'


def probe_env():
    """The environment tlg-probe needs to start: on Linux the libraries packaged with the port
    (SDL3, FFmpeg, ...) live in out/lib, and the frozen launcher's own LD_LIBRARY_PATH (PyInstaller's
    _internal) is replaced by the one it had at start."""
    env = os.environ.copy()
    if os.name != 'nt':
        original = env.pop('LD_LIBRARY_PATH_ORIG', None) if FROZEN else env.get('LD_LIBRARY_PATH')
        bundled = OUT_DIR / 'lib'
        paths = [str(bundled)] if bundled.is_dir() else []
        if original:
            paths.append(original)
        if paths:
            env['LD_LIBRARY_PATH'] = os.pathsep.join(paths)
        else:
            env.pop('LD_LIBRARY_PATH', None)
    return env


def cpu_missing_sets(log=print):
    """Instruction sets `tlg-probe --cpu-features` reports missing ([] when complete); None when the
    probe could not tell (it did not start: the table is then built anyway, see isa_table). A CPU
    that lacks a set nothing can rewrite (AVX and older) stops here (exit 20) with the probe's reason.
    The probe gets the same library path as the game (out/lib in the Linux package)."""
    try:
        result = subprocess.run([str(PROBE), '--cpu-features'], stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=30, creationflags=NO_WINDOW, env=probe_env())
    except (OSError, subprocess.SubprocessError):
        return []  # no probe yet: check_game reports it
    if result.returncode == 20:
        raise RuntimeError(result.stdout.strip() or 'this CPU cannot run the game')
    for line in result.stdout.splitlines():
        if line.startswith('CPU: missing '):
            return [name.strip() for name in line[len('CPU: missing '):].split(',') if name.strip()]
        if line.startswith('CPU: complete'):
            return []
    detail = (result.stderr or result.stdout).strip().splitlines()
    log(f'CPU check failed (exit {result.returncode}): {detail[-1] if detail else "no output"}; '
        'building the instruction rewrite table anyway')
    return None


def red_zone_wanted(env=None):
    """Windows red-zone protection (scripts/red_zone.py, from iss_pc #29/#41): on by default on
    Windows, TLG_RED_ZONE_REWRITE=0 turns it off; on Linux only TLG_RED_ZONE_REWRITE=1 (tests)
    turns it on."""
    env = os.environ if env is None else env
    policy = env.get('TLG_RED_ZONE_REWRITE') or ''
    return policy != '0' if os.name == 'nt' else policy == '1'


def isa_table(log=print):
    """ps4_core ISA rewrite (upstream gow3_pc #129): on a CPU without MOVBE, BMI1, LZCNT or SSE4A
    the probe replaces those instructions in the image, from the table scripts/isa_rewrite.py
    writes (iced-x86). TLG_ISA_REWRITE=1 (every set) or a list such as TLG_ISA_REWRITE=sse4a builds
    it on any CPU (testing), =0 never. The same table carries the red-zone protection
    (red_zone_wanted), so on Windows it is always built; the script keeps a table that already
    matches the image. A failed table is reported and the probe then explains what is missing."""
    policy = os.environ.get('TLG_ISA_REWRITE') or ''
    red_zone = red_zone_wanted()
    if not red_zone:
        ISA_TABLE.unlink(missing_ok=True)  # always matches the boot-linked.bin just written
    missing = cpu_missing_sets(log)
    # None (unknown) builds it too: the probe only rewrites the sets this CPU really lacks.
    if not ((policy and policy != '0') or (policy != '0' and (missing is None or missing)) or red_zone):
        return
    scripts = PORT_DIR / 'scripts'
    result = subprocess.run([*python_command(scripts / 'isa_rewrite.py'), str(OUT_DIR / 'boot-linked.bin'),
                             '--out', str(OUT_DIR), *(['--red-zone'] if red_zone else [])], cwd=str(scripts),
                            capture_output=True, text=True, creationflags=NO_WINDOW)
    if result.returncode:
        ISA_TABLE.unlink(missing_ok=True)
    for line in (result.stdout + result.stderr).splitlines():
        log(line)


def window_icon():
    """The port's icon (launcher/tlg.png) as BMP, SDL's built-in format, in out/; None if absent."""
    source = PORT_DIR / 'launcher' / 'tlg.png'
    target = OUT_DIR / 'window_icon.bmp'
    try:
        if source.is_file() and (not target.is_file() or target.stat().st_mtime < source.stat().st_mtime):
            from PIL import Image  # optional: without Pillow the window keeps the default icon
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            Image.open(source).convert('RGB').resize((128, 128)).save(target)
        return target if target.is_file() else None
    except Exception:
        return None


def build_env(settings, extra=None):
    env = dict(os.environ)
    for key, value in DEFAULT_ENV.items():
        env.setdefault(key, value)  # explicit TLG_* in the environment always win
    env['TLG_GC_BUDGET_MB'] = os.environ.get('TLG_GC_BUDGET_MB', str(int(settings['vram_budget_mb'])))
    env['TLG_READBACKS'] = os.environ.get('TLG_READBACKS', str(settings.get('gpu_readbacks', '2')))
    env['TLG_STICK_DEADZONE'] = os.environ.get(
        'TLG_STICK_DEADZONE', f"{int(settings.get('stick_deadzone', 10)) / 100:.2f}")
    env['TLG_LANGUAGE'] = os.environ.get('TLG_LANGUAGE', str(
        game_languages(settings.get('game_dir')).get(resolve_game_language(settings), 1)))
    if settings.get('ui_language', 'auto') != 'auto':
        env['TLG_UI_LANG'] = settings['ui_language']
    # Without the console module the port's own mixer (runtime_ngs2.c) plays the audio.
    env['TLG_NGS2'] = 'native' if ngs2_module(settings) else 'hle'
    env['TLG_CONFIG'] = str(user_dir() / 'tlg.ini')
    # Window name and app id (matches tlg-pc.desktop for Alt+Tab and the dock) and icon.
    env.setdefault('TLG_APP_NAME', 'The Last Guardian')
    env.setdefault('TLG_APP_ID', 'tlg-pc')
    icon = window_icon()
    if icon:
        env.setdefault('TLG_WINDOW_ICON', str(icon))
    # The present limiter never lets more frames through than the patched engine rate; unlocked
    # flips as soon as a frame is ready (480 Hz vblank) up to the display refresh or the menu limit.
    env['TLG_ENGINE_FPS'] = {'30': '30', '60': '60'}.get(applied_frame_rate, '240')
    if applied_frame_rate == 'unlocked':
        env.setdefault('TLG_VBLANK_HZ', '0')
    restart = f'"{sys.executable}" --play' if FROZEN else f'"{sys.executable}" "{Path(__file__).resolve()}"'
    env.setdefault('TLG_RESTART_COMMAND', restart)
    # Linux package: the libraries built with the port (SDL3, FFmpeg, ...) are in out/lib, never the
    # frozen launcher's own (PyInstaller's _internal).
    if os.name != 'nt':
        libraries = probe_env().get('LD_LIBRARY_PATH')
        if libraries:
            env['LD_LIBRARY_PATH'] = libraries
        else:
            env.pop('LD_LIBRARY_PATH', None)
    # Shaders and pipelines beside the saves (the GPU reads it when it starts; before, Linux used
    # shadPS4's ~/.local/share/shadPS4 and Windows <saves>/user).
    env['TLG_GPU_USER_DIR'] = str(gpu_user_dir())
    # Start-up switches the player changed in the Qt launcher (TLG_<name>=0/1); untouched ones add
    # nothing, and TLG_* set outside the launcher win.
    env.update(backports_table.environment(experimental_states(settings), os.environ))
    if extra:
        env.update(extra)
    return env


def new_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f'run-{datetime.datetime.now():%Y%m%d-%H%M%S}.log'
    latest = OUT_DIR / 'last_run.log'
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(log)
    except OSError:
        pass
    for old in sorted(LOG_DIR.glob('run-*.log'), reverse=True)[KEEP_LOGS:]:
        old.unlink(missing_ok=True)
    return log


def desktop_env():
    """Environment for the programs the launcher opens for the player (browser, file manager): never
    the frozen launcher's LD_LIBRARY_PATH (a browser started with it loads PyInstaller's libraries
    and dies silently)."""
    env = os.environ.copy()
    if os.name != 'nt' and FROZEN:
        original = env.pop('LD_LIBRARY_PATH_ORIG', None)
        if original:
            env['LD_LIBRARY_PATH'] = original
        else:
            env.pop('LD_LIBRARY_PATH', None)
    return env


def open_external(target):
    """Opens a URL or a local path with the system's handler, detached from the launcher.
    Returns True when a handler was started."""
    target = str(target)
    try:
        if os.name == 'nt':
            os.startfile(target)  # noqa: S606 (the player's own link or folder)
            return True
        opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
        subprocess.Popen([opener, target], env=desktop_env(), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        try:
            import webbrowser
            return bool(webbrowser.open(target))
        except Exception:
            return False


def detach_options():
    """Popen options that make the game an independent process: closing the launcher (or its
    terminal) does not reach it. Linux: its own session. Windows: its own process group, no console."""
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    return {'start_new_session': True}


def wait_for_exit(pid):
    """Blocks until process pid ends (no window, no Qt: a closed launcher's watcher)."""
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
        if handle:
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
            kernel.CloseHandle(handle)
        return
    while True:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        try:   # a zombie (exited, not yet reaped) counts as ended
            if Path(f'/proc/{int(pid)}/stat').read_text().split(') ', 1)[1][:1] == 'Z':
                return
        except (OSError, IndexError):
            pass
        time.sleep(1.0)


def reopen_after(pid):
    """Starts a detached watcher that opens the Qt launcher again once the game (pid) exits."""
    if FROZEN:
        cmd = [sys.executable, '--reopen-after', str(pid)]
    else:
        cmd = [sys.executable, str(Path(__file__).resolve().parent / 'tlg_launcher_qt.py'),
               '--reopen-after', str(pid)]
    try:
        subprocess.Popen(cmd, env=desktop_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **detach_options())
        return True
    except OSError:
        return False


def raise_open_file_limit():
    """Linux: lifts the open-file limit to its hard maximum; the game inherits it. A desktop session
    starts programs with a soft limit of 1024 (systemd DefaultLimitNOFILESoft), which the GPU code can
    pass while it loads the pipeline cache (iss_pc 2cbcb28: SDL then failed to create the window)."""
    if os.name == 'nt':
        return
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard != resource.RLIM_INFINITY and soft < hard:
            resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
    except (ImportError, OSError, ValueError):
        pass


def launch(settings, seconds=0, extra_env=None, detached=False, header=()):
    """Writes the in-game settings, starts the game; returns (process, log path).
    The game always writes straight into the log file (after the header lines): a pipe that only
    the launcher reads stalls the game once its buffer fills and the launcher is gone. Follow the
    file with logtail.LogTail and wait() for the exit code. detached=True (Qt launcher): the game
    also runs in its own session, so closing the launcher never reaches it."""
    data = user_dir()
    data.mkdir(parents=True, exist_ok=True)
    key_map = settings.get('key_map') or {}
    update_ini(data / 'tlg.ini', {
        'display_mode': str(settings['display_mode']).lower(),  # the game's keys: windowed|borderless|fullscreen
        'vsync': int(bool(settings['vsync'])),
        'show_fps': int(bool(settings['show_fps'])),
        'mouse_enabled': int(bool(settings.get('mouse_enabled', True))),
        'mouse_sensitivity': f"{float(settings.get('mouse_sensitivity', 1.0)):.2f}",
        'mouse_invert_y': int(bool(settings.get('mouse_invert_y', False))),
        'key_map': key_map_spec(key_map) if isinstance(key_map, dict) else str(key_map),
    })
    log = new_log()
    try:   # saves copied aside before every start; never blocks the game
        import savemanager
        note = savemanager.backup_before_play(data)
    except Exception as error:  # noqa: BLE001
        note = f'Save backup failed, starting anyway: {error}'
    if note:
        print(note, flush=True)
    cmd = [str(PROBE), str(OUT_DIR / 'boot-linked.bin'), '--app0', settings['game_dir'],
           '--user', str(data), '--content-profile', str(OUT_DIR / 'content.bin'),
           '--patches', str(OUT_DIR / 'patches.bin'), '--timeout', str(int(seconds))]
    if ISA_TABLE.is_file():
        cmd += ['--isa-rewrite', str(ISA_TABLE)]
    raise_open_file_limit()
    with open(log, 'wb') as out:   # the child keeps its own copy of the descriptor
        out.write(''.join(line + '\n' for line in header).encode('utf-8'))
        out.flush()
        process = subprocess.Popen(cmd, cwd=str(data), env=build_env(settings, extra_env),
                                   stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                   **(detach_options() if detached else {}))
    return process, log


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    attach_stdio()
    seconds = int(argv[0]) if argv and argv[0].isdigit() else 0
    settings = load_settings()
    if os.environ.get('TLG_GAME_DIR'):
        settings['game_dir'] = os.environ['TLG_GAME_DIR']
    if argv[:1] == ['--clear-shader-cache']:
        freed, failures = clear_shader_cache(settings)
        print(f'Cache de shaders: {shader_cache.human_size(freed)} liberados', flush=True)
        for path, error in failures:
            print(f'Não apagado (em uso? feche o jogo): {path}: {error}', file=sys.stderr)
        return 1 if failures else 0
    if os.environ.get('TLG_NGS2') == 'hle':
        settings['native_audio'] = False
    problems = check_game(settings['game_dir'])
    for kind, detail in problems:
        print(f'{"Compile primeiro / Build first" if kind == "not_built" else "Faltando / Missing"}: {detail}',
              file=sys.stderr)
    if blocking(problems):
        return 1
    notes = []
    prepare(settings, log=lambda line: notes.append(line) if line.startswith('Frame rate') else None)
    process, log = launch(settings, seconds, header=notes)
    print(f'Rodando (log: {log})', flush=True)
    tail = logtail.LogTail(log)
    while True:   # echo only: the game never waits for this loop or the console
        done = process.poll() is not None
        try:
            for line in tail.poll(final=done):
                print(line, flush=True)
        except (OSError, ValueError):
            pass
        if done:
            return process.returncode
        time.sleep(0.2)


if __name__ == '__main__':
    sys.exit(main())
