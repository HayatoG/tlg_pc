"""Launcher presentation regression checks; no game process or real settings are used."""
import copy
from collections import Counter
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import tlg_launcher as ui


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def contrast(root, foreground, background):
    def luminance(color):
        channels = [value / 65535 for value in root.winfo_rgb(color)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    low, high = sorted((luminance(foreground), luminance(background)))
    return (high + 0.05) / (low + 0.05)


class LauncherUITest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ui.tk.Tk()
        except ui.tk.TclError as error:
            self.skipTest(f'Tk display unavailable: {error}')
        self.root.withdraw()
        output = Path(__file__).resolve().parents[1] / 'out'
        output.mkdir(exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(self.folder.cleanup)
        self.user = Path(self.folder.name)
        self.settings = copy.deepcopy(ui.tlg_run.DEFAULT_SETTINGS)
        self.settings['ui_language'] = 'pt_BR'
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        for patch in (
            mock.patch.object(ui.tlg_run, 'load_settings', return_value=self.settings),
            mock.patch.object(ui.tlg_run, 'config_path', return_value=self.user / 'settings.json'),
            mock.patch.object(ui.tlg_run, 'USER_DIR', self.user),
            mock.patch.object(ui.tlg_run, 'check_game', return_value=[]),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.app = ui.Launcher(self.root)
        self.addCleanup(self.close_root)
        self.root.deiconify()
        self.root.update()

    def close_root(self):
        owners = [self.root, *widgets(self.root)]
        for timer in self.root.tk.call('after', 'info'):
            command = str(self.root.tk.call('after', 'info', timer)[0])
            owner = next((widget for widget in owners if command in (widget._tclCommands or [])), self.root)
            owner.after_cancel(timer)
        self.root.destroy()

    def test_navigation_language_rebuild_and_session_log(self):
        self.app.append('Session preserved — Trico')
        for key, button in self.app.nav_buttons.items():
            button.invoke()
            self.assertEqual(self.app.current_page, key)
            self.assertEqual(button.cget('style'), 'Selected.Nav.TButton')
        self.app.settings['ui_language'] = 'en_US'
        self.app.build()
        self.root.update()
        self.assertEqual(self.app.current_page, 'journal')
        self.assertIn('Session preserved — Trico', self.app.log.get('1.0', 'end'))
        self.assertEqual(self.app.nav_buttons['setup'].cget('text'), 'Game & language')
        self.app.lines.put('New session output')
        self.app.pump()
        self.assertIn('New session output', self.app.log.get('1.0', 'end'))
        self.assertFalse(self.errors)

    def test_all_settings_remain_available_and_existing_callbacks_save(self):
        expected = {'game_dir', 'system_lib_dir', 'native_audio', 'vsync', 'show_fps',
                    'vram_budget_mb', 'mouse_enabled', 'mouse_invert_y', 'mouse_sensitivity'}
        self.assertEqual(set(self.app.vars), expected)
        self.assertEqual(set(self.app.ini_vars), set(ui.INI_DEFAULTS) - {'rcas', 'cas'})
        self.app.vars['vram_budget_mb'].set(7000)
        self.app.vars['mouse_sensitivity'].set(1.5)
        self.app.changed()
        saved_file = json.loads((self.user / 'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(saved_file['vram_budget_mb'], 7000)
        self.assertEqual(saved_file['mouse_sensitivity'], 1.5)
        self.app.ini_vars['smaa'].set(True)
        self.app.filters_changed()
        self.assertEqual(ui.tlg_run.read_ini(self.user / 'tlg.ini')['smaa'], '1')
        self.assertFalse(self.errors)

    def test_historical_control_inventory_has_no_missing_controls(self):
        # This fixture was collected from the original UI at source_commit, not the new layout.
        baseline = json.loads((Path(__file__).parent / 'data' / 'launcher_ui_legacy.json').read_text(
            encoding='utf-8'))['inventory']
        self.app.settings['ui_language'] = 'en_US'
        self.app.build()
        actual = {'vars': sorted(self.app.vars), 'filters': sorted(self.app.ini_vars),
                  'buttons': [], 'checks': [], 'combos': [], 'spins': [], 'links': []}
        for widget in widgets(self.root):
            if isinstance(widget, ui.ttk.Button):
                actual['buttons'].append(str(widget.cget('text')).removeprefix('▷  '))
            if isinstance(widget, ui.ttk.Checkbutton):
                actual['checks'].append(str(widget.cget('text')))
            if isinstance(widget, ui.ttk.Combobox):
                actual['combos'].append(list(widget.cget('values')))
            if isinstance(widget, ui.ttk.Spinbox):
                actual['spins'].append([str(widget.cget(key)) for key in ('from', 'to', 'increment')])
            if isinstance(widget, ui.ttk.Label) and widget.bind('<Button-1>'):
                actual['links'].append(str(widget.cget('text')))
        self.app.remap_dialog()
        actual['remap_entries'] = sum(type(widget) == ui.ttk.Entry
                                      for widget in widgets(self.app.remap_window))
        actual['remap_buttons'] = [str(widget.cget('text')) for widget in widgets(self.app.remap_window)
                                   if isinstance(widget, ui.ttk.Button)]
        self.app.mods_dialog()
        actual['mods_buttons'] = [str(widget.cget('text')) for widget in widgets(self.app.mods_window)
                                  if isinstance(widget, ui.ttk.Button)]
        for key, expected in baseline.items():
            with self.subTest(inventory=key):
                if isinstance(expected, int):
                    self.assertEqual(actual[key], expected)
                else:
                    encode = lambda values: Counter(json.dumps(value, sort_keys=True) for value in values)
                    self.assertFalse(encode(expected) - encode(actual[key]))
        self.assertEqual(len(actual['buttons']) - len(baseline['buttons']), 5)  # New navigation only.

    def test_text_contrast_in_normal_focus_selection_and_disabled_states(self):
        style = ui.ttk.Style(self.root)
        states = [tuple(state for state, enabled in zip(('focus', 'readonly', 'disabled'), flags) if enabled)
                  for flags in itertools.product((False, True), repeat=3)]
        for name in ('TEntry', 'TSpinbox', 'TCombobox'):
            for state in states:
                for foreground, background in (('foreground', 'fieldbackground'),
                                               ('selectforeground', 'selectbackground')):
                    with self.subTest(style=name, state=state, pair=foreground):
                        self.assertGreaterEqual(contrast(self.root, style.lookup(name, foreground, state),
                                                         style.lookup(name, background, state)), 4.5)
        for name in ('TLabel', 'Muted.TLabel', 'Eyebrow.TLabel', 'Card.TLabel',
                     'TButton', 'Nav.TButton', 'Selected.Nav.TButton', 'Play.TButton', 'TCheckbutton'):
            for state in ((), ('focus',), ('active',), ('pressed',), ('disabled',)):
                with self.subTest(style=name, state=state):
                    self.assertGreaterEqual(contrast(self.root, style.lookup(name, 'foreground', state),
                                                     style.lookup(name, 'background', state)), 4.5)
        for state in ((), ('selected',)):
            self.assertGreaterEqual(contrast(self.root, style.lookup('TCheckbutton', 'indicatorforeground', state),
                                             style.lookup('TCheckbutton', 'indicatorbackground', state)), 4.5)
        for name in ('TEntry', 'TSpinbox', 'TCombobox'):
            for state in ((), ('focus',), ('readonly', 'focus')):
                self.assertGreaterEqual(contrast(self.root, style.lookup(name, 'bordercolor', state),
                                                 style.lookup(name, 'fieldbackground', state)), 3)
        self.assertGreaterEqual(contrast(self.root, self.app.log.cget('foreground'),
                                         self.app.log.cget('background')), 4.5)
        self.assertGreaterEqual(contrast(self.root, self.app.log.cget('selectforeground'),
                                         self.app.log.cget('selectbackground')), 4.5)
        # Check the actual Tcl popdown listbox, which has a separate palette from ttk.
        popdown = self.root.tk.call('ttk::combobox::PopdownWindow', str(self.app.game_lang_box))
        listbox = str(popdown) + '.f.l'
        for foreground, background in (('-foreground', '-background'),
                                       ('-selectforeground', '-selectbackground')):
            self.assertGreaterEqual(contrast(self.root, self.root.tk.call(listbox, 'cget', foreground),
                                             self.root.tk.call(listbox, 'cget', background)), 4.5)

    def test_every_choice_and_checkbox_uses_the_existing_persistence_callbacks(self):
        for key, choices in (('display_mode', [self.app.t(value) for value in ui.DISPLAY_MODES]),
                             ('frame_rate', [self.app.t('fps_' + value) for value in ui.tlg_run.FRAME_RATES])):
            box = next(widget for widget in widgets(self.root) if isinstance(widget, ui.ttk.Combobox)
                       and list(widget.cget('values')) == choices)
            values = ui.DISPLAY_MODES if key == 'display_mode' else ui.tlg_run.FRAME_RATES
            for index, expected in enumerate(values):
                box.current(index)
                box.event_generate('<<ComboboxSelected>>')
                self.assertEqual(json.loads((self.user / 'settings.json').read_text(encoding='utf-8'))[key], expected)
        for widget in widgets(self.root):
            if isinstance(widget, ui.ttk.Checkbutton):
                variable = str(widget.cget('variable'))
                before = self.root.getvar(variable)
                widget.invoke()
                self.assertNotEqual(self.root.getvar(variable), before)
                key = next((key for key, var in self.app.vars.items() if str(var) == variable), None)
                if key:
                    saved = json.loads((self.user / 'settings.json').read_text(encoding='utf-8'))
                    self.assertEqual(saved[key], self.root.tk.getboolean(self.root.getvar(variable)))
                else:
                    key = next(key for key, var in self.app.ini_vars.items() if str(var) == variable)
                    self.assertEqual(ui.tlg_run.read_ini(self.user / 'tlg.ini')[key],
                                     str(int(self.root.getvar(variable))))
        for index in range(3):
            self.app.sharpener.current(index)
            self.app.sharpener.event_generate('<<ComboboxSelected>>')
            ini = ui.tlg_run.read_ini(self.user / 'tlg.ini')
            self.assertEqual((ini['rcas'], ini['cas']), (str(int(index == 1)), str(int(index == 2))))
        self.app.game_lang_box.current(0)
        self.app.game_lang_box.event_generate('<<ComboboxSelected>>')
        self.assertEqual(self.app.settings['game_language'], self.app.game_lang_values[0])
        for key, (low, high) in ui.COLOR_RANGES.items():
            self.app.ini_vars[key].set(str(high + 1))
            self.app.filters_changed()
            self.assertEqual(float(ui.tlg_run.read_ini(self.user / 'tlg.ini')[key]), high)
            self.app.ini_vars[key].set(str(low - 1))
            self.app.filters_changed()
            self.assertEqual(float(ui.tlg_run.read_ini(self.user / 'tlg.ini')[key]), low)
        self.assertFalse(self.errors)

    def test_folder_buttons_shortcuts_links_and_dialog_actions(self):
        buttons = [widget for widget in widgets(self.root) if isinstance(widget, ui.ttk.Button)]
        browse_buttons = [widget for widget in buttons if widget.cget('text') == self.app.t('browse')]
        for key, button in zip(('game_dir', 'system_lib_dir'), browse_buttons):
            with mock.patch.object(ui.filedialog, 'askdirectory', return_value=str(self.user / key)):
                button.invoke()
                self.assertEqual(self.app.settings[key], str(self.user / key))
        with mock.patch.object(self.app, 'open') as open_folder:
            for key, path in (('saves', self.user / 'savedata'), ('logs', ui.tlg_run.LOG_DIR)):
                next(widget for widget in buttons if widget.cget('text') == self.app.t(key)).invoke()
                open_folder.assert_called_with(path)
        with mock.patch.object(ui.webbrowser, 'open') as open_link:
            for label, url in zip((widget for widget in widgets(self.root)
                                  if isinstance(widget, ui.ttk.Label) and widget.bind('<Button-1>')),
                                 (ui.CHANNEL_URL, ui.DISCORD_URL, ui.SPONSOR_URL)):
                label.event_generate('<Button-1>')
                open_link.assert_called_with(url)
        next(widget for widget in buttons if widget.cget('text') == self.app.t('remap')).invoke()
        entries = [widget for widget in widgets(self.app.remap_window) if type(widget) == ui.ttk.Entry]
        entries[0].insert(0, 'Mouse X1')
        entries[0].event_generate('<FocusOut>')
        self.assertEqual(self.app.settings['key_map']['cross'], 'Mouse X1')
        remap_buttons = [widget for widget in widgets(self.app.remap_window) if isinstance(widget, ui.ttk.Button)]
        next(widget for widget in remap_buttons if widget.cget('text') == self.app.t('reset')).invoke()
        self.assertEqual(self.app.settings['key_map'], {})
        next(widget for widget in remap_buttons if widget.cget('text') == self.app.t('close')).invoke()
        mods = [('fixture.xml:test', 'Audit fixture', 'Temporary test mod', False)]
        with mock.patch.object(ui.tlg_run, 'list_mods', return_value=mods) as list_mods, \
                mock.patch.object(ui.tlg_run, 'set_mod_enabled') as toggle:
            next(widget for widget in buttons if widget.cget('text') == self.app.t('mods')).invoke()
            next(widget for widget in widgets(self.app.mods_window) if isinstance(widget, ui.ttk.Checkbutton)).invoke()
            toggle.assert_called_once_with('fixture.xml:test', True)
            next(widget for widget in widgets(self.app.mods_window) if isinstance(widget, ui.ttk.Button)
                 and widget.cget('text') == self.app.t('mods_refresh')).invoke()
            self.assertEqual(list_mods.call_count, 2)
        self.assertFalse(self.errors)

    def test_play_button_preparation_launch_log_completion_and_error(self):
        process = mock.Mock()
        process.stdout = ['Trico session output\n']
        process.wait.return_value = 0
        logfile = self.user / 'session.log'
        with mock.patch.object(ui.threading, 'Thread') as thread, \
                mock.patch.object(ui.tlg_run, 'prepare') as prepare, \
                mock.patch.object(ui.tlg_run, 'launch', return_value=(process, logfile)) as launch:
            self.app.play_button.invoke()
            self.assertTrue(self.app.play_button.instate(['disabled']))
            self.assertTrue(self.app.cache_button.instate(['disabled']))
            thread.return_value.start.assert_called_once()
            thread.call_args.kwargs['target']()  # Execute only the mocked game services.
            self.app.pump()
            prepare.assert_called_once()
            launch.assert_called_once_with(self.app.settings)
            self.assertIn('Trico session output', logfile.read_text(encoding='utf-8'))
            self.assertIn(self.app.t('ended', code=0), self.app.log.get('1.0', 'end'))
            self.assertFalse(self.app.play_button.instate(['disabled']))
        with mock.patch.object(ui.tlg_run, 'prepare', side_effect=RuntimeError('Audit error')), \
                mock.patch.object(ui.messagebox, 'showerror') as error:
            self.app.run_game()
            self.app.pump()
            error.assert_called_once_with(self.app.t('error'), 'Audit error')
        self.app.lines.put(('ended', 2))
        with mock.patch.object(ui.messagebox, 'showwarning') as warning:
            self.app.pump()
            warning.assert_called_once()
        self.assertFalse(self.errors)

    def test_cache_confirmation_and_quit_callbacks(self):
        with mock.patch.object(ui.tlg_run, 'shader_cache_size', return_value=1024), \
                mock.patch.object(ui.tlg_run, 'clear_shader_cache', return_value=(1024, [])) as clear, \
                mock.patch.object(ui.messagebox, 'askyesno', return_value=False) as confirm, \
                mock.patch.object(ui.messagebox, 'showinfo') as information:
            self.app.cache_button.invoke()
            clear.assert_not_called()
            confirm.return_value = True
            self.app.cache_button.invoke()
            clear.assert_called_once_with(self.app.settings)
            information.assert_called_once()
        self.app.process = mock.Mock()
        with mock.patch.object(self.root, 'destroy') as close:
            next(widget for widget in widgets(self.root) if isinstance(widget, ui.ttk.Button)
                 and widget.cget('text') == self.app.t('quit')).invoke()
            self.app.process.terminate.assert_called_once()
            close.assert_called_once()
        self.app.process = None
        self.assertFalse(self.errors)

    def test_game_region_language_choices_and_interface_language_event(self):
        with mock.patch.object(ui.tlg_run, 'game_languages', return_value=ui.tlg_run.LANGUAGES_EU):
            self.app.refresh_language_choices()
            self.assertEqual(list(self.app.game_lang_box.cget('values')),
                             [ui.GAME_LANGUAGE_NAMES[key] for key in ui.tlg_run.LANGUAGES_EU])
            index = list(ui.tlg_run.LANGUAGES_EU).index('pt_PT')
            self.app.game_lang_box.current(index)
            self.app.game_lang_box.event_generate('<<ComboboxSelected>>')
            self.assertEqual(self.app.settings['game_language'], 'pt_PT')
        self.app.append('Language event audit')
        self.app.show_page('setup')
        box = next(widget for widget in widgets(self.root) if isinstance(widget, ui.ttk.Combobox)
                   and list(widget.cget('values')) == [self.app.t('auto'), *ui.UI_LANGUAGE_NAMES.values()])
        box.current(ui.UI_LANGUAGES.index('en_US'))
        box.event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.assertEqual(self.app.settings['ui_language'], 'en_US')
        self.assertEqual(self.app.current_page, 'setup')
        self.assertIn('Language event audit', self.app.log.get('1.0', 'end'))
        self.assertFalse(self.errors)

    def test_missing_art_falls_back_to_themed_initial_screen(self):
        self.app.art_loaded = False
        self.app.banner = None
        with mock.patch.object(Path, 'is_file', return_value=False), \
                mock.patch.object(ui, 'art_path', return_value=None):
            self.app.build()
            self.root.update()
        self.assertIsNone(self.app.banner)
        self.assertEqual(self.app.current_page, 'journey')
        self.assertFalse(self.errors)

    def test_ready_running_and_missing_game_states(self):
        self.assertFalse(self.app.play_button.instate(['disabled']))
        self.app.process = mock.Mock()
        self.app.refresh_status()
        self.assertTrue(self.app.play_button.instate(['disabled']))
        self.assertTrue(self.app.cache_button.instate(['disabled']))
        self.app.process = None
        with mock.patch.object(ui.tlg_run, 'check_game', return_value=[('missing', 'eboot.bin')]):
            self.app.refresh_status()
            self.assertTrue(self.app.play_button.instate(['disabled']))
            self.assertIn('eboot.bin', self.app.status.cget('text'))
        self.assertFalse(self.app.cache_button.instate(['disabled']))

    def test_pages_fit_minimum_size_in_both_languages_and_dialogs_open(self):
        for language in ('pt_BR', 'en_US'):
            self.app.settings['ui_language'] = language
            self.app.build()
            self.root.geometry('1040x700')
            self.root.update()
            for key in self.app.pages:
                self.app.show_page(key)
                self.root.update()
                self.assertTrue(self.app.play_button.winfo_ismapped())
                self.assertLessEqual(self.app.play_button.winfo_rooty() + self.app.play_button.winfo_height(),
                                     self.root.winfo_rooty() + self.root.winfo_height())
                if key == 'journey':
                    canvas = next(w for w in self.app.pages[key].winfo_children()
                                  if isinstance(w, ui.tk.Canvas))
                    for item in canvas.find_all():
                        if canvas.type(item) == 'text':
                            self.assertLessEqual(canvas.bbox(item)[3], canvas.winfo_height())
                    continue
                page = self.app.pages[key]
                canvases = [w for holder in page.winfo_children()
                            for w in holder.winfo_children() if isinstance(w, ui.tk.Canvas)]
                self.assertEqual(len(canvases), 1)
                canvas = canvases[0]
                body = canvas.nametowidget(canvas.itemcget(canvas.find_all()[0], 'window'))
                self.assertLessEqual(body.winfo_reqwidth(), canvas.winfo_width(), (language, key))
        self.app.remap_dialog()
        self.app.mods_dialog()
        self.root.update()
        self.assertTrue(self.app.remap_window.winfo_exists())
        self.assertTrue(self.app.mods_window.winfo_exists())
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
