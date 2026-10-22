#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Last Guardian frame rate patches (TLG_FPS=30|60|unlocked) and community mods/cheats,
written together to out/patches.bin.

Each built-in frame rate patch is a list of {image offset, expected bytes, new bytes} for eboot
1.03 only (sha256 below, or a SELF dump of it): the expected bytes are checked in eboot.bin
before anything is written, so another build never gets byte writes in the wrong place. The
loader (probe.c apply_patches) applies the file after relocation. Image offsets are eboot
virtual addresses; the Ghidra addresses in the comments (base 0x1000000) are offset + 0x1000000.
Research: docs/60fps.md.

30 with no mods enabled writes an empty patch file: the game runs exactly as on PS4.

Mods/cheats (--mods-dir/--mods-config, mod_patches.py): shadPS4/GoldHEN cheat XML files the
player drops in the mods folder. Nothing in there has any effect until it is enabled (the
file's own isEnabled="true", or mods.json), same contract as the built-in patches above.

Resolution (--resolution WxH, TLG_RESOLUTION wins): the default 1920x1080 mode becomes WxH,
rendered natively; wider than 16:9 also gets Hor+ cameras and a UI canvas of that aspect.
"""
import argparse
import hashlib
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mod_patches

TITLE_IDS = {'CUSA03627', 'CUSA03745'}   # US, EU (tlg_run.py LANGUAGES_BY_TITLE)
EBOOT_103_SHA256 = '91dce685be81f8f6bc88097d4fc7a62e97ca08d109621c57fe9371ae125feb3c'
SELF_MAGIC = b'O\x15=\x1d'
TEXT_FILE_OFFSET = 0x4000      # PT_LOAD 0 (R E): file offset of vaddr 0
TEXT_SIZE = 0x16b2d5c
GHIDRA_BASE = 0x1000000


def f32(value):
    return struct.pack('<f', value)


def rip_disp(instruction_end, target):
    """disp32 of a rip-relative operand: target - address of the next instruction (Ghidra addresses)."""
    return struct.pack('<i', target - instruction_end)


# Patches by name: [(ghidra address, expected bytes, new bytes, what it does)].
PATCHES = {
    # JsDevice/JsSwapChain init (0x1c4f9f0): sceVideoOutSetFlipRate(handle, 1) -> 0.
    # Rate 1 shows a frame every second vblank (30 Hz on the 60 Hz vblank); 0 every vblank.
    'flip_rate_60': [
        (0x1c5151a, bytes.fromhex('be01000000'), bytes.fromhex('be00000000'),
         'sceVideoOutSetFlipRate(h, 1) -> (h, 0)'),
    ],
    # Lua SetMaxFps(fps) binding (0x12091a0): game+0x180 = 1.0/fps, the engine's minimum frame
    # time. The scripts call SetMaxFps(30) (states/main.lua, common/gamesetuptbl.lua).
    # 60: load 0.5 (0x24f17e8) instead of 1.0 (0x24eaf84) -> 0.5/fps: SetMaxFps(30) means 60.
    'max_fps_double': [
        (0x12091db, bytes.fromhex('c5fa100d') + rip_disp(0x12091e3, 0x24eaf84),
         bytes.fromhex('c5fa100d') + rip_disp(0x12091e3, 0x24f17e8),
         'SetMaxFps(n): minimum frame time 1/n -> 0.5/n'),
    ],
    # Unlocked: vdivss xmm1,xmm1,xmm0 -> vxorps xmm1,xmm1,xmm1: minimum frame time 0 (no limit),
    # as SetMaxFps(0) does.
    'max_fps_off': [
        (0x12091e3, bytes.fromhex('c5f25ec8'), bytes.fromhex('c5f057c9'),
         'SetMaxFps(n): minimum frame time 1/n -> 0'),
    ],
    # SmoothDeltaTime (0x1d16480): a frame time in (0.031667, 0.035) s becomes exactly 1/30 s
    # before the 2nd-order filter and the 1/360 s rounding. These three constants are read only
    # here. 60: the same snap one octave up, (0.0158333, 0.0175) -> 1/60.
    'dt_snap_60': [
        (0x24f17f8, f32(0.035), f32(0.0175), 'dt snap upper bound 0.035 -> 0.0175'),
        (0x24f17fc, f32(1 / 30), f32(1 / 60), 'dt snap target 1/30 -> 1/60'),
        (0x24f1800, f32(0.0316666663), f32(0.0158333331), 'dt snap lower bound 0.031667 -> 0.015833'),
    ],
}

MODES = {
    '30': [],
    # max_fps_double/max_fps_off are left out: 60 and unlocked were reached without them
    # (game+0x180 is no frame limiter in the tested scenes; its reader is not found yet).
    # TLG_FPS_PATCHES=flip_rate_60,max_fps_off tries them.
    '60': ['flip_rate_60', 'dt_snap_60'],
    'unlocked': ['flip_rate_60'],
}
# The engine rate each mode presents at most (TLG_ENGINE_FPS: the overlay's frame limiter and
# tlg_graphics.h PresentLimit). Unlocked is paced by the present thread (TLG_VBLANK_HZ=0).
ENGINE_FPS = {'30': 30, '60': 60, 'unlocked': 240}


def normalize_mode(value):
    value = (value or '30').strip().lower()
    return {'unlimited': 'unlocked', 'uncapped': 'unlocked', 'free': 'unlocked', '0': 'unlocked'}.get(value, value)


def mode_writes(eboot, names):
    """[(image offset, new bytes, description)] after checking every expected byte in eboot."""
    writes = []
    for name in names:
        for address, expected, new, what in PATCHES[name]:
            offset = address - GHIDRA_BASE
            if not (0 <= offset and offset + len(expected) <= TEXT_SIZE) or len(expected) != len(new):
                raise ValueError(f'{name}: bad patch entry at {address:#x}')
            found = eboot[TEXT_FILE_OFFSET + offset:TEXT_FILE_OFFSET + offset + len(expected)]
            if found != expected:
                raise ValueError(f'{name}: {address:#x} has {found.hex()}, expected {expected.hex()}')
            writes.append((offset, new, f'{name}: {address:#x} {what}'))
    return writes


# Resolution (TLG_RESOLUTION=WxH, e.g. 3440x1440): the mode table (0x18 bytes per entry: u16
# render W,H, output W,H; u64 checkerboard; name pointer) starts with the normal (non-Pro) list,
# whose default entry at 0x26ec3a0 is 1920x1080 rendered, 1920x1080 output. It becomes WxH, WxH;
# the Pro list (0x26ec3e8, picked when the output height is > 1080) is left alone.
RESOLUTION_ENTRY = 0x26ec3a0
RESOLUTION_EXPECTED = bytes.fromhex('80073804800738040000000000000000')
# Segment types the loader maps: PT_LOAD and PT_SCE_RELRO (read-only data fixed up at load).
LOADED_SEGMENTS = (1, 0x61000010)


def parse_resolution(value):
    """(width, height) of "WxH", or None when it is empty, not a size or 1920x1080."""
    parts = str(value or '').lower().replace(' ', '').split('x')
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    width, height = (int(part) for part in parts)
    if not (0 < width <= 0xffff and 0 < height <= 0xffff) or (width, height) == (1920, 1080):
        return None
    return width, height


def file_offset(eboot, offset, length):
    """File offset of image bytes [offset, offset + length) of the ELF eboot through its PT_LOAD
    and PT_SCE_RELRO headers; None when no segment holds them."""
    if eboot[:4] != b'ELF' or len(eboot) < 0x40:
        return None
    phoff, = struct.unpack_from('<Q', eboot, 0x20)
    phentsize, phnum = struct.unpack_from('<HH', eboot, 0x36)
    for i in range(phnum):
        kind, _, p_offset, vaddr, _, filesz, _, _ = struct.unpack_from('<IIQQQQQQ', eboot, phoff + i * phentsize)
        if kind in LOADED_SEGMENTS and vaddr <= offset and offset + length <= vaddr + filesz:
            return p_offset + offset - vaddr
    return None


# Hor+ for frames wider than 16:9. The perspective builder 0x1de0440 sets m00 = cot(fov/2) and
# m11 = m00 * aspect ([camera+0x414]), and the gameplay cameras keep that aspect at 16:9 whatever
# the frame size, so a wider frame stretched the 16:9 view. Its post-tan code spills the same 13
# registers on both paths (0x1de06af and 0x1de076c); doing that once before the branch frees
# 0x1de076c-0x1de07e1 for a routine, called instead of `vmulss xmm8,xmm10,[rsp+160h]` (m11), that
# sets m00 = m11 / frame aspect when the camera aspect is within 1.70-1.85. Cameras that take the
# aspect from the frame size (the main gameplay camera once the mode is patched) would keep the
# 16:9 width and lose height (Vert-); they get m11 = m00 * 16/9 first, so they widen the same way.
# Other cameras (square targets) are left alone.
HOR_PLUS_CALL = 0x1de0584
HOR_PLUS_CALL_EXPECTED = bytes.fromhex('c52a59842460010000')
HOR_PLUS_CALL_NEW = bytes.fromhex('e8e30100000f1f4000')  # call 0x1de076c; nop
HOR_PLUS_BLOCK = 0x1de06a1
HOR_PLUS_BLOCK_EXPECTED = bytes.fromhex(
    'c5782eb3080400000f84bd000000c5f8298424c0000000c58a590564137100c57829ac24d0000000c578299c24e0'
    '000000c5f829bc24f0000000c5f829a42400010000c5f8299c2410010000c5f829942420010000c5f8298c243001'
    '0000c57829a42440010000c57829942450010000c578298c2460010000c5f829b42470010000c5f829ac24800100'
    '00c57a11b42490010000e88ed36d00c5fa100dea127100c5f25ec0c5fa118304040000c5fa11830c040000c5fa10'
    '842490010000c5fa118308040000e9ce000000c5f8298424c0000000c57829ac24d0000000c578299c24e0000000'
    'c5f829bc24f0000000c5f829a42400010000c5f8299c2410010000c5f829942420010000c5f8298c243001000'
    '0c57829a42440010000c57829942450010000c578298c2460010000c5f829b42470010000c5f829ac2480010000')
# Spills, vucomiss xmm14,[rbx+408h]; je 0x1de07e1; the unchanged fov path ending in jmp 0x1de083a;
# then at 0x1de076c: vmovss xmm3,[rsp+168h] (aspect); an aspect within 0.02 of the frame's becomes
# 16:9; vmulss xmm8,xmm10,xmm3; skip unless 1.70 <= aspect <= 1.85; vmulss xmm10,xmm8,[1/frame
# aspect]; ret; f32 1.70, 1.85, 16/9, then the frame aspect - 0.02 and + 0.02 and 1/frame aspect.
HOR_PLUS_BLOCK_NEW = bytes.fromhex(
    'c5f8298424c0000000c57829ac24d0000000c578299c24e0000000c5f829bc24f0000000c5f829a42400010000c5'
    'f8299c2410010000c5f829942420010000c5f8298c2430010000c57829a42440010000c57829942450010000c578'
    '298c2460010000c5f829b42470010000c5f829ac2480010000c5782eb3080400000f84bd000000c58a5905f81271'
    '00c57a11b42490010000e88ed36d00c5fa100dea127100c5f25ec0c5fa118304040000c5fa11830c040000c5fa10'
    '842490010000c5fa118308040000e9ce000000'
    'c5fa109c2468010000c5f82e1d410000007212c5f82e1d3b0000007708c5fa101d29000000c52a59c3c5f82e1d15'
    '0000007212c5f82e1d0f0000007708c53a591515000000c39a99d93fcdccec3f398ee33f')


# UI canvas: the UI init copies {1920, 1080, 1920, 1080} from 0x2525480 (its only reference) into
# the UI state; the first pair becomes the UI projection size, the second the layout size that
# anchors elements to the screen edges. For a wider frame both widths become 1080 * frame aspect,
# so the UI keeps its proportions and edge-anchored elements (HUD prompts, menus) move out to the
# edges. Widening only the projection leaves the screen grey.
UI_SIZE = 0x2525480
UI_SIZE_EXPECTED = struct.pack('<4i', 1920, 1080, 1920, 1080)
# Guide (button hint box) draw, 0x190fdf0: scales its 1920x1080 layout to the UI canvas with
# width/1920 and height/1080 and its 16 px corners with width*16/1920 (these four floats, used
# only there). With a wider canvas the box stretched sideways; dividing by the canvas width keeps it square.
GUIDE_SCALE = 0x24efa14
GUIDE_SCALE_EXPECTED = struct.pack('<4f', 1 / 1920, 1 / 1080, -32, 16 / 1920)
# Subtitle draw, 0x1c30320: the same width/1920, height/1080 scale (these two floats, used only
# there) stretched the subtitle lines sideways on a wider canvas.
SUBTITLE_SCALE = 0x24f1464
SUBTITLE_SCALE_EXPECTED = struct.pack('<2f', 1 / 1920, 1 / 1080)
# Garlic (GPU) heap: the render setup (0x1dd3a46) allocates 0xb0000000 bytes (2816 MiB; the Pro
# path adds 512 MiB) for the game's own allocator (Gomalloc), render targets included. A large
# stage at 1080p already uses most of it, so it always gets 4064 MiB: headroom for larger frames
# and supersampling. The launcher grows the direct memory (TLG_DMEM_MB) by the same amount.
# mov r15d, imm32 caps it below 4 GiB; 32 MiB stay free in case the allocator rounds sizes up
# in 32 bits.
GARLIC_SIZE = 0x1dd3a46
GARLIC_SIZE_EXPECTED = bytes.fromhex('41bf000000b0')
GARLIC_EXTRA_MB = 1248


def checked_offset(eboot, address, expected):
    """Image offset of `address` (Ghidra) after checking the eboot holds `expected` there."""
    offset = address - GHIDRA_BASE
    start = file_offset(eboot or b'', offset, len(expected))
    if start is None:
        raise ValueError(f'{address:#x} is not in the eboot image')
    found = eboot[start:start + len(expected)]
    if found != expected:
        raise ValueError(f'{address:#x} has {found.hex()}, expected {expected.hex()}')
    return offset


def resolution_writes(eboot, size):
    """[(image offset, new bytes, description)] of the default mode entry, and of Hor+ and the UI
    canvas for frames wider than 16:9, after checking them."""
    width, height = size
    offset = checked_offset(eboot, RESOLUTION_ENTRY, RESOLUTION_EXPECTED)
    new = struct.pack('<4H', width, height, width, height) + RESOLUTION_EXPECTED[8:]
    writes = [(offset, new, f'resolution: {RESOLUTION_ENTRY:#x} default mode 1920x1080 -> {width}x{height}')]
    if width * 9 > height * 16:
        call = checked_offset(eboot, HOR_PLUS_CALL, HOR_PLUS_CALL_EXPECTED)
        block = checked_offset(eboot, HOR_PLUS_BLOCK, HOR_PLUS_BLOCK_EXPECTED)
        aspect = width / height
        new = HOR_PLUS_BLOCK_NEW + struct.pack('<3f', aspect - 0.02, aspect + 0.02, height / width)
        new += b'\xcc' * (len(HOR_PLUS_BLOCK_EXPECTED) - len(new))
        writes += [(block, new, f'Hor+: {HOR_PLUS_BLOCK:#x} 16:9 cameras -> {width}:{height}'),
                   (call, HOR_PLUS_CALL_NEW, f'Hor+: {HOR_PLUS_CALL:#x} calls it')]
        ui = checked_offset(eboot, UI_SIZE, UI_SIZE_EXPECTED)
        ui_width = round(1080 * width / height)
        writes.append((ui, struct.pack('<4i', ui_width, 1080, ui_width, 1080),
                       f'UI: {UI_SIZE:#x} canvas 1920x1080 -> {ui_width}x1080'))
        guide = checked_offset(eboot, GUIDE_SCALE, GUIDE_SCALE_EXPECTED)
        writes.append((guide, struct.pack('<4f', 1 / ui_width, 1 / 1080, -32, 16 / ui_width),
                       f'UI: {GUIDE_SCALE:#x} hint box scale 1920 -> {ui_width}'))
        subtitle = checked_offset(eboot, SUBTITLE_SCALE, SUBTITLE_SCALE_EXPECTED)
        writes.append((subtitle, struct.pack('<2f', 1 / ui_width, 1 / 1080),
                       f'UI: {SUBTITLE_SCALE:#x} subtitle scale 1920 -> {ui_width}'))
    return writes


def garlic_writes(eboot):
    """[(image offset, new bytes, description)] of the larger GPU heap, after checking it."""
    garlic = checked_offset(eboot, GARLIC_SIZE, GARLIC_SIZE_EXPECTED)
    size_mb = 2816 + GARLIC_EXTRA_MB
    return [(garlic, GARLIC_SIZE_EXPECTED[:2] + struct.pack('<I', size_mb << 20),
             f'garlic: {GARLIC_SIZE:#x} GPU heap 2816 -> {size_mb} MB')]


def write_patch_file(path, writes):
    """G3PATCH2 (probe.c apply_patches): base 0 (no pointer slots), then (offset, length, bytes).
    Base 0 only matters for a write that lands exactly on a relocated pointer slot (none of the
    built-in frame rate patches or typical shadPS4/GoldHEN literal-value mods do); it does not
    change plain byte/float writes either way."""
    blob = struct.pack('<8sQQ', b'G3PATCH2', 0, len(writes))
    for offset, data, _ in writes:
        blob += struct.pack('<QQ', offset, len(data)) + data
    Path(path).write_bytes(blob)


def read_eboot_elf(game_dir):
    """eboot.bin as a plain ELF, unwrapping a SELF dump of any game version; None if unreadable
    or an unparsable SELF. Independent of the v1.03 pin below: mods filter by their own AppVer."""
    try:
        eboot = (Path(game_dir) / 'eboot.bin').read_bytes()
    except OSError:
        return None
    if eboot[:4] == SELF_MAGIC:
        try:
            from prepare import parse_self
            return bytes(parse_self(eboot)[0])
        except ValueError:
            return None
    return eboot


def compile_mods(game_dir, eboot, mods_dir, mods_config, lines):
    """[(offset, bytes, description)] from the player's mods folder, or [] when mods_dir is not
    set, the eboot could not be read, or nothing in there is enabled."""
    if not mods_dir or not eboot:
        return []
    try:
        segments = mod_patches.eboot_segments(eboot)
        app_version = mod_patches.game_app_version(game_dir)
        found = mod_patches.external_patches(mods_dir, app_version, TITLE_IDS)
        selected = mod_patches.external_selection(found, mods_config)
        return mod_patches.compile_external(selected, segments)
    except (OSError, ValueError, struct.error) as error:
        lines.append(f'Mods: {error}: not applied')
        return []


def prepare(game_dir, out_dir, mode, mods_dir=None, mods_config=None, resolution=None):
    """Writes out/patches.bin for the mode plus any enabled mod; returns (applied mode, lines).
    Any problem with the frame rate patches (other eboot build, unexpected bytes) falls back to
    30 FPS without them; a mod problem only drops that mod, never the frame rate patches."""
    mode = normalize_mode(mode)
    lines = []
    if mode not in MODES:
        lines.append(f'Frame rate: unknown TLG_FPS={mode!r}; using 30')
        mode = '30'
    fps_writes = []
    eboot = None
    # TLG_FPS_PATCHES="a,b" (measurements): these patches instead of the mode's own.
    names = [n for n in os.environ.get('TLG_FPS_PATCHES', '').split(',') if n in PATCHES] or MODES[mode]
    if names:
        try:
            eboot = (Path(game_dir) / 'eboot.bin').read_bytes()
        except OSError as error:
            eboot = b''
            lines.append(f'Frame rate: cannot read eboot.bin ({error})')
        digest = hashlib.sha256(eboot).hexdigest()
        usable = digest == EBOOT_103_SHA256
        if not usable and eboot[:4] == SELF_MAGIC:
            # A SELF dump of 1.03 (sha256 b7f61057…, #40) wraps the same ELF as the plain
            # dump the hash is for, at other file offsets: patch the ELF inside (the image
            # prepare.py hands the loader). mode_writes checks every expected byte, so a SELF
            # of another build still falls back to 30.
            try:
                from prepare import parse_self
                eboot = bytes(parse_self(eboot)[0])
                usable = True
                lines.append(f'Frame rate: eboot.bin is a SELF ({digest[:16]}…), checking the ELF inside')
            except ValueError as error:
                lines.append(f'Frame rate: cannot read the SELF eboot.bin ({error})')
        if not usable:
            lines.append(f'Frame rate: eboot.bin is not v1.03 ({digest[:16]}…): {mode} FPS patches not applied, 30 FPS')
            mode = '30'
        else:
            try:
                fps_writes = mode_writes(eboot, names)
            except ValueError as error:
                lines.append(f'Frame rate: {error}: patches not applied, 30 FPS')
                mode, fps_writes = '30', []
    for _, data, what in fps_writes:
        lines.append(f'Frame rate patch {what} ({data.hex()})')
    mod_writes = []
    if mods_dir:
        mod_writes = compile_mods(game_dir, eboot or read_eboot_elf(game_dir), mods_dir, mods_config, lines)
        for _, data, what in mod_writes:
            lines.append(f'Mod {what} ({data.hex()})')
    res_writes = []
    size = parse_resolution(os.environ.get('TLG_RESOLUTION') or resolution)
    if size:
        try:
            res_writes = resolution_writes(read_eboot_elf(game_dir), size)
        except ValueError as error:
            lines.append(f'Resolution: {error}: not applied, 1920x1080')
        for _, data, what in res_writes:
            lines.append(f'Resolution patch {what} ({data.hex()})')
    heap = []
    try:
        heap = garlic_writes(read_eboot_elf(game_dir))
    except (OSError, ValueError) as error:
        lines.append(f'GPU heap: {error}: not applied, 2816 MB')
    for _, data, what in heap:
        lines.append(f'Patch {what} ({data.hex()})')
    writes = fps_writes + mod_writes + res_writes + heap
    write_patch_file(Path(out_dir) / 'patches.bin', writes)
    lines.append(f'Frame rate: {mode} FPS mode, {len(writes)} patch writes')
    return mode, lines


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('game_dir')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--mode', default='30', help='30, 60 or unlocked')
    p.add_argument('--mods-dir', help='folder of shadPS4/GoldHEN cheat XML files')
    p.add_argument('--mods-config', help='mods.json: {"enabled": [...], "disabled": [...]}')
    p.add_argument('--resolution', help='WxH, e.g. 3440x1440 (default 1920x1080)')
    a = p.parse_args()
    _, lines = prepare(a.game_dir, a.out, a.mode, a.mods_dir, a.mods_config, a.resolution)
    print('\n'.join(lines))


if __name__ == '__main__':
    sys.exit(main())
