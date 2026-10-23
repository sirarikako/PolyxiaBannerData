"""Offline regression for resumable Chinese Genshin announcement archival."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.collect import collect_miyoushe_announcements as m


def post(pid, created_at=1601251200, game_id=2):
    return {"post_id": str(pid), "game_id": game_id, "subject": f"原神公告 {pid}",
            "created_at": created_at, "content": f"原始内容 {pid}"}


def listing(posts, cursor, last):
    return {"retcode": 0, "data": {
        "list": [{"post": p} for p in posts], "last_id": cursor, "is_last": last}}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "genshin/zh-cn/miyoushe"

    def run_collector(self, handler):
        with patch.object(m, "fetch", side_effect=handler), patch.object(m.time, "sleep"):
            return m.Collector(self.root, checkpoint_seconds=10**6).run()

    def test_committed_repository_archive_integrity_if_present(self):
        # Exercise the real committed checkpoint files in CI, in addition
        # to synthetic mocked API responses. Never mutate archive data.
        root = m.OUTPUT
        if not (root / "pages").is_dir():
            self.skipTest("No committed archive pages in checkout")
        pages, posts, cursor, last, _ = m.read_pages(root)
        self.assertGreater(len(pages), 0)
        self.assertTrue(cursor or last)
        index_path = root / "index.json"
        if index_path.is_file():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            ids = [row["postId"] for row in index["posts"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(set(ids), set(posts))
            for row in index["posts"]:
                raw = row.get("rawFile")
                if raw is not None:
                    pid = row["postId"]
                    self.assertEqual(raw, "posts/" + pid + ".json")
                    path = root / raw
                    self.assertTrue(path.is_file(), raw)
                    obj = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual(m.validate_detail(obj, pid)["post_id"], pid)

    def test_paged_archive_and_original_full_contents(self):
        calls = []
        def fake(url, params, **_):
            calls.append((url, dict(params)))
            if url.endswith("getNewsList"):
                if not params["last_id"]:
                    return listing([post("19"), post("18")], "cursor-next", False)
                self.assertEqual(params["last_id"], "cursor-next")
                return listing([post("17")], "done", True)
            return {"retcode": 0, "data": {"post": {"post": post(params["post_id"])}}}
        report = self.run_collector(fake)
        self.assertTrue(report["complete"])
        self.assertEqual((report["pagesSaved"], report["fullPostsSaved"]), (2, 3))
        self.assertTrue((self.root / "posts/19.json").exists())
        self.assertEqual(json.loads((self.root / "posts/19.json").read_text())["data"]["post"]["post"]["content"], "原始内容 19")
        self.assertEqual((self.root / "pages/000001.json").exists(), True)
        detail_calls = [params for url, params in calls if url.endswith("getPostFull")]
        self.assertEqual(detail_calls[0].get("post_id"), "19")
        self.assertEqual(sum(url.endswith("getNewsList") for url, _ in calls), 2)
        self.assertTrue(any(p[1].get("last_id") == "cursor-next" for p in calls))
        self.assertEqual(report["nextCursor"], None)

    def test_resume_cached_page_and_download_missing_details(self):
        self.root.mkdir(parents=True)
        m.save_json(self.root / "pages/000001.json", {
            "apiUrl": m.PAGE_SOURCES[0][0],
            "params": {"gids": 2, "type": 1, "page_size": 20, "last_id": "", "client_type": 4},
            "response": listing([post("31"), post("30")], "page2", False),
        })
        m.save_json(self.root / "posts/31.json", {"data": {"post": {"post": post("31")}}})
        calls=[]
        def fake(url, params, **_):
            calls.append((url, dict(params)))
            if url.endswith("getNewsList"):
                self.assertEqual(params["last_id"], "page2")
                return listing([post("29")], "done", True)
            return {"data": {"post": {"post": post(params["post_id"])}}}
        result = self.run_collector(fake)
        self.assertTrue(result["complete"])
        self.assertEqual(result["pagesSaved"], 2)
        self.assertEqual(result["fullPostsSaved"], 3)
        self.assertFalse(any(c[1].get("post_id") == "31" for c in calls))
        self.assertTrue(any(c[1].get("post_id") == "30" for c in calls))

    def test_failures_mark_incomplete_and_are_retryable(self):
        def broken(url, params, **_):
            if url.endswith("getNewsList"):
                return listing([post("88")], "done", True)
            raise RuntimeError("detail is temporarily unavailable")
        report = self.run_collector(broken)
        self.assertFalse(report["complete"])
        self.assertEqual(report["fullPostsMissing"], 1)
        self.assertIn("88", report["detailErrors"])
        def fixed(url, params, **_):
            if url.endswith("getNewsList"):
                self.fail("No need to refetch cached last page")
            return {"data": {"post": {"post": post(params["post_id"])}}}
        report = self.run_collector(fixed)
        self.assertTrue(report["complete"])
        self.assertEqual(report["fullPostsSaved"], 1)

    def test_captcha_pauses_details_but_preserves_complete_list(self):
        calls = []
        def fake(url, params, **_):
            calls.append((url, dict(params)))
            if url.endswith("getNewsList"):
                if not params["last_id"]:
                    return listing([post("91")], "next", False)
                return listing([post("90")], "done", True)
            raise m.VerificationRequired("retcode 1034")
        result = self.run_collector(fake)
        self.assertEqual(result["pagesSaved"], 2)
        self.assertTrue(result["lastPageReached"])
        self.assertTrue(result["detailPaused"])
        self.assertEqual(result["fullPostsMissing"], 2)
        self.assertFalse(result["complete"])
        self.assertEqual(sum(1 for url,_ in calls if url.endswith("getPostFull")), 1)

    def test_429_pauses_without_trying_alternate_detail_host(self):
        calls = []
        def fake(url, params, **_):
            calls.append(url)
            if url.endswith("getNewsList"):
                return listing([post("92")], "done", True)
            raise m.RateLimited("HTTP 429")
        result = self.run_collector(fake)
        self.assertTrue(result["detailPaused"])
        self.assertEqual(result["pagesSaved"], 1)
        self.assertEqual(sum(u.endswith("getPostFull") for u in calls), 1)

    def test_confirmed_empty_after_short_historical_page_finishes_list(self):
        calls = []
        def fake(url, params, **_):
            calls.append((url, dict(params)))
            if not url.endswith("getNewsList"):
                self.fail("List-only stage must never fetch full details")
            if not params["last_id"]:
                return listing([post("81")], "1560", False)
            self.assertEqual(params["last_id"], "1560")
            return listing([], "1560", False)
        with patch.object(m, "fetch", side_effect=fake), patch.object(m.time, "sleep"):
            report = m.Collector(self.root, stage="list", checkpoint_seconds=10**6).run()
        self.assertTrue(report["listComplete"])
        self.assertFalse(report["complete"])
        self.assertTrue(report["listExhausted"])
        self.assertFalse(report["lastPageReached"])
        self.assertEqual(report["listEndBasis"], "confirmed_empty_after_short_page")
        self.assertEqual(report["pagesSaved"], 1)
        self.assertEqual(report["fullPostsMissing"], 1)
        self.assertEqual(sum(url.endswith("getNewsList") for url, _ in calls), 3)
        self.assertTrue((self.root / "end-probe.json").exists())

        def forbid(*_args, **_kwargs):
            self.fail("Resume must trust validated archived page + terminal probe")
        with patch.object(m, "fetch", side_effect=forbid):
            resumed = m.Collector(self.root, stage="list").run()
        self.assertTrue(resumed["listComplete"])
        self.assertEqual(resumed["listEndBasis"], "confirmed_empty_after_short_page")

    def test_empty_after_full_page_is_not_accepted_as_terminal(self):
        def fake(url, params, **_):
            if not params["last_id"]:
                return listing([post(str(300 + n)) for n in range(20)], "20", False)
            return listing([], "20", False)
        with patch.object(m, "fetch", side_effect=fake), patch.object(m.time, "sleep"):
            report = m.Collector(self.root, stage="list", checkpoint_seconds=10**6).run()
        self.assertFalse(report["listComplete"])
        self.assertEqual(report["pagesSaved"], 1)
        self.assertFalse((self.root / "end-probe.json").exists())
        self.assertTrue(report["errors"])

    def test_list_stage_does_not_download_details_and_details_resume(self):
        def fake(url, params, **_):
            if url.endswith("getNewsList"):
                return listing([post("94")], "end", True)
            return {"data": {"post": {"post": post(params["post_id"])}}}
        with patch.object(m, "fetch", side_effect=fake), patch.object(m.time, "sleep"):
            one = m.Collector(self.root, stage="list").run()
            two = m.Collector(self.root, stage="details").run()
        self.assertTrue(one["listComplete"])
        self.assertFalse(one["complete"])
        self.assertEqual(one["fullPostsSaved"], 0)
        self.assertTrue(two["complete"])
        self.assertEqual(two["fullPostsSaved"], 1)

    def test_list_quality_counts_duplicates_and_time_reversals(self):
        def fake(url, params, **_):
            if params["last_id"] == "":
                older = post("112")
                newer = post("113", created_at=1601251300)
                return listing([older, newer], "two", False)
            return listing([post("112"), post("114")], "end", True)
        with patch.object(m, "fetch", side_effect=fake), patch.object(m.time, "sleep"):
            report = m.Collector(self.root, stage="list").run()
        self.assertTrue(report["listComplete"])
        self.assertEqual(report["listQuality"]["rawListEntries"], 4)
        self.assertEqual(report["listQuality"]["uniquePostIds"], 3)
        self.assertEqual(report["listQuality"]["duplicatePostIdCount"], 1)
        self.assertEqual(report["listQuality"]["createdAtOrderReversals"], 1)

    def test_banner_details_prioritize_oldest_and_respect_request_budget(self):
        # Three candidates, newest first in list. Only oldest two should be
        # attempted; the normal announcement must never be downloaded.
        calls = []
        def fake(url, params, **_):
            if url.endswith("getNewsList"):
                items = [post("91", created_at=1601251300),
                         post("92", created_at=1601251200),
                         post("93", created_at=1601251100),
                         post("94", created_at=1601251000)]
                items[0]["subject"] = "祈愿公告 新"
                items[1]["subject"] = "祈愿公告 中"
                items[2]["subject"] = "祈愿公告 旧"
                items[3]["subject"] = "普通活动公告"
                return listing(items, "end", True)
            calls.append(str(params["post_id"]))
            return {"data": {"post": {"post": {
                **post(params["post_id"]),
                "subject": "祈愿公告 " + str(params["post_id"])}}}}
        with patch.object(m, "fetch", side_effect=fake), patch.object(m.time, "sleep"):
            first = m.Collector(self.root, stage="list").run()
            result = m.Collector(self.root, stage="banner-details",
                                 max_detail_requests=2).run()
        self.assertTrue(first["listComplete"])
        self.assertEqual(result["detailRequestsAttempted"], 2)
        self.assertTrue(result["detailBudgetExhausted"])
        self.assertEqual(calls, ["93", "92"])
        self.assertEqual(result["bannerCandidateNotices"], 3)
        self.assertEqual(result["bannerDetailsSaved"], 2)
        self.assertEqual(result["bannerDetailsMissing"], 1)
        self.assertFalse(result["bannerDetailsComplete"])
        self.assertEqual(result["fullPostsMissing"], 2)

    def test_banner_details_rejects_unfinished_list(self):
        def fake(url, params, **_):
            return listing([post("91")], "next", False)
        with patch.object(m, "fetch", side_effect=fake), patch.object(m.time, "sleep"):
            m.Collector(self.root, stage="list", max_pages=1).run()
            result = m.Collector(self.root, stage="banner-details").run()
        self.assertFalse(result["listComplete"])
        self.assertTrue(any("requires" in e for e in result["errors"]))

    def test_version_details_selects_only_main_game_and_reuses_banner_details(self):
        # Mix main game version notes, cloud client, editor and wish notice.
        # Existing original JSON is reused even if another stage saved it.
        cases = [
            ("210", "「白垩与黑龙」1.2版本更新说明"),
            ("209", "「白垩与黑龙」1.2版本更新通知"),
            ("208", "3.0~3.2版本持续时间说明"),
            ("207", "9月28日停服维护更新通知"),
            ("206", "9月28日维护更新说明"),
            ("205", "12月3日《云·原神》版本更新"),
            ("204", "7.0版本「编辑器和千星沙箱」更新修复与优化说明"),
            ("203", "「杯装之诗」角色活动祈愿开启"),
        ]
        calls = []
        def fake(url, params, **_):
            if url.endswith("getNewsList"):
                items = []
                for pid, title in cases:
                    item = post(pid, created_at=1601251200 + (210 - int(pid)) * 100)
                    item["subject"] = title
                    items.append(item)
                return listing(items, "end", True)
            pid = str(params["post_id"])
            calls.append(pid)
            return {"data": {"post": {"post": {
                **post(pid), "subject": next(title for ident, title in cases if ident == pid)
            }}}}
        with patch.object(m, "fetch", side_effect=fake), patch.object(m.time, "sleep"):
            m.Collector(self.root, stage="list").run()
            # A full post already archived through some other workflow.
            m.save_json(self.root / "posts/210.json", {"data": {"post": {"post": {
                **post("210"), "subject": cases[0][1]
            }}}})
            report = m.Collector(self.root, stage="version-details",
                                 max_detail_requests=2).run()
        self.assertEqual(report["versionCandidateNotices"], 5)
        self.assertEqual(report["versionDetailsSaved"], 3)
        self.assertEqual(report["versionDetailsMissing"], 2)
        self.assertEqual(report["detailRequestsAttempted"], 2)
        self.assertTrue(report["detailBudgetExhausted"])
        self.assertEqual(calls, ["209", "208"])
        self.assertEqual(report["versionCandidateKinds"]["release_notes"]["saved"], 1)
        self.assertEqual(report["versionCandidateKinds"]["maintenance_notice"]["saved"], 1)
        self.assertEqual(report["versionCandidateKinds"]["schedule_change"]["saved"], 1)

    def test_version_details_rejects_partial_historical_list(self):
        def fake(url, params, **_):
            if url.endswith("getNewsList"):
                item = post("301")
                item["subject"] = "5.0版本更新维护预告"
                return listing([item], "next", False)
            self.fail("Must not query details before list is complete")
        with patch.object(m, "fetch", side_effect=fake), patch.object(m.time, "sleep"):
            m.Collector(self.root, stage="list", max_pages=1).run()
            report = m.Collector(self.root, stage="version-details").run()
        self.assertFalse(report["listComplete"])
        self.assertTrue(report["errors"])

    def test_future_era_only_is_not_marked_complete(self):
        def fake(url, params, **_):
            if url.endswith("getNewsList"):
                return listing([post("101", 1780000000)], "end", True)
            return {"data": {"post": {"post": post(params["post_id"], 1780000000)}}}
        report = self.run_collector(fake)
        self.assertFalse(report["complete"])
        self.assertFalse(report["reachesLaunch2020"])
        self.assertTrue(report["lastPageReached"])

    def test_zero_game_id_in_genshin_news_and_detail(self):
        # Real Genshin news-list records can carry game_id=0.
        self.assertEqual(m.post_from_entry({"post": post("78817337", game_id=0)})["post_id"], "78817337")
        self.assertEqual(m.validate_detail({"data": {"post": {"post": post("78817337", game_id=0)}}}, "78817337")["game_id"], 0)

        def fake(url, params, **_):
            if url.endswith("getNewsList"):
                return listing([post("78817337", game_id=0)], "done", True)
            return {"data": {"post": {"post": post(params["post_id"], game_id=0)}}}
        report = self.run_collector(fake)
        self.assertTrue(report["complete"])
        self.assertEqual(report["pagesSaved"], 1)
        self.assertEqual(report["fullPostsSaved"], 1)

    def test_other_game_id_rejected_in_detail(self):
        with self.assertRaisesRegex(ValueError, "Wrong game ID"):
            m.validate_detail({"data": {"post": {"post": post("777", game_id=6)}}}, "777")

    def test_wrong_game_does_not_get_archived(self):
        def fake(url, params, **_):
            if url.endswith("getNewsList"):
                return listing([post("20", game_id=6)], "done", True)
            self.fail("Must not fetch cross-game detail")
        report = self.run_collector(fake)
        self.assertFalse(report["complete"])
        self.assertEqual(report["pagesSaved"], 0)
        self.assertEqual(report["fullPostsSaved"], 0)
        self.assertTrue(report["errors"])

    def test_duplicated_cursor_does_not_complete(self):
        def fake(url, params, **_):
            return listing([post("1")], params["last_id"] or "dup", False)
        report = self.run_collector(fake)
        self.assertFalse(report["complete"])
        self.assertEqual(report["pagesSaved"], 1)
        self.assertTrue(any("cursor" in s.lower() for s in report["errors"]))


if __name__ == "__main__":
    unittest.main()