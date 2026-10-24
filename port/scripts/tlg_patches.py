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
"""
import argparse
import hashlib
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mod_patches

TITLE_IDS = {'CUSA03627', 'CUSA03745', 'CUSA04936', 'CUSA04943'}   # US, EU, KR, CN (tlg_run.py LANGUAGES_BY_TITLE)
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
    # Material/cloth update null pointer guard (0x128c100, loop header at 0x128c161..0x128c1a4):
    # At 60+ FPS on fast multi-core CPUs, worker threads can run 0x128c100 before streaming
    # populates the pointer table at [r12 + 0x28] (fault at 0x28c193) or an element entry at
    # [rcx + rax*8] (fault at 0x28c197 reading [rax + 0x28] right before test r15, r15).
    'cloth_null_guard': [
        (0x128c161,
         bytes.fromhex(
             '6666666666662e0f1f840000000000'
             '4d8b7424484863c7498b4c242841bb00000000488d1c4048c1e306'
             '4963841ea0000000488b04c14c8b7828488945904d85ff7479'
         ),
         bytes.fromhex(
             '49837c2428000f84f90400000f1f00'
             '4d8b74244889f8498b4c24284531db8d1c4048c1e306'
             '4963841ea0000000488b04c1488945904885c074074c8b78284d85ff7479'
         ),
         'cloth update null table/element guard at 0x28c161..0x28c1a4'),
    ],
}

MODES = {
    '30': [],
    # max_fps_double/max_fps_off are left out: 60 and unlocked were reached without them
    # (game+0x180 is no frame limiter in the tested scenes; its reader is not found yet).
    # TLG_FPS_PATCHES=flip_rate_60,max_fps_off tries them.
    '60': ['flip_rate_60', 'dt_snap_60', 'cloth_null_guard'],
    'unlocked': ['flip_rate_60', 'cloth_null_guard'],
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


def prepare(game_dir, out_dir, mode, mods_dir=None, mods_config=None):
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
    writes = fps_writes + mod_writes
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
    a = p.parse_args()
    _, lines = prepare(a.game_dir, a.out, a.mode, a.mods_dir, a.mods_config)
    print('\n'.join(lines))


if __name__ == '__main__':
    sys.exit(main())
