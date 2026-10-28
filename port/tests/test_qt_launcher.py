# SPDX-License-Identifier: GPL-2.0-or-later
"""The Qt launcher (launcher/tlg_launcher_qt.py + launcher/qt) adapted to The Last Guardian: texts in
both languages with nothing of inFAMOUS left, the game start path (tlg_run), the screens' writes
(settings.json and tlg.ini, in temporary folders only) and close-on-play / reopen."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from paths import ROOT
sys.path.insert(0, str(ROOT / 'launcher'))
import tlg_run  # noqa: E402
from qt import logic  # noqa: E402

try:
    from PySide6.QtCore import QCoreApplication
    from qt.backend import Backend
    from qt.controls import Controls
    from qt.graphics import Graphics, SECTIONS
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

QT_DIR = ROOT / 'launcher' / 'qt'
FOREIGN = re.compile(r'inFAMOUS|Seattle|Delsin|ISS_|iss_pc|CUSA00223|graffiti|grafite|Conduit|karma', re.I)


def qml_text():
    return '\n'.join(p.read_text(encoding='utf-8') for p in (QT_DIR / 'qml' / 'Launcher').glob('*.qml'))


class TextTests(unittest.TestCase):
    def setUp(self):
        self.strings = logic.load_strings()

    def test_every_string_is_bilingual_and_about_this_game(self):
        for key, entry in self.strings.items():
            self.assertTrue(entry.get('en') and entry.get('pt'), key)
            self.assertIsNone(FOREIGN.search(entry['en'] + entry['pt']), key)

    def test_every_key_the_screens_ask_for_exists(self):
        tk = logic.tk_text()
        keys = set(re.findall(r'Theme\.tr\("([a-z0-9_]+)"\)', qml_text()))
        for path in QT_DIR.glob('*.py'):
            keys |= set(re.findall(r"\bt_?\('([a-z0-9_]+)'", path.read_text(encoding='utf-8')))
        keys |= {'gfx_what_' + k for k in ('display_mode', 'vsync', 'show_fps', 'frame_rate', 'gpu_readbacks',
                                           'native_audio', 'skip_logos', 'close_on_play', 'reopen_launcher',
                                           'vram_budget_mb')}
        keys |= {'fps_' + k for k in tlg_run.FRAME_RATES} | {'readbacks_' + k for k in '012'}
        keys |= {'gfx_preset_' + p for p in ('performance', 'balanced', 'quality', 'ps4')}
        missing = sorted(k for k in keys if not k.endswith('_') and k not in self.strings and k not in tk)
        self.assertEqual([], missing)

    def test_no_foreign_names_in_the_code(self):
        for path in list(QT_DIR.rglob('*.py')) + list((QT_DIR / 'qml').rglob('*.qml')) + \
                [ROOT / 'launcher' / n for n in ('tlg_launcher_qt.py', 'preset_share.py', 'userdata.py',
                                                 'savemanager.py', 'padsettings.py', 'update_install.py')]:
            text = path.read_text(encoding='utf-8')
            for word in ('inFAMOUS', 'infamous', 'ISS_', 'iss_pc', 'CUSA00223', 'Seattle'):
                self.assertNotIn(word, text, f'{word} in {path.name}')


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = mock.patch.dict(os.environ, {'TLG_USER_DIR': str(self.root / 'user')})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('TLG_LANGUAGE', 'TLG_READBACKS', 'TLG_STICK_DEADZONE', 'TLG_DEFERRED_READBACK'):
            os.environ.pop(name, None)

    def test_game_language_auto_follows_the_system_and_the_disc(self):
        us = {'game_dir': ''}
        self.assertEqual(['auto', 'en', 'pt_BR', 'es_LA', 'fr_CA'], tlg_run.game_language_choices(us))
        self.assertEqual('pt_BR', tlg_run.resolve_game_language(dict(us, game_language='auto'), {'LANG': 'pt_BR.UTF-8'}))
        self.assertEqual('es_LA', tlg_run.resolve_game_language(dict(us, game_language='auto'), {'LANG': 'es_ES.UTF-8'}))
        self.assertEqual('en', tlg_run.resolve_game_language(dict(us, game_language='auto'), {'LANG': 'ja_JP'}))
        self.assertEqual('fr_CA', tlg_run.resolve_game_language(dict(us, game_language='fr_CA')))
        self.assertEqual('en', tlg_run.resolve_game_language(dict(us, game_language='de')))   # not on the US disc
        with mock.patch.object(tlg_run.shader_cache, 'title_id', return_value='CUSA03745'):
            eu = {'game_dir': '/eu'}
            self.assertEqual('pt_PT', tlg_run.resolve_game_language(dict(eu, game_language='auto'), {'LANG': 'pt_BR'}))
            self.assertIn('de', tlg_run.game_language_choices(eu))
        with mock.patch.object(tlg_run.shader_cache, 'title_id', return_value='CUSA04936'):
            kr = {'game_dir': '/kr'}   # #46: Korean disc
            self.assertEqual(['auto', 'en', 'ko', 'zh_TW', 'zh_CN'], tlg_run.game_language_choices(kr))
            self.assertEqual('ko', tlg_run.resolve_game_language(dict(kr, game_language='auto'), {'LANG': 'ko_KR.UTF-8'}))
            self.assertEqual('zh_TW', tlg_run.resolve_game_language(dict(kr, game_language='auto'), {'LANG': 'zh_TW.UTF-8'}))
            self.assertEqual(9, tlg_run.game_languages('/kr')['ko'])

    def test_build_env_hands_the_launcher_choices_to_the_game(self):
        settings = dict(tlg_run.DEFAULT_SETTINGS, game_dir='', game_language='pt_BR', gpu_readbacks='0',
                        stick_deadzone=15, deferred_readback=True)
        env = tlg_run.build_env(settings)
        self.assertEqual(('0', '0.15', '17'), (env['TLG_READBACKS'], env['TLG_STICK_DEADZONE'], env['TLG_LANGUAGE']))
        self.assertEqual('1', env['TLG_DEFERRED_READBACK'])
        self.assertEqual('1', env['TLG_READBACK_LINEAR'])         # the port default stays
        self.assertEqual(str(self.root / 'user' / 'tlg.ini'), env['TLG_CONFIG'])
        with mock.patch.dict(os.environ, {'TLG_READBACKS': '1', 'TLG_DEFERRED_READBACK': '0'}):
            env = tlg_run.build_env(settings)
        self.assertEqual(('1', '0'), (env['TLG_READBACKS'], env['TLG_DEFERRED_READBACK']))

    def test_launch_writes_the_key_map_of_either_launcher(self):
        settings = dict(tlg_run.DEFAULT_SETTINGS, game_dir=str(self.root / 'game'))
        with mock.patch.object(tlg_run, 'OUT_DIR', self.root / 'out'), \
                mock.patch.object(tlg_run, 'LOG_DIR', self.root / 'out' / 'logs'), \
                mock.patch.object(tlg_run.subprocess, 'Popen'):
            tlg_run.launch(dict(settings, key_map={'cross': 'Q', 'circle': 'Left Shift'}))
            ini = tlg_run.read_ini(self.root / 'user' / 'tlg.ini')
            self.assertEqual('cross=Q', ini['key_map'])
            tlg_run.launch(dict(settings, key_map='r1=Mouse X1'), detached=True)
            self.assertEqual('r1=Mouse X1', tlg_run.read_ini(self.root / 'user' / 'tlg.ini')['key_map'])

    def test_mods_live_in_the_data_folder(self):
        self.assertEqual(self.root / 'user' / 'mods', tlg_run.mods_dir())
        self.assertEqual(self.root / 'user' / 'mods.json', tlg_run.mods_config())
        self.assertEqual(self.root / 'user', tlg_run.USER_DIR)   # the Tk launcher's name for it


class EntryTests(unittest.TestCase):
    def test_reopen_after_waits_for_the_game_then_opens_the_window(self):
        sys.path.insert(0, str(ROOT / 'launcher'))
        import tlg_launcher_qt
        with mock.patch.object(sys, 'argv', ['x', '--reopen-after', '123']), \
                mock.patch.object(tlg_launcher_qt.tlg_run, 'wait_for_exit') as wait, \
                mock.patch('qt.app.App') as app, mock.patch.object(tlg_launcher_qt.os, '_exit') as quit_:
            app.return_value.run.return_value = 0
            tlg_launcher_qt.main()
        wait.assert_called_once_with(123)
        app.return_value.run.assert_called_once()
        quit_.assert_called_once_with(0)


@unittest.skipUnless(HAVE_QT, 'PySide6 not installed')
class ScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = mock.patch.dict(os.environ, {'TLG_USER_DIR': str(self.root / 'user'),
                                               'XDG_CONFIG_HOME': str(self.root / 'cfg')})
        patcher.start()
        self.addCleanup(patcher.stop)
        probes = {'gpu': lambda: ('GPU', '1.3'), 'pad': lambda: 'Xbox', 'problems': lambda: [], 'cache': lambda: 0,
                  'save': lambda: None, 'news': lambda: [], 'version': lambda: 'v1',
                  'saves': {'running': lambda: False, 'scan': lambda: [], 'open': lambda p: None}}
        settings = dict(tlg_run.DEFAULT_SETTINGS, game_dir='/g', ui_language='en_US')
        self.backend = Backend(settings=settings, probes=probes)
        self.graphics = Graphics(self.backend, {'vram': lambda: 6144})
        self.controls = Controls(self.backend)
        self.ini = self.root / 'user' / 'tlg.ini'

    def saved(self):
        return json.loads(tlg_run.config_path().read_text(encoding='utf-8'))

    def test_graphics_rows_exist_and_write_where_the_game_reads(self):
        rows = {r['id'] for r in self.graphics.model.rows} if hasattr(self.graphics.model, 'rows') else None
        for _, ids in SECTIONS:
            for rid in ids:
                self.assertTrue(rid.startswith('s:') or any(i.id == rid for i in logic.backports_table.ITEMS), rid)
                if rows is not None:
                    self.assertIn(rid, rows)
        self.graphics.setValue('menu:smaa', '1')
        self.assertIn('smaa=1', self.ini.read_text(encoding='utf-8'))
        self.graphics.setValue('s:frame_rate', '60')
        self.graphics.setValue('s:vram_budget_mb', '99999')
        saved = self.saved()
        self.assertEqual(('60', 24000), (saved['frame_rate'], saved['vram_budget_mb']))
        self.graphics.setValue('TLG_BACKGROUND_WARMUP', '0')
        self.assertIs(False, self.saved()['background_warmup'])
        self.graphics.applyPreset('ps4')
        self.assertIn('fps_limit=30', self.ini.read_text(encoding='utf-8'))
        self.assertIn('True to PS4', self.graphics.presetText)

    def test_controls_keep_the_tk_key_map_and_the_mouse_in_sync(self):
        self.backend.settings['key_map'] = {'cross': 'Q'}
        self.assertEqual('cross=Q', self.controls.savedKeyMap)
        self.controls.setDraft('cross=Q,r1=Mouse X1|3')
        self.assertTrue(self.controls.draftValid)
        self.controls.applyKeyMap()
        self.assertEqual({'cross': 'Q', 'r1': 'Mouse X1|3'}, self.saved()['key_map'])
        rows = {r['name']: r for r in self.controls.keyRows}
        self.assertTrue(any(r['changed'] for r in rows.values()))
        self.assertEqual('E | Mouse Middle', [r for r in self.controls.keyRows if not r['fixed']][2]['keys'])
        self.controls.setValue('m:mouse_sensitivity', '2.5')
        self.assertEqual('2.50', tlg_run.read_ini(self.ini)['mouse_sensitivity'])
        self.assertEqual(2.5, self.backend.settings['mouse_sensitivity'])   # launch() writes it back at Play
        self.controls.toggleMouse()
        self.assertIs(False, self.saved()['mouse_enabled'])
        self.controls.clearKeyMap()
        self.assertEqual({}, self.saved()['key_map'])

    def test_game_language_box(self):
        options = [o['value'] for o in self.backend.gameLanguageOptions]
        self.assertEqual('auto', options[0])
        self.backend.setGameLanguage('fr_CA')
        self.assertEqual('fr_CA', self.saved()['game_language'])
        self.backend.setGameLanguage('xx')                      # not a language: ignored
        self.assertEqual('fr_CA', self.backend.settings['game_language'])

    def test_close_on_play_then_reopen_when_the_game_exits(self):
        self.backend.settings.update(close_on_play=True, reopen_launcher=True)
        with mock.patch('qt.backend.QTimer.singleShot') as single, mock.patch.object(self.backend._tail_timer, 'start'):
            self.backend._on_game_started(str(self.root / 'run.log'))
        self.assertEqual(2000, single.call_args.args[0])
        self.backend.process = mock.Mock(pid=4321)
        self.backend.process.poll.return_value = None
        with mock.patch.object(tlg_run, 'reopen_after') as reopen, mock.patch.object(self.app, 'quit'):
            self.backend._quit_app()
        reopen.assert_called_once_with(4321)
        self.backend.settings['close_on_play'] = False
        with mock.patch('qt.backend.QTimer.singleShot') as single, mock.patch.object(self.backend._tail_timer, 'start'):
            self.backend._on_game_started(str(self.root / 'run.log'))
        single.assert_not_called()

    def test_play_uses_the_detached_launch(self):
        self.backend._ready = True
        with mock.patch.object(tlg_run, 'prepare'), \
                mock.patch.object(tlg_run, 'launch', return_value=(mock.Mock(wait=lambda: 0), self.root / 'l.log')) as launch, \
                mock.patch('qt.backend.threading.Thread') as thread:
            self.backend.play()
            thread.call_args.kwargs['target']()
        self.assertIs(True, launch.call_args.kwargs['detached'])


if __name__ == '__main__':
    unittest.main()
