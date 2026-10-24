"""星铁历史回放比较器的离线隔离测试。"""
from scripts.experiments.replay_starrail_history_zh_cn import (
    pool_key, compare_pool, select_articles
)

def banner(identifier="hsr-000101", version="2.0", phase=1, provider="miyoushe"):
    return {"id": identifier, "gameVersion": version, "phase": phase,
            "poolType": "character_event", "names": {"zh-CN": "流光定影"},
            "featured": {"fiveStar": [{"names": {"zh-CN": "测试五星"}}],
                         "fourStar": [{"names": {"zh-CN": "测试四星A"}},
                                      {"names": {"zh-CN": "测试四星B"}},
                                      {"names": {"zh-CN": "测试四星C"}}]},
            "regions": [{"server": "cn_official",
                         "startAt": "2024-02-06T06:00:00+08:00",
                         "endAt": "2024-02-29T12:00:00+08:00"}],
            "sources": [{"provider": provider,
                         "url": "https://www.miyoushe.com/sr/article/48812553"}]}

def parsed():
    return {"poolType": "character_event", "bannerName": "流光定影",
            "featured": {"fiveStar": ["测试五星"],
                         "fourStar": ["测试四星C", "测试四星B", "测试四星A"]},
            "time": {"startAt": "2024-02-06T06:00:00+08:00",
                     "endAt": "2024-02-29T12:00:00+08:00"}}

def test_same_name_different_five_star_not_collider():
    b = banner()
    other = banner("hsr-000102")
    other["featured"]["fiveStar"][0]["names"]["zh-CN"] = "其他五星"
    assert pool_key(b) != pool_key(other)

def test_exact_comparison_ignores_four_star_order():
    assert compare_pool(parsed(), banner()) == {}

def test_any_wrong_time_is_reported():
    p = parsed()
    p["time"]["endAt"] = "2024-02-29T11:59:00+08:00"
    assert list(compare_pool(p, banner())) == ["endAt"]

def test_any_wrong_four_star_is_reported():
    p = parsed()
    p["featured"]["fourStar"][2] = "其他四星"
    assert "fourStar" in compare_pool(p, banner())

def test_source_selection_filters_by_version_and_game():
    b = banner()
    ignored = banner("hsr-000103", version="3.0")
    selected, missing = select_articles({"banners": [b, ignored]}, {"2.0"}, set())
    assert list(selected) == ["48812553"]
    assert selected["48812553"][0]["id"] == b["id"]
    assert not missing

def test_missing_official_source_is_visible():
    b = banner(provider="firefly")
    selected, missing = select_articles({"banners": [b]}, {"2.0"}, set())
    assert not selected
    assert missing[0]["id"] == b["id"]


def make_raw(pid, subject, body):
    return {"retcode": 0, "data": {"post": {"post": {
        "post_id": int(pid), "game_id": 6, "subject": subject,
        "content": "<p>" + body.replace("\n", "</p><p>") + "</p>"}}}}

def test_legacy_20_header_without_version_and_four_star():
    from scripts.experiments.starrail_legacy_text_zh_cn import build
    body = """亲爱的开拓者：
本期角色活动跃迁时间为 2024/02/06 2.0版本更新后 - 2024/02/29 11:59
▌「镜映婆娑」角色活动跃迁
● 活动期间，限定5星角色「黑天鹅（虚无•风）」，
4星角色「米沙（毁灭•冰）」「停云（同谐•雷）」「桂乃芬（虚无•火）」概率提升。
▌「濯世垂虹」角色活动跃迁
● 活动期间，限定5星角色「丹恒•饮月（毁灭•虚数）」，
4星角色「米沙（毁灭•冰）」「停云（同谐•雷）」「桂乃芬（虚无•火）」概率提升。
▌「锋芒崭露」角色试用活动
活动时间：2024/02/06 2.0版本更新后 - 2024/03/08 11:59
"""
    parsed_doc = build(make_raw("48812336", "角色活动跃迁：「镜映婆娑」、「濯世垂虹」", body),
                       "48812336", compare_version="2.0", compare_phase=1)
    assert parsed_doc["identityAuthority"] == "historical-v1-comparison-only"
    assert not parsed_doc["review"]["warnings"]
    assert len(parsed_doc["banners"]) == 2
    assert parsed_doc["banners"][0]["featured"]["fiveStar"] == ["黑天鹅"]
    assert parsed_doc["banners"][0]["featured"]["fourStar"] == ["米沙", "停云", "桂乃芬"]
    assert parsed_doc["banners"][1]["time"]["endAt"] == "2024-02-29T12:00:00+08:00"

def test_legacy_10_image_only_four_stars_not_guessed():
    from scripts.experiments.starrail_legacy_text_zh_cn import build
    body = "亲爱的开拓者：▌「蝶立锋锷」活动跃迁 活动期间，限定5星角色「希儿（巡猎•量子）」概率提升。"
    parsed_doc = build(make_raw("38387897", "「蝶立锋锷」活动跃迁开启！", body),
                       "38387897", compare_version="1.0", compare_phase=1)
    assert parsed_doc["banners"][0]["featured"]["fiveStar"] == ["希儿"]
    assert parsed_doc["banners"][0]["featured"]["fourStar"] == []
    assert parsed_doc["banners"][0]["time"] is None
    assert parsed_doc["review"]["status"] == "needs_review"

def test_preamble_one_time_multiple_five_star_targets():
    from scripts.transform.build_starrail_warp_notice_zh_cn import summary_time_by_five_star
    source = ("限定5星角色「长夜月（记忆•冰）」「海瑟音（虚无•物理）」「黑天鹅（虚无•风）」"
              "与限定5星光锥「致长夜的星光（记忆）」「海洋为何而歌（虚无）」"
              "将会返场，跃迁时间为 4.0版本更新后 - 2026/03/03 11:59。")
    result = summary_time_by_five_star(source)
    for name in ("长夜月", "海瑟音", "黑天鹅", "致长夜的星光", "海洋为何而歌"):
        assert result[name]["endAt"] == "2026-03-03T12:00:00+08:00"
