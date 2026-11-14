"""星铁物品名称匹配：先精确匹配，仅在唯一时回退日式引号变体。"""

# 官方物品表与跃迁公告可能分别使用「」和『』。
# 不做空格删除、繁简转换或模糊匹配，以免同名物品错误关联。
_STAR_RAIL_BRACKETS = str.maketrans({"『": "「", "』": "」"})


def starrail_name_key(name: str) -> str:
    return name.translate(_STAR_RAIL_BRACKETS)


def resolve_starrail_item_id(mapping: dict, name: str) -> tuple[int | None, str]:
    """返回 (唯一物品 ID, 匹配状态)，有歧义或数据异常时不猜测。"""
    if not isinstance(name, str):
        return None, "missing"
    if name in mapping:
        value = mapping[name]
        if type(value) is int and value > 0:
            return value, "exact"
        return None, "invalid"

    key = starrail_name_key(name)
    aliases = [value for other_name, value in mapping.items()
               if isinstance(other_name, str) and starrail_name_key(other_name) == key]
    if not aliases:
        return None, "missing"
    if any(type(value) is not int or value <= 0 for value in aliases):
        return None, "invalid"
    if len(set(aliases)) != 1:
        return None, "ambiguous"
    return aliases[0], "punctuation_alias"
