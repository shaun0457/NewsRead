"""Ticket 67：AI 引擎偵測、自帶 key、每種工作的引擎、用量紀錄、退避和錯誤代碼。全部用假引擎，不呼叫真實模型。"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import types
import unittest
import urllib.error
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from easyread import ai_engines as ai
from easyread import engines, ledger, openai_api
from easyread.log import log
from easyread.store import write_json_atomic

from tests.doubles import ApiTestCase

SECRET = "sk-ant-api03-SECRETSECRETSECRET-a9Fw"
FOUND_ALL = {"claude": {"found": True, "version": "9.9.9 (Claude Code)"}, "codex": {"found": True, "version": "codex 1"},
             "antigravity": {"found": False, "version": ""}, "ollama": {"running": False, "models": []}}
FOUND_NONE = {"claude": {"found": False}, "codex": {"found": False}, "antigravity": {"found": False},
              "ollama": {"running": False, "models": []}}


class FakeAdapter:
    """依序回傳排好的結果或丟出排好的 AIError；calls 記下每次呼叫拿到的 spec。"""

    def __init__(self, *steps, check=None):
        self.steps = list(steps)
        self.calls: list[dict] = []
        self.checks: list[dict] = []
        self.check_result = check

    def call(self, spec, prompt, cancel=None, json_mode=False):
        self.calls.append(dict(spec))
        if not self.steps:
            raise AssertionError("unexpected call")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    def check(self, spec):
        self.checks.append(dict(spec))
        if isinstance(self.check_result, BaseException):
            raise self.check_result


def ok(text="好", input=120, cached=0, output=30, cost=None, quota=None, billing="subscription"):
    return {"text": text, "input": input, "cached": cached, "output": output, "cost_usd": cost, "quota": quota, "billing": billing}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.index = ledger.Index(self.root / "newsread.sqlite3")
        self.settings = ai.Settings(self.root / "ai.json")
        self.found = json.loads(json.dumps(FOUND_ALL))
        self.waits: list[float] = []
        self.adapters = {e: FakeAdapter() for e in ai.ENGINES}

    def engines(self, **kw):
        return ai.Engines(self.settings, self.index, adapters=self.adapters, detector=lambda fresh=False: self.found,
                          wait=lambda s, cancel: self.waits.append(s), has_sdk=lambda: True, quota=lambda: None, **kw)

    def set_task(self, task, primary=None, fallback=None):
        self.settings.update(lambda d: d["tasks"].__setitem__(task, {"primary": primary, "fallback": fallback}))

    def add_anthropic(self, status="ok"):
        self.settings.update(lambda d: d.__setitem__("anthropic", {"key": SECRET, "status": status, "tested_at": None, "code": None}))


ANTHROPIC_SONNET = {"engine": "anthropic", "model": "claude-sonnet-5-5", "entry": ""}
CLAUDE_SONNET = {"engine": "claude", "model": "claude-sonnet-5-5", "entry": ""}


class FallbackTest(Base):
    def test_invalid_key_is_not_retried_and_the_fallback_runs_with_a_notice(self):
        self.add_anthropic()
        self.set_task("thesis_change", ANTHROPIC_SONNET, CLAUDE_SONNET)
        self.adapters["anthropic"] = FakeAdapter(ai.AIError("AUTH_INVALID", "401 invalid x-api-key"))
        self.adapters["claude"] = FakeAdapter(ok("改用訂閱"), ok("第二次"))
        eng = self.engines()
        res = eng.run("thesis_change", "p", prompt_version="v1")
        self.assertEqual(res["text"], "改用訂閱")
        self.assertEqual((res["engine"], res["fallback"], res["notice"]), ("claude", True, "AUTH_INVALID"))
        self.assertEqual(len(self.adapters["anthropic"].calls), 1)  # 同一把 key 不重試
        self.assertEqual(self.waits, [])
        self.assertEqual(self.settings.load()["anthropic"]["status"], "invalid")
        self.assertEqual(self.settings.load()["anthropic"]["code"], "AUTH_INVALID")
        # 之後直接用備用，不再碰那把 key
        res = eng.run("thesis_change", "p", prompt_version="v1")
        self.assertEqual(res["text"], "第二次")
        self.assertEqual(len(self.adapters["anthropic"].calls), 1)
        view = eng.view()
        self.assertEqual(view["tasks"]["thesis_change"]["state"], "fallback")
        self.assertEqual(view["tasks"]["thesis_change"]["reason"], "auth_invalid")
        self.assertEqual(view["anthropic"]["status"], "invalid")

    def test_invalid_key_without_a_fallback_pauses_the_task(self):
        self.add_anthropic()
        self.set_task("thesis_change", ANTHROPIC_SONNET)
        self.adapters["anthropic"] = FakeAdapter(ai.AIError("AUTH_INVALID"))
        eng = self.engines()
        with self.assertRaises(ai.AIError) as cm:
            eng.run("thesis_change", "p", prompt_version="v1")
        self.assertEqual(cm.exception.code, "PAUSED")
        self.assertEqual(eng.plan("thesis_change", self.settings.load(), self.found)["state"], "paused")
        self.assertFalse(eng.available("thesis_change"))
        with self.assertRaises(ai.AIError) as cm:  # 第二次不再呼叫
            eng.run("thesis_change", "p", prompt_version="v1")
        self.assertEqual(cm.exception.code, "PAUSED")
        self.assertEqual(len(self.adapters["anthropic"].calls), 1)
        self.assertTrue(eng.available("triage"))  # 別的工作照常（自動選到 Claude Code）

    def test_auto_skips_an_invalid_key(self):
        self.found = json.loads(json.dumps(FOUND_NONE))
        self.add_anthropic(status="invalid")
        eng = self.engines()
        self.assertEqual(eng.plan("ask", self.settings.load(), self.found)["state"], "paused")
        self.found["codex"] = {"found": True}
        p = eng.plan("ask", self.settings.load(), self.found)
        self.assertEqual((p["state"], p["using"]["engine"]), ("ready", "codex"))

    def test_logged_out_cli_falls_back_and_redetect_clears_the_mark(self):
        self.add_anthropic()
        self.set_task("ask", CLAUDE_SONNET, ANTHROPIC_SONNET)
        self.adapters["claude"] = FakeAdapter(ai.AIError("AUTH_INVALID"))
        self.adapters["anthropic"] = FakeAdapter(ok(cost=0.01, billing="api"))
        eng = self.engines()
        res = eng.run("ask", "p", prompt_version="v1")
        self.assertEqual((res["engine"], res["notice"]), ("anthropic", "AUTH_INVALID"))
        self.assertEqual(eng.view()["detected"]["claude"]["auth"], "invalid")
        self.assertEqual(eng.redetect()["tasks"]["ask"]["state"], "ready")

    def test_other_errors_do_not_switch_engines(self):
        self.add_anthropic()
        self.set_task("draft", CLAUDE_SONNET, ANTHROPIC_SONNET)
        self.adapters["claude"] = FakeAdapter(ai.AIError("UPSTREAM_ERROR"))
        with self.assertRaises(ai.AIError) as cm:
            self.engines().run("draft", "p", prompt_version="v1")
        self.assertEqual(cm.exception.code, "UPSTREAM_ERROR")
        self.assertEqual(self.adapters["anthropic"].calls, [])


class NoAiTest(Base):
    def test_without_any_engine_tasks_say_no_ai(self):
        self.found = json.loads(json.dumps(FOUND_NONE))
        eng = self.engines()
        view = eng.view()
        self.assertFalse(view["any_ai"])
        self.assertEqual({t: s["state"] for t, s in view["tasks"].items()}, {t: "no_ai" for t in ai.TASKS})
        for t in ai.TASKS:
            self.assertFalse(eng.available(t))
        with self.assertRaises(ai.AIError) as cm:
            eng.run("triage", "p", prompt_version="v1")
        self.assertEqual(cm.exception.code, "NO_AI")
        self.assertEqual(self.index.usage(), [])
        self.assertEqual(str(cm.exception), "NO_AI: " + ai.message("NO_AI"))

    def test_ollama_counts_when_running_with_a_model(self):
        self.found = json.loads(json.dumps(FOUND_NONE))
        self.found["ollama"] = {"running": True, "models": ["qwen3:8b"]}
        self.adapters["ollama"] = FakeAdapter(ok(cost=0.0, billing="local"))
        res = self.engines().run("translate", "p", prompt_version="v1")
        self.assertEqual((res["engine"], res["model"]), ("ollama", "qwen3:8b"))
        self.assertEqual(self.index.usage()[0]["cost_usd"], 0.0)


class BackoffTest(Base):
    def test_rate_limit_backs_off_exponentially_and_stops_at_the_cap(self):
        self.set_task("triage", CLAUDE_SONNET)
        self.adapters["claude"] = FakeAdapter(*[ai.AIError("RATE_LIMITED") for _ in range(ai.MAX_ATTEMPTS)])
        with self.assertRaises(ai.AIError) as cm:
            self.engines().run("triage", "p", prompt_version="v1")
        self.assertEqual(cm.exception.code, "RATE_LIMITED")
        self.assertEqual(len(self.adapters["claude"].calls), ai.MAX_ATTEMPTS)
        self.assertEqual(self.waits, [2.0, 4.0, 8.0])
        self.assertEqual(self.index.usage(), [])

    def test_retry_after_is_honoured_but_capped(self):
        self.set_task("triage", CLAUDE_SONNET)
        self.adapters["claude"] = FakeAdapter(ai.AIError("RATE_LIMITED", retry_after=ai._retry_after("9999")),
                                              ai.AIError("RATE_LIMITED", retry_after=ai._retry_after("1")), ok())
        res = self.engines().run("triage", "p", prompt_version="v1")
        self.assertEqual(res["text"], "好")
        self.assertEqual(self.waits, [ai.BACKOFF_MAX, 4.0])  # 上游的 1 秒比退避短，用退避的 4 秒
        self.assertEqual(len(self.index.usage()), 1)
        self.assertIsNone(ai._retry_after("nan"))
        self.assertIsNone(ai._retry_after("-3"))
        self.assertIsNone(ai._retry_after(None))

    def test_cancel_during_backoff_stops_waiting(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ai.AIError) as cm:
            ai._wait(60, cancel)
        self.assertEqual(cm.exception.code, "CANCELLED")
        self.set_task("triage", CLAUDE_SONNET)
        with self.assertRaises(ai.AIError) as cm:
            self.engines().run("triage", "p", prompt_version="v1", cancel=cancel)
        self.assertEqual(cm.exception.code, "CANCELLED")
        self.assertEqual(self.adapters["claude"].calls, [])


class UsageTest(Base):
    def test_api_calls_record_cost_and_subscriptions_record_quota(self):
        self.add_anthropic()
        self.set_task("draft", {"engine": "anthropic", "model": "claude-opus-5-5", "entry": ""})
        self.set_task("triage", {"engine": "claude", "model": "claude-haiku-5-5", "entry": ""})
        quota = {"five_hour": {"used": 0.42, "resets_at": 1_800_000_000}, "seven_day": {"used": 0.61, "resets_at": 1_800_100_000}}
        self.adapters["anthropic"] = FakeAdapter(ok(input=1000, output=500, cost=0.014, billing="api"))
        self.adapters["claude"] = FakeAdapter(ok(input=200, cached=50, output=10, quota=quota))
        eng = self.engines()
        eng.run("draft", "p", prompt_version="draft-v3", source="theme_page")
        eng.run("triage", "p", prompt_version="triage-v1")
        api, sub = self.index.usage()
        self.assertEqual((api["engine"], api["model"], api["task"], api["source"]), ("anthropic", "claude-opus-5-5", "draft", "theme_page"))
        self.assertEqual((api["input_tokens"], api["output_tokens"], api["cost_usd"]), (1000, 500, 0.014))
        self.assertIsNone(sub["cost_usd"])  # 訂閱不折算金額
        self.assertEqual(sub["cost"], "unknown")
        self.assertEqual(sub["quota"], quota)
        self.assertEqual((sub["input_tokens"], sub["cached_tokens"], sub["output_tokens"]), (200, 50, 10))
        self.assertEqual(eng.view()["detected"]["claude"]["auth"], "ok")
        self.assertEqual(eng.view()["tasks"]["draft"]["month_cost"], 0.014)
        self.assertEqual(eng.view()["tasks"]["triage"]["today"], 1)

    def test_switching_engine_or_model_is_a_new_prompt_version(self):
        self.set_task("ask", CLAUDE_SONNET)
        self.adapters["claude"] = FakeAdapter(ok(), ok())
        self.adapters["codex"] = FakeAdapter(ok())
        eng = self.engines()
        self.assertEqual(eng.run("ask", "p", prompt_version="ask-v2")["prompt_version"], "ask-v2@claude/claude-sonnet-5-5")
        self.assertEqual(self.index.current_prompt("ask"), "ask-v2@claude/claude-sonnet-5-5")
        self.set_task("ask", {"engine": "claude", "model": "claude-opus-5-5", "entry": ""})
        self.assertEqual(eng.run("ask", "p", prompt_version="ask-v2")["prompt_version"], "ask-v2@claude/claude-opus-5-5")
        self.set_task("ask", {"engine": "codex", "model": "", "entry": ""})
        self.assertEqual(eng.run("ask", "p", prompt_version="ask-v2")["prompt_version"], "ask-v2@codex/default")
        self.assertEqual(self.index.current_prompt("ask"), "ask-v2@codex/default")
        eng.run  # noqa: B018
        self.adapters["claude"] = FakeAdapter(ok())
        self.set_task("ask", CLAUDE_SONNET)
        eng.run("ask", "p", prompt_version="ask-v2")  # 同一組版本可以重複登記

    def test_run_needs_a_known_task_and_a_prompt_version(self):
        eng = self.engines()
        with self.assertRaises(ValueError):
            eng.run("summarise", "p", prompt_version="v1")
        with self.assertRaises(ValueError):
            eng.run("ask", "p", prompt_version="")

    def test_prices(self):
        self.assertEqual(ai.price("claude-opus-5-5", 1_000_000, 0, 0, 1_000_000), 24.0)
        self.assertEqual(ai.price("claude-sonnet-5-5", 0, 1_000_000, 0, 0), 0.1)
        self.assertEqual(ai.price("claude-haiku-5-5", 100_000, 0, 0, 0), 0.01)
        self.assertIsNone(ai.price("claude-haiku-5-5", 100_001, 0, 0, 0))  # 長 prompt 的價格不一樣，不亂算
        self.assertIsNone(ai.price("claude-haiku-5-5", 10, 5, 0, 0))  # 讀快取的價格不確定
        self.assertIsNone(ai.price("claude-opus-5-5", 10, 0, 5, 0))  # 寫快取不算
        self.assertIsNone(ai.price("gpt-unknown", 10, 0, 0, 10))


class ErrorTextTest(Base):
    def test_errors_carry_a_code_and_a_fixed_message_only(self):
        self.set_task("ask", CLAUDE_SONNET)
        self.adapters["claude"] = FakeAdapter(ai.AIError("ENGINE_ERROR", f"upstream said key={SECRET} user@example.com"))
        with self.assertLogs(log, level="DEBUG") as logs:
            with self.assertRaises(ai.AIError) as cm:
                self.engines().run("ask", "p", prompt_version="v1")
        e = cm.exception
        self.assertEqual(str(e), "ENGINE_ERROR: " + ai.message("ENGINE_ERROR"))
        self.assertNotIn("SECRETSECRET", e.detail)  # 留著的上游原文也先過 scrubber
        self.assertNotIn("user@example.com", e.detail)
        text = "\n".join(logs.output)
        self.assertIn("code=ENGINE_ERROR", text)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("upstream said", text)

    def test_status_and_text_classification(self):
        self.assertEqual(ai.from_status(401).code, "AUTH_INVALID")
        self.assertEqual(ai.from_status(429, retry_after="12").retry_after, 12.0)
        self.assertEqual(ai.from_status(529).code, "UPSTREAM_ERROR")
        self.assertEqual(ai.from_status(503).code, "UPSTREAM_ERROR")
        self.assertEqual(ai.from_status(404).code, "BAD_REQUEST")
        self.assertEqual(ai.from_status(None).code, "ENGINE_ERROR")
        cli = lambda msg: ai.from_cli(engines.EngineError(msg), 1200).code  # noqa: E731
        self.assertEqual(cli("Claude Code 出错：Not logged in · Please run /login"), "AUTH_INVALID")
        self.assertEqual(cli("Claude Code 出错：Claude AI usage limit reached|1700000000"), "RATE_LIMITED")
        self.assertEqual(cli("Codex 没有给出结果：429 Too Many Requests"), "RATE_LIMITED")
        self.assertEqual(cli("Codex 没有给出结果：boom"), "ENGINE_ERROR")
        from easyread.i18n import tr
        self.assertEqual(cli(tr("超过 {n} 秒没有结果", n=1200)), "TIMEOUT")
        self.assertEqual(ai.AIError("WHATEVER").code, "ENGINE_ERROR")

    def test_sdk_errors_by_class_name_and_status(self):
        def fake(name, status=None, headers=None, bases=(Exception,)):
            cls = type(name, bases, {})
            e = cls("message with " + SECRET)
            e.status_code = status
            e.response = types.SimpleNamespace(headers=headers or {})
            return e
        self.assertEqual(ai.from_sdk(fake("AuthenticationError", 401)).code, "AUTH_INVALID")
        rate = ai.from_sdk(fake("RateLimitError", 429, {"retry-after": "7"}))
        self.assertEqual((rate.code, rate.retry_after), ("RATE_LIMITED", 7.0))
        self.assertEqual(ai.from_sdk(fake("InternalServerError", 500)).code, "UPSTREAM_ERROR")
        conn = type("APIConnectionError", (Exception,), {})
        self.assertEqual(ai.from_sdk(conn("x")).code, "NETWORK")
        self.assertEqual(ai.from_sdk(type("APITimeoutError", (conn,), {})("x")).code, "TIMEOUT")
        self.assertNotIn("SECRETSECRET", ai.from_sdk(fake("AuthenticationError", 401)).detail)

    @unittest.skipUnless(ai.anthropic_installed(), "anthropic SDK not installed")
    def test_real_sdk_exceptions_map_and_the_client_does_not_retry(self):
        import anthropic
        import httpx
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        res = lambda code, h=None: httpx.Response(code, request=req, headers=h or {})  # noqa: E731
        self.assertEqual(ai.from_sdk(anthropic.AuthenticationError("bad", response=res(401), body=None)).code, "AUTH_INVALID")
        rl = ai.from_sdk(anthropic.RateLimitError("slow", response=res(429, {"retry-after": "5"}), body=None))
        self.assertEqual((rl.code, rl.retry_after), ("RATE_LIMITED", 5.0))
        self.assertEqual(ai.from_sdk(anthropic.APIConnectionError(request=req)).code, "NETWORK")
        self.assertEqual(ai.from_sdk(anthropic.APITimeoutError(request=req)).code, "TIMEOUT")
        client = ai._anthropic_client("sk-ant-test-0000000000", 5)
        self.assertEqual(client.max_retries, 0)


class AdapterTest(unittest.TestCase):
    def test_anthropic_adapter_streams_and_prices(self):
        msg = types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text="回答")],
                                    usage=types.SimpleNamespace(input_tokens=1000, cache_read_input_tokens=0,
                                                                cache_creation_input_tokens=0, output_tokens=200))
        seen = {}

        class Stream:
            text_stream = iter(["回", "答"])

            def __enter__(self):
                return self

            def __exit__(self, *a):
                seen["closed"] = True

            def get_final_message(self):
                return msg

        def factory(key, timeout):
            seen["key"], seen["timeout"] = key, timeout
            return types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: seen.update(kw=kw) or Stream()))

        res = ai.AnthropicAdapter(factory).call({"key": SECRET, "model": "claude-sonnet-5-5"}, "問題")
        self.assertEqual(res["text"], "回答")
        self.assertEqual((res["input"], res["output"], res["billing"]), (1000, 200, "api"))
        self.assertEqual(res["cost_usd"], 0.004)
        self.assertEqual(seen["kw"]["model"], "claude-sonnet-5-5")
        self.assertEqual(seen["kw"]["messages"], [{"role": "user", "content": "問題"}])
        self.assertTrue(seen["closed"])
        msg.stop_reason = "max_tokens"
        Stream.text_stream = iter([])
        with self.assertRaises(ai.AIError) as cm:
            ai.AnthropicAdapter(factory).call({"key": SECRET, "model": "claude-sonnet-5-5"}, "問題")
        self.assertEqual((cm.exception.code, cm.exception.usage["output"], cm.exception.usage["cost_usd"]), ("OUTPUT_TRUNCATED", 200, 0.004))

    def test_anthropic_adapter_cancel_and_errors_release_the_stream(self):
        state = {"closed": 0}

        class Stream:
            def __init__(self, error=None):
                self.error = error
                self.text_stream = iter(["a", "b"])

            def __enter__(self):
                if self.error:
                    raise self.error
                return self

            def __exit__(self, *a):
                state["closed"] += 1

        cancel = threading.Event()
        cancel.set()
        factory = lambda key, timeout: types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: Stream()))  # noqa: E731
        with self.assertRaises(ai.AIError) as cm:
            ai.AnthropicAdapter(factory).call({"key": SECRET, "model": "claude-sonnet-5-5"}, "p", cancel=cancel)
        self.assertEqual(cm.exception.code, "CANCELLED")
        self.assertEqual(state["closed"], 1)
        err = type("AuthenticationError", (Exception,), {"status_code": 401})("bad key")
        factory = lambda key, timeout: types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: Stream(err)))  # noqa: E731
        with self.assertRaises(ai.AIError) as cm:
            ai.AnthropicAdapter(factory).call({"key": SECRET, "model": "claude-sonnet-5-5"}, "p")
        self.assertEqual(cm.exception.code, "AUTH_INVALID")

    def test_cli_adapter_tells_subscription_from_api_billing(self):
        limits = {"five_hour": {"used": 0.3, "resets_at": 1}}

        def run(record):
            def fake(c, prompt, cwd, cancel, meter):
                self.assertTrue(c["lean"])
                self.assertEqual(c["model"], "claude-haiku-5-5")
                meter.add(input=10, cached=0, output=5, **record)
                return "ok"
            return fake

        with mock.patch.object(engines, "claude_path", return_value="claude"), \
                mock.patch("easyread.usage.remember"):
            with mock.patch.object(engines, "run_claude", run({"limits": limits, "cost_usd": 0.5})):
                res = ai.CliAdapter("claude").call({"model": "claude-haiku-5-5"}, "p")
            self.assertEqual((res["billing"], res["cost_usd"], res["quota"]), ("subscription", None, limits))
            with mock.patch.object(engines, "run_claude", run({"cost_usd": 0.02})):
                res = ai.CliAdapter("claude").call({"model": "claude-haiku-5-5"}, "p")
            self.assertEqual((res["billing"], res["cost_usd"]), ("api", 0.02))
            with mock.patch.object(engines, "run_claude", side_effect=engines.EngineError("Not logged in · Please run /login")):
                with self.assertRaises(ai.AIError) as cm:
                    ai.CliAdapter("claude").call({"model": "claude-haiku-5-5"}, "p")
            self.assertEqual(cm.exception.code, "AUTH_INVALID")
            with mock.patch.object(engines, "run_claude", side_effect=engines.Cancelled()):
                with self.assertRaises(ai.AIError) as cm:
                    ai.CliAdapter("claude").call({"model": "claude-haiku-5-5"}, "p")
            self.assertEqual(cm.exception.code, "CANCELLED")
        with mock.patch.object(engines, "codex_path", return_value=None):
            with self.assertRaises(ai.AIError) as cm:
                ai.CliAdapter("codex").call({"model": ""}, "p")
        self.assertEqual(cm.exception.code, "ENGINE_MISSING")

    def test_openai_adapter_sends_one_request_and_maps_http_errors(self):
        headers = Message()
        headers["Retry-After"] = "3"
        http = urllib.error.HTTPError("https://x.example/v1/chat/completions", 429, "slow", headers, None)
        err = openai_api._http_error(http)
        self.assertEqual((err.status, err.retry_after), (429, "3"))
        seen = {}

        def fake(o, prompt, images, cancel, meter, json_mode):
            seen.update(o)
            raise err
        with mock.patch.object(openai_api, "complete", fake):
            with self.assertRaises(ai.AIError) as cm:
                ai.OpenAIAdapter().call({"base_url": "https://x.example/v1", "model": "m", "key": "k" * 20}, "p")
        self.assertEqual((cm.exception.code, cm.exception.retry_after), ("RATE_LIMITED", 3.0))
        self.assertEqual(seen["request_attempts"], 1)  # 重試由 Engines 管
        self.assertEqual(seen["api_key"], "k" * 20)
        with mock.patch.object(openai_api, "complete", side_effect=openai_api._network_error(OSError("down"))):
            with self.assertRaises(ai.AIError) as cm:
                ai.OpenAIAdapter(local=True).call({"model": "qwen3:8b"}, "p")
        self.assertEqual(cm.exception.code, "NETWORK")


class ReviewFixesTest(Base):
    def test_auto_moves_on_to_the_next_engine_in_the_same_call(self):
        self.adapters["claude"] = FakeAdapter(ai.AIError("AUTH_INVALID"))
        self.adapters["codex"] = FakeAdapter(ok("codex 接手"))
        res = self.engines().run("ask", "p", prompt_version="v1")  # 預設是自動
        self.assertEqual((res["engine"], res["text"], res["notice"], res["fallback"]), ("codex", "codex 接手", "AUTH_INVALID", True))
        self.assertEqual(len(self.adapters["claude"].calls), 1)

    def test_ordinary_cli_errors_are_not_mistaken_for_a_logout(self):
        for msg in ("backlog index corrupted", "Prompt is too long: 401 tokens over", "at cli.js:401:7", "credentials helper crashed"):
            self.assertEqual(ai.from_cli(engines.EngineError(msg), 1200).code, "ENGINE_ERROR", msg)
        for msg in ("Invalid API key · Please run /login", "OAuth token has expired", "401 Unauthorized", "authentication_error"):
            self.assertEqual(ai.from_cli(engines.EngineError(msg), 1200).code, "AUTH_INVALID", msg)

    def test_billed_calls_that_fail_are_still_recorded(self):
        self.set_task("draft", CLAUDE_SONNET)
        self.adapters["claude"] = FakeAdapter(ai.AIError("OUTPUT_TRUNCATED", usage={"input": 900, "cached": 0, "output": 16000,
                                                                                      "cost_usd": None, "quota": None}))
        with self.assertRaises(ai.AIError) as cm:
            self.engines().run("draft", "p", prompt_version="v1")
        self.assertEqual(cm.exception.code, "OUTPUT_TRUNCATED")
        (row,) = self.index.usage()
        self.assertEqual((row["task"], row["input_tokens"], row["output_tokens"]), ("draft", 900, 16000))

    def test_a_bad_context_manifest_is_rejected_before_calling_ai(self):
        self.set_task("ask", CLAUDE_SONNET)
        with self.assertRaises(ValueError):
            self.engines().run("ask", "p", prompt_version="v1", context_manifest="M-missing")
        self.assertEqual(self.adapters["claude"].calls, [])

    def test_openai_prompt_versions_name_the_service(self):
        self.found = json.loads(json.dumps(FOUND_NONE))
        self.settings.update(lambda d: d["openai"].extend([
            {"id": "oA", "name": "A", "base_url": "https://a.example/v1", "api": "chat", "model": "gpt-x", "key": "k" * 20},
            {"id": "oB", "name": "B", "base_url": "https://b.example/v1", "api": "chat", "model": "gpt-x", "key": "k" * 20}]))
        self.adapters["openai"] = FakeAdapter(ok(billing="api"), ok(billing="api"))
        eng = self.engines()
        self.set_task("ask", {"engine": "openai", "model": "gpt-x", "entry": "oA"})
        a = eng.run("ask", "p", prompt_version="v1")["prompt_version"]
        self.set_task("ask", {"engine": "openai", "model": "gpt-x", "entry": "oB"})
        b = eng.run("ask", "p", prompt_version="v1")["prompt_version"]
        self.assertEqual((a, b), ("v1@openai:oA/gpt-x", "v1@openai:oB/gpt-x"))
        self.assertEqual(self.adapters["openai"].calls[1]["base_url"], "https://b.example/v1")

    def test_unexpected_adapter_exceptions_become_error_codes(self):
        with mock.patch.object(openai_api, "complete", side_effect=json.JSONDecodeError("x", "<html>", 0)):
            with self.assertRaises(ai.AIError) as cm:
                ai.OpenAIAdapter().call({"base_url": "https://a.example/v1", "model": "m", "key": "k" * 20}, "p")
        self.assertEqual((cm.exception.code, cm.exception.detail), ("ENGINE_ERROR", "JSONDecodeError"))
        with mock.patch.object(engines, "claude_path", return_value="claude"), \
                mock.patch.object(engines, "run_claude", side_effect=FileNotFoundError("claude")):
            with self.assertRaises(ai.AIError) as cm:
                ai.CliAdapter("claude").call({"model": ""}, "p")
        self.assertEqual(cm.exception.code, "ENGINE_ERROR")

    def test_cli_failures_after_tokens_were_reported_carry_the_usage(self):
        def fake(c, prompt, cwd, cancel, meter):
            meter.add(input=50, cached=0, output=7)
            raise engines.EngineError("Claude Code 出错：boom")
        with mock.patch.object(engines, "claude_path", return_value="claude"), mock.patch.object(engines, "run_claude", fake):
            with self.assertRaises(ai.AIError) as cm:
                ai.CliAdapter("claude").call({"model": ""}, "p")
        self.assertEqual((cm.exception.usage["input"], cm.exception.usage["output"]), (50, 7))


class RedirectTest(unittest.TestCase):
    """OpenAI 相容接口回 3xx 時不跟過去：urllib 會把帶 key 的 Authorization 原樣送到新地址。"""

    def serve(self, handler):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_port

    def test_the_key_never_follows_a_redirect(self):
        leaked = []

        class Target(BaseHTTPRequestHandler):
            def do_GET(self):
                leaked.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data": []}')
            do_POST = do_GET

            def log_message(self, *a):
                pass

        target = self.serve(Target)

        class Hop(BaseHTTPRequestHandler):
            def do_GET(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))  # 讀掉 body，Windows 才不會中止連線
                self.send_response(302 if self.command == "GET" else 307)
                self.send_header("Location", f"http://127.0.0.1:{target}/v1/models")
                self.send_header("Content-Length", "0")
                self.end_headers()
            do_POST = do_GET

            def log_message(self, *a):
                pass

        hop = self.serve(Hop)
        o = {"base_url": f"http://127.0.0.1:{hop}/v1", "api_key": SECRET, "model": "m", "request_attempts": 1, "timeout": 5}
        with self.assertRaises(engines.EngineError) as cm:
            openai_api.models(o)
        self.assertEqual(cm.exception.status, 302)
        with self.assertRaises(engines.EngineError) as cm:
            openai_api.complete(o, "p", [], None, None)
        self.assertEqual(cm.exception.status, 307)
        self.assertEqual(leaked, [])
        with mock.patch.object(openai_api, "complete", side_effect=cm.exception):
            with self.assertRaises(ai.AIError) as err:
                ai.OpenAIAdapter().call({"base_url": o["base_url"], "model": "m", "key": SECRET}, "p")
        self.assertEqual(err.exception.code, "ENGINE_ERROR")

    def test_upstream_error_text_is_scrubbed(self):
        e = urllib.error.HTTPError("https://x.example/v1", 401, "no", Message(), None)
        e.detail = f'{{"error": "bad key {SECRET}"}}'
        self.assertNotIn("SECRETSECRET", str(openai_api._http_error(e)))


class SettingsFileTest(unittest.TestCase):
    def test_broken_or_hand_edited_files_load_as_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai.json"
            s = ai.Settings(path)
            for raw in ("[1,2]", '{"tasks": "x", "openai": {"a": 1}, "anthropic": 5}',
                        '{"tasks": {"ask": {"primary": {"engine": "evil"}}}, "openai": [{"id": 3}], "engines": {"rm": {}}}'):
                path.write_text(raw, encoding="utf-8")
                data = s.load()
                self.assertEqual(data["tasks"]["ask"], {"primary": None, "fallback": None})
                self.assertIsNone(data["anthropic"])
                self.assertEqual(data["openai"], [])
                self.assertEqual(data["engines"], {})
            path.unlink()
            self.assertIsNone(s.load()["anthropic"])

    @unittest.skipIf(os.name == "nt", "Windows 沿用使用者資料夾的權限")
    def test_settings_file_is_private_from_the_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai.json"
            seen = []
            real = os.replace

            def spy(src, dst):  # 暫存檔改名之前就已經是 0600
                seen.append(stat.S_IMODE(os.stat(src).st_mode))
                return real(src, dst)
            with mock.patch("os.replace", spy):
                ai.Settings(path).update(lambda d: d.__setitem__("anthropic", {"key": SECRET}))
            self.assertEqual(seen, [0o600])
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_a_failed_write_leaves_no_temp_file_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai.json"
            with self.assertRaises(TypeError):
                write_json_atomic(path, {"key": SECRET, "bad": object()}, mode=0o600)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_last4_never_reveals_a_short_key(self):
        self.assertEqual(ai.last4(SECRET), "a9Fw")
        self.assertEqual(ai.last4("short-key"), "")
        self.assertEqual(ai.last4(None), "")


# ---------- HTTP ----------
class AiApiCase(ApiTestCase):
    def make_app(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.ai_path, self.db = root / "ai.json", root / "newsread.sqlite3"
        self.found = json.loads(json.dumps(FOUND_ALL))
        self.adapters = {e: FakeAdapter() for e in ai.ENGINES}
        self.addCleanup(ai._ENGINES.clear)
        return {"ledger_path": self.db, "ai_path": self.ai_path,
                "ai_options": {"adapters": self.adapters, "detector": lambda fresh=False: self.found,
                               "wait": lambda s, c: None, "has_sdk": lambda: True, "quota": lambda: None}}

    def bad(self, path, body, field):
        status, data = self.request("POST", path, body)
        self.assertEqual(status, 400, data)
        self.assertEqual(data["field"], field, data)
        return data


class AiApiTest(AiApiCase):
    def test_key_is_masked_everywhere_but_the_local_file(self):
        self.adapters["anthropic"].check_result = None
        with self.assertLogs(log, level="DEBUG") as logs:
            log.info("start")
            status, data = self.post("/api/ai/keys/anthropic", {"key": "  " + SECRET + " "})
            self.assertEqual(status, 200, data)
            self.assertEqual(data["anthropic"]["last4"], "a9Fw")
            self.assertEqual(data["test"]["status"], "ok")
            self.assertEqual(self.adapters["anthropic"].checks[0]["key"], SECRET)
            bodies = [json.dumps(data)]
            for path in ("/api/ai", "/api/config"):
                status, got = self.get(path)
                self.assertEqual(status, 200)
                bodies.append(json.dumps(got))
            self.adapters["anthropic"].check_result = ai.AIError("AUTH_INVALID", "invalid x-api-key " + SECRET)
            status, data = self.post("/api/ai/keys/anthropic", {"key": SECRET})
            self.assertEqual(data["test"], {"ok": False, "status": "invalid", "code": "AUTH_INVALID", "message": ai.message("AUTH_INVALID")})
            bodies.append(json.dumps(data))
            status, data = self.post("/api/ai/keys/openai", {"name": "範例服務", "base_url": "https://api.example.com/v1",
                                                             "model": "m-1", "key": "sk-openai-SECRETSECRET-9zZ9"})
            self.assertEqual(status, 200, data)
            bodies.append(json.dumps(data))
        for body in bodies:
            self.assertNotIn("SECRETSECRET", body)
        self.assertNotIn("SECRET", "\n".join(logs.output))
        self.assertIn(SECRET, self.ai_path.read_text(encoding="utf-8"))  # 只存在本機設定檔
        self.assertEqual(data["openai"][0]["last4"], "9zZ9")

    def test_anthropic_key_validation_and_remove(self):
        self.bad("/api/ai/keys/anthropic", {}, "key")
        self.bad("/api/ai/keys/anthropic", {"key": "has space inside-key"}, "key")
        self.bad("/api/ai/keys/anthropic", {"key": "x" * (ai.MAX_KEY + 1)}, "key")
        self.bad("/api/ai/keys/anthropic", {"key": "金鑰金鑰金鑰金鑰金鑰"}, "key")
        self.bad("/api/ai/keys/anthropic", {"key": 12345678}, "key")
        status, data = self.post("/api/ai/keys/anthropic", {"key": SECRET})
        self.assertEqual(status, 200)
        status, data = self.post("/api/ai/keys/anthropic/remove")
        self.assertEqual((status, data["anthropic"]), (200, None))

    def test_unverifiable_key_is_kept_but_marked(self):
        self.adapters["anthropic"].check_result = ai.AIError("NETWORK", "dns failed")
        status, data = self.post("/api/ai/keys/anthropic", {"key": SECRET})
        self.assertEqual((data["test"]["status"], data["anthropic"]["status"], data["anthropic"]["code"]), ("unverified", "unverified", "NETWORK"))

    def test_openai_entries_validate_urls_and_keep_keys_on_the_same_host(self):
        for url in ("http://api.example.com/v1", "ftp://x/v1", "https://user:pw@api.example.com", "https://api.example.com/v1?k=1",
                    "https://api.example.com/v1#x", "javascript:alert(1)", "https://", "https://exa mple.com", "https://x:99999/v1",
                    "https://" + "a" * ai.MAX_URL):
            self.bad("/api/ai/keys/openai", {"base_url": url, "model": "m"}, "base_url")
        self.bad("/api/ai/keys/openai", {"base_url": "https://api.example.com/v1"}, "model")
        self.bad("/api/ai/keys/openai", {"base_url": "https://api.example.com/v1", "model": "m", "api": "soap"}, "api")
        self.bad("/api/ai/keys/openai", {"base_url": "https://api.example.com/v1", "model": "m", "name": "n" * 41}, "name")
        status, data = self.post("/api/ai/keys/openai", {"base_url": "http://localhost:1234/v1/", "model": "local-model"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["openai"][0]["base_url"], "http://localhost:1234/v1")
        self.assertEqual(self.adapters["openai"].checks[0]["base_url"], "http://localhost:1234/v1")  # 本機的不用 key 也測
        status, data = self.post("/api/ai/keys/openai", {"base_url": "https://api.example.com/v1", "model": "m", "key": "sk-aaaaaaaaaaaa-1111"})
        oid = data["id"]
        status, data = self.post(f"/api/ai/keys/openai/{oid}", {"base_url": "https://api.example.com/v1", "model": "m2", "name": "改名"})
        entry = next(o for o in data["openai"] if o["id"] == oid)
        self.assertEqual((entry["last4"], entry["model"], entry["name"]), ("1111", "m2", "改名"))  # 沒帶 key = 不改
        status, data = self.post(f"/api/ai/keys/openai/{oid}", {"base_url": "https://other.example.com/v1", "model": "m2"})
        entry = next(o for o in data["openai"] if o["id"] == oid)
        self.assertFalse(entry["has_key"])  # 換地址就不把舊 key 送過去
        self.assertEqual(data["test"]["status"], "untested")
        self.assertEqual(self.request("POST", "/api/ai/keys/openai/nope", {"base_url": "https://a.example.com", "model": "m"})[0], 404)
        status, data = self.post(f"/api/ai/keys/openai/{oid}/remove")
        self.assertEqual([o["id"] for o in data["openai"]].count(oid), 0)

    def test_openai_entries_are_capped(self):
        for i in range(ai.MAX_OPENAI):
            self.assertEqual(self.post("/api/ai/keys/openai", {"base_url": "http://127.0.0.1:1234/v1", "model": f"m{i}"})[0], 200)
        self.bad("/api/ai/keys/openai", {"base_url": "http://127.0.0.1:1234/v1", "model": "one-more"}, "form")

    def test_choose_engines_per_task(self):
        status, data = self.get("/api/ai")
        self.assertEqual(data["tasks"]["triage"]["state"], "ready")
        self.assertEqual(data["tasks"]["triage"]["using"], "claude||claude-haiku-5-5")  # 自動：Claude Code · Haiku
        self.assertEqual(data["tasks"]["draft"]["using"], "claude||claude-opus-5-5")
        self.assertIn("codex||", [c["id"] for c in data["choices"]])
        status, data = self.post("/api/ai/tasks", {"task": "translate", "primary": "codex||", "fallback": "claude||claude-sonnet-5-5"})
        self.assertEqual(status, 200, data)
        self.assertEqual((data["tasks"]["translate"]["primary"], data["tasks"]["translate"]["fallback"]), ("codex||", "claude||claude-sonnet-5-5"))
        status, data = self.post("/api/ai/tasks", {"task": "translate", "primary": "codex||", "fallback": "codex||"})
        self.assertIsNone(data["tasks"]["translate"]["fallback"])  # 備用跟主要一樣等於沒有
        status, data = self.post("/api/ai/tasks", {"task": "translate", "primary": ""})
        self.assertIsNone(data["tasks"]["translate"]["primary"])
        self.bad("/api/ai/tasks", {"task": "rm -rf", "primary": "codex||"}, "task")
        for bad in ("evil||", "claude||gpt-5", "anthropic||", "codex||o3", "openai|nope|m", "claude|x|claude-haiku-5-5", 5, "a" * 200):
            self.bad("/api/ai/tasks", {"task": "ask", "primary": bad}, "primary")
        self.bad("/api/ai/tasks", {"task": "ask", "fallback": "evil||"}, "fallback")

    def test_redetect_and_unknown_paths(self):
        status, data = self.post("/api/ai/detect")
        self.assertEqual(status, 200)
        self.assertTrue(data["detected"]["claude"]["found"])
        self.assertEqual(self.get("/api/ai/whatever")[0], 404)
        self.assertEqual(self.request("POST", "/api/ai/whatever", {})[0], 404)
        self.assertEqual(self.request("POST", "/api/ai/tasks", {}, token="wrong")[0], 403)

    def test_body_limit_and_bad_json(self):
        status, data = self.request("POST", "/api/ai/tasks", b"{" + b" " * (ai.MAX_BODY + 10) + b"}")
        self.assertEqual(status, 413)
        status, data = self.request("POST", "/api/ai/tasks", b"[" * 15000)  # 很深的巢狀，但沒超過大小上限
        self.assertEqual(status, 400)
        status, data = self.request("POST", "/api/ai/tasks", b"not json")
        self.assertEqual(status, 400)

    def test_unexpected_errors_return_a_fixed_message(self):
        with mock.patch.object(ai.Engines, "set_task", side_effect=RuntimeError("boom " + SECRET)):
            with self.assertLogs(log, level="WARNING") as logs:
                status, data = self.request("POST", "/api/ai/tasks", {"task": "ask"})
        self.assertEqual(status, 500)
        self.assertNotIn("SECRET", json.dumps(data))
        self.assertNotIn("SECRET", "\n".join(logs.output))

    def test_without_ai_the_rest_of_the_app_works(self):
        self.found.update(json.loads(json.dumps(FOUND_NONE)))
        status, data = self.get("/api/ai")
        self.assertFalse(data["any_ai"])
        self.assertEqual(data["tasks"]["triage"]["state"], "no_ai")
        self.assertFalse(self.db.exists())  # 看設定不建帳本檔
        from easyread import entities
        self.addCleanup(entities._STORES.pop, self.db, None)
        status, ent = self.post("/api/entities", {"type": "theme", "name": "範例題材"})
        self.assertEqual(status, 200, ent)
        status, rows = self.get("/api/ledger")
        self.assertEqual(status, 200, rows)
        self.assertEqual(self.get("/settings")[0], 200)


if __name__ == "__main__":
    unittest.main()
