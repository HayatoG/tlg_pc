#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Last Guardian frame rate (TLG_FPS=<fps>) and resolution (TLG_RESOLUTION=<width>x<height>)
patches, written to out/patches.bin.

Each patch is a list of {image offset, expected bytes, new bytes} for eboot 1.03 only (sha256
below, or a SELF dump of it): the expected bytes are checked in eboot.bin before anything is
written, so another build never gets byte writes in the wrong place. The loader (probe.c
apply_patches) applies the file after relocation. Image offsets are eboot virtual addresses;
the Ghidra addresses in the comments (base 0x1000000) are offset + 0x1000000. Research:
docs/60fps.md.

30 FPS (the game's own, the default) and 1920x1080 write nothing: the game runs exactly as on PS4.
"""
import argparse
import hashlib
import math
import os
from pathlib import Path
import re
import struct
import sys

EBOOT_103_SHA256 = '91dce685be81f8f6bc88097d4fc7a62e97ca08d109621c57fe9371ae125feb3c'
SELF_MAGIC = b'O\x15=\x1d'
TEXT_FILE_OFFSET = 0x4000      # PT_LOAD 0 (R E): file offset of vaddr 0
TEXT_SIZE = 0x16b2d5c
GHIDRA_BASE = 0x1000000
# Segment types the loader maps: PT_LOAD and PT_SCE_RELRO (read-only data fixed up at load).
LOADED_SEGMENTS = (1, 0x61000010)


def f32(value):
    return struct.pack('<f', value)


def rip_disp(instruction_end, target):
    """disp32 of a rip-relative operand: target - address of the next instruction (Ghidra addresses)."""
    return struct.pack('<i', target - instruction_end)


# Patches by name: [(ghidra address, expected bytes, new bytes, what it does)].
PATCHES = {
    # JsDevice/JsSwapChain init (0x1c4f9f0): sceVideoOutSetFlipRate(handle, 1) -> 0.
    # Rate 1 shows a frame every second vblank (30 Hz on the 60 Hz vblank); 0 every vblank.
    'flip_rate': [
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
}

# Frame rate: 30 is the game as on PS4 (no patch); any other rate flips every vblank (flip_rate)
# and moves the dt snap to it. TLG_FPS_PATCHES=flip_rate,max_fps_off (and max_fps_double) try the
# other patches by name.
GAME_FPS = 30
GAME_SIZE = (1920, 1080)      # what the game renders on a PS4 with a 1080p TV


def parse_number(value):
    """A non-negative number (text or number, a comma may be the decimal point) rounded to the
    nearest integer; None when it is not one."""
    try:
        number = float(str(value).strip().replace(',', '.'))
    except ValueError:
        return None
    return round(number) if math.isfinite(number) and number >= 0 else None


def parse_fps(value):
    """The frame rate; the game's own when it is 0 or not a number."""
    return parse_number(value) or GAME_FPS


def fps_patches(fps):
    """{name: entries} of a frame rate (see PATCHES)."""
    if fps == GAME_FPS:
        return {}
    # SmoothDeltaTime (0x1d16480): a frame time in (0.95/fps, 1.05/fps) s becomes exactly 1/fps s
    # (30: 0.031667, 0.035 -> 1/30) before the 2nd-order filter and the 1/360 s rounding. These
    # three constants are read only there.
    return {'flip_rate': PATCHES['flip_rate'], 'dt_snap': [
        (0x24f17f8, f32(0.035), f32(1.05 / fps), f'dt snap upper bound 0.035 -> {1.05 / fps:.6f}'),
        (0x24f17fc, f32(1 / 30), f32(1 / fps), f'dt snap target 1/30 -> 1/{fps}'),
        (0x24f1800, f32(0.0316666663), f32(0.95 / fps), f'dt snap lower bound 0.031667 -> {0.95 / fps:.6f}'),
    ]}


def parse_resolution(value):
    """(width, height) of "WxH"; a side that is 0, empty or not a number (or over 65535, what the
    game's u16 holds) is worked out from the other one in 16:9. None, the game's own, when
    neither is a size or when it is the game's own size."""
    sides = re.fullmatch(r'(.*)x(.*)', str(value or '').strip().lower().replace(' ', ''))
    width, height = ((side if side and side <= 0xffff else None)
                     for side in (parse_number(text) for text in (sides.groups() if sides else ('', ''))))
    if width and not height:
        height = round(width * 9 / 16)
    elif height and not width:
        width = round(height * 16 / 9)
    return (width, height) if width and height and (width, height) != GAME_SIZE \
        and width <= 0xffff and height <= 0xffff else None


def resolution_patches(width, height):
    """{name: entries} of a resolution. The mode table (0x18 bytes per entry: u16 render W,H,
    output W,H; u64 checkerboard; name pointer) starts with the Pro list's default entry at
    0x26ec3e8: 1680x1890 checkerboard, output 3360x1890; it becomes WxH, WxH, no checkerboard.
    The 23 bytes at 0x1c4fa6a in JsDevice::CreateDevice (0x1c4f9f0) are `jne +0x167;
    cmp dword [rsp+0x124], 0x438; jbe +0x156`, the output height > 1080 test that picks the Pro
    list: NOPed, the Pro list is always used."""
    return {'resolution': [
        (0x26ec3e8, bytes.fromhex('90066207200d62070100000000000000'),
         struct.pack('<4HQ', width, height, width, height, 0),
         f'default mode 1680x1890 checkerboard -> {width}x{height}'),
        (0x1c4fa6a, bytes.fromhex('0f856701000081bc2424010000380400000f8656010000'), b'\x90' * 23,
         'CreateDevice: always use the Pro mode list'),
    ]}


def file_offset(eboot, offset, length):
    """File offset of image bytes [offset, offset + length): text by TEXT_FILE_OFFSET, anything
    after it (the data tables) through the ELF's PT_LOAD and PT_SCE_RELRO headers; None when no segment holds them."""
    if offset + length <= TEXT_SIZE:
        return TEXT_FILE_OFFSET + offset
    if eboot[:4] != b'\x7fELF' or len(eboot) < 0x40:
        return None
    phoff, = struct.unpack_from('<Q', eboot, 0x20)
    phentsize, phnum = struct.unpack_from('<HH', eboot, 0x36)
    for i in range(phnum):
        position = phoff + i * phentsize
        if position + 56 > len(eboot):
            break
        kind, _, p_offset, vaddr, _, filesz, _, _ = struct.unpack_from('<IIQQQQQQ', eboot, position)
        if kind in LOADED_SEGMENTS and vaddr <= offset and offset + length <= vaddr + filesz \
                and p_offset + offset - vaddr + length <= len(eboot):
            return p_offset + offset - vaddr
    return None


def mode_writes(eboot, patches):
    """[(image offset, new bytes, description)] after checking every expected byte in eboot."""
    writes = []
    for name, entries in patches.items():
        for address, expected, new, what in entries:
            offset = address - GHIDRA_BASE
            if offset < 0 or len(expected) != len(new):
                raise ValueError(f'{name}: bad patch entry at {address:#x}')
            start = file_offset(eboot, offset, len(new))
            if start is None:
                raise ValueError(f'{name}: {address:#x} is not in the eboot image')
            found = eboot[start:start + len(new)]
            if found != expected:
                raise ValueError(f'{name}: {address:#x} has {found.hex()}, expected {expected.hex()}')
            writes.append((offset, new, f'{name}: {address:#x} {what}'))
    return writes


def write_patch_file(path, writes):
    """G3PATCH2 (probe.c apply_patches): base 0 (no pointer slots), then (offset, length, bytes)."""
    blob = struct.pack('<8sQQ', b'G3PATCH2', 0, len(writes))
    for offset, data, _ in writes:
        blob += struct.pack('<QQ', offset, len(data)) + data
    Path(path).write_bytes(blob)


def load_eboot(game_dir):
    """(eboot bytes the patches can be checked against, or None; notes; why not) for 1.03: the
    checked plain dump or the ELF inside a SELF dump of it."""
    notes = []
    try:
        eboot = (Path(game_dir) / 'eboot.bin').read_bytes()
    except OSError as error:
        eboot = b''
        notes.append(f'cannot read eboot.bin ({error})')
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
            notes.append(f'eboot.bin is a SELF ({digest[:16]}…), checking the ELF inside')
        except ValueError as error:
            notes.append(f'cannot read the SELF eboot.bin ({error})')
    return (eboot if usable else None), notes, f'eboot.bin is not v1.03 ({digest[:16]}…)'


def prepare(game_dir, out_dir, fps='30', resolution='native'):
    """Writes out/patches.bin for the frame rate and the resolution; returns (applied frame rate:
    the rate as text; log lines). Any problem (other eboot build, unexpected bytes) falls back to
    30 FPS / the game's own size without patches; the resolution line is only added when a size
    was asked for."""
    lines = []
    rate = parse_fps(fps)
    if parse_number(fps) is None and str(fps or '').strip():
        lines.append(f'Frame rate: not a number: {fps!r}; using {GAME_FPS}')
    size = parse_resolution(resolution)
    requested = size is not None
    # TLG_FPS_PATCHES="a,b" (measurements): these patches instead of the rate's own.
    names = [n for n in os.environ.get('TLG_FPS_PATCHES', '').split(',') if n in PATCHES]
    groups = {'Frame rate': {n: PATCHES[n] for n in names} or fps_patches(rate),
              'Resolution': resolution_patches(*size) if size else {}}
    writes = {label: [] for label in groups}
    if any(groups.values()):
        eboot, notes, problem = load_eboot(game_dir)
        first = next(label for label, patches in groups.items() if patches)
        lines += [f'{first}: {note}' for note in notes]
        for label, patches in groups.items():
            try:
                if patches and eboot is None:
                    raise ValueError(problem)
                writes[label] = mode_writes(eboot, patches) if patches else []
            except ValueError as error:
                lines.append(f'{label}: {error}: patches not applied')
                groups[label] = {}
    if not groups['Frame rate']:
        rate = GAME_FPS
    if not groups['Resolution']:
        size = None
    write_patch_file(Path(out_dir) / 'patches.bin', writes['Frame rate'] + writes['Resolution'])
    lines += [f'Frame rate patch {what} ({data.hex()})' for _, data, what in writes['Frame rate']]
    lines.append(f'Frame rate: {rate} FPS mode, {len(writes["Frame rate"])} patch writes')
    lines += [f'Resolution patch {what} ({data.hex()})' for _, data, what in writes['Resolution']]
    if requested:
        lines.append(f'Resolution: {f"{size[0]}x{size[1]}" if size else "native"}, '
                     f'{len(writes["Resolution"])} patch writes')
    return str(rate), lines


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('game_dir')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--fps', default='30', help='frame rate; 0 or not a number: the game\'s own (30)')
    p.add_argument('--resolution', default='native', help='WxH; a side that is 0 is worked out in 16:9, both 0: the game\'s own (1920x1080)')
    a = p.parse_args()
    _, lines = prepare(a.game_dir, a.out, a.fps, a.resolution)
    print('\n'.join(lines))


if __name__ == '__main__':
    sys.exit(main())
