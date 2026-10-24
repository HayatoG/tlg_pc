# SPDX-License-Identifier: GPL-2.0-or-later
"""Every switch the Qt launcher's Graphics and Fixes screens offer for The Last Guardian.

The table layout and helpers come from infamous_pc's backports_table.py (same Qt screens), but
every row here was checked against THIS port's sources (tests/test_backports_table.py keeps it so):
  - MENU: tlg.ini keys parsed by gpu/shim/tlg_settings.cpp (Set) and shown by the in-game menu
    (gpu/shim/tlg_overlay.cpp); ranges and defaults from tlg_settings.h / tlg_graphics.h /
    tlg_perf_stats.h. They take effect on the next frame.
  - DIAGNOSTICS: TLG_* environment switches the GPU code reads at start (texture_cache.h,
    vk_presenter.cpp, resource.h, emulator_settings.h). They are kept in settings.json and passed
    as TLG_<name>=0/1 only when the player changed them.
There are no BPnn backports in this port (the GPU code has no TLG_BPnn switches), and no
Advanced parameters (advanced_table.py is empty), so those screens stay hidden.
"""
from collections import namedtuple
from pathlib import Path

import advanced_table

Item = namedtuple('Item', 'id group key env vtype default choices lo hi unit shader live store '
                          'pass_env risky broken name what source tab')


def _make(id, group, key, env, vtype, default, name, what, *, choices=(), lo=0, hi=0, unit='',
          shader=False, live=False, store='ini', pass_env=False, risky=False, broken=False,
          source='', tab=''):
    return Item(id, group, key, env, vtype, default, choices, lo, hi, unit, shader, live, store,
                pass_env, risky, broken, name, what, source, tab)


def _ab(key, env, default, live, name, what, store='launcher', pass_env=True, risky=False, broken=False):
    return _make(env, 'ab', key, env, 'bool', None if default is None else '1' if default else '0',
                 name, what, live=live, store=store, pass_env=pass_env, risky=risky, broken=broken)


def _menu(tab, key, vtype, default, name, what, **kw):
    return _make('menu:' + key, 'menu', key, '', vtype, default, name, what, live=True, tab=tab, **kw)


# The in-game menu (Insert). Display mode, VSync and the FPS overlay's on/off switch are launcher
# settings (settings.json -> tlg.ini at every start) and are not repeated here.
_CORNERS = (('0', 'Top left', 'Superior esquerdo'), ('1', 'Top right', 'Superior direito'),
            ('2', 'Bottom left', 'Inferior esquerdo'), ('3', 'Bottom right', 'Inferior direito'))
MENU = [
    _menu('Image', 'fsr1', 'bool', '0', ('Upscale with FSR 1', 'Ampliar com FSR 1'),
          ('Enlarges the game image when it is smaller than the window (spatial filter, no shimmer).',
           'Amplia a imagem do jogo quando ela é menor que a janela (filtro espacial, sem tremor).')),
    _menu('Image', 'rcas', 'bool', '1', ('Sharpening (RCAS)', 'Nitidez (RCAS)'),
          ('Sharpens the final image. Needs FSR 1 when the game image is smaller than the window.',
           'Deixa a imagem final mais nítida. Precisa do FSR 1 quando a imagem do jogo é menor que a janela.')),
    _menu('Image', 'rcas_strength', 'int', '75', ('Sharpening strength', 'Intensidade da nitidez'),
          ('How strong the RCAS sharpening is.', 'Quão forte é a nitidez do RCAS.'), lo=0, hi=100, unit='%'),
    _menu('Image', 'cas', 'bool', '1', ('AMD CAS sharpening', 'Nitidez AMD CAS'),
          ('Contrast-adaptive sharpening at any image size; replaces RCAS while on.',
           'Nitidez adaptativa ao contraste em qualquer tamanho de imagem; substitui o RCAS enquanto ligada.')),
    _menu('Image', 'cas_strength', 'int', '100', ('CAS strength', 'Intensidade do CAS'),
          ('How strong the CAS sharpening is.', 'Quão forte é a nitidez do CAS.'), lo=0, hi=100, unit='%'),
    _menu('Image', 'smaa', 'bool', '0', ('SMAA 1x anti-aliasing', 'Antisserrilhado SMAA 1x'),
          ('Smooths jagged edges on the final image (a little GPU time).',
           'Suaviza as bordas serrilhadas da imagem final (um pouco de tempo de GPU).')),
    _menu('Image', 'dlaa', 'bool', '1', ('DLAA anti-aliasing', 'Anti-aliasing DLAA'),
          ("NVIDIA RTX: stable foliage edges; F8 switches to the game's own SMAA.",
           'NVIDIA RTX: bordas estáveis na folhagem; F8 troca para o SMAA do próprio jogo.')),
    _menu('Image', 'hdr', 'bool', '1', ('HDR', 'HDR'),
          ("The game's own HDR10 output, used when HDR is on in Windows display settings. Recommended: on.",
           'A saída HDR10 do próprio jogo, usada quando o HDR está ligado nas configurações de tela do Windows. '
           'Recomendado: ligado.')),
    _menu('Effects', 'shadow_scale', 'choice', '1', ('Shadow resolution', 'Resolução das sombras'),
          ("Draws the shadow maps at 2x or 4x the game's 2048x2048. Recommended: Game (2048). The sharper edges are "
           'hard to see, and 8192 costs about 8 FPS and about 1 GB of video memory.',
           'Desenha os mapas de sombra em 2x ou 4x os 2048x2048 do jogo. Recomendado: Jogo (2048). As bordas mais '
           'nítidas são difíceis de notar, e 8192 custa cerca de 8 FPS e cerca de 1 GB de memória de vídeo.'),
          choices=(('1', 'Game (2048)', 'Jogo (2048)'), ('2', '4096', '4096'), ('4', '8192', '8192'))),
    _menu('Effects', 'ssao', 'int', '100', ('Ambient occlusion', 'Oclusão de ambiente'),
          ('Strength of the contact shadows in corners and under grass. 0% turns the pass off (saves a little GPU '
           'time). Above 150% the half-resolution AO shows blocky halos.',
           'Força das sombras de contato em cantos e sob a grama. 0% desliga o passe (economiza um pouco de GPU). '
           'Acima de 150% a AO em meia resolução mostra halos em blocos.'), lo=0, hi=400, unit='%'),
    _menu('Effects', 'bloom', 'int', '100', ('Bloom', 'Bloom'),
          ('Glow around bright light. 0% turns the pass off.', 'Brilho em volta da luz forte. 0% desliga o passe.'),
          lo=0, hi=400, unit='%'),
    _menu('Effects', 'ssr', 'int', '100', ('Screen-space reflections', 'Reflexos em espaço de tela'),
          ('Reflections and light glare on water and wet stone. 0% turns the pass off.',
           'Reflexos e brilho de luz na água e na pedra molhada. 0% desliga o passe.'), lo=0, hi=400, unit='%'),
    _menu('Effects', 'motion_blur', 'int', '100', ('Motion blur', 'Desfoque de movimento'),
          ('Camera motion blur. 0% turns the pass off.', 'Desfoque ao mover a câmera. 0% desliga o passe.'),
          lo=0, hi=400, unit='%'),
    _menu('Effects', 'chromatic_add', 'int', '0', ('Chromatic aberration', 'Aberração cromática'),
          ('Color fringes toward the screen edges. The game ships with this off: 0% is as shipped.',
           'Franjas de cor nas bordas da tela. O jogo vem com isto desligado: 0% é o original.'),
          lo=0, hi=100, unit='%'),
    _menu('Effects', 'vignette_add', 'int', '0', ('Vignette', 'Vinheta'),
          ('Darkened screen corners. The game ships with this off: 0% is as shipped.',
           'Cantos da tela escurecidos. O jogo vem com isto desligado: 0% é o original.'), lo=0, hi=100, unit='%'),
    _menu('Effects', 'game_sharpen', 'int', '100', ('Game sharpening', 'Nitidez do jogo'),
          ("The game's own sharpening filter. The difference is hard to see: 100% recommended.",
           'O filtro de nitidez do próprio jogo. A diferença é difícil de ver: 100% recomendado.'),
          lo=0, hi=400, unit='%'),
    _menu('Effects', 'lod', 'int', '100', ('Character detail distance', 'Distância de detalhe dos personagens'),
          ('How far the boy and Trico keep their detailed models. Higher keeps full detail further away.',
           'Até onde o menino e o Trico mantêm os modelos detalhados. Mais alto mantém o detalhe completo mais longe.'),
          lo=25, hi=400, unit='%'),
    _menu('Color', 'color_adjust', 'bool', '0', ('Color adjustments', 'Ajustes de cor'),
          ('Turns on the brightness, contrast, saturation and gamma sliders below.',
           'Liga os controles de brilho, contraste, saturação e gama abaixo.')),
    _menu('Color', 'color_brightness', 'float', '0', ('Brightness', 'Brilho'),
          ('Added to the final image: 0 is the game\'s own.', 'Somado à imagem final: 0 é o do jogo.'),
          lo=-0.5, hi=0.5),
    _menu('Color', 'color_contrast', 'float', '1', ('Contrast', 'Contraste'),
          ('1 is the game\'s own.', '1 é o do jogo.'), lo=0.5, hi=1.5),
    _menu('Color', 'color_saturation', 'float', '1', ('Saturation', 'Saturação'),
          ('1 is the game\'s own, 0 is black and white.', '1 é a do jogo, 0 é preto e branco.'), lo=0.0, hi=2.0),
    _menu('Color', 'color_gamma', 'float', '1', ('Gamma', 'Gama'),
          ('1 is the game\'s own.', '1 é a do jogo.'), lo=0.5, hi=2.0),
    _menu('Performance', 'fps_limit', 'choice', '0', ('Frame rate limit', 'Limite de FPS'),
          ('Caps the presented frames (never above the game frame rate chosen above).',
           'Limita os quadros apresentados (nunca acima da taxa de quadros do jogo escolhida acima).'),
          choices=(('30', '30', '30'), ('60', '60', '60'), ('120', '120', '120'), ('240', '240', '240'),
                   ('0', 'Unlimited', 'Sem limite'))),
    _menu('Performance', 'frames_queued', 'choice', '1', ('Frames queued', 'Quadros na fila'),
          ('More frames queued: steadier FPS, slower response to input.',
           'Mais quadros na fila: FPS mais estável, resposta mais lenta.'),
          choices=(('1', '1 (lowest latency)', '1 (menor atraso)'), ('2', '2', '2'),
                   ('0', 'Unlimited', 'Sem limite'))),
    _menu('Performance', 'async_shaders', 'bool', '1',
          ('Compile new shaders in the background', 'Compilar shaders novos em segundo plano'),
          ('Fewer hitches when a new effect appears; an object whose shader is not ready yet may be missing for a frame.',
           'Menos engasgos quando aparece um efeito novo; um objeto cujo shader ainda não está pronto pode sumir por um quadro.')),
    _menu('Overlay', 'overlay_fps', 'bool', '1', ('Overlay: FPS', 'Overlay: FPS'),
          ('Shows the frame rate in the performance overlay.', 'Mostra os quadros por segundo no overlay.')),
    _menu('Overlay', 'overlay_frametime', 'bool', '1', ('Overlay: frame time', 'Overlay: tempo de quadro'),
          ('Shows the time of each frame.', 'Mostra o tempo de cada quadro.')),
    _menu('Overlay', 'overlay_upscaler', 'bool', '0', ('Overlay: upscaler', 'Overlay: upscaler'),
          ('Shows the active upscaler.', 'Mostra o upscaler ativo.')),
    _menu('Overlay', 'overlay_gpu', 'bool', '1', ('Overlay: GPU', 'Overlay: GPU'),
          ('Shows the GPU name and use.', 'Mostra o nome e o uso da GPU.')),
    _menu('Overlay', 'overlay_cpu', 'bool', '0', ('Overlay: CPU', 'Overlay: CPU'),
          ('Shows the game\'s CPU use.', 'Mostra o uso de CPU do jogo.')),
    _menu('Overlay', 'overlay_ram', 'bool', '0', ('Overlay: RAM', 'Overlay: RAM'),
          ('Shows RAM used by the game and total.', 'Mostra a RAM usada pelo jogo e a total.')),
    _menu('Overlay', 'overlay_vram', 'bool', '1', ('Overlay: VRAM', 'Overlay: VRAM'),
          ('Shows video memory used and available.', 'Mostra a memória de vídeo usada e disponível.')),
    _menu('Overlay', 'overlay_scale', 'int', '100', ('Overlay font size', 'Tamanho da fonte do overlay'),
          ('Size of the overlay text.', 'Tamanho do texto do overlay.'), lo=50, hi=300, unit='%'),
    _menu('Overlay', 'overlay_corner', 'choice', '1', ('Overlay corner', 'Canto do overlay'),
          ('Where the overlay sits.', 'Onde o overlay fica.'), choices=_CORNERS),
    _menu('Overlay', 'overlay_opacity', 'int', '50', ('Overlay background opacity', 'Opacidade do fundo do overlay'),
          ('0% is no background.', '0% é sem fundo.'), lo=0, hi=100, unit='%'),
    _menu('Overlay', 'overlay_layout', 'choice', '0', ('Overlay layout', 'Disposição do overlay'),
          ('Items side by side or stacked.', 'Itens lado a lado ou empilhados.'),
          choices=(('0', 'One line', 'Uma linha'), ('1', 'One item per line', 'Um item por linha'))),
]

BACKPORTS = []   # no TLG_BPnn switch exists in this port's GPU code

# Start-up switches (environment, read once when the game starts). Defaults: the value the game
# gets from this port (tlg_run.DEFAULT_ENV or the code's own fallback).
DIAGNOSTICS = [
    _ab('deferred_readback', 'TLG_DEFERRED_READBACK', False, False,
        ('Deferred GPU readbacks', 'Leituras da GPU adiadas'),
        ('Only the thread that reads GPU results waits, not the whole GPU. Experimental in this game.',
         'Só a thread que lê resultados da GPU espera, não a GPU inteira. Experimental neste jogo.'), risky=True),
    _ab('stale_readback', 'TLG_STALE_READBACK', False, False,
        ('Stale readbacks', 'Leituras da GPU com um quadro de atraso'),
        ('CPU reads see the last published GPU version instead of waiting (needs deferred readbacks).',
         'A CPU lê a última versão publicada pela GPU em vez de esperar (precisa das leituras adiadas).'), risky=True),
    _ab('direct_memory_access', 'TLG_DIRECT_MEMORY_ACCESS', False, False,
        ('Direct memory access (shaders)', 'Acesso direto à memória (shaders)'),
        ('Shaders read constants straight from the game\'s memory when their address is computed: '
         'fixes some broken scenes, but the game runs slower. Its shaders are compiled again, in a cache '
         'of their own.',
         'Os shaders leem constantes direto da memória do jogo quando o endereço é calculado: corrige '
         'algumas cenas com problema, mas o jogo fica mais lento. Os shaders dela são compilados de novo, '
         'num cache próprio.'), risky=True),
    _ab('readback_linear', 'TLG_READBACK_LINEAR', True, False,
        ('Read small render targets back', 'Ler de volta render targets pequenos'),
        ('Copies small and linear render targets back to the CPU: the game\'s auto exposure needs it (#38, #40).',
         'Copia render targets pequenos e lineares de volta para a CPU: a exposição automática do jogo precisa (#38, #40).')),
    _ab('background_warmup', 'TLG_BACKGROUND_WARMUP', True, False,
        ('Load pipelines while playing', 'Carregar pipelines durante o jogo'),
        ('The cached pipelines load in the background (a corner note shows progress); off blocks until all are loaded.',
         'Os pipelines em cache carregam em segundo plano (uma nota no canto mostra o progresso); desligado espera carregar tudo.')),
    _ab('block1d', 'TLG_BLOCK1D', False, False, ('BC 1D textures as 2D', 'Texturas BC 1D como 2D'),
        ('Block-compressed 1D textures as 2D images, for drivers that refuse BC 1D.',
         'Texturas 1D comprimidas como imagens 2D, para drivers que recusam BC 1D.')),
    _ab('pipeline_binaries', 'TLG_PIPELINE_BINARIES', False, False,
        ('Pipeline binaries (VK_KHR_pipeline_binary)', 'Pipeline binaries (VK_KHR_pipeline_binary)'),
        ('Crashes the game on the NVIDIA 595 driver; off by default in this port.',
         'Derruba o jogo no driver NVIDIA 595; desligado por padrão neste port.'), broken=True),
]

ADVANCED = advanced_table.build(_make)
ITEMS = MENU + BACKPORTS + DIAGNOSTICS + ADVANCED
PREFIX = 'TLG_'


def _from_launcher(item, settings):
    value = settings.get(item.key)
    return item.default if value is None else '1' if value else '0'


def read_states(ini, settings=None):
    """{item.id: value text or None}: the player's choice, None = the default applies.
    A value equal to the default is also None, so only real changes are kept."""
    settings = settings or {}
    states = {}
    for item in ITEMS:
        value = _from_launcher(item, settings) if item.store == 'launcher' else ini.get(item.key)
        states[item.id] = normalize(item, value)
    return states


def normalize(item, value):
    """The value if valid and different from the default, else None."""
    if value is None:
        return None
    value = str(value).strip()
    if item.vtype == 'bool':
        valid = value in ('0', '1')
    elif item.vtype == 'choice':
        valid = value in [c[0] for c in item.choices]
    elif item.vtype == 'float':
        try:
            number = float(value)
            valid = item.lo <= number <= item.hi
        except ValueError:
            valid = False
        if valid:
            if abs(number - float(item.default)) <= 1e-6 * max(1.0, abs(number)):
                return None
            value = f'{number:g}'
    else:
        try:
            valid = item.lo <= int(value) <= item.hi
        except ValueError:
            valid = False
        value = str(int(value)) if valid else value
    return value if valid and value != item.default else None


# Slider steps of the 'float' items (launchers).
FLOAT_STEPS = {'color_brightness': 0.05, 'color_contrast': 0.05, 'color_saturation': 0.05, 'color_gamma': 0.05}


def effective(item, states):
    """The value the game will use; None for an automatic switch left on automatic."""
    value = states.get(item.id)
    return item.default if value is None else value


def ini_updates(states):
    """tlg.ini keys to write: the value for a change, None to remove the key (default again)."""
    return {item.key: states.get(item.id) for item in ITEMS if item.store == 'ini'}


def environment(states, environ=None):
    """TLG_<name>=0/1 for the switches the player changed; one already in the environment wins.
    Untouched switches add nothing, so the defaults hold."""
    environ = {} if environ is None else environ
    env = {}
    for item in ITEMS:
        value = states.get(item.id)
        if value is None or not item.pass_env or item.env in environ:
            continue
        env[item.env] = value
    return env


def previous_release(states):
    """Kept for the shared screens: this port has no backports to undo."""
    return dict(states)


def defaults(states, group=None):
    """Forget every choice (of one group, or all)."""
    return {k: (None if group is None or _group(k) == group else v) for k, v in states.items()}


def is_recommended(item):
    """Rows that are part of the Recommended profile: the switches that are on by default."""
    return item.group in ('bp', 'ab') and item.vtype == 'bool' and item.default == '1'


def changes(states):
    """How many start-up switches differ from the Recommended profile. The game menu options
    (overlay corner, limits...) are preferences and do not count."""
    return sum(1 for item in BACKPORTS + DIAGNOSTICS if states.get(item.id) is not None)


def advanced_changes(states):
    return sum(1 for item in ADVANCED if states.get(item.id) is not None)


def notice_pending(settings):
    """No one-time notice in this port (inFAMOUS showed one about its backports)."""
    return False


def mark_notice_seen(settings):
    settings['backports_notice_seen'] = True


def _group(item_id):
    return next((item.group for item in ITEMS if item.id == item_id), None)


def write_ini(path, updates):
    """Sets or removes keys in tlg.ini, keeping every other line (the game's own keys included)."""
    path = Path(path)
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        lines = ['# tlg settings']
    out, seen = [], set()
    for line in lines:
        key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else None
        if key in updates:
            seen.add(key)
            if updates[key] is not None:
                out.append(f'{key}={updates[key]}')
        else:
            out.append(line)
    out += [f'{k}={v}' for k, v in updates.items() if v is not None and k not in seen]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')
