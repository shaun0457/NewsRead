"""Ticket 68：訂閱額度保護。全部用假引擎、假的額度數字和可以撥的時鐘，不呼叫真的 CLI；資料是虛構的範例。"""
from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from easyread import ai_engines as ai
from easyread import ledger, quota_guard, triage
from tests import test_triage as tt
from tests.test_ai_engines import ANTHROPIC_SONNET, CLAUDE_SONNET, SECRET, AiApiCase, FakeAdapter, ok
from tests.test_ai_engines import Base as EngineBase


def quota(used, now, resets_in=3600.0, seen_ago=60.0):
    """usage.latest() 的格式：Claude Code 最近一次回報的 5 小時額度。"""
    return {"limits": {"five_hour": {"used": used, "resets_at": now + resets_in}, "seven_day": {"used": 0.2, "resets_at": now + 86400}},
            "at": now - seen_ago}


def api(cost=0.01, text="好"):
    return ok(text, cost=cost, billing="api")


class GuardBase(EngineBase):
    def setUp(self):
        super().setUp()
        self.t = time.time()
        self.q = None
        self.notes: list[dict] = []

    def engines(self, notifier=None):
        return ai.Engines(self.settings, self.index, adapters=self.adapters, detector=lambda fresh=False: self.found,
                          wait=lambda s, cancel: self.waits.append(s), has_sdk=lambda: True, quota=lambda: self.q,
                          now=lambda: self.t, notifier=notifier or self.notes.append)

    def guard(self, **kw):
        self.settings.update(lambda d: d["guard"].update(kw))

    def events(self):
        return quota_guard.Events(self.index).list()

    def codes(self):
        return [e["code"] for e in reversed(self.events())]

    def bg(self, eng, task="triage"):
        return eng.run(task, "p", prompt_version="v1", trigger="background")


class TriggerTest(GuardBase):
    def test_trigger_must_be_given_explicitly(self):
        eng = self.engines()
        with self.assertRaises(TypeError):
            eng.run("ask", "p", prompt_version="v1")  # noqa — 沒標 trigger
        with self.assertRaises(ValueError):
            eng.run("ask", "p", prompt_version="v1", trigger="auto")
        self.assertEqual(self.adapters["claude"].calls, [])

    def test_triage_marks_its_calls_as_background(self):
        seen = []
        with mock.patch.object(ai.Engines, "run", lambda self, *a, **kw: seen.append(kw["trigger"]) or ok()):
            b = TriageGuardBase("setUp")
            b.setUp()
            self.addCleanup(b.doCleanups)
            b.add(datetime.now(timezone.utc) - timedelta(hours=1))
            triage.run_pending(b.app, engine=b.engine())
        self.assertEqual(seen, ["background"])


class BackgroundApiOnlyTest(GuardBase):
    """條款不明確（ticket 68 的條款查證）：背景工作預設不用訂閱 CLI，改用 API key 或本機模型。"""

    def test_default_settings(self):
        self.assertEqual(self.settings.load()["guard"], {"background_subscription": False, "threshold": 70,
                                                         "on_exceed": "wait", "api_monthly_usd": 15.0})

    def test_background_uses_the_api_key_and_manual_uses_the_subscription(self):
        self.add_anthropic()
        self.set_task("translate", CLAUDE_SONNET)  # 設定選的是訂閱
        self.adapters["anthropic"] = FakeAdapter(api())
        self.adapters["claude"] = FakeAdapter(ok("手動"))
        eng = self.engines()
        res = self.bg(eng, "translate")
        self.assertEqual((res["engine"], res["model"]), ("anthropic", "claude-sonnet-5-5"))
        self.assertEqual(self.adapters["claude"].calls, [])
        res = eng.run("translate", "p", prompt_version="v1", trigger="manual")
        self.assertEqual((res["engine"], res["quota_notice"]), ("claude", None))

    def test_without_a_key_background_pauses_and_records_one_event(self):
        eng = self.engines()
        for _ in range(3):
            with self.assertRaises(ai.AIError) as cm:
                self.bg(eng)
            self.assertEqual(cm.exception.code, "BACKGROUND_NO_API")
        self.assertEqual(self.adapters["claude"].calls, [])
        self.assertEqual(self.codes(), ["BACKGROUND_NO_API"])  # 每一輪都碰到，只記一筆
        self.assertEqual(self.events()[0]["task"], "triage")

    def test_a_local_model_counts_for_background(self):
        self.found["ollama"] = {"running": True, "models": ["local-m"]}
        self.adapters["ollama"] = FakeAdapter(ok(cost=0.0, billing="local"))
        self.assertEqual(self.bg(self.engines())["engine"], "ollama")

    def test_a_cli_billed_through_an_api_key_is_not_a_subscription(self):
        self.settings.update(lambda d: d["engines"].__setitem__("claude", {"auth": "ok", "billing": "api"}))
        self.adapters["claude"] = FakeAdapter(ok(cost=0.02, billing="api"))
        self.assertEqual(self.bg(self.engines())["engine"], "claude")


class ThresholdTest(GuardBase):
    def setUp(self):
        super().setUp()
        self.guard(background_subscription=True)

    def test_at_75_percent_background_does_not_call_the_engine(self):
        self.q = quota(0.75, self.t)
        eng = self.engines()
        for task in ("triage", "thesis_change", "translate", "draft"):
            with self.assertRaises(ai.AIError) as cm:
                self.bg(eng, task)
            self.assertEqual(cm.exception.code, "QUOTA_PAUSED", task)
        with self.assertRaises(ai.AIError):
            self.bg(eng)  # 同一段暫停再碰到一次
        self.assertEqual(self.adapters["claude"].calls, [])
        ev = [e for e in self.events() if e["task"] == "triage"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["data"]["used"], 0.75)
        self.assertEqual(ev[0]["data"]["threshold"], 70)
        self.assertEqual(ev[0]["data"]["until"], int(self.t + 3600))

    def test_manual_calls_still_run_with_a_reminder(self):
        self.q = quota(0.75, self.t)
        self.adapters["claude"] = FakeAdapter(ok("照跑"))
        res = self.engines().run("ask", "p", prompt_version="v1", trigger="manual")
        self.assertEqual((res["text"], res["quota_notice"]), ("照跑", "QUOTA_OVER"))
        self.assertEqual(self.events(), [])  # 手動的不算觸發保護

    def test_threshold_is_configurable_and_inclusive(self):
        self.adapters["claude"] = FakeAdapter(ok(), ok())
        eng = self.engines()
        self.q = quota(0.69, self.t)
        self.assertEqual(self.bg(eng)["engine"], "claude")
        self.q = quota(0.70, self.t)
        with self.assertRaises(ai.AIError):
            self.bg(eng)
        self.guard(threshold=80)
        self.q = quota(0.75, self.t)
        self.assertEqual(self.bg(eng)["engine"], "claude")

    def test_after_the_reset_time_background_runs_again(self):
        self.q = quota(0.95, self.t, resets_in=600)
        self.adapters["claude"] = FakeAdapter(ok())
        eng = self.engines()
        with self.assertRaises(ai.AIError):
            self.bg(eng)
        self.t += 601  # 額度數字是重置前記下的，已經不準了
        self.assertEqual(self.bg(eng)["engine"], "claude")

    def test_codex_is_not_paused_by_the_claude_quota(self):
        self.q = quota(0.9, self.t)
        self.set_task("translate", {"engine": "codex", "model": "", "entry": ""})
        self.adapters["codex"] = FakeAdapter(ok())
        self.assertEqual(self.bg(self.engines(), "translate")["engine"], "codex")

    def test_wait_mode_does_not_switch_to_a_configured_api_fallback(self):
        self.q = quota(0.9, self.t)
        self.add_anthropic()
        self.set_task("translate", CLAUDE_SONNET, ANTHROPIC_SONNET)
        with self.assertRaises(ai.AIError) as cm:
            self.bg(self.engines(), "translate")
        self.assertEqual(cm.exception.code, "QUOTA_PAUSED")
        self.assertEqual(self.adapters["anthropic"].calls, [])

    def test_an_api_primary_keeps_running_over_the_threshold(self):
        self.q = quota(0.9, self.t)
        self.add_anthropic()
        self.set_task("translate", ANTHROPIC_SONNET)
        self.adapters["anthropic"] = FakeAdapter(api())
        self.assertEqual(self.bg(self.engines(), "translate")["engine"], "anthropic")
        self.assertEqual(self.events(), [])


class SwitchToApiTest(GuardBase):
    def setUp(self):
        super().setUp()
        self.guard(background_subscription=True, on_exceed="api")
        self.q = quota(0.8, self.t)

    def test_over_the_threshold_background_uses_the_key(self):
        self.add_anthropic()
        self.set_task("triage", {"engine": "claude", "model": "claude-haiku-5-5", "entry": ""})
        self.adapters["anthropic"] = FakeAdapter(api(), api())
        eng = self.engines()
        self.assertEqual(self.bg(eng)["engine"], "anthropic")
        self.assertEqual(self.bg(eng)["engine"], "anthropic")
        self.assertEqual(self.adapters["claude"].calls, [])
        self.assertEqual(self.codes(), ["QUOTA_SWITCHED_API"])

    def test_without_a_key_it_waits(self):
        with self.assertRaises(ai.AIError) as cm:
            self.bg(self.engines())
        self.assertEqual(cm.exception.code, "QUOTA_PAUSED")
        self.assertEqual(self.codes(), ["QUOTA_PAUSED"])


class ApiCapTest(GuardBase):
    def setUp(self):
        super().setUp()
        self.guard(api_monthly_usd=1.0)
        self.add_anthropic()

    def spend(self, usd, at=None):
        if at is None:
            self.index.record_usage(source="test", task="ask", engine="anthropic", model="m", cost_usd=usd)
            return
        with self.index.write() as db:  # 上個月的花費：直接寫時間
            db.execute("INSERT INTO ai_usage (at, source, task, engine, model, input_tokens, cached_tokens, output_tokens, "
                       "cost_usd) VALUES (?,?,?,?,?,0,0,0,?)", (ledger.iso(at), "test", "ask", "anthropic", "m", usd))

    def test_80_percent_and_the_cap_notify_once_each(self):
        self.spend(0.70)
        self.spend(5.0, at=quota_guard.month_start(self.t) - timedelta(seconds=1))  # 上個月的不算
        self.adapters["anthropic"] = FakeAdapter(api(0.05), api(0.05), api(0.25), api(0.01))
        eng = self.engines()
        self.bg(eng)  # 0.75：還沒到 80%
        self.assertEqual(self.notes, [])
        self.bg(eng)  # 0.80
        self.bg(eng)  # 1.05：到上限
        self.assertEqual([n["code"] for n in self.notes], ["API_CAP_WARN", "API_CAP_REACHED"])
        self.assertEqual(self.notes[1]["data"]["cap_usd"], 1.0)
        with self.assertRaises(ai.AIError) as cm:
            self.bg(eng)  # 到上限之後背景分類不用 API
        self.assertEqual(cm.exception.code, "API_CAP")
        self.set_task("ask", ANTHROPIC_SONNET)
        res = eng.run("ask", "p", prompt_version="v1", trigger="manual")  # 手動照跑，提醒到上限了
        self.assertEqual((res["engine"], res["quota_notice"]), ("anthropic", "API_CAP"))
        self.assertEqual(len(self.notes), 2)  # 每個月各一次
        self.assertEqual(eng.guard_status()["api"]["reached"], True)

    def test_at_the_cap_translation_and_drafting_stop(self):
        self.spend(1.0)
        self.guard(background_subscription=True)
        eng = self.engines()
        for task in ("translate", "draft"):
            with self.assertRaises(ai.AIError) as cm:
                self.bg(eng, task)  # 用訂閱也停
            self.assertEqual(cm.exception.code, "API_CAP")
        self.assertEqual(self.adapters["claude"].calls + self.adapters["anthropic"].calls, [])
        self.assertEqual(sorted(e["task"] for e in self.events()), ["draft", "translate"])
        self.assertTrue(all(e["code"] == "API_CAP_STOPPED" for e in self.events()))

    def test_at_the_cap_triage_waits_for_the_subscription(self):
        self.spend(2.0)
        self.set_task("triage", {"engine": "anthropic", "model": "claude-haiku-5-5", "entry": ""},
                      {"engine": "claude", "model": "claude-haiku-5-5", "entry": ""})
        eng = self.engines()
        with self.assertRaises(ai.AIError) as cm:  # 背景不能用訂閱：等
            self.bg(eng)
        self.assertEqual(cm.exception.code, "API_CAP")
        self.guard(background_subscription=True)
        self.adapters["claude"] = FakeAdapter(ok())
        self.assertEqual(self.bg(eng)["engine"], "claude")  # 改用訂閱額度
        self.q = quota(0.9, self.t)
        with self.assertRaises(ai.AIError) as cm:
            self.bg(eng)
        self.assertEqual(cm.exception.code, "QUOTA_PAUSED")
        self.assertEqual(self.adapters["anthropic"].calls, [])

    def test_manual_drafting_at_the_cap_runs_with_a_reminder(self):
        self.spend(1.5)
        self.set_task("draft", {"engine": "anthropic", "model": "claude-opus-5-5", "entry": ""})
        self.adapters["anthropic"] = FakeAdapter(api(0.2))
        res = self.engines().run("draft", "p", prompt_version="v1", trigger="manual")
        self.assertEqual((res["engine"], res["quota_notice"]), ("anthropic", "API_CAP"))

    def test_cap_zero_means_no_api_in_background_not_a_reached_cap(self):
        self.guard(api_monthly_usd=0.0)
        self.found["ollama"] = {"running": True, "models": ["local-m"]}
        self.adapters["ollama"] = FakeAdapter(ok(cost=0.0, billing="local"), ok(cost=0.0, billing="local"))
        eng = self.engines()
        self.assertEqual(self.bg(eng)["engine"], "ollama")             # 分類用本機模型，不用 API
        self.assertEqual(self.bg(eng, "translate")["engine"], "ollama")  # 翻譯沒有被當成「到上限」停掉
        self.assertEqual(self.adapters["anthropic"].calls, [])
        status = eng.guard_status()
        self.assertEqual((status["background"]["paused"], status["api"]["reached"], status["api"]["warn"]), (False, False, False))
        self.assertEqual(self.events(), [])

    def test_a_stopped_task_is_recorded_again_next_month(self):
        self.spend(1.0)
        eng = self.engines()
        for _ in range(2):
            with self.assertRaises(ai.AIError):
                self.bg(eng, "translate")
        self.t = (quota_guard.month_start(self.t) + timedelta(days=40)).timestamp()  # 下個月（再花到上限）
        self.spend(1.0, at=datetime.fromtimestamp(self.t, timezone.utc))
        with self.assertRaises(ai.AIError):
            self.bg(eng, "translate")
        months = [e["data"]["month"] for e in reversed(self.events()) if e["code"] == "API_CAP_STOPPED"]
        self.assertEqual(len(months), 2)
        self.assertNotEqual(months[0], months[1])

    def test_unknown_costs_do_not_count(self):
        self.index.record_usage(source="test", task="ask", engine="openai", model="m", cost_usd=None)
        self.assertEqual(self.engines().guard_status()["api"]["spent_usd"], 0.0)

    def test_a_failing_notifier_does_not_break_the_call(self):
        self.spend(0.9)
        self.adapters["anthropic"] = FakeAdapter(api(0.2))

        def boom(event):
            raise RuntimeError("telegram down")
        self.assertEqual(self.bg(self.engines(notifier=boom))["engine"], "anthropic")
        self.assertEqual(self.codes(), ["API_CAP_REACHED"])

    def test_the_default_notifier_sends_nothing_until_one_is_set(self):
        quota_guard.notify({"code": "API_CAP_WARN"})  # 沒設：不做事
        got = []
        quota_guard.set_notifier(got.append)
        self.addCleanup(quota_guard.set_notifier, None)
        quota_guard.notify({"code": "API_CAP_WARN"})
        quota_guard.set_notifier(lambda e: 1 / 0)
        quota_guard.notify({"code": "API_CAP_WARN"})  # 丟例外也不往外傳
        self.assertEqual(got, [{"code": "API_CAP_WARN"}])


class BrokenQuotaFileTest(GuardBase):
    def test_an_unreadable_quota_file_does_not_fail_every_call(self):
        def broken():
            raise ValueError("C:/secret/limits.json is not JSON")
        self.adapters["claude"] = FakeAdapter(ok("照跑"))
        eng = ai.Engines(self.settings, self.index, adapters=self.adapters, detector=lambda fresh=False: self.found,
                         wait=lambda s, cancel: None, has_sdk=lambda: True, quota=broken, now=lambda: self.t)
        with self.assertLogs(level="WARNING") as logs:
            res = eng.run("ask", "p", prompt_version="v1", trigger="manual")
        self.assertEqual(res["text"], "照跑")
        self.assertNotIn("secret", "".join(logs.output))
        self.assertFalse(eng.guard_status()["quota"]["over"])


class QuotaStateTest(unittest.TestCase):
    NOW = 1_800_000_000.0

    def test_reset_time_and_bounds(self):
        now = self.NOW
        st = quota_guard.quota_state(quota(0.8, now), 70, now)
        self.assertEqual((st["over"], st["until"]), (True, now + 3600))
        st = quota_guard.quota_state(quota(0.8, now, resets_in=-1), 70, now)
        self.assertFalse(st["over"])  # 已經過了重置時間
        # 重置時間比記下的時間晚超過 5 小時：最多暫停到記下的時間 + 5 小時
        st = quota_guard.quota_state(quota(0.8, now, resets_in=30 * 86400, seen_ago=0), 70, now)
        self.assertEqual(st["until"], now + quota_guard.WINDOW)
        self.assertFalse(quota_guard.quota_state(quota(0.8, now, resets_in=30 * 86400, seen_ago=0), 70,
                                                 now + quota_guard.WINDOW)["over"])
        # 沒有重置時間：同樣最多 5 小時
        q = {"limits": {"five_hour": {"used": 0.9}}, "at": now - 100}
        self.assertEqual(quota_guard.quota_state(q, 70, now)["until"], now - 100 + quota_guard.WINDOW)

    def test_unusable_numbers_do_not_pause(self):
        now = self.NOW
        for latest in (None, {}, [], {"limits": "x"}, {"limits": {"five_hour": {"used": "0.9"}}, "at": now},
                       {"limits": {"five_hour": {"used": True, "resets_at": now + 10}}, "at": now},
                       {"limits": {"five_hour": {"used": 0.9, "resets_at": now + 10}}},  # 沒有記下時間
                       {"limits": {"five_hour": {"used": float("nan"), "resets_at": now + 10}}, "at": now}):
            self.assertFalse(quota_guard.quota_state(latest, 70, now)["over"], latest)


class EventsTest(GuardBase):
    def test_events_keep_only_codes_and_fixed_numbers(self):
        ev = quota_guard.Events(self.index)
        ev.add("QUOTA_PAUSED", "triage", {"used": 0.75, "threshold": 70, "detail": "upstream said " + SECRET, "month": "x"})
        got = ev.list()[0]
        self.assertEqual(got["data"], {"used": 0.75, "threshold": 70})
        self.assertEqual(got["message"], quota_guard.message("QUOTA_PAUSED"))
        self.assertNotIn(SECRET, json.dumps(ev.list()))
        with self.assertRaises(ValueError):
            ev.add("SOMETHING_ELSE")

    def test_the_table_is_capped_and_lists_newest_first(self):
        ev = quota_guard.Events(self.index)
        with mock.patch.object(quota_guard, "MAX_EVENTS", 3):
            for i in range(5):
                ev.add("CATCHUP_DONE", f"t{i}", {"count": i})
        rows = ev.list()
        self.assertEqual([r["task"] for r in rows], ["t4", "t3", "t2"])
        with mock.patch.object(quota_guard, "MAX_LIST", 2):
            self.assertEqual(len(ev.list(limit=10_000)), 2)

    def test_once_per_key(self):
        ev = quota_guard.Events(self.index)
        self.assertIsNotNone(ev.add("API_CAP_WARN", "", {}, key="2026-11", once=True))
        ev.add("CATCHUP_DONE", "")
        self.assertIsNone(ev.add("API_CAP_WARN", "", {}, key="2026-11", once=True))

    def test_rate_limited_does_not_break_the_repeat_check_of_other_events(self):
        ev = quota_guard.Events(self.index)
        self.assertIsNotNone(ev.add("RATE_LIMITED", "triage", {}, key="100", once=True))
        self.assertIsNotNone(ev.add("QUOTA_SWITCHED_API", "triage", {}, key="u1"))
        self.assertIsNone(ev.add("RATE_LIMITED", "triage", {}, key="100", once=True))   # 同一個時段
        self.assertIsNone(ev.add("QUOTA_SWITCHED_API", "triage", {}, key="u1"))         # 中間的限流不算「上一筆」
        self.assertIsNotNone(ev.add("RATE_LIMITED", "triage", {}, key="101", once=True))
        self.assertIsNone(ev.add("QUOTA_SWITCHED_API", "triage", {}, key="u1"))
        self.assertEqual([e["code"] for e in ev.list()], ["RATE_LIMITED", "QUOTA_SWITCHED_API", "RATE_LIMITED"])
        self.assertIsNotNone(ev.add("API_CAP_WARN", "", {}, key="2026-12", once=True))


class SettingsTest(GuardBase):
    def test_hand_edited_guard_settings_fall_back_to_defaults(self):
        self.settings.path.write_text(json.dumps({"guard": {"background_subscription": "yes", "threshold": 0, "on_exceed": "x",
                                                            "api_monthly_usd": -3}}), encoding="utf-8")
        self.assertEqual(self.settings.load()["guard"], quota_guard.defaults())
        self.settings.path.write_text(json.dumps({"guard": {"background_subscription": True, "threshold": 85,
                                                            "on_exceed": "api", "api_monthly_usd": 20}}), encoding="utf-8")
        self.assertEqual(self.settings.load()["guard"], {"background_subscription": True, "threshold": 85, "on_exceed": "api",
                                                         "api_monthly_usd": 20.0})


# ---------- 背景分類 ----------
class TriageGuardBase(tt.Base):
    def setUp(self):
        super().setUp()
        self.t = time.time()
        self.q = None

    def engine(self):
        return ai.Engines(self.settings, self.index, adapters=self.adapters, detector=lambda fresh=False: self.found,
                          wait=lambda s, c: None, has_sdk=lambda: True, quota=lambda: self.q, now=lambda: self.t)

    def state(self, item):
        return self.rows("SELECT state, attempts, error FROM triage_state WHERE item_id=?", item)[0]

    def guard_codes(self):
        return [e["code"] for e in reversed(quota_guard.Events(self.index).list())]


class TriageGuardTest(TriageGuardBase):
    def recent(self, minutes=60):
        return datetime.now(timezone.utc) - timedelta(minutes=minutes)

    def test_paused_items_stay_pending_in_the_database(self):
        self.q = quota(0.75, self.t)
        first = self.add(self.recent())
        for _ in range(3):
            self.assertEqual(self.triage_round()["paused"], 1)
        second = self.add(self.recent(), text="另一則範例新聞，暫停期間才匯入。")  # 暫停期間照常匯入
        self.triage_round()
        self.assertEqual(self.adapter.prompts, [])
        for item in (first, second):
            self.assertEqual(self.state(item), {"state": "pending", "attempts": 0, "error": None})
        # 不在記憶體：重新打開資料庫還在待分類
        triage._STORES.pop(self.app.ledger_path, None)
        self.assertEqual({r["item_id"] for r in triage.store(self.app).due(10)}, {first, second})
        self.assertEqual(self.guard_codes(), ["QUOTA_PAUSED"])

    def test_default_settings_keep_background_triage_off_the_subscription(self):
        self.settings.update(lambda d: d["guard"].__setitem__("background_subscription", False))
        item = self.add(self.recent())
        self.assertEqual(self.triage_round()["paused"], 1)
        self.assertEqual(self.state(item)["state"], "pending")
        self.assertEqual(self.adapter.prompts, [])
        self.assertEqual(self.guard_codes(), ["BACKGROUND_NO_API"])

    def test_catch_up_after_the_reset_in_import_order_capped_per_round(self):
        self.assertEqual(triage.CATCHUP_MAX, 50)
        self.q = quota(0.9, self.t, resets_in=600)
        items = [self.add(self.recent(30 - i), text=f"範例新聞第 {i} 則：公司公告營收成長。") for i in range(5)]
        self.assertEqual(self.triage_round()["paused"], 1)
        self.t += 601  # 過了重置時間
        with mock.patch.object(triage, "CATCHUP_MAX", 3):
            counts = self.triage_round(*[self.answer() for _ in range(5)], limit=1)  # 補做時不受一般的每輪上限限制
            self.assertEqual(counts["done"], 3)  # 碰到每輪補做的上限
            done = [r["item_id"] for r in self.rows("SELECT item_id FROM triage_state WHERE state='done'")]
            self.assertEqual(sorted(done), sorted(items[:3]))  # 依匯入順序
            self.assertEqual(self.guard_codes(), ["QUOTA_PAUSED"])
            counts = self.triage_round(limit=1)
            self.assertEqual(counts["done"], 2)
        self.assertEqual(self.guard_codes(), ["QUOTA_PAUSED", "CATCHUP_DONE"])
        self.assertFalse(self.store.events.catchup_open("triage"))
        # 補做完之後回到一般的每輪上限
        more = [self.add(self.recent(), text=f"之後的範例新聞 {i}。") for i in range(2)]
        self.assertEqual(self.triage_round(self.answer(), limit=1)["done"], 1)
        self.assertEqual(self.state(more[1])["state"], "pending")

    def test_pausing_again_during_catch_up_stops_the_round(self):
        self.q = quota(0.9, self.t, resets_in=600)
        for i in range(3):
            self.add(self.recent(30 - i), text=f"範例新聞 {i}。")
        self.triage_round()
        self.t += 601
        hit = {"n": 0}

        def answer_then_over(prompt):
            hit["n"] += 1
            self.q = quota(0.95, self.t, resets_in=3600)  # 這次呼叫之後額度又超過了
            return self.answer()(prompt)
        counts = self.triage_round(answer_then_over)
        self.assertEqual((counts["done"], counts["paused"]), (1, 1))
        self.assertTrue(self.store.events.catchup_open("triage"))
        self.assertEqual(self.guard_codes(), ["QUOTA_PAUSED", "QUOTA_PAUSED"])  # 新的重置時間是新的一段

    def test_catch_up_is_not_marked_done_while_still_paused(self):
        self.q = quota(0.9, self.t, resets_in=600)
        self.add(self.recent(), text="不是文章的資料也會排進來，但這裡用一般新聞。")
        self.triage_round()
        self.store.due = lambda limit: []  # 這一輪沒有到期的（例如都在退避），保護也還沒解除
        triage.run_pending(self.app, engine=self.engine())
        self.assertTrue(self.store.events.catchup_open("triage"))
        self.assertEqual(self.guard_codes(), ["QUOTA_PAUSED"])

    def test_a_round_stops_at_the_time_budget(self):
        for i in range(3):
            self.add(self.recent(30 - i), text=f"範例新聞 {i}：公司公告營收成長。")
        ticks = iter([0.0, 0.0, triage.ROUND_BUDGET + 1, triage.ROUND_BUDGET + 2])
        self.adapter.steps.extend(self.answer() for _ in range(3))
        counts = triage.run_pending(self.app, limit=3, engine=self.engine(), clock=lambda: next(ticks))
        self.assertEqual(counts["done"], 1)  # 第二則開始前已經超過時間
        self.assertEqual(len(self.store.due(10)), 2)

    def test_cancel_during_catch_up_does_not_mark_it_done(self):
        self.q = quota(0.9, self.t, resets_in=600)
        self.add(self.recent())
        self.triage_round()
        self.t += 601
        stop = mock.Mock()
        stop.is_set.return_value = True
        triage.run_pending(self.app, engine=self.engine(), cancel=stop)
        self.assertTrue(self.store.events.catchup_open("triage"))


# ---------- HTTP ----------
class GuardApiTest(AiApiCase):
    def make_app(self):
        app = super().make_app()
        self.q = None
        app["ai_options"]["quota"] = lambda: self.q
        return app

    def test_status_settings_and_events(self):
        status, data = self.get("/api/ai/guard/events")
        self.assertEqual((status, data), (200, {"events": []}))  # 資料庫還沒建也能讀
        status, data = self.get("/api/ai/guard")
        self.assertEqual(status, 200, data)
        # 預設背景不用訂閱、又沒有 key：背景工作暫停
        self.assertEqual(data["background"], {"paused": True, "reason": "no_api", "until": None})
        self.assertEqual(data["settings"], quota_guard.defaults())
        status, data = self.post("/api/ai/guard", {"background_subscription": True, "threshold": 80})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["guard"]["settings"]["threshold"], 80)
        self.assertEqual(data["guard"]["background"]["paused"], False)
        self.q = quota(0.85, time.time())
        status, data = self.get("/api/ai/guard")
        self.assertEqual((data["background"]["paused"], data["background"]["reason"]), (True, "quota"))
        self.assertEqual(data["quota"]["used"], 0.85)
        status, data = self.post("/api/ai/guard", {"on_exceed": "api", "api_monthly_usd": 20})
        self.assertEqual(data["guard"]["settings"], {"background_subscription": True, "threshold": 80, "on_exceed": "api",
                                                     "api_monthly_usd": 20.0})
        self.assertEqual(data["guard"]["background"]["reason"], "quota")  # 改用 API 但沒有 key：照樣等
        self.assertEqual(json.loads(self.ai_path.read_text(encoding="utf-8"))["guard"]["threshold"], 80)

    def test_bad_settings(self):
        for body, field in (({"threshold": 0}, "threshold"), ({"threshold": 101}, "threshold"), ({"threshold": 70.5}, "threshold"),
                            ({"threshold": "70"}, "threshold"), ({"threshold": True}, "threshold"),
                            ({"on_exceed": "later"}, "on_exceed"), ({"api_monthly_usd": -1}, "api_monthly_usd"),
                            ({"api_monthly_usd": 1e9}, "api_monthly_usd"), ({"api_monthly_usd": "15"}, "api_monthly_usd"),
                            ({"background_subscription": "yes"}, "background_subscription")):
            self.bad("/api/ai/guard", body, field)
        self.assertEqual(self.post("/api/ai/guard", {"threshold": 75}, token="wrong")[0], 403)
        self.assertEqual(self.get("/api/ai/guard/nope")[0], 404)



CLAUDE_CFG = {"engine": "claude", "claude": {}}
CODEX_CFG = {"engine": "codex", "codex": {}}
API_CFG = {"engine": "openai", "openai": {"base_url": "https://api.example.com/v1", "model": "m"}}
LOCAL_CFG = {"engine": "openai", "openai": {"base_url": "http://127.0.0.1:11434/v1", "model": "m"}}


class ManualKindsTest(GuardBase):
    """手動提醒要知道這次用的引擎算哪一種（#97）。"""

    def test_reader_kind_by_engine_and_billing(self):
        data = self.settings.load()
        k = ai.Engines.reader_kind
        self.assertEqual(k({"engine": "claude"}, data), "claude")
        self.assertEqual(k({"engine": "codex"}, data), "subscription")
        self.assertEqual(k({"engine": "openai", "openai": {"base_url": "https://api.example.com/v1"}}, data), "api")
        self.assertEqual(k({"engine": "openai", "openai": {"base_url": "http://127.0.0.1:11434/v1"}}, data), "local")
        self.assertEqual(k({"engine": "openai", "openai": {"preset": "ollama"}}, data), "local")
        self.assertEqual(k({"engine": "none"}, data), "none")
        self.settings.update(lambda d: d["engines"].__setitem__("claude", {"auth": "ok", "billing": "api"}))
        self.assertEqual(k({"engine": "claude"}, self.settings.load()), "api")

    def test_guard_status_lists_the_kinds(self):
        import copy
        from easyread import config
        cfg = {**copy.deepcopy(config.DEFAULTS), "engine": "openai", "openai": {"base_url": "https://api.example.com/v1", "model": "m"},
               "chat": {"default": "c1", "models": [{"id": "c1", "engine": "claude"},
                                                     {"id": "c2", "engine": "openai", "preset": "ollama", "model": "q"}]}}
        with mock.patch("easyread.ai_engines.config.load", return_value=cfg):
            kinds = self.engines().guard_status()["engines"]
        self.assertEqual(kinds, {"translate": "api", "chat": {"c1": "claude", "c2": "local"}, "chat_default": "claude"})

    def test_unreadable_config_leaves_the_kinds_empty(self):
        with mock.patch("easyread.ai_engines.config.load", side_effect=OSError("locked")), self.assertLogs(level="WARNING"):
            self.assertEqual(self.engines().guard_status()["engines"], {})


class TranslationGateTest(GuardBase):
    """匯入後自動開始的翻譯（閱讀器自己的引擎設定）送出前問額度保護（使用者 2026-11-28）。"""

    def spend(self, usd):
        self.index.record_usage(source="test", task="ask", engine="openai", model="m", cost_usd=usd)

    def gate(self, cfg):
        return self.engines().translation_gate(cfg)

    def test_claude_and_codex_subscriptions_wait_for_the_user_by_default(self):
        for cfg in (CLAUDE_CFG, CODEX_CFG):
            self.assertEqual(self.gate(cfg), {"reason": "subscription", "until": None}, cfg["engine"])
        self.assertIsNone(self.gate({"engine": "antigravity", "antigravity": {}}))  # 其他訂閱照樣自動翻
        self.assertIsNone(self.gate({"engine": "none"}))
        self.assertEqual(self.events(), [])  # 不算觸發保護，不記事件

    def test_api_keys_and_local_models_translate_automatically(self):
        self.assertIsNone(self.gate(API_CFG))
        self.assertIsNone(self.gate(LOCAL_CFG))

    def test_claude_cli_billed_through_the_api_counts_as_api(self):
        self.settings.update(lambda d: d["engines"].__setitem__("claude", {"auth": "ok", "billing": "api"}))
        self.assertIsNone(self.gate(CLAUDE_CFG))
        self.guard(api_monthly_usd=1.0)
        self.spend(1.5)
        self.assertEqual(self.gate(CLAUDE_CFG)["reason"], "api_cap")

    def test_allowed_subscription_waits_only_while_the_claude_quota_is_over(self):
        self.guard(background_subscription=True)
        self.assertIsNone(self.gate(CLAUDE_CFG))
        self.q = quota(0.75, self.t)
        for _ in range(2):  # 同一段暫停只記一筆
            wait = self.gate(CLAUDE_CFG)
            self.assertEqual(wait["reason"], "quota")
            self.assertEqual(wait["until"], self.t + 3600.0)
        self.assertEqual([(e["code"], e["task"]) for e in self.events()], [("QUOTA_PAUSED", "translate")])
        self.assertIsNone(self.gate(CODEX_CFG))  # 看不到 Codex 的額度
        self.q = quota(0.4, self.t)
        self.assertIsNone(self.gate(CLAUDE_CFG))

    def test_api_cap_stops_automatic_translation_until_it_is_raised(self):
        self.guard(api_monthly_usd=1.0)
        self.spend(1.0)
        for _ in range(2):
            self.assertEqual(self.gate(API_CFG), {"reason": "api_cap", "until": None})
        self.assertEqual([(e["code"], e["task"]) for e in self.events()], [("API_CAP_STOPPED", "translate")])
        self.assertIsNone(self.gate(LOCAL_CFG))  # 本機模型不花錢
        self.guard(api_monthly_usd=5.0)
        self.assertIsNone(self.gate(API_CFG))

    def over_with_api_fallback(self):
        self.guard(background_subscription=True, on_exceed="api")
        self.q = quota(0.75, self.t)

    def test_over_the_threshold_switches_to_a_priced_api_key_when_set_to(self):
        """設定「超過門檻改用 API key」：自動翻譯改用 AI 模型頁的 Anthropic key，不等重置（#96，使用者 2026-11-28）。"""
        self.over_with_api_fallback()
        self.add_anthropic()
        cfg = {**CLAUDE_CFG, "target": "zh-TW", "openai": {"timeout": 300}}
        use = self.gate(cfg)["use"]
        self.assertEqual((use["engine"], use["target"]), ("openai", "zh-TW"))
        o = use["openai"]
        self.assertEqual((o["preset"], o["base_url"], o["model"], o["api_key"], o["timeout"]),
                         ("anthropic", ai.ANTHROPIC_OPENAI_BASE, "claude-sonnet-5-5", SECRET, 300))
        self.gate(cfg)
        self.assertEqual([(e["code"], e["task"]) for e in self.events()], [("QUOTA_SWITCHED_API", "translate")])

    def test_switching_still_waits_without_a_usable_key_or_with_the_cap_reached(self):
        self.over_with_api_fallback()
        self.assertEqual(self.gate(CLAUDE_CFG)["reason"], "quota")  # 沒有 key
        self.add_anthropic(status="invalid")
        self.assertEqual(self.gate(CLAUDE_CFG)["reason"], "quota")  # key 失效
        self.add_anthropic()
        self.guard(api_monthly_usd=1.0)
        self.spend(1.0)
        self.assertEqual(self.gate(CLAUDE_CFG)["reason"], "quota")  # 這個月到上限
        self.guard(api_monthly_usd=0)
        self.assertEqual(self.gate(CLAUDE_CFG)["reason"], "quota")  # 上限 0 = 背景不用 API

    def test_switching_skips_an_api_whose_price_is_unknown(self):
        """價格不認得的 API 花費算不進每月上限，不自動改用它。"""
        self.over_with_api_fallback()
        self.settings.update(lambda d: d["openai"].append(
            {"id": "oA", "name": "A", "base_url": "https://a.example/v1", "api": "chat", "model": "gpt-x", "key": "k" * 20}))
        self.assertEqual(self.gate(CLAUDE_CFG)["reason"], "quota")

    def test_wait_setting_keeps_waiting_even_with_a_key(self):
        self.guard(background_subscription=True, on_exceed="wait")
        self.q = quota(0.75, self.t)
        self.add_anthropic()
        self.assertEqual(self.gate(CLAUDE_CFG)["reason"], "quota")

    def test_a_zero_cap_means_background_never_uses_the_api(self):
        self.guard(api_monthly_usd=0)
        self.assertEqual(self.gate(API_CFG), {"reason": "api_off", "until": None})
        self.assertEqual(self.events(), [])


if __name__ == "__main__":
    unittest.main()
