import unittest
from unittest import mock

from easyread import usage

# 2026-10 实测的 claude -p --output-format stream-json --verbose 输出（删减）
CLAUDE_RESULT = {"type": "result", "total_cost_usd": 0.0915, "usage": {
    "input_tokens": 2, "cache_creation_input_tokens": 10838, "cache_read_input_tokens": 23584, "output_tokens": 4}}
CLAUDE_RATE = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning", "unifiedWindows": {
    "five_hour": {"utilization": 0.24, "resetsAt": 1790871000}, "seven_day": {"utilization": 0.86, "resetsAt": 1791054000}}}}


class UsageTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(usage, "remember")  # 别把测试数据写进真实的 limits.json
        self.remember = patcher.start()
        self.addCleanup(patcher.stop)

    def test_claude_subscription_reports_limits_not_cost(self):
        rec = usage.from_claude(CLAUDE_RESULT, CLAUDE_RATE)
        self.assertEqual((rec["input"], rec["cached"], rec["output"]), (34424, 23584, 4))
        self.assertEqual(rec["limits"]["five_hour"]["used"], 0.24)
        self.assertNotIn("cost_usd", rec)  # 订阅时按官方价折算的费用不是真花的钱

    def test_claude_api_key_reports_cost(self):
        rec = usage.from_claude(CLAUDE_RESULT, None)
        self.assertEqual(rec["cost_usd"], 0.0915)
        self.assertNotIn("limits", rec)

    def test_codex(self):
        rec = usage.from_codex({"type": "turn.completed", "usage": {"input_tokens": 24821, "cached_input_tokens": 13440, "output_tokens": 5}})
        self.assertEqual(rec, {"input": 24821, "cached": 13440, "output": 5})

    def test_openai_chat_and_deepseek_and_responses(self):
        chat = usage.from_openai({"usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 60}}})
        deepseek = usage.from_openai({"usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_cache_hit_tokens": 70}})
        responses = usage.from_openai({"usage": {"input_tokens": 100, "output_tokens": 20, "input_tokens_details": {"cached_tokens": 50}}})
        self.assertEqual(chat, {"input": 100, "cached": 60, "output": 20})
        self.assertEqual(deepseek["cached"], 70)
        self.assertEqual(responses, {"input": 100, "cached": 50, "output": 20})
        self.assertEqual(usage.from_openai({}), {"input": 0, "cached": 0, "output": 0})  # 有的接口不返回 usage

    def test_meter_and_merge(self):
        m = usage.Meter("claude")
        m.add(**usage.from_claude(CLAUDE_RESULT, CLAUDE_RATE))
        m.add(input=10, output=5)
        run = m.snapshot()
        self.assertEqual((run["calls"], run["input"], run["output"]), (2, 34434, 9))
        total = usage.merge(usage.merge(None, run), run)
        self.assertEqual((total["calls"], total["input"]), (4, 68868))
        self.assertEqual(total["limits"]["seven_day"]["used"], 0.86)
        self.remember.assert_called_once()  # 只有带额度的那次调用会记下来


if __name__ == "__main__":
    unittest.main()
