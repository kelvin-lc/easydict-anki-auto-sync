import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


class TwoButtonTests(unittest.TestCase):
    def test_keeps_native_ratings_and_only_affects_easydict(self):
        hooks = types.SimpleNamespace(reviewer_will_init_answer_buttons=[],
                                      reviewer_will_answer_card=[])
        path = pathlib.Path(__file__).resolve().parents[1] / 'anki_addon/easydict_two_buttons/__init__.py'
        spec = importlib.util.spec_from_file_location('two_buttons', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'aqt': types.SimpleNamespace(gui_hooks=hooks)}):
            spec.loader.exec_module(module)
        def card(model):
            return types.SimpleNamespace(note=lambda: types.SimpleNamespace(
                note_type=lambda: {'name': model}))
        target, other = card(module.MODEL), card('Basic')
        buttons = ((1, 'Again'), (2, 'Hard'), (3, 'Good'), (4, 'Easy'))
        self.assertEqual(module.answer_buttons(buttons, None, target),
                         ((1, 'Again'), (3, 'Good')))
        self.assertEqual(module.answer_buttons(buttons, None, other), buttons)
        for ease in range(1, 5):
            self.assertEqual(module.allow_answer((True, ease), None, target),
                             (ease in (1, 3), ease))
            self.assertEqual(module.allow_answer((True, ease), None, other), (True, ease))
        self.assertEqual(module.allow_answer((False, 3), None, target), (False, 3))
        self.assertEqual(hooks.reviewer_will_init_answer_buttons, [module.answer_buttons])
        self.assertEqual(hooks.reviewer_will_answer_card, [module.allow_answer])
