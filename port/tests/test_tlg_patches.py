from paths import ROOT
import struct
import tempfile
import unittest
from pathlib import Path
import tlg_patches as t

TABLE = t.resolution_patches(1, 1)['resolution'][0]     # (address, original bytes, ...)


def text_with(*groups, expected=True):
    """A text segment with each patch's expected bytes (or other bytes) at its offset."""
    text = bytearray(t.TEXT_SIZE)
    for patches in groups:
        for entries in patches.values():
            for address, original, _, _ in entries:
                offset = address - t.GHIDRA_BASE
                if offset + len(original) <= t.TEXT_SIZE:      # the mode table is in the data segment
                    text[offset:offset + len(original)] = original if expected else b'\xcc' * len(original)
    return text


def plain_elf(text):
    data = bytearray(t.TEXT_FILE_OFFSET) + text
    struct.pack_into('<16sHHIQQQIHHHHHH', data, 0,
                     b'\x7fELF\x02\x01\x01\x09', 0xfe10, 62, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, t.TEXT_FILE_OFFSET, 0, 0, len(text), len(text), 0x4000)
    return data


def self_dump(text, table=None, kind=1):
    """The same ELF in a SELF: one plaintext segment, stored at another file offset.
    table: bytes of a second segment of that type holding the mode table at its address."""
    count = 2 if table is not None else 1
    base = 32 + count * 32
    data = bytearray(0x200) + text + (table or b'')
    data[:4] = t.SELF_MAGIC
    struct.pack_into('<H', data, 24, count)
    struct.pack_into('<QQQQ', data, 32, 0x800, 0x200, len(text), len(text))
    struct.pack_into('<16sHHIQQQIHHHHHH', data, base,
                     b'\x7fELF\x02\x01\x01\x09', 0xfe10, 62, 1, 0, 64, 0, 0, 64, 56, count, 0, 0, 0)
    struct.pack_into('<IIQQQQQQ', data, base + 64, 1, 5, t.TEXT_FILE_OFFSET, 0, 0, len(text), len(text), 0x4000)
    if table is not None:
        struct.pack_into('<QQQQ', data, 64, 0x800 | (1 << 20), 0x200 + len(text), len(table), len(table))
        struct.pack_into('<IIQQQQQQ', data, base + 64 + 56, kind, 6, t.TEXT_FILE_OFFSET + len(text),
                         TABLE[0] - t.GHIDRA_BASE, 0, len(table), len(table), 0x4000)
    return data


def mode_table():
    """A data segment holding the mode table's default entry and the bytes around it."""
    return TABLE[1] + b'\xaa' * 8


def writes_of(blob):
    count, = struct.unpack_from('<Q', blob, 16)
    position, found = 24, []
    for _ in range(count):
        offset, length = struct.unpack_from('<QQ', blob, position)
        found.append((offset, blob[position + 16:position + 16 + length]))
        position += 16 + length
    return found


class PatchTests(unittest.TestCase):
    def prepare(self, eboot, fps='30', resolution='native'):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'eboot.bin').write_bytes(eboot)
            applied, lines = t.prepare(tmp, tmp, fps, resolution)
            return applied, lines, Path(tmp, 'patches.bin').read_bytes()

    def build(self, fps='30', resolution='native', table=True):
        size = t.parse_resolution(resolution) or (1, 1)
        eboot = self_dump(text_with(t.fps_patches(t.parse_fps(fps)), t.resolution_patches(*size)),
                          mode_table() if table else None)
        return self.prepare(eboot, fps, resolution)

    # Frame rate
    def test_self_dump_of_103_gets_the_patches(self):
        # #40: a SELF dump of 1.03 has another sha256 than the plain dump, but the same code.
        applied, lines, blob = self.prepare(self_dump(text_with(t.fps_patches(60))), '60')
        self.assertEqual(applied, '60')
        self.assertIn('Frame rate: 60 FPS mode, 4 patch writes', lines)
        self.assertEqual(struct.unpack_from('<8sQQ', blob), (b'G3PATCH2', 0, 4))

    def test_self_dump_of_another_build_stays_at_30(self):
        applied, lines, blob = self.prepare(self_dump(text_with(t.fps_patches(90), expected=False)), '90')
        self.assertEqual(applied, '30')
        self.assertEqual(struct.unpack_from('<8sQQ', blob), (b'G3PATCH2', 0, 0))

    def test_unreadable_self_stays_at_30(self):
        applied, lines, _ = self.prepare(t.SELF_MAGIC + bytes(60), '60')
        self.assertEqual(applied, '30')
        self.assertTrue(any(line.startswith('Frame rate: cannot read the SELF') for line in lines))

    def test_plain_elf_with_another_hash_stays_at_30(self):
        # Unchanged: a plain ELF is only patched when it is the checked 1.03 dump.
        applied, lines, _ = self.prepare(plain_elf(text_with(t.fps_patches(60))), '60')
        self.assertEqual(applied, '30')
        self.assertTrue(any('is not v1.03' in line for line in lines))

    def test_30_writes_an_empty_patch_file(self):
        applied, lines, blob = self.prepare(b'', '30')
        self.assertEqual((applied, struct.unpack_from('<8sQQ', blob)), ('30', (b'G3PATCH2', 0, 0)))

    def test_any_rate_moves_the_dt_snap(self):
        applied, lines, blob = self.build('144')
        self.assertEqual(applied, '144')
        self.assertEqual([data for _, data in writes_of(blob)][1:],
                         [t.f32(1.05 / 144), t.f32(1 / 144), t.f32(0.95 / 144)])
        # 60 is the old patch: 0.0175, 1/60, 0.0158333
        self.assertEqual([entry[2] for entry in t.fps_patches(60)['dt_snap']],
                         [t.f32(0.0175), t.f32(1 / 60), t.f32(0.0158333331)])

    def test_the_games_own_rate(self):
        # 30, 0, empty and not a number are the game as on PS4: nothing is written.
        for value in ('30', '0', '', None, '-5', 'fast', 'unlocked'):
            applied, lines, blob = self.prepare(b'', value)
            self.assertEqual((applied, writes_of(blob)), ('30', []), value)
        self.assertTrue(any('not a number' in line for line in self.prepare(b'', 'fast')[1]))

    def test_fractional_rates_are_rounded(self):
        for value, expected in (('59.94', 60), ('144.4', 144), ('59,6', 60), ('0.4', 30), (90.5, 90), ('7', 7), ('1000', 1000)):
            self.assertEqual(t.parse_fps(value), expected, value)
        applied, lines, blob = self.build('59.94')
        self.assertEqual(applied, '60')

    # Resolution
    def test_native_has_no_resolution_patch(self):
        applied, lines, blob = self.build('30', 'native')
        self.assertEqual(writes_of(blob), [])
        self.assertFalse(any(line.startswith('Resolution') for line in lines))

    def test_resolution_writes_the_mode_and_the_nops(self):
        applied, lines, blob = self.build('30', '1280x720')
        self.assertEqual(writes_of(blob), [
            (TABLE[0] - t.GHIDRA_BASE, bytes.fromhex('00 05 d0 02 00 05 d0 02') + bytes(8)),
            (0x1c4fa6a - t.GHIDRA_BASE, b'\x90' * 23)])
        self.assertIn('Resolution: 1280x720, 2 patch writes', lines)

    def test_any_size_and_the_rate_together(self):
        applied, lines, blob = self.build('60', '2560 x 1080')
        self.assertEqual(applied, '60')
        self.assertEqual(len(writes_of(blob)), 4 + 2)
        self.assertEqual(writes_of(blob)[4][1][:8], struct.pack('<4H', 2560, 1080, 2560, 1080))
        self.assertIn('Resolution: 2560x1080, 2 patch writes', lines)

    def test_mode_table_in_a_relro_segment(self):
        # PT_SCE_RELRO (0x61000010): read-only data the loader maps too.
        eboot = self_dump(text_with(t.resolution_patches(1, 1)), mode_table(), kind=0x61000010)
        applied, lines, blob = self.prepare(eboot, '30', '640x360')
        self.assertIn('Resolution: 640x360, 2 patch writes', lines)

    def test_mode_table_outside_the_image_keeps_native_and_the_rate(self):
        applied, lines, blob = self.build('60', '3840x2160', table=False)
        self.assertEqual(applied, '60')
        self.assertEqual(len(writes_of(blob)), 4)
        self.assertIn('Resolution: native, 0 patch writes', lines)
        self.assertTrue(any('is not in the eboot image' in line for line in lines))

    def test_mode_table_in_an_unmapped_segment_stays_native(self):
        eboot = self_dump(text_with(t.resolution_patches(1, 1)), mode_table(), kind=0x61000000)
        applied, lines, blob = self.prepare(eboot, '30', '640x360')
        self.assertIn('Resolution: native, 0 patch writes', lines)

    def test_other_build_stays_native(self):
        eboot = self_dump(text_with(t.resolution_patches(1, 1), expected=False), mode_table())
        applied, lines, blob = self.prepare(eboot, '30', '1280x720')
        self.assertEqual(writes_of(blob), [])
        self.assertIn('Resolution: native, 0 patch writes', lines)

    def test_plain_elf_with_another_hash_stays_native(self):
        applied, lines, blob = self.prepare(plain_elf(text_with(t.resolution_patches(1, 1))), '30', '1280x720')
        self.assertEqual(writes_of(blob), [])
        self.assertTrue(any(line.startswith('Resolution: eboot.bin is not v1.03') for line in lines))

    def test_a_missing_side_follows_in_16_9(self):
        for value, expected in (('1280x0', (1280, 720)), ('0x720', (1280, 720)), ('x720', (1280, 720)),
                                ('1280x', (1280, 720)), ('1280xabc', (1280, 720)), ('1000x0', (1000, 562)),
                                ('0x1440', (2560, 1440)), ('70000x720', (1280, 720)), ('1280x70000', (1280, 720)),
                                ('1280x1000', (1280, 1000)), (' 2560 x 1080 ', (2560, 1080))):
            self.assertEqual(t.parse_resolution(value), expected, value)

    def test_the_games_own_size(self):
        # Both sides 0 or not sizes, or 1920x1080 itself: nothing is written.
        for value in ('0x0', 'x', '', None, 'native', '8k', '1280', '70000x70000', '-5x-5', '1920x1080', '0x1080', '1920x0'):
            applied, lines, blob = self.prepare(b'', '30', value)
            self.assertEqual((t.parse_resolution(value), writes_of(blob)), (None, []), value)
            self.assertFalse(any(line.startswith('Resolution') for line in lines), value)

    def test_one_side_patches_the_derived_size(self):
        applied, lines, blob = self.build('30', '0x720')
        self.assertIn('Resolution: 1280x720, 2 patch writes', lines)
        self.assertEqual(writes_of(blob)[0][1][:8], struct.pack('<4H', 1280, 720, 1280, 720))


if __name__ == '__main__':
    unittest.main()
