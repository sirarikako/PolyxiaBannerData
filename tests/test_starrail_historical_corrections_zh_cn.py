"""星铁历史名称统一与版本维护时间核验回归（只读）。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_NAMES = {
    "hsr-000022": ("1.4", 2, "溯回忆象", "44857709"),
    "hsr-000078": ("2.5", 1, "铭心之萃•卡芙卡", "57174807"),
    "hsr-000079": ("2.5", 1, "铭心之萃•黑天鹅", "57174807"),
    "hsr-000080": ("2.5", 1, "铭心之萃•知更鸟", "57174807"),
    "hsr-000110": ("3.0", 1, "真意之汇•唯有香如故", "61039078"),
    "hsr-000111": ("3.0", 1, "真意之汇•我将，巡征追猎", "61039078"),
    "hsr-000112": ("3.0", 1, "真意之汇•偏偏希望无价", "61039078"),
    "hsr-000118": ("3.0", 2, "真意之汇•驶向第二次生命", "61729646"),
    "hsr-000119": ("3.0", 2, "真意之汇•夜色流光溢彩", "61729646"),
    "hsr-000120": ("3.0", 2, "真意之汇•雨一直下", "61729646"),
    "hsr-000231": ("4.2", 1, "流光定影•欢迎来到银河城", "74771168"),
    "hsr-000239": ("4.2", 2, "流光定影•邂逅于下一个花季", "75267885"),
}
MAINTENANCE = {
    "3.8": ("2025-12-17T06:00:00+08:00", 4),
    "4.0": ("2026-02-13T06:00:00+08:00", 8),
    "4.2": ("2026-04-22T06:00:00+08:00", 8),
}

def load():
    return json.loads((ROOT / "public/v1/starrail.json").read_text(encoding="utf-8"))

def test_official_name_and_source_by_internal_id():
    data = load()
    by_id = {row["id"]: row for row in data["banners"]}
    # 286 是历史校准时的基线，并非永久卡池上限。
    assert len(data["banners"]) >= 286
    assert len(by_id) == len(data["banners"])
    for bid, (version, phase, official_name, post_id) in OFFICIAL_NAMES.items():
        row = by_id[bid]
        assert (row["gameVersion"], row["phase"], row["names"]["zh-CN"]) == (
            version, phase, official_name)
        assert any(src.get("provider") == "miyoushe" and
                   src.get("url") == f"https://www.miyoushe.com/sr/article/{post_id}"
                   for src in row["sources"])

def test_version_maintenance_dates_preserved():
    data = load()
    for version, (time, expected_pools) in MAINTENANCE.items():
        first = [b for b in data["banners"] if b["gameVersion"] == version and
                 b["phase"] == 1 and b["poolType"] in ("character_event", "light_cone_event")]
        assert len(first) == expected_pools
        assert all(next(r["startAt"] for r in b["regions"] if r["server"] == "cn_official") == time
                   for b in first)

def test_user_confirmed_10_pools_not_modified():
    data = load()
    by_id = {row["id"]: row for row in data["banners"]}
    assert {bid: by_id[bid]["featured"]["fiveStar"][0]["names"]["zh-CN"] for bid in (
        "hsr-000001", "hsr-000002", "hsr-000003", "hsr-000004")} == {
        "hsr-000001": "希儿", "hsr-000002": "于夜色中",
        "hsr-000003": "景元", "hsr-000004": "拂晓之前"}
    assert by_id["hsr-000205"]["phase"] == 1
    assert by_id["hsr-000209"]["phase"] == 1
