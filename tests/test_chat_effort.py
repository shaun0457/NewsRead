import copy
import unittest
from easyread import config, chat_options


class ChatEffortTest(unittest.TestCase):
    def test_explicit_override_does_not_change_card_or_translation(self):
        saved = copy.deepcopy(config.DEFAULTS)
        saved["claude"].update(model="opus", reasoning_effort="high")
        request = copy.deepcopy(saved)
        selected = chat_options.apply(request, {"reasoning_effort": "low"})
        self.assertEqual(request["claude"]["reasoning_effort"], "low")
        self.assertEqual(saved["claude"]["reasoning_effort"], "high")
        self.assertEqual(selected, {"reasoning_effort": "low"})
        chat_options.apply(request, {"reasoning_effort": ""})
        self.assertEqual(request["claude"]["reasoning_effort"], "")

    def test_legacy_requests_and_invalid_levels(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        self.assertEqual(chat_options.apply(cfg, None), {})
        with self.assertRaises(ValueError):
            chat_options.apply(cfg, {"reasoning_effort": "invalid"})
        cfg["claude"]["model"] = "haiku"
        with self.assertRaises(ValueError):
            chat_options.apply(cfg, {"reasoning_effort": "high"})
