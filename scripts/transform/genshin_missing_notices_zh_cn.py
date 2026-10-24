"""无官方帖子时的原神人工公告输入；身份与来源独立于米游社文章 ID。

仅在逐池整合阶段使用，不能伪造 source.postId、官方原文或 OCR 结果。
官方解析恢复后，按稳定身份合并并逐字段核对；有冲突时保留自动值并阻断候选。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker

from scripts.transform.genshin_notice_manual_zh_cn import (
    ALLOWED, classify_differences, merge_data,
)

MISSING_ROOT = Path("manual/notices/genshin/zh-CN/missing")
KINDS = {"version_update", "wish_preview", "wish_notice"}
POOL_TYPES = {"character_event", "character_event_2", "weapon_event", "chronicled"}
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas/manual/genshin-missing-notice.schema.json"


def _identity(kind: str, obj: dict) -> tuple:
    if kind == "version_update":
        return (str(obj.get("version") or ""),)
    if kind == "wish_preview":
        return (str(obj.get("version") or ""), obj.get("phase"))
    if kind == "wish_notice":
        return (str(obj.get("version") or ""), obj.get("phase"),
                obj.get("poolType"), obj.get("variant") if obj.get("poolType") == "chronicled" else None)
    raise ValueError("未知公告类型")


def _time(value: object) -> None:
    if not isinstance(value, str):
        raise ValueError("必须提供 ISO +08:00 时间")
    dt = datetime.fromisoformat(value)
    if dt.utcoffset() != timedelta(hours=8) or dt.second or dt.microsecond:
        raise ValueError("时间必须是 +08:00 且精确到分钟")


def read_missing(root: Path) -> tuple[list[dict], list[dict]]:
    result, errors = [], []
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for path in sorted((root / MISSING_ROOT).glob("*.json")):
        relative = path.relative_to(root).as_posix()
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(obj, dict) or obj.get("format") != "genshin-missing-notice-v1"
                    or set(obj) - {"format", "noticeType", "identity", "data", "evidence"}):
                raise ValueError("人工缺失公告格式不正确")
            schema_errors = list(validator.iter_errors(obj))
            if schema_errors:
                issue = sorted(schema_errors, key=lambda e: str(e.json_path))[0]
                raise ValueError(f"人工 Schema 校验失败 {issue.json_path}: {issue.message}")
            kind, identity, values = obj.get("noticeType"), obj.get("identity"), obj.get("data")
            evidence = obj.get("evidence")
            if kind not in KINDS or not isinstance(identity, dict) or not isinstance(values, dict):
                raise ValueError("noticeType/identity/data 不正确")
            if (not isinstance(evidence, dict) or
                    not isinstance(evidence.get("summary"), str) or not evidence["summary"].strip()):
                raise ValueError("必须在 evidence.summary 中填写人工核实依据")
            keys = ({"version"} if kind == "version_update" else
                    {"version", "phase"} if kind == "wish_preview" else
                    {"version", "phase", "poolType"})
            allowed_keys = keys | ({"variant"} if kind == "wish_notice" else set())
            if not keys.issubset(identity) or set(identity) - allowed_keys:
                raise ValueError("identity 的必填或允许字段不正确")
            version = identity.get("version")
            if not isinstance(version, str) or not version.strip() or "/" in version or "\\" in version:
                raise ValueError("identity.version 不正确")
            if kind != "version_update" and (type(identity.get("phase")) is not int
                                                or identity["phase"] not in range(1, 10)):
                raise ValueError("identity.phase 必须是 1~9")
            if kind == "wish_notice":
                if identity.get("poolType") not in POOL_TYPES:
                    raise ValueError("identity.poolType 不正确")
                if identity["poolType"] == "chronicled":
                    if identity.get("variant") not in ("chronicled", "special_recollection"):
                        raise ValueError("集录必须明确 variant")
                elif identity.get("variant") is not None:
                    raise ValueError("非集录祈愿不能设置 variant")
            if set(values) - ALLOWED[kind]:
                raise ValueError("data 中包含不属于该公告类型的字段")
            if kind == "version_update":
                if "version" in values:
                    raise ValueError("data.version 与 identity 冲突")
                values = {"version": version, **values}
                if not isinstance(values.get("maintenance"), dict):
                    raise ValueError("缺少维护开始时间")
                _time(values["maintenance"].get("startAt"))
            elif kind == "wish_preview":
                if "version" in values or "phase" in values:
                    raise ValueError("data 版本/期数与 identity 冲突")
                values = {"version": version, "phase": identity["phase"], **values}
                if not isinstance(values.get("time"), dict):
                    raise ValueError("缺少预告时间")
                _time(values["time"].get("endAt"))
                # 纯特殊池的预告允许省略 up；常规池 UP 的完整性由整合器检查。
            else:
                if "poolType" in values or "variant" in values:
                    raise ValueError("data.poolType 与 identity 冲突")
                values = {"poolType": identity["poolType"], **values}
                if identity["poolType"] == "chronicled":
                    values["variant"] = identity["variant"]
                if not isinstance(values.get("bannerName"), str) or not values["bannerName"].strip():
                    raise ValueError("缺少祈愿名称")
                if not isinstance(values.get("time"), dict):
                    raise ValueError("缺少祈愿时间")
                _time(values["time"].get("endAt"))
                if not isinstance(values.get("up"), dict) and identity["poolType"] != "chronicled":
                    raise ValueError("缺少祈愿 UP 名单")
            id_tuple = (kind, *_identity(kind, identity))
            identity_json = json.dumps(id_tuple, ensure_ascii=False, separators=(",", ":"))
            key = "manual-" + hashlib.sha256(identity_json.encode("utf-8")).hexdigest()[:20]
            external_id = ":".join(str(x) for x in id_tuple if x is not None)
            data = {"game": "genshin", "locale": "zh-CN", "noticeType": kind,
                    **deepcopy(values), "source": {"provider": "manual",
                    "sourceKey": key, "externalId": external_id},
                    "review": {"warnings": []}}
            result.append({"kind": kind, "identity": identity, "sourceKey": key,
                           "manualIdentity": deepcopy(identity), "manualSourceKey": key,
                           "manualEvidence": deepcopy(evidence),
                           "path": relative, "manualFile": relative, "manualOnly": True,
                           "data": data, "differences": [], "blockingDifferences": [],
                           "warningDifferences": [], "filled": [], "matched": []})
        except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
            errors.append({"path": relative, "error": f"缺失公告人工数据无效：{exc}"})
    return result, errors


def _same(kind: str, auto: dict, missing: dict, previews: list[dict] | None = None) -> bool:
    """匹配依据是业务身份；名称、UP、起止时间都是待比对的值。

    官方祈愿公告本身没有 version/phase，因此先利用其结束时间与已知预告
    （包含人工预告）的关联推导身份。不能以名称/时间均相等作为比较前提。
    """
    data, human = auto["data"], missing["data"]
    identity = missing["identity"]
    if kind == "version_update":
        return data.get("version") == identity["version"]
    if kind == "wish_preview":
        return (data.get("version"), data.get("phase")) == (identity["version"], identity["phase"])
    if (data.get("poolType") != identity["poolType"]
            or (data.get("variant") if data.get("poolType") == "chronicled" else None)
                != identity.get("variant")):
        return False
    if isinstance(data.get("version"), str) and isinstance(data.get("phase"), int):
        return (data["version"], data["phase"]) == (identity["version"], identity["phase"])
    end = (data.get("time") or {}).get("endAt")
    inferred = {(p["data"].get("version"), p["data"].get("phase"))
                for p in previews or [] if "data" in p
                and (p["data"].get("time") or {}).get("endAt") == end}
    if not inferred:
        # 即使官方公告的结束时间与人工预告同时写错，也可借助开池落入
        # 已知预告的时间区间进行第二重身份核验。多期命中时拒绝猜测。
        start = (data.get("time") or {}).get("startAt")
        try:
            instant = datetime.fromisoformat(start) if start else None
        except ValueError:
            instant = None
        if instant and instant.utcoffset() is not None:
            for preview in previews or []:
                if "data" not in preview:
                    continue
                interval = preview["data"].get("time") or {}
                try:
                    low = datetime.fromisoformat(interval["startAt"])
                    high = datetime.fromisoformat(interval["endAt"])
                except (KeyError, TypeError, ValueError):
                    continue
                if low.tzinfo and high.tzinfo and low <= instant <= high:
                    inferred.add((preview["data"].get("version"), preview["data"].get("phase")))
    if inferred:
        return len(inferred) == 1 and (identity["version"], identity["phase"]) in inferred
    # 仍无法确定版本/期数时，只接受真实的共同时间锚点。
    # 常见的重复祈愿名称（如武器池）不能单独作为跨版本身份依据。
    at, ht = data.get("time") or {}, human.get("time") or {}
    return any(at.get(field) and at.get(field) == ht.get(field)
               for field in ("startAt", "endAt"))


def merge_missing(existing: list[dict], missing: list[dict], kind: str,
                  previews: list[dict] | None = None) -> list[dict]:
    rows = list(existing)
    seen: set[tuple] = set()
    for human in missing:
        if human["kind"] != kind:
            continue
        ident = (kind, *_identity(kind, human["identity"]))
        if ident in seen:
            # 两份有效人工文件声称同一业务身份时，不能采用先读到的那份继续发布。
            for previous in rows:
                if previous.get("manualSourceKey") == human["sourceKey"]:
                    previous["error"] = "同一人工公告身份重复，已暂停两份来源"
                    previous.pop("data", None)
            rows.append({"path": human["path"], "error": "同一人工公告身份重复",
                         "sourceKey": human["sourceKey"]})
            continue
        seen.add(ident)
        matching = [r for r in existing if "data" in r and _same(kind, r, human, previews)]
        if len(matching) > 1:
            rows.append({"path": human["path"], "error": "多个官方公告匹配同一人工公告",
                         "sourceKey": human["sourceKey"]})
            continue
        if matching:
            target = matching[0]
            proposed = {key: value for key, value in human["data"].items()
                        if key not in ("source", "review", "game", "locale", "noticeType",
                                       "version", "phase", "poolType", "variant")}
            effective, diffs, filled, matched = merge_data(target["data"], proposed)
            block, warn = classify_differences(kind, diffs)
            target["data"] = effective
            target["manualFile"] = human["manualFile"]
            target["manualIdentity"] = deepcopy(human["identity"])
            target["manualSourceKey"] = human["sourceKey"]
            target["manualEvidence"] = deepcopy(human["manualEvidence"])
            target["differences"] = list(target.get("differences") or []) + diffs
            target["blockingDifferences"] = list(target.get("blockingDifferences") or []) + block
            target["warningDifferences"] = list(target.get("warningDifferences") or []) + warn
            target["filled"] = list(target.get("filled") or []) + filled
            target["matched"] = list(target.get("matched") or []) + matched
        else:
            rows.append(human)
    return rows
