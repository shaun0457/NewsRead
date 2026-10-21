import json
import unittest
from pathlib import Path
from unittest import mock

from easyread import chat_models, chat_options, cli_models, config, detect, engines, usage


class AntigravityEngineTest(unittest.TestCase):
    def test_engine_names_and_who(self):
        self.assertIn("antigravity", engines.ENGINE_NAMES)
        self.assertEqual(engines.who({"engine": "antigravity"}), "antigravity")

    def test_usage_from_antigravity(self):
        sample = {
            "conversation_id": "test-id",
            "status": "SUCCESS",
            "response": "Hello world",
            "usage": {
                "input_tokens": 100,
                "cache_read_tokens": 20,
                "output_tokens": 50,
                "total_tokens": 150,
            },
        }
        u = usage.from_antigravity(sample)
        self.assertEqual(u["input"], 100)
        self.assertEqual(u["cached"], 20)
        self.assertEqual(u["output"], 50)

    @mock.patch("easyread.engines._communicate")
    @mock.patch("easyread.engines._popen")
    @mock.patch("easyread.engines.antigravity_path", return_value="C:\\fake\\agy.exe")
    def test_run_antigravity_success(self, mock_path, mock_popen, mock_comm):
        mock_comm.return_value = json.dumps({
            "status": "SUCCESS",
            "response": "Translated response",
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 0},
        })
        meter = usage.Meter("antigravity")
        cfg = {"command": "agy", "model": "gemini-4-argon-high", "reasoning_effort": "high"}
        out = engines.run_antigravity(cfg, "Prompt", Path("."), meter=meter)
        self.assertEqual(out, "Translated response")
        self.assertEqual(meter.snapshot()["input"], 10)
        self.assertEqual(meter.snapshot()["output"], 5)

    @mock.patch("easyread.engines._communicate")
    @mock.patch("easyread.engines._popen")
    @mock.patch("easyread.engines.antigravity_path", return_value="C:\\fake\\agy.exe")
    def test_run_antigravity_failure(self, mock_path, mock_popen, mock_comm):
        mock_comm.return_value = json.dumps({
            "status": "FAILED",
            "error": "Quota exceeded",
        })
        cfg = {"command": "agy"}
        with self.assertRaises(engines.EngineError) as ctx:
            engines.run_antigravity(cfg, "Prompt", Path("."))
        self.assertIn("Quota exceeded", str(ctx.exception))

    def test_cli_models_and_options(self):
        opts = chat_options.apply({"engine": "antigravity", "antigravity": {}}, {"reasoning_effort": "high"})
        self.assertEqual(opts.get("reasoning_effort"), "high")

        listing = cli_models.listing()
        self.assertIn("antigravity", listing)
        self.assertTrue(len(listing["antigravity"]["models"]) > 0)

    def test_chat_models_engine_cfg(self):
        cfg = config.load()
        cfg["chat"]["models"].append({
            "id": "test-agy", "name": "Gemini Test", "engine": "antigravity", "model": "gemini-4-argon-high"
        })
        ecfg, m = chat_models.engine_cfg(cfg, "test-agy")
        self.assertEqual(ecfg["engine"], "antigravity")
        self.assertEqual(ecfg["antigravity"]["model"], "gemini-4-argon-high")


if __name__ == "__main__":
    unittest.main()
