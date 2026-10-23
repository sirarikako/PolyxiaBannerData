"""星铁真实帖子人工补缺与缺帖来源的安全读取，禁止伪造帖子证据。"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]

def validate_manual(path, schema_name, root=ROOT):
    schema = json.loads((root / "schemas/manual" / schema_name).read_text(encoding="utf-8"))
    obj = json.loads(path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = list(validator.iter_errors(obj))
    if errors:
        first = sorted(errors, key=lambda e: str(e.json_path))[0]
        raise ValueError(f"{path}: {first.json_path}: {first.message}")
    return obj

def identity(row):
    return tuple(row.get(x) for x in ("version", "phase", "poolType", "bannerName"))

def compare_and_fill(auto, manual):
    """只填 None/缺失，已确认的自动字段不得静默覆盖；UP 列表整项比较。"""
    out = deepcopy(auto)
    conflicts, filled = [], []
    for field in ("featured", "time"):
        if field not in manual:
            continue
        dest = out.setdefault(field, {})
        if dest is None:
            out[field] = dest = {}
        for k, val in manual[field].items():
            old = dest.get(k)
            if old is None:
                dest[k] = deepcopy(val)
                filled.append(field + "." + k)
            elif old != val:
                conflicts.append({"field": field + "." + k, "auto": old, "manual": val})
    return out, conflicts, filled

def load_missing(root=ROOT):
    folder = root / "manual/notices/starrail/zh-CN/missing"
    result = []
    for path in sorted(folder.glob("*.json")):
        obj = validate_manual(path, "starrail-missing-warp.schema.json", root)
        result.append((path, obj))
    return result

def load_real(root=ROOT):
    folder = root / "manual/notices/starrail/zh-CN/miyoushe"
    raw_folder = root / "data/announcements/starrail/zh-cn/miyoushe/posts"
    result = []
    for path in sorted(folder.glob("*.json")):
        obj = validate_manual(path, "starrail-notice-manual.schema.json", root)
        pid = obj["postId"]
        if path.stem != pid or not (raw_folder / (pid + ".json")).is_file():
            raise ValueError(f"真实帖子人工文件 {path} 缺少匹配的官方原文，不能伪造文章")
        result.append((path, obj))
    return result
