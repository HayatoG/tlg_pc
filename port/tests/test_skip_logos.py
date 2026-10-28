from paths import ROOT
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import tlg_patches as t

sys.path.insert(0, str(ROOT / 'launcher'))
import tlg_run

TEXT_VADDR = 0x200000   # image offsets of the three logo enables are 0x231d79..0x231e45


def fixture_elf(enabled=1):
    """A minimal ELF with one PT_LOAD whose bytes hold the three `mov dword [rsp+disp], 1`."""
    phoff, size = 0x40, 0x40000
    header = bytearray(0x40)
    header[:4] = b'\x7fELF'
    struct.pack_into('<Q', header, 0x20, phoff)
    struct.pack_into('<HH', header, 0x36, 0x38, 1)
    data = bytearray(header) + struct.pack('<IIQQQQQQ', 1, 5, 0x1000, TEXT_VADDR, TEXT_VADDR, size, size, 0x1000)
    data += bytes(0x1000 - len(data)) + bytes(size)
    for address, displacement in t.LOGO_MOVS.items():
        at = 0x1000 + address - t.GHIDRA_BASE - TEXT_VADDR
        data[at:at + 11] = bytes.fromhex('c78424') + struct.pack('<Ii', displacement, enabled)
    return bytes(data)


class SkipLogosTests(unittest.TestCase):
    def test_clears_the_three_enables(self):
        writes = t.logo_writes(fixture_elf())
        self.assertEqual([offset for offset, _, _ in writes],
                         [address - t.GHIDRA_BASE for address, _ in t.LOGO_ENABLES])
        for (_, data, _), displacement in zip(writes, t.LOGO_MOVS.values()):
            self.assertEqual(data, bytes.fromhex('c78424') + struct.pack('<Ii', displacement, 0))

    def test_other_bytes_fail_closed(self):
        for elf in (fixture_elf(enabled=0), b'another build', None):
            with self.assertRaises(ValueError):
                t.logo_writes(elf)

    def test_prepare_applies_only_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'eboot.bin').write_bytes(fixture_elf())
            with patch.dict(os.environ, {'TLG_SKIP_LOGOS': ''}):
                _, lines = t.prepare(tmp, tmp, '30')
                self.assertFalse([line for line in lines if 'skip logos' in line])
                _, lines = t.prepare(tmp, tmp, '30', skip_logos=True)
                self.assertEqual(len([line for line in lines if 'skip logos' in line]), 3)
            with patch.dict(os.environ, {'TLG_SKIP_LOGOS': '1'}):
                _, lines = t.prepare(tmp, tmp, '30')
                self.assertEqual(len([line for line in lines if 'skip logos' in line]), 3)

    def test_prepare_reports_another_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'eboot.bin').write_bytes(b'another build')
            _, lines = t.prepare(tmp, tmp, '30', skip_logos=True)
            self.assertTrue(any(line.startswith('Skip logos: ') for line in lines))

    def test_launcher_setting(self):
        self.assertIs(tlg_run.DEFAULT_SETTINGS['skip_logos'], False)


if __name__ == '__main__':
    unittest.main()
