"""星铁独立逐池整合：自动/人工核对、已发布检查、候选隔离与只读预览。"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from scripts.transform.starrail_notice_manual_zh_cn import (
    compare_and_fill, identity, load_missing, load_real,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "data/derived/starrail/warp-notices"
UPDATES = "data/derived/starrail/version-updates"
OUTPUT = "data/derived/starrail/v1-candidates"
REPORT = "data/derived/starrail/v1-readiness/v1-readiness_zh-CN.json"
MAPPINGS = "public/item-mappings/starrail/zh-CN.json"
V1 = "public/v1/starrail.json"
TYPES = {"character_event": ("character", "character", "11"),
         "light_cone_event": ("light_cone", "light_cone", "12"),
         "collab_character": ("character", "character", "21"),
         "collab_light_cone": ("light_cone", "light_cone", "22")}
SPECIAL = {"collab_character", "collab_light_cone"}

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def star_names(featured):
    items = (featured or {}).get("fiveStar") or []
    return tuple(sorted(x if isinstance(x, str) else x.get("names", {}).get("zh-CN") or
                        x.get("name", "") for x in items))

def slot(row):
    return (*identity(row), star_names(row.get("featured")))

def key_for(pid, pool, name, five_star):
    raw = json.dumps([pool, name, sorted(five_star)], ensure_ascii=False)
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return str(pid) + "-" + suffix

def draft_for(row, mappings, source):
    pool = row["poolType"]
    cat, kind, code = TYPES[pool]
    up = row["featured"]
    def items(grade):
        return [{"itemId": str(mappings[n]) if n in mappings else None,
                 "type": kind, "names": {"zh-CN": n}} for n in up[grade]]
    t = row["time"]
    return {"gameVersion": row["version"], "phase": row["phase"], "category": cat,
            "poolType": pool, "names": {"zh-CN": row["bannerName"]},
            "gachaTypes": {"raw": [code], "uigf": [code]},
            "featured": {"fiveStar": items("fiveStar"), "fourStar": items("fourStar")},
            "regions": [{"server": "cn_official", "startAt": t["startAt"], "endAt": t["endAt"]}],
            "sources": [source]}

def assemble(root=ROOT, write=True):
    mappings = read(root / MAPPINGS)
    published = read(root / V1)["banners"]
    current = {}
    current_special = {}
    for b in published:
        k = (b["gameVersion"], b["phase"], b["poolType"], b["names"]["zh-CN"],
             star_names(b["featured"]))
        if k in current:
            raise ValueError("已发布 V1 存在重名、同版本同期的重复卡池：" + str(k))
        current[k] = b
        if b["poolType"] in SPECIAL:
            skey = (b["poolType"], b["names"]["zh-CN"], star_names(b["featured"]))
            if skey in current_special:
                raise ValueError("已发布联动池存在重复逻辑身份：" + str(skey))
            current_special[skey] = b
    updates = {}
    for path in sorted((root / UPDATES).glob("version-update_zh-CN_*.json")):
        data = read(path)
        if data.get("format") != "starrail-version-update-v1" or data.get("game") != "starrail":
            raise ValueError("版本公告候选格式错误：" + str(path))
        old = updates.get(data["version"])
        if old and old["maintenance"] != data["maintenance"]:
            raise ValueError("同版本维护时间来源相互矛盾：" + data["version"])
        updates[data["version"]] = data

    candidates = []
    unparsed = []
    real_manual = load_real(root)
    for path in sorted((root / SOURCE).glob("warp-notice_zh-CN_*.json")):
        data = read(path)
        if data.get("format") != "starrail-warp-notice-v1" or data.get("game") != "starrail":
            raise ValueError("跃迁候选格式不正确：" + str(path))
        pid = str(data["source"]["postId"])
        if not data.get("banners"):
            unparsed.append({"postId": pid, "source": str(path.relative_to(root)),
                             "issues": data.get("review", {}).get("warnings", [])})
        for banner in data.get("banners", []):
            row = {**deepcopy(banner), "version": data["version"], "phase": data["phase"]}
            row["sourceKey"] = key_for(pid, row["poolType"], row["bannerName"], star_names(row.get("featured")))
            row["source"] = {"provider": "miyoushe", "url": data["source"]["url"]}
            row["origin"] = str(path.relative_to(root))
            row["issues"] = []
            row["manualData"] = False
            candidates.append(row)

    # 长期联动公告正文没有版本号/期数，不能猜测；只使用对应真实文章的人工身份确认。
    for path in sorted((root / "data/derived/starrail/collab-notices").glob("collab-notice_zh-CN_*.json")):
        data = read(path)
        if data.get("format") != "starrail-collab-notice-v1" or data.get("game") != "starrail":
            raise ValueError("联动公告候选格式无效：" + str(path))
        pid = str(data["source"]["postId"])
        records = [item for _mp, config in real_manual if config["postId"] == pid
                   for item in config["banners"]]
        unresolved = []
        for banner in data.get("banners", []):
            options = [item["identity"] for item in records
                       if item["identity"]["poolType"] == banner["poolType"]
                       and item["identity"]["bannerName"] == banner["bannerName"]
                       and ("fiveStarName" not in item["identity"] or
                            item["identity"]["fiveStarName"] in star_names(banner.get("featured")))]
            if len(options) != 1:
                unresolved.append(banner["bannerName"])
                continue
            ident = options[0]
            entry = {**deepcopy(banner), "version": ident["version"], "phase": ident["phase"]}
            entry["sourceKey"] = key_for(pid, entry["poolType"], entry["bannerName"],
                                        star_names(entry.get("featured")))
            entry["source"] = {"provider": "miyoushe", "url": data["source"]["url"]}
            entry["origin"] = str(path.relative_to(root))
            entry["issues"] = []
            entry["manualData"] = False
            candidates.append(entry)
        if unresolved:
            unparsed.append({"postId": pid, "type": "waiting_identity",
                             "source": str(path.relative_to(root)),
                             "names": unresolved, "issues": []})

    for path, data in real_manual:
        pid = data["postId"]
        for entry in data["banners"]:
            ident = entry["identity"]
            k = identity(ident)
            matching = [x for x in candidates if slot(x)[:4] == k
                        and x["sourceKey"].startswith(pid + "-")
                        and ("fiveStarName" not in ident or ident["fiveStarName"] in slot(x)[4])]
            if len(matching) > 1:
                raise ValueError("真实帖子人工来源匹配多个自动卡池：" + str(k))
            if matching:
                target = matching[0]
                merged, conflicts, filled = compare_and_fill(target, entry["data"])
                target.update({field: merged[field] for field in ("featured", "time") if field in merged})
                target["manualData"] = True
                target["manualFiles"] = [str(path.relative_to(root))]
                target["filled"] = filled
                if conflicts:
                    target["issues"].append({"type": "manual_conflict", "details": conflicts})
            else:
                # 确认文章原文存在，才允许人工重建该篇中无法解析的单池。
                row = {**ident, **deepcopy(entry["data"]), "sourceKey": key_for(pid, ident["poolType"], ident["bannerName"],
                                                     star_names(entry["data"].get("featured"))),
                       "source": {"provider": "miyoushe", "url": "https://www.miyoushe.com/sr/article/" + pid},
                       "origin": str(path.relative_to(root)), "issues": [],
                       "manualData": True, "manualFiles": [str(path.relative_to(root))]}
                candidates.append(row)

    for path, data in load_missing(root):
        ident, supplied = data["identity"], data["data"]
        hashed = hashlib.sha256(json.dumps({"identity": ident, "fiveStar": star_names(supplied.get("featured"))},
                                    ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
        candidates.append({**ident, **deepcopy(supplied),
                           "sourceKey": "manual-" + hashed,
                           "source": {"provider": "manual", "externalId": "starrail-" + hashed},
                           "origin": str(path.relative_to(root)), "issues": [],
                           "manualData": True, "manualFiles": [str(path.relative_to(root))]})

    groups = {}
    for row in candidates:
        groups.setdefault(slot(row), []).append(row)
    rows = []
    ready_files = {}
    for ident, options in sorted(groups.items()):
        official = [x for x in options if x["source"]["provider"] == "miyoushe"]
        problems = []
        if len(official) > 1:
            problems.append("同一个业务身份对应多个官方卡池来源，需要人工核实")
        main = deepcopy(official[0] if official else options[0])
        for entry in options:
            if entry is official[0] if official else entry is options[0]:
                continue
            merged, conflicts, filled = compare_and_fill(main, entry)
            main.update({field: merged[field] for field in ("featured", "time") if field in merged})
            main.setdefault("filled", []).extend(filled)
            if conflicts:
                problems.append({"type": "source_conflict", "source": entry["origin"], "details": conflicts})
        problems.extend(main.get("issues", []))
        up, time = main.get("featured") or {}, main.get("time") or {}
        if main["poolType"] not in TYPES:
            problems.append("未知池类型")
        expected_four = 0 if main["poolType"] in SPECIAL else 3
        if len(up.get("fiveStar") or []) != 1 or len(up.get("fourStar") or []) != expected_four:
            problems.append(f"UP 不完整：需要 1 五星 + {expected_four} 四星")
        if len(set((up.get("fiveStar") or []) + (up.get("fourStar") or []))) != 1 + expected_four:
            problems.append("UP 名称出现重复")
        maintenance = (updates.get(main["version"]) or {}).get("maintenance") or {}
        if time.get("startCondition") in {"after_version_update", "date_only"}:
            maintenance_start = maintenance.get("startAt")
            # 4.4 等公告只提供起始日期，绝不自动猜测 00:00/06:00；
            # 版本更新公告能证明时间，且日期吻合，才可补充。
            if time.get("startCondition") == "date_only" and maintenance_start:
                if maintenance_start[:10] != time.get("startDate"):
                    problems.append("跃迁起始日期与版本维护公告日期不一致")
                elif not time.get("startAt"):
                    time["startAt"] = maintenance_start
                    main["time"] = time
            elif time.get("startCondition") == "after_version_update":
                if not time.get("startAt") and maintenance_start:
                    time["startAt"] = maintenance_start
                    main["time"] = time
                elif maintenance_start and time.get("startAt") != maintenance_start:
                    problems.append("跃迁时间和正式版本维护开始时间不一致")
        if not time.get("startAt") or "endAt" not in time or (
            time.get("endAt") is None and main["poolType"] not in SPECIAL
        ):
            problems.append("时间不完整，等待版本维护公告或人工依据")
        if time.get("startAt") and time.get("endAt") and time["startAt"] >= time["endAt"]:
            problems.append("开始时间不能晚于或等于结束时间")
        if not isinstance(main.get("bannerName"), str) or not main["bannerName"]:
            problems.append("缺少卡池名")

        drafted = draft_for(main, mappings, main["source"]) if not problems else None
        old = current.get(ident)
        if old is None and main["poolType"] in SPECIAL:
            old = current_special.get((main["poolType"], main["bannerName"],
                                       star_names(main.get("featured"))))
        published_diff = []
        # 同版本、同期、池种和五星 UP 全部相同，却出现不同池名时，
        # 历史公告可能采用新正式名而旧 V1 采用旧展示名。
        # 必须阻断新候选而不是分配新的内部 ID。
        if old is None and len(star_names(main.get("featured"))) == 1:
            near = [b for b in published if
                    b["gameVersion"] == main["version"] and b["phase"] == main["phase"] and
                    b["poolType"] == main["poolType"] and
                    star_names(b["featured"]) == star_names(main["featured"])]
            if near:
                if len(near) == 1:
                    old = near[0]
                    if old["names"]["zh-CN"] != main["bannerName"]:
                        published_diff.append("names.zh-CN")
                problems.append("疑似已发布同五星卡池，但卡池名称不一致；禁止重复追加，需人工复核")
        if old is None and not problems and drafted and main["poolType"] not in SPECIAL:
            # 官方第二期偶尔继续展示第一期尚未结束的卡池。
            # 只在同版本、同名、同五星、起止时间完全一致时视为延续，
            # 不能把新一期重复复刻误当成旧池。
            new_region = drafted["regions"][0]
            same_run = [b for b in published if
                        b["gameVersion"] == main["version"] and
                        b["poolType"] == main["poolType"] and
                        b["phase"] is not None and b["phase"] < main["phase"] and
                        b["names"]["zh-CN"] == main["bannerName"] and
                        star_names(b["featured"]) == star_names(main["featured"]) and
                        any(r["server"] == "cn_official" and
                            r["startAt"] == new_region["startAt"] and
                            r["endAt"] == new_region["endAt"] for r in b["regions"])]
            if len(same_run) == 1:
                old = same_run[0]
            elif len(same_run) > 1:
                problems.append("不同旧期存在多个相同时间卡池，不能自动识别跨期延续")
        if old and drafted and old["gameVersion"] == main["version"] and old["phase"] == main["phase"]:
            # 新公告可能没有 gachaIds 或尚未补全 itemId；这些缺失不属于旧 V1 错误。
            for grade in ("fiveStar", "fourStar"):
                old_names = sorted(x["names"].get("zh-CN") for x in old["featured"][grade])
                new_names = sorted(x["names"].get("zh-CN") for x in drafted["featured"][grade])
                if old_names != new_names:
                    published_diff.append("featured." + grade + ".names")
                old_ids = {x["names"].get("zh-CN"): x.get("itemId") for x in old["featured"][grade]}
                for item in drafted["featured"][grade]:
                    name, known = item["names"].get("zh-CN"), item.get("itemId")
                    if known is not None and old_ids.get(name) is not None and old_ids[name] != known:
                        published_diff.append("featured." + grade + ".itemId." + str(name))
            old_region = next((x for x in old["regions"] if x["server"] == "cn_official"), {})
            new_region = drafted["regions"][0]
            for field in ("startAt", "endAt"):
                if old_region.get(field) != new_region.get(field):
                    published_diff.append("regions.cn_official." + field)
            if old["poolType"] != drafted["poolType"]:
                published_diff.append("poolType")
            # raw 可未知，但明示为确定类型时才比较。
            if drafted["gachaTypes"].get("uigf") != old["gachaTypes"].get("uigf"):
                published_diff.append("gachaTypes.uigf")
        if problems:
            status = "needs_review"
        elif old:
            status = "already_published"
        else:
            status = "ready_candidate"
        row = {"format": "starrail-v1-candidate-zh-CN-v1", "game": "starrail", "locale": "zh-CN",
               "version": main["version"], "phase": main["phase"], "poolType": main["poolType"],
               "bannerName": main["bannerName"], "sourceKey": main["sourceKey"],
               "status": status, "issues": problems, "publishedDifferences": published_diff,
               "existingId": old["id"] if old else None,
               "sources": [x["origin"] for x in options],
               "manualFilled": main.get("filled", []), "manualRecovery": bool(main.get("manualData")),
               "v1Draft": drafted}
        rows.append(row)
        if status == "ready_candidate":
            ready_files["v1-candidate_zh-CN_" + main["sourceKey"] + ".json"] = row
    report = {"format": "starrail-v1-readiness-v1", "count": len(rows),
              "ready": len(ready_files),
              "alreadyPublished": sum(r["status"] == "already_published" for r in rows),
              "unparsedNotices": unparsed, "rows": rows}
    if write:
        folder = root / OUTPUT
        folder.mkdir(parents=True, exist_ok=True)
        for filename, row in ready_files.items():
            save(folder / filename, row)
        # 不允许已失效的历史 ready 文件继续留作独立发布输入。
        for path in folder.glob("v1-candidate_zh-CN_*.json"):
            if path.name not in ready_files:
                path.unlink()
        save(root / REPORT, report)
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(assemble(write=not args.check_only), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
