from paths import ROOT
import struct
import tempfile
import unittest
from pathlib import Path
import tlg_patches as t


def text_with(names, expected=True):
    """A text segment with each patch's expected bytes (or other bytes) at its offset."""
    text = bytearray(t.TEXT_SIZE)
    for name in names:
        for address, original, _, _ in t.PATCHES[name]:
            offset = address - t.GHIDRA_BASE
            text[offset:offset + len(original)] = original if expected else b'\xcc' * len(original)
    return text


def plain_elf(text):
    data = bytearray(t.TEXT_FILE_OFFSET) + text
    struct.pack_into('<16sHHIQQQIHHHHHH', data, 0,
                     b'\x7fELF\x02\x01\x01\x09', 0xfe10, 62, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, t.TEXT_FILE_OFFSET, 0, 0, len(text), len(text), 0x4000)
    return data


def self_dump(text):
    """The same ELF in a SELF: one plaintext segment, stored at another file offset."""
    data = bytearray(0x200) + text
    data[:4] = t.SELF_MAGIC
    struct.pack_into('<H', data, 24, 1)
    struct.pack_into('<QQQQ', data, 32, 0x800, 0x200, len(text), len(text))
    struct.pack_into('<16sHHIQQQIHHHHHH', data, 64,
                     b'\x7fELF\x02\x01\x01\x09', 0xfe10, 62, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into('<IIQQQQQQ', data, 128, 1, 5, t.TEXT_FILE_OFFSET, 0, 0, len(text), len(text), 0x4000)
    return data


class FrameRatePatchTests(unittest.TestCase):
    def prepare(self, eboot, mode):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'eboot.bin').write_bytes(eboot)
            applied, lines = t.prepare(tmp, tmp, mode)
            return applied, lines, Path(tmp, 'patches.bin').read_bytes()

    def test_self_dump_of_103_gets_the_patches(self):
        # #40: a SELF dump of 1.03 has another sha256 than the plain dump, but the same code.
        applied, lines, blob = self.prepare(self_dump(text_with(t.MODES['60'])), '60')
        self.assertEqual(applied, '60')
        self.assertIn('Frame rate: 60 FPS mode, 4 patch writes', lines)
        self.assertEqual(struct.unpack_from('<8sQQ', blob), (b'G3PATCH2', 0, 4))

    def test_self_dump_of_another_build_stays_at_30(self):
        applied, lines, blob = self.prepare(self_dump(text_with(t.MODES['unlocked'], expected=False)), 'unlocked')
        self.assertEqual(applied, '30')
        self.assertEqual(struct.unpack_from('<8sQQ', blob), (b'G3PATCH2', 0, 0))

    def test_unreadable_self_stays_at_30(self):
        applied, lines, _ = self.prepare(t.SELF_MAGIC + bytes(60), '60')
        self.assertEqual(applied, '30')
        self.assertTrue(any(line.startswith('Frame rate: cannot read the SELF') for line in lines))

    def test_plain_elf_with_another_hash_stays_at_30(self):
        # Unchanged: a plain ELF is only patched when it is the checked 1.03 dump.
        applied, lines, _ = self.prepare(plain_elf(text_with(t.MODES['60'])), '60')
        self.assertEqual(applied, '30')
        self.assertTrue(any('is not v1.03' in line for line in lines))

    def test_30_writes_an_empty_patch_file(self):
        applied, lines, blob = self.prepare(b'', '30')
        self.assertEqual((applied, struct.unpack_from('<8sQQ', blob)), ('30', (b'G3PATCH2', 0, 0)))


class ModTitleIdTests(unittest.TestCase):
    EU_XML = """<?xml version="1.0"?>
<Patch>
  <TitleID><ID>CUSA03745</ID></TitleID>
  <Metadata Title="The Last Guardian" Name="Test" Author="x" PatchVer="1.0" AppVer="01.03" AppElf="eboot.bin" isEnabled="true">
    <PatchList><Line Type="bytes" Address="0x00401000" Value="90"/></PatchList>
  </Metadata>
</Patch>"""

    def test_eu_title_id_is_accepted(self):
        # The EU disc is CUSA03745 (tlg_run.py LANGUAGES_BY_TITLE); a cheat file scoped to it
        # must not be silently filtered out by TITLE_IDS.
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'eu.xml').write_text(self.EU_XML)
            found = t.mod_patches.external_patches(tmp, '01.03', t.TITLE_IDS)
            self.assertEqual([key for key, _, _ in found], ['eu.xml/Test'])


if __name__ == '__main__':
    unittest.main()


def resolution_elf(expected=True):
    """An ELF whose one PT_LOAD maps image offset 0 up to the mode table, with the bytes the
    resolution patches expect (or other bytes) in place."""
    size = t.RESOLUTION_ENTRY - t.GHIDRA_BASE + 0x100
    image = bytearray(size)
    for address, original in ((t.RESOLUTION_ENTRY, t.RESOLUTION_EXPECTED),
                               (t.HOR_PLUS_CALL, t.HOR_PLUS_CALL_EXPECTED),
                               (t.HOR_PLUS_BLOCK, t.HOR_PLUS_BLOCK_EXPECTED),
                               (t.UI_SIZE, t.UI_SIZE_EXPECTED),
                               (t.GUIDE_SCALE, t.GUIDE_SCALE_EXPECTED),
                               (t.SUBTITLE_SCALE, t.SUBTITLE_SCALE_EXPECTED),
                               (t.GARLIC_SIZE, t.GARLIC_SIZE_EXPECTED)):
        offset = address - t.GHIDRA_BASE
        image[offset:offset + len(original)] = original if expected else b'\xcc' * len(original)
    return plain_elf(image)


class ResolutionPatchTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(t.parse_resolution('3840x1600'), (3840, 1600))
        self.assertEqual(t.parse_resolution(' 3440 X 1440'), (3440, 1440))
        for value in (None, '', '1920x1080', 'native', '0x1080', '70000x1080'):
            self.assertIsNone(t.parse_resolution(value))

    def test_16_9_changes_only_the_mode(self):
        writes = t.resolution_writes(resolution_elf(), (2560, 1440))
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][1][:8], struct.pack('<4H', 2560, 1440, 2560, 1440))

    def test_gpu_heap(self):
        (offset, data, _), = t.garlic_writes(resolution_elf())
        self.assertEqual(offset, t.GARLIC_SIZE - t.GHIDRA_BASE)
        self.assertEqual(data, bytes.fromhex('41bf') + struct.pack('<I', (2816 + t.GARLIC_EXTRA_MB) << 20))
        with self.assertRaises(ValueError):
            t.garlic_writes(resolution_elf(expected=False))

    def test_ultrawide_gets_hor_plus_and_a_wider_ui(self):
        writes = t.resolution_writes(resolution_elf(), (3840, 1600))
        offsets = {offset: data for offset, data, _ in writes}
        self.assertEqual(len(writes), 6)
        self.assertEqual(offsets[t.UI_SIZE - t.GHIDRA_BASE], struct.pack('<4i', 2592, 1080, 2592, 1080))
        self.assertEqual(offsets[t.GUIDE_SCALE - t.GHIDRA_BASE],
                         struct.pack('<4f', 1 / 2592, 1 / 1080, -32, 16 / 2592))
        self.assertEqual(offsets[t.SUBTITLE_SCALE - t.GHIDRA_BASE], struct.pack('<2f', 1 / 2592, 1 / 1080))
        block = offsets[t.HOR_PLUS_BLOCK - t.GHIDRA_BASE]
        self.assertEqual(len(block), len(t.HOR_PLUS_BLOCK_EXPECTED))
        self.assertIn(struct.pack('<f', 1600 / 3840), block)

    def test_other_bytes_are_refused(self):
        with self.assertRaises(ValueError):
            t.resolution_writes(resolution_elf(expected=False), (3440, 1440))
