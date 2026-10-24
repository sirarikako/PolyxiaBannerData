"""星铁真实格式摘录的离线回归；文本摘录仅作测试样本，不伪造官方文章源。"""
import json
from pathlib import Path
import shutil

from scripts.collect.collect_starrail_notices_zh_cn import kind
from scripts.transform.build_starrail_warp_notice_zh_cn import build as build_warp
from scripts.transform.build_starrail_version_update_zh_cn import build as build_version
from scripts.transform.starrail_notice_text_zh_cn import parse_range
from scripts.transform.assemble_starrail_warp_candidates_zh_cn import assemble

PROJECT = Path(__file__).resolve().parents[1]

def raw(pid, title, body):
    return {"retcode": 0, "data": {"post": {"post": {
        "post_id": int(pid), "game_id": 6, "subject": title,
        "content": "<p>" + body.replace("\n", "</p><p>") + "</p>"}}}}

# 该版式见星铁 4.5 活动跃迁第一期公告转发；仅保留功能验证需要的句子。
FOUR_FIVE = """
亲爱的开拓者：
本期活动跃迁时间为 2026/08/26 4.5版本更新后 - 2026/09/12 11:59，包含如下内容：
▌「晴音和鸣」「流光定影•你将起身歌唱」活动跃迁
● 「晴音和鸣」角色活动跃迁期间，限定5星角色「知更鸟•晴歌（记忆•风）」，4星角色「丹恒（巡猎•风）」「青雀（智识•量子）」「加拉赫（丰饶•火）」跃迁成功概率限时提升。
● 「流光定影•你将起身歌唱」光锥活动跃迁期间，限定5星光锥「你将起身歌唱（记忆）」，4星光锥「梦的蒙太奇（丰饶）」「天才们的问候（记忆）」「放个短假（欢愉）」跃迁成功概率限时提升。
▌「虹隽晨昏」「溯回忆象•愿虹光永驻天空」活动跃迁
● 「虹隽晨昏」角色活动跃迁期间，限定5星角色「风堇（记忆•风）」，4星角色「丹恒（巡猎•风）」「青雀（智识•量子）」「加拉赫（丰饶•火）」跃迁成功概率限时提升。
● 「溯回忆象•愿虹光永驻天空」光锥活动跃迁期间，限定5星光锥「愿虹光永驻天空（记忆）」，4星光锥「梦的蒙太奇（丰饶）」「天才们的问候（记忆）」「放个短假（欢愉）」跃迁成功概率限时提升。
"""
FOUR_SIX = """
亲爱的开拓者：
限定5星角色「真珠（欢愉•冰）」与限定5星光锥「献给明日的色彩（欢愉）」跃迁成功概率限时提升，4星角色「青雀（智识•量子）」「雪衣（毁灭•量子）」「米沙（毁灭•冰）」与4星光锥「一场术后对话（丰饶）」「与行星相会（同谐）」「无边曼舞（虚无）」跃迁成功概率限时提升，跃迁时间为 2026/09/28 4.6版本更新后 - 2026/11/10 15:00。
限定5星角色「绯英（欢愉•物理）」与限定5星光锥「邂逅于下一个花季（欢愉）」将会返场，跃迁时间为 2026/09/28 4.6版本更新后 - 2026/10/21 11:59。
"""

def test_45_actual_layout_four_independent_pools():
    body = FOUR_FIVE + """
▌角色试用活动
●活动时间：2026/08/26 4.5版本更新后 - 2026/09/28 03:59
"""
    notice = build_warp(raw("77739472", "4.5版本活动跃迁（其一）", body), "77739472")
    assert notice["review"]["status"] == "parsed", notice["review"]
    pools = notice["banners"]
    assert len(pools) == 4
    assert [b["poolType"] for b in pools] == [
        "character_event", "light_cone_event", "character_event", "light_cone_event"
    ]
    assert pools[0]["featured"]["fiveStar"] == ["知更鸟•晴歌"]
    assert pools[1]["featured"]["fourStar"] == ["梦的蒙太奇", "天才们的问候", "放个短假"]
    assert all(b["time"]["endAt"] == "2026-09-12T12:00:00+08:00" for b in pools)

def test_46_summary_only_must_not_guess_banner_names():
    result = build_warp(raw("78448395", "4.6版本活动跃迁（其一）", FOUR_SIX), "78448395")
    assert result["review"]["status"] == "needs_review"
    assert result["banners"] == []
    assert result["review"]["warnings"]
    assert parse_range("2026/09/28 4.6版本更新后 - 2026/11/10 15:00")["endAt"] == "2026-11-10T15:00:00+08:00"


def test_46_two_distinct_end_dates_with_group_details():
    body = FOUR_SIX + """
▌「沧海萃珠」「流光定影•献给明日的色彩」活动跃迁
● 「沧海萃珠」角色活动跃迁期间，限定5星角色「真珠（欢愉•冰）」，4星角色「青雀（智识•量子）」「雪衣（毁灭•量子）」「米沙（毁灭•冰）」跃迁成功概率限时提升。
● 「流光定影•献给明日的色彩」光锥活动跃迁期间，限定5星光锥「献给明日的色彩（欢愉）」，4星光锥「一场术后对话（丰饶）」「与行星相会（同谐）」「无边曼舞（虚无）」跃迁成功概率限时提升。
▌「韶艾裁英」「溯回忆象•邂逅于下一个花季」活动跃迁
● 「韶艾裁英」角色活动跃迁期间，限定5星角色「绯英（欢愉•物理）」，4星角色「青雀（智识•量子）」「雪衣（毁灭•量子）」「米沙（毁灭•冰）」跃迁成功概率限时提升。
● 「溯回忆象•邂逅于下一个花季」光锥活动跃迁期间，限定5星光锥「邂逅于下一个花季（欢愉）」，4星光锥「一场术后对话（丰饶）」「与行星相会（同谐）」「无边曼舞（虚无）」跃迁成功概率限时提升。
"""
    doc = build_warp(raw("78448395", "4.6版本活动跃迁（其一）", body), "78448395")
    assert doc["review"]["status"] == "parsed", doc["review"]
    assert len(doc["banners"]) == 4
    assert [b["time"]["endAt"] for b in doc["banners"]] == [
        "2026-11-10T15:00:00+08:00", "2026-11-10T15:00:00+08:00",
        "2026-10-21T12:00:00+08:00", "2026-10-21T12:00:00+08:00"]

def test_update_title_with_version_name():
    title = "4.5版本「碧海归歌」版本更新说明"
    assert kind(title) == "version_update"
    assert kind("4.6版本更新说明") == "version_update"
    assert kind("4.6版本「月升之前」更新说明") == "version_update"
    assert kind("《云•星穹铁道》4.5版本更新说明") is None
    r = build_version(raw("77754794", title, "▌更新时间\n2026/08/26 06:00 开始，预计需要5个小时。"), "77754794")
    assert r["maintenance"]["startAt"] == "2026-08-26T06:00:00+08:00"

def test_conditional_without_date_needs_maintenance():
    r = parse_range("3.3版本更新后 - 2025/06/11 11:59")
    assert r["startAt"] is None
    assert r["startCondition"] == "after_version_update"
    assert r["endAt"] == "2025-06-11T12:00:00+08:00"

def setup_root(tmp_path):
    (tmp_path / "public/item-mappings/starrail").mkdir(parents=True)
    (tmp_path / "public/v1").mkdir(parents=True)
    (tmp_path / "schemas/manual").mkdir(parents=True)
    for filename in ("starrail-missing-warp.schema.json", "starrail-notice-manual.schema.json"):
        shutil.copyfile(PROJECT / "schemas/manual" / filename, tmp_path / "schemas/manual" / filename)
    (tmp_path / "public/item-mappings/starrail/zh-CN.json").write_text("{}", encoding="utf-8")
    (tmp_path / "public/v1/starrail.json").write_text(
        json.dumps({"game": "starrail", "banners": []}), encoding="utf-8")

def missing(name, ending="2026-10-21T12:00:00+08:00"):
    return {"format": "starrail-missing-warp-v1",
            "identity": {"version": "4.6", "phase": 1, "poolType": "character_event", "bannerName": name},
            "data": {"featured": {"fiveStar": ["绯英"], "fourStar": ["青雀", "雪衣", "米沙"]},
                     "time": {"startAt": "2026-09-28T06:00:00+08:00", "endAt": ending}},
            "evidence": {"summary": "依据独立复核的官方公告及正式卡池名人工填补"}}

def test_missing_manual_ready_and_conflict_removes_old_candidate(tmp_path):
    setup_root(tmp_path)
    manual_dir = tmp_path / "manual/notices/starrail/zh-CN/missing"
    manual_dir.mkdir(parents=True)
    (manual_dir / "4.6-character.json").write_text(json.dumps(missing("韶艾裁英"), ensure_ascii=False), encoding="utf-8")
    first = assemble(tmp_path, write=True)
    assert first["ready"] == 1, first
    candidates = list((tmp_path / "data/derived/starrail/v1-candidates").glob("*.json"))
    assert len(candidates) == 1
    (tmp_path / "data/derived/starrail/warp-notices").mkdir(parents=True)
    official = {"format": "starrail-warp-notice-v1", "game": "starrail", "version": "4.6", "phase": 1,
                "source": {"postId": "111", "url": "https://www.miyoushe.com/sr/article/111"},
                "banners": [{"bannerName": "韶艾裁英", "poolType": "character_event",
                             "featured": {"fiveStar": ["绯英"], "fourStar": ["青雀", "雪衣", "米沙"]},
                             "time": {"startAt": "2026-09-28T06:00:00+08:00",
                                      "endAt": "2026-10-22T12:00:00+08:00"}}]}
    (tmp_path / "data/derived/starrail/warp-notices/warp-notice_zh-CN_111.json").write_text(
        json.dumps(official, ensure_ascii=False), encoding="utf-8")
    second = assemble(tmp_path, write=True)
    assert second["ready"] == 0, second
    assert second["rows"][0]["status"] == "needs_review"
    assert not list((tmp_path / "data/derived/starrail/v1-candidates").glob("*.json"))

def test_multiple_simultaneous_character_pools_not_collision(tmp_path):
    setup_root(tmp_path)
    folder = tmp_path / "manual/notices/starrail/zh-CN/missing"
    folder.mkdir(parents=True)
    for name in ("韶艾裁英", "沧海萃珠"):
        (folder / (name + ".json")).write_text(json.dumps(missing(name), ensure_ascii=False), encoding="utf-8")
    result = assemble(tmp_path, write=False)
    assert result["ready"] == 2, result


def test_missing_long_term_collab_is_ready_without_end_time(tmp_path):
    setup_root(tmp_path)
    folder = tmp_path / "manual/notices/starrail/zh-CN/missing"
    folder.mkdir(parents=True)
    record = {"format": "starrail-missing-warp-v1",
              "identity": {"version": "4.7", "phase": 1,
                           "poolType": "collab_character", "bannerName": "长期联动测试"},
              "data": {"featured": {"fiveStar": ["特别角色"], "fourStar": []},
                       "time": {"startAt": "2026-12-01T12:00:00+08:00", "endAt": None}},
              "evidence": {"summary": "经人工核实的长期联动官方资料"}}
    (folder / "4.7-collab.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    result = assemble(tmp_path, write=True)
    assert result["ready"] == 1, result
    assert result["rows"][0]["v1Draft"]["poolType"] == "collab_character"
    assert result["rows"][0]["v1Draft"]["regions"][0]["endAt"] is None

def test_same_name_same_phase_different_up_both_allowed(tmp_path):
    setup_root(tmp_path)
    folder = tmp_path / "manual/notices/starrail/zh-CN/missing"
    folder.mkdir(parents=True)
    for idx, five in enumerate(("特别角色甲", "特别角色乙")):
        record = missing("流光定影")
        record["data"]["featured"]["fiveStar"] = [five]
        (folder / ("same-name-" + str(idx) + ".json")).write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8")
    result = assemble(tmp_path, write=True)
    assert result["ready"] == 2, result
    assert len(list((tmp_path / "data/derived/starrail/v1-candidates").glob("*.json"))) == 2


def test_official_collab_requires_verified_manual_version_and_phase(tmp_path):
    from scripts.transform.build_starrail_collab_notice_zh_cn import build as build_collab
    setup_root(tmp_path)
    body = """
本次联动跃迁将于 2025/07/11 12:00 后长期开放，包含以下内容：
▌「圣剑辉烈之誓」角色联动跃迁
● 「圣剑辉烈之誓」角色联动跃迁期间，联动限定5星角色「Saber（毁灭•风）」跃迁成功概率提升。
▌「王的诞生」光锥联动跃迁
● 「王的诞生」光锥联动跃迁期间，联动限定5星光锥「没有回报的加冕（毁灭）」跃迁成功概率提升。
▌「此身剑所天成」角色联动跃迁
● 「此身剑所天成」角色联动跃迁期间，联动限定5星角色「Archer（巡猎•量子）」跃迁成功概率提升。
▌「冬木赤影」光锥联动跃迁
● 「冬木赤影」光锥联动跃迁期间，联动限定5星光锥「理想燃烧的地狱（巡猎）」跃迁成功概率提升。
※「联动跃迁」为长期开放，无关闭时间。
"""
    pid = "66236171"
    article = raw(pid, "「联动跃迁」说明", body)
    parsed = build_collab(article, pid)
    assert parsed["review"]["status"] == "waiting_identity"
    assert len(parsed["banners"]) == 4
    assert parsed["banners"][0]["featured"]["fiveStar"] == ["Saber"]
    assert parsed["banners"][0]["time"]["startAt"] == "2025-07-11T12:00:00+08:00"
    assert parsed["banners"][0]["time"]["endAt"] is None
    derived = tmp_path / "data/derived/starrail/collab-notices"
    derived.mkdir(parents=True)
    (derived / ("collab-notice_zh-CN_" + pid + ".json")).write_text(
        json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    # 未确认版本期数时，不产生可发布候选。
    no_manual = assemble(tmp_path, write=False)
    assert no_manual["ready"] == 0
    assert len(no_manual["unparsedNotices"]) == 1
    raw_folder = tmp_path / "data/announcements/starrail/zh-cn/miyoushe/posts"
    raw_folder.mkdir(parents=True)
    (raw_folder / (pid + ".json")).write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")
    real_manual = tmp_path / "manual/notices/starrail/zh-CN/miyoushe"
    real_manual.mkdir(parents=True)
    manual_doc = {"format": "starrail-notice-manual-v1", "postId": pid,
                  "banners": [{"identity": {"version": "3.4", "phase": 1,
                                            "poolType": "collab_character",
                                            "bannerName": "圣剑辉烈之誓"},
                               "data": {"featured": {"fiveStar": ["Saber"]}}}]}
    (real_manual / (pid + ".json")).write_text(json.dumps(manual_doc, ensure_ascii=False), encoding="utf-8")
    yes = assemble(tmp_path, write=True)
    assert yes["ready"] == 1, yes
    assert yes["rows"][0]["sourceKey"].startswith(pid + "-")
    assert yes["rows"][0]["v1Draft"]["regions"][0]["endAt"] is None


def test_historical_same_five_different_official_name_is_not_ready(tmp_path):
    """已标准化的 2.5 卡芙卡池不得被旧别名生成第二条。"""
    setup_root(tmp_path)
    published = json.loads((PROJECT / "public/v1/starrail.json").read_text(encoding="utf-8"))
    existing = next(x for x in published["banners"] if x["id"] == "hsr-000078")
    (tmp_path / "public/v1/starrail.json").write_text(
        json.dumps({"game": "starrail", "banners": [existing]}, ensure_ascii=False),
        encoding="utf-8")
    official = {"format": "starrail-warp-notice-v1", "game": "starrail",
                "version": "2.5", "phase": 1,
                "source": {"postId": "57174807",
                           "url": "https://www.miyoushe.com/sr/article/57174807"},
                "banners": [{"bannerName": "夜将不眠", "poolType": "character_event",
                             "featured": {"fiveStar": ["卡芙卡"],
                                          "fourStar": ["貊泽", "艾丝妲", "卢卡"]},
                             "time": {"startAt": "2024-09-10T06:00:00+08:00",
                                      "endAt": "2024-10-02T12:00:00+08:00"}}]}
    folder = tmp_path / "data/derived/starrail/warp-notices"
    folder.mkdir(parents=True)
    (folder / "warp-notice_zh-CN_57174807.json").write_text(
        json.dumps(official, ensure_ascii=False), encoding="utf-8")
    result = assemble(tmp_path, write=True)
    assert result["ready"] == 0
    row = result["rows"][0]
    assert row["status"] == "needs_review"
    assert row["existingId"] == "hsr-000078"
    assert "names.zh-CN" in row["publishedDifferences"]
    assert not list((tmp_path / "data/derived/starrail/v1-candidates").glob("*.json"))

def test_historical_continued_pool_not_published_again(tmp_path):
    setup_root(tmp_path)
    published = json.loads((PROJECT / "public/v1/starrail.json").read_text(encoding="utf-8"))
    existing = next(x for x in published["banners"] if x["id"] == "hsr-000205")
    (tmp_path / "public/v1/starrail.json").write_text(
        json.dumps({"game": "starrail", "banners": [existing]}, ensure_ascii=False),
        encoding="utf-8")
    official = {"format": "starrail-warp-notice-v1", "game": "starrail",
                "version": "4.0", "phase": 2,
                "source": {"postId": "73668032",
                           "url": "https://www.miyoushe.com/sr/article/73668032"},
                "banners": [{"bannerName": "光映千翎", "poolType": "character_event",
                             "featured": {"fiveStar": ["爻光"],
                                          "fourStar": ["佩拉", "寒鸦", "青雀"]},
                             "time": {"startAt": "2026-02-13T06:00:00+08:00",
                                      "endAt": "2026-03-24T15:00:00+08:00"}}]}
    folder = tmp_path / "data/derived/starrail/warp-notices"
    folder.mkdir(parents=True)
    (folder / "warp-notice_zh-CN_73668032.json").write_text(
        json.dumps(official, ensure_ascii=False), encoding="utf-8")
    result = assemble(tmp_path, write=True)
    assert result["ready"] == 0
    assert result["alreadyPublished"] == 1
    assert result["rows"][0]["existingId"] == "hsr-000205"
