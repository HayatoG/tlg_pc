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
import subprocess
import sys

import shader_cache

# A packaged build (PyInstaller) keeps its folders next to the executable: scripts/, out/, user/.
FROZEN = bool(getattr(sys, 'frozen', False))
PORT_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
REPO_DIR = PORT_DIR.parent
OUT_DIR = PORT_DIR / 'out'
USER_DIR = PORT_DIR / 'user'
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
    ini = read_ini(USER_DIR / 'tlg.ini')
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
    return Path(os.environ.get('TLG_GPU_USER_DIR') or USER_DIR)


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
    return 0


def frame_rate(settings):
    """The requested frame rate mode: TLG_FPS, else the launcher's setting."""
    return os.environ.get('TLG_FPS') or str(settings.get('frame_rate', '30'))


def prepare(settings, log=print):
    """Builds out/boot-linked.bin, out/content.bin and out/patches.bin (frame rate patches);
    returns the module list that was linked."""
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
        [*python_command(scripts / 'tlg_patches.py'), game, '--out', str(OUT_DIR), '--mode', frame_rate(settings)],
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


def cpu_missing_sets(log=print):
    """Instruction sets `tlg-probe --cpu-features` reports missing ([] when complete); None when the
    probe could not tell (it did not start: the table is then built anyway, see isa_table). A CPU
    that lacks a set nothing can rewrite (AVX and older) stops here (exit 20) with the probe's reason.
    The probe gets the same library path as the game (out/lib in the Linux package)."""
    env = os.environ.copy()
    bundled = OUT_DIR / 'lib'
    if os.name != 'nt' and bundled.is_dir():
        env['LD_LIBRARY_PATH'] = os.pathsep.join(filter(None, [str(bundled), os.environ.get('LD_LIBRARY_PATH')]))
    try:
        result = subprocess.run([str(PROBE), '--cpu-features'], stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=30, creationflags=NO_WINDOW, env=env)
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
    env['TLG_LANGUAGE'] = os.environ.get('TLG_LANGUAGE', str(
        game_languages(settings.get('game_dir')).get(settings['game_language'], 1)))
    if settings.get('ui_language', 'auto') != 'auto':
        env['TLG_UI_LANG'] = settings['ui_language']
    # Without the console module the port's own mixer (runtime_ngs2.c) plays the audio.
    env['TLG_NGS2'] = 'native' if ngs2_module(settings) else 'hle'
    env['TLG_CONFIG'] = str(USER_DIR / 'tlg.ini')
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
    # Linux package: the libraries built with the port (SDL3, FFmpeg, ...) are in out/lib.
    bundled = OUT_DIR / 'lib'
    if os.name != 'nt' and bundled.is_dir():
        env['LD_LIBRARY_PATH'] = os.pathsep.join(filter(None, [str(bundled), os.environ.get('LD_LIBRARY_PATH')]))
    # Shaders and pipelines beside the saves (the GPU reads it when it starts; before, Linux used
    # shadPS4's ~/.local/share/shadPS4 and Windows <saves>/user).
    env['TLG_GPU_USER_DIR'] = str(gpu_user_dir())
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


def launch(settings, seconds=0, extra_env=None):
    """Writes the in-game settings, starts the game; returns (process, log path).
    The process's combined output is a text pipe; the caller copies it to the log."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    update_ini(USER_DIR / 'tlg.ini', {
        'display_mode': str(settings['display_mode']).lower(),  # the game's keys: windowed|borderless|fullscreen
        'vsync': int(bool(settings['vsync'])),
        'show_fps': int(bool(settings['show_fps'])),
        'mouse_enabled': int(bool(settings.get('mouse_enabled', True))),
        'mouse_sensitivity': f"{float(settings.get('mouse_sensitivity', 1.0)):.2f}",
        'mouse_invert_y': int(bool(settings.get('mouse_invert_y', False))),
        'key_map': key_map_spec(settings.get('key_map') or {}),
    })
    log = new_log()
    cmd = [str(PROBE), str(OUT_DIR / 'boot-linked.bin'), '--app0', settings['game_dir'],
           '--user', str(USER_DIR), '--content-profile', str(OUT_DIR / 'content.bin'),
           '--patches', str(OUT_DIR / 'patches.bin'), '--timeout', str(int(seconds))]
    if ISA_TABLE.is_file():
        cmd += ['--isa-rewrite', str(ISA_TABLE)]
    process = subprocess.Popen(cmd, cwd=str(USER_DIR), env=build_env(settings, extra_env),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding='utf-8', errors='replace', bufsize=1)
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
    if problems:
        for kind, detail in problems:
            print(f'{"Compile primeiro" if kind == "not_built" else "Faltando"}: {detail}', file=sys.stderr)
        return 1
    notes = []
    prepare(settings, log=lambda line: notes.append(line) if line.startswith('Frame rate') else None)
    process, log = launch(settings, seconds)
    print(f'Rodando (log: {log})', flush=True)
    with open(log, 'w', encoding='utf-8') as out:
        for line in notes:
            print(line, flush=True)
            out.write(line + '\n')
        for line in process.stdout:
            sys.stdout.write(line)
            out.write(line)
            out.flush()
    return process.wait()


if __name__ == '__main__':
    sys.exit(main())
