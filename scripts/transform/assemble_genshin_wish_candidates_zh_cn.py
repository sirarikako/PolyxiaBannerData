#!/usr/bin/env python3
"""离线按单篇祈愿公告整合原神简体中文 v1 前置候选，不修改正式 v1。

版本更新(version) -> 祈愿预告(version, phase) -> OCR 结束时间 -> 单篇祈愿公告。
不以五星角色确定期数，不等待同一期其他公告，也不推断公告未出现的池子。

python -m scripts.transform.assemble_genshin_wish_candidates_zh_cn
python -m scripts.transform.assemble_genshin_wish_candidates_zh_cn --post-id 78782590
python -m scripts.transform.assemble_genshin_wish_candidates_zh_cn --check-only
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from scripts.transform.genshin_notice_manual_zh_cn import apply as apply_manual, index_additional
from scripts.transform.genshin_missing_notices_zh_cn import read_missing, merge_missing

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('data/derived/genshin')
OUTPUT = Path('data/derived/genshin/v1-candidates')
REPORT = Path('data/derived/genshin/v1-readiness/v1-readiness_zh-CN.json')
MAPPINGS = Path('public/item-mappings/genshin/zh-CN.json')
V1 = Path('public/v1/genshin.json')
OCR_READY = {'recognized', 'recognized_conditional'}
NORMAL = {'character_event', 'character_event_2', 'weapon_event'}
SUPPORTED = NORMAL | {'chronicled'}
TYPE = {'character_event': ('character', ['301'], ['301']),
        'character_event_2': ('character', ['400'], ['301']),
        'weapon_event': ('weapon', ['302'], ['302']),
        'chronicled': ('chronicled', None, ['500'])}


def read(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise ValueError('JSON 根节点必须是对象')
    return obj


def save(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(obj, ensure_ascii=False, indent=2) + '\n'
    if not path.exists() or path.read_text(encoding='utf-8') != content:
        path.write_text(content, encoding='utf-8')


def minute(value: object) -> datetime | None:
    """同语种来源统一使用带时区 ISO；按公告精度（分钟）比较瞬时值。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.second or parsed.microsecond:
        return None
    return parsed.astimezone(timezone.utc)


def names(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    return [v if isinstance(v, str) else v.get('name', '') if isinstance(v, dict) else ''
            for v in items]


def inventory(notice: dict) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    pool = notice.get('poolType')
    if pool == 'chronicled':
        src = notice.get('selectable') or {}
        return ([(n, 'character') for n in names(src.get('fiveStarCharacters'))] +
                [(n, 'weapon') for n in names(src.get('fiveStarWeapons'))]), []
    src = notice.get('up') or {}
    return ([(n, 'character') for n in names(src.get('fiveStarCharacters'))] +
            [(n, 'weapon') for n in names(src.get('fiveStarWeapons'))],
            [(n, 'character') for n in names(src.get('fourStarCharacters'))] +
            [(n, 'weapon') for n in names(src.get('fourStarWeapons'))])


def validate_contents(notice: dict, preview: dict) -> list[str]:
    pool, up = notice.get('poolType'), notice.get('up') or {}
    errors: list[str] = []
    five, four = inventory(notice)
    if pool not in SUPPORTED:
        return ['unsupported_pool_type']
    if not isinstance(notice.get('bannerName'), str) or not notice['bannerName'].strip():
        errors.append('missing_banner_name')
    if not all(isinstance(n, str) and n.strip() for n, _ in five + four):
        errors.append('invalid_item_name')
    if len(set(five)) != len(five) or len(set(four)) != len(four):
        errors.append('duplicate_item')
    if pool in ('character_event', 'character_event_2'):
        if len(names(up.get('fiveStarCharacters'))) != 1 or len(names(up.get('fourStarCharacters'))) != 3:
            errors.append('incomplete_character_up')
        if names(up.get('fiveStarWeapons')) or names(up.get('fourStarWeapons')):
            errors.append('unexpected_weapon_up')
        expected = set(names((preview.get('up') or {}).get('fiveStarCharacters')))
        if any(name not in expected for name, _ in five):
            errors.append('five_star_preview_conflict')
    elif pool == 'weapon_event':
        if len(names(up.get('fiveStarWeapons'))) != 2 or len(names(up.get('fourStarWeapons'))) != 5:
            errors.append('incomplete_weapon_up')
        if names(up.get('fiveStarCharacters')) or names(up.get('fourStarCharacters')):
            errors.append('unexpected_character_up')
        expected = set(names((preview.get('up') or {}).get('fiveStarWeapons')))
        if {n for n, _ in five} != expected:
            errors.append('five_star_preview_conflict')
    else:
        if notice.get('variant') not in ('chronicled', 'special_recollection'):
            errors.append('invalid_special_variant')
        if not five or not any(kind == 'character' for _, kind in five) or not any(kind == 'weapon' for _, kind in five):
            errors.append('incomplete_selectable')
        if any(names(up.get(field)) for field in ('fiveStarCharacters', 'fiveStarWeapons', 'fourStarCharacters', 'fourStarWeapons')):
            errors.append('unexpected_special_up')
    return errors


def draft(notice: dict, preview: dict, mappings: dict) -> tuple[dict, list[str]]:
    pool, raw, uigf = TYPE[notice['poolType']]
    five, four = inventory(notice)
    unknown = sorted({n for n, _ in five + four if not isinstance(mappings.get(n), int) or mappings[n] <= 0})
    def convert(items: list[tuple[str, str]]) -> list[dict]:
        return [{'itemId': str(mappings[n]) if n not in unknown else None,
                 'names': {'zh-CN': n}, 'type': kind} for n, kind in items]
    start = minute((notice.get('time') or {}).get('startAt'))
    end = minute((notice.get('time') or {}).get('endAt'))
    result = {'gameVersion': preview['version'], 'phase': preview['phase'],
              'category': TYPE[notice['poolType']][0], 'poolType': notice['poolType'],
              'names': {'zh-CN': notice['bannerName']},
              'gachaTypes': {'raw': raw, 'uigf': uigf},
              'featured': {'fiveStar': convert(five), 'fourStar': convert(four)},
              'regions': [{'server': 'cn_official',
                           'startAt': start.astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds') if start else None,
                           'endAt': (end + timedelta(minutes=1)).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds') if end else None}],
              'sources': [({'provider': 'manual', 'externalId': source['externalId']}
                          if source.get('provider') == 'manual' else
                          {'provider': 'miyoushe', 'url': source['url']})
                          for source in (preview['source'], notice['source'])]}
    if notice['poolType'] == 'chronicled':
        result['variant'] = notice['variant']
    if notice['poolType'] in ('weapon_event', 'chronicled'):
        result['fatePointLimit'] = 1  # 现行项目规则；正式发布仍须人工核实
    return result, unknown


def build_index(root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    def collect(folder: str, pattern: str, kind: str) -> list[dict]:
        items = []
        for path in sorted((root / SOURCE / folder).glob(pattern)):
            pid = None
            try:
                j = read(path)
                if isinstance(j.get('source'), dict):
                    pid = str(j['source'].get('postId') or '') or None
                if j.get('game') != 'genshin' or j.get('locale') != 'zh-CN' or j.get('noticeType', kind) != kind:
                    raise ValueError('game/locale/noticeType 不正确')
                pid = str((j.get('source') or {}).get('postId') or '')
                if not re.fullmatch(r'\d+', pid):
                    raise ValueError('缺少真实来源文章 ID')
                merged = apply_manual(root, kind, pid, j)
                items.append({'path': path.relative_to(root).as_posix(), **merged})
            except (ValueError, OSError) as exc:
                items.append({'path': path.relative_to(root).as_posix(),
                              'postId': pid, 'error': str(exc)})
        items.extend(index_additional(root, items, kind))
        return items
    manuals, errors = read_missing(root)
    groups = [collect('version-updates', 'version-update_zh-CN_*.json', 'version_update'),
              collect('wish-previews', 'wish-preview_zh-CN_*.json', 'wish_preview'),
              collect('wish-notices', 'wish-notice_zh-CN_*.json', 'wish_notice')]
    updates = merge_missing(groups[0], manuals, 'version_update')
    previews = merge_missing(groups[1], manuals, 'wish_preview')
    notices = merge_missing(groups[2], manuals, 'wish_notice', previews=previews)
    # 原人工 Schema 校验错误只记录一次，不反复生成同一错误的三个来源。
    notices.extend(errors)
    return updates, previews, notices


def assemble(root: Path = ROOT, post_id: str | None = None, write: bool = True) -> dict:
    updates, previews, notices = build_index(root)
    version_map: dict[str, list[dict]] = defaultdict(list)
    for row in updates:
        if 'data' in row and isinstance(row['data'].get('version'), str):
            version_map[row['data']['version']].append(row)
    indexed_previews: dict[datetime, list[dict]] = defaultdict(list)
    identity_previews: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in previews:
        if 'data' in row:
            identity_previews[(row['data'].get('version'), row['data'].get('phase'))].append(row)
            key = minute((row['data'].get('time') or {}).get('endAt'))
            if key is not None:
                indexed_previews[key].append(row)
    mappings = read(root / MAPPINGS) if (root / MAPPINGS).exists() else {}
    v1 = read(root / V1).get('banners', []) if (root / V1).exists() else []
    v1_by_notice: dict[str, list[dict]] = defaultdict(list)
    v1_by_slot: dict[tuple, list[dict]] = defaultdict(list)
    for published in v1:
        v1_by_slot[(published.get('gameVersion'), published.get('phase'), published.get('poolType'),
                    published.get('variant') if published.get('poolType') == 'chronicled' else None)].append(published)
        for source in published.get('sources', []):
            url = source.get('url', '')
            if isinstance(url, str) and re.search(r'/article/\d+$', url):
                v1_by_notice[url].append(published)
    rows: list[dict] = []
    completed: dict[tuple, list[int]] = defaultdict(list)
    for source in notices:
        src_path = source['path']
        id_from_file = re.search(r'_(\d+)\.json$', src_path)
        pid = id_from_file.group(1) if id_from_file else None
        key = pid or source.get('sourceKey')
        if not key and 'data' in source:
            key = (source['data'].get('source') or {}).get('sourceKey')
        if post_id is not None and pid != post_id:
            continue
        row = {'postId': pid, 'sourceKey': key, 'noticeFile': source.get('evidenceFile', src_path), 'status': 'waiting',
               'issues': [], 'warnings': [], 'version': None, 'phase': None,
               'previewFile': None, 'versionUpdateFile': None, 'existingV1Id': None,
               'manualDifferences': list(source.get('differences') or []),
               'blockingDifferences': list(source.get('blockingDifferences') or []),
               'warningDifferences': list(source.get('warningDifferences') or []),
               'manualFilled': list(source.get('filled') or []),
               'manualMatched': list(source.get('matched') or []),
               'manualFile': source.get('manualFile'),
               'manualSourceKey': source.get('manualSourceKey'),
               'manualIdentity': source.get('manualIdentity'),
               'manualEvidence': source.get('manualEvidence'),
               'recoveredFromRaw': bool(source.get('fallback'))}
        rows.append(row)
        out = root / OUTPUT / f'v1-candidate_zh-CN_{key}.json' if key else None
        def fail(code: str, status: str = 'waiting') -> None:
            if status == 'conflict' or row['status'] != 'conflict':
                row['status'] = status
            if code not in row['issues']:
                row['issues'].append(code)
        if 'data' not in source:
            fail('invalid_notice_json', 'conflict')
            continue
        notice = source['data']
        if not key or (pid and str((notice.get('source') or {}).get('postId')) != pid):
            fail('invalid_notice_post_id', 'conflict')
            continue
        ocr = notice.get('imageTimeRecognition') or {}
        ocr_time = ocr.get('times') or {}
        notice_time = notice.get('time') or {}
        manual_fields = set(row['manualFilled'] + row['manualMatched'])
        manual_end = 'time.endAt' in manual_fields or bool(source.get('manualOnly'))
        ocr_ok = ocr.get('status') in OCR_READY and minute(ocr_time.get('endAt')) is not None
        end = minute(notice_time.get('endAt'))
        if end is None or not (ocr_ok or manual_end):
            fail('waiting_ocr_end_time')
            continue
        if ocr_ok and minute(ocr_time['endAt']) != end:
            fail('ocr_notice_end_conflict', 'conflict')
            continue
        row['endTimeEvidence'] = 'manual' if manual_end and not ocr_ok else 'ocr'
        if source.get('blockingDifferences'):
            fail('manual_auto_mismatch', 'conflict')
        manual_identity = source.get('manualIdentity')
        if manual_identity and isinstance(manual_identity.get('phase'), int):
            # 缺帖 JSON 已明确记录版本与期数，先按身份选预告，再核对结束时间。
            # 官方恢复时即使人工作错时间，仍要把同一池关联起来并发出冲突。
            options = identity_previews.get((manual_identity['version'], manual_identity['phase']), [])
            if not options:
                fail('waiting_identity_preview')
                continue
            if len(options) > 1:
                fail('ambiguous_identity_preview', 'conflict')
                row['matchingPreviews'] = [x['path'] for x in options]
                continue
            if minute((options[0]['data'].get('time') or {}).get('endAt')) != end:
                fail('manual_identity_end_time_conflict', 'conflict')
        else:
            options = indexed_previews.get(end, [])
            if not options:
                fail('unmatched_end_time')
                continue
            if len(options) > 1:
                fail('ambiguous_end_time', 'conflict')
                row['matchingPreviews'] = [x['path'] for x in options]
                continue
        pv = options[0]
        preview = pv['data']
        for upstream in (pv,):
            row['manualDifferences'].extend(upstream.get('differences') or [])
            row['blockingDifferences'].extend(upstream.get('blockingDifferences') or [])
            row['warningDifferences'].extend(upstream.get('warningDifferences') or [])
            if upstream.get('blockingDifferences'):
                fail('preview_manual_auto_mismatch', 'conflict')
        row['previewFile'] = pv.get('evidenceFile', pv['path'])
        row['manualAudits'] = [
            {'kind': kind, 'sourceKey': entry.get('manualSourceKey'),
             'file': entry.get('manualFile'), 'identity': entry.get('manualIdentity'),
             'evidence': entry.get('manualEvidence')}
            for kind, entry in (('wish_notice', source), ('wish_preview', pv))
            if entry.get('manualEvidence')]
        row['version'], row['phase'] = preview.get('version'), preview.get('phase')
        if not isinstance(row['version'], str) or not isinstance(row['phase'], int) or row['phase'] < 1:
            fail('invalid_preview_version_phase', 'conflict')
            continue
        updates_for_version = version_map.get(row['version'], [])
        if not updates_for_version:
            fail('waiting_version_update')
            continue
        if len(updates_for_version) > 1:
            fail('ambiguous_version_update', 'conflict')
            continue
        upd = updates_for_version[0]
        row['versionUpdateFile'] = upd.get('evidenceFile', upd['path'])
        if upd.get('manualEvidence'):
            row['manualAudits'].append({
                'kind': 'version_update', 'sourceKey': upd.get('manualSourceKey'),
                'file': upd.get('manualFile'), 'identity': upd.get('manualIdentity'),
                'evidence': upd.get('manualEvidence')})
        row['manualDifferences'].extend(upd.get('differences') or [])
        row['blockingDifferences'].extend(upd.get('blockingDifferences') or [])
        row['warningDifferences'].extend(upd.get('warningDifferences') or [])
        if upd.get('blockingDifferences'):
            fail('version_manual_auto_mismatch', 'conflict')
        if not minute((upd['data'].get('maintenance') or {}).get('startAt')):
            fail('invalid_version_update', 'conflict')
            continue
        if preview.get('time', {}).get('startAt') and notice_time.get('startAt'):
            if minute(preview['time']['startAt']) != minute(notice_time['startAt']):
                fail('start_time_conflict', 'conflict')
        if ocr_ok and minute(ocr_time.get('startAt')) and minute(notice_time.get('startAt')) != minute(ocr_time['startAt']):
            fail('ocr_notice_start_conflict', 'conflict')
        warnings = list((notice.get('review') or {}).get('warnings') or [])
        if manual_end:
            warnings = [w for w in warnings if not (
                w.startswith('文章含图片') or w.startswith('正文未明确给出祈愿结束时间')
                or w.startswith('图片识别失败'))]
        if 'time.startAt' in manual_fields or 'time.startCondition' in manual_fields:
            warnings = [w for w in warnings if not w.startswith('正文未明确给出祈愿开始时间')]
        if warnings or (ocr_ok and ocr.get('warnings')):
            fail('source_review_warnings', 'conflict')
        if not minute(notice_time.get('startAt')) and (
                preview.get('phase') != 1 or notice_time.get('startCondition') != 'after_version_update'):
            fail('missing_start_time', 'conflict')
        for code in validate_contents(notice, preview):
            fail(code, 'conflict')
        published = v1_by_notice.get((notice.get('source') or {}).get('url'), [])
        by_slot = v1_by_slot.get((row['version'], row['phase'], notice.get('poolType'),
                                  notice.get('variant') if notice.get('poolType') == 'chronicled' else None), [])
        if not published:
            published = by_slot
        if len(published) > 1:
            fail('duplicate_existing_v1_source', 'conflict')
        elif published:
            existing = published[0]
            row['existingV1Id'] = existing.get('id')
            if (existing.get('gameVersion'), existing.get('phase'), existing.get('poolType')) != (row['version'], row['phase'], notice.get('poolType')):
                fail('existing_v1_identity_conflict', 'conflict')
            a, b = inventory(notice)
            if sorted((n, t) for n, t in a) != sorted((it['names'].get('zh-CN'), it.get('type')) for it in existing.get('featured', {}).get('fiveStar', [])):
                fail('existing_v1_five_star_conflict', 'conflict')
            if sorted((n, t) for n, t in b) != sorted((it['names'].get('zh-CN'), it.get('type')) for it in existing.get('featured', {}).get('fourStar', [])):
                fail('existing_v1_four_star_conflict', 'conflict')
            region = next((reg for reg in existing.get('regions', []) if reg.get('server') == 'cn_official'), {})
            if minute(region.get('endAt')) != end + timedelta(minutes=1):
                fail('existing_v1_end_time_conflict', 'conflict')
            if minute(region.get('startAt')) and minute(notice_time.get('startAt')) and minute(region['startAt']) != minute(notice_time['startAt']):
                fail('existing_v1_start_time_conflict', 'conflict')
        if row['issues']:
            continue
        draft_data, unknown = draft(notice, preview, mappings)
        if unknown:
            row['warnings'].append('missing_item_ids')
            row['missingItemNames'] = unknown
        if notice_time.get('startCondition') == 'after_version_update':
            row['warnings'].append('conditional_start_time')
        row['status'] = 'ready_candidate'
        row['candidateFile'] = out.relative_to(root).as_posix()
        row['_candidate'] = {
            'format': 'genshin-v1-candidate-zh-CN-v1', 'game': 'genshin', 'locale': 'zh-CN',
            'status': 'ready_candidate', 'postId': pid, 'sourceKey': key, 'version': row['version'], 'phase': row['phase'],
            'bannerName': notice['bannerName'], 'poolType': notice['poolType'],
            'variant': notice.get('variant'), 'existingV1Id': row['existingV1Id'],
            'v1Draft': draft_data,
            'timeEvidence': {'versionMaintenanceStartAt': upd['data']['maintenance']['startAt'],
                             'previewEndAt': preview['time']['endAt'],
                             'ocrEndAt': ocr_time.get('endAt') if ocr_ok else None,
                             'ocrStatus': ocr.get('status'),
                             'endTimeSource': row['endTimeEvidence'],
                             'manualFile': source.get('manualFile'),
                             'ocrImageSha256': ocr_time.get('imageSha256') if ocr_ok else None,
                             'startRaw': notice_time.get('startRaw'),
                             'endRaw': notice_time.get('endRaw'),
                             'startCondition': notice_time.get('startCondition'),
                             'exclusiveEndPolicy': '原公告分钟结束时间 + 1 分钟；仅候选转换'},
            'provenance': {'versionUpdateFile': row['versionUpdateFile'], 'versionUpdatePostId': upd['data']['source'].get('postId'),
                           'previewFile': row['previewFile'], 'previewPostId': preview['source'].get('postId'),
                           'noticeFile': row['noticeFile'], 'noticePostId': pid, 'noticeSourceKey': key},
            'warnings': list(row['warnings']),
            'manualAudit': {'filled': row['manualFilled'], 'matched': row['manualMatched'],
                            'file': row['manualFile'], 'sources': row.get('manualAudits', [])},
            'note': '离线候选；不自动确定版本更新后的精确开池时间，不自动分配内部 ID，不修改正式 v1'}
        completed[(row['version'], row['phase'], notice.get('poolType'), notice.get('variant'))].append(len(rows) - 1)
    for indexes in completed.values():
        if len(indexes) > 1:
            for i in indexes:
                rows[i]['status'] = 'conflict'
                rows[i]['issues'].append('duplicate_pool_slot')
    for row in rows:
        data = row.pop('_candidate', None)
        pid = row.get('postId')
        out = root / OUTPUT / f'v1-candidate_zh-CN_{row.get("sourceKey")}.json' if row.get('sourceKey') else None
        if not write or out is None:
            continue
        if row['status'] == 'ready_candidate' and data:
            save(out, data)
        elif out.exists():
            # 仅清理由本工具生成且不再满足门槛的同 ID 候选，防止陈旧产物被误用。
            try:
                if read(out).get('format') == 'genshin-v1-candidate-zh-CN-v1':
                    out.unlink()
            except (ValueError, OSError):
                pass
    # 若原始祈愿公告已删除，其旧候选不能继续被导入器视为有效输入。
    # 只清理由本工具生成、且已不在本次公告索引内的候选，不碰其他文件。
    if write and post_id is None:
        current_posts = {row['sourceKey'] for row in rows if row.get('sourceKey')}
        for old in sorted((root / OUTPUT).glob('v1-candidate_zh-CN_*.json')):
            old_id = old.stem.removeprefix('v1-candidate_zh-CN_')
            if old_id not in current_posts:
                if read(old).get('format') == 'genshin-v1-candidate-zh-CN-v1':
                    old.unlink()
    statuses = dict(sorted(Counter(row['status'] for row in rows).items()))
    report = {'format': 'genshin-v1-readiness-zh-CN-v1', 'game': 'genshin', 'locale': 'zh-CN',
              'policy': '按公告逐池匹配；关键人工差异阻断；普通差异在最终报告通知，不阻断发布',
              'counts': {'versionUpdateFiles': len(updates), 'previewFiles': len(previews),
                         'noticeFiles': len(notices), 'evaluatedNotices': len(rows), 'statuses': statuses},
              'sourceErrors': [{'file': entry['path'], 'error': entry['error'],
                                'postId': entry.get('postId'), 'sourceKey': entry.get('sourceKey')}
                               for entry in updates + previews + notices if 'error' in entry],
              'manualComparisons': [
                  {'postId': (entry.get('data') or {}).get('source', {}).get('postId'),
                   'sourceKey': entry.get('manualSourceKey') or entry.get('sourceKey'),
                   'identity': entry.get('manualIdentity'),
                   'evidence': entry.get('manualEvidence'),
                   'kind': kind, 'file': entry.get('evidenceFile', entry['path']), 'manualFile': entry.get('manualFile'),
                   'fallback': bool(entry.get('fallback')),
                   'differences': entry.get('differences', []),
                   'blockingDifferences': entry.get('blockingDifferences', []),
                   'warningDifferences': entry.get('warningDifferences', []),
                   'filled': entry.get('filled', []), 'matched': entry.get('matched', [])}
                  for kind, group in (('version_update', updates), ('wish_preview', previews),
                                      ('wish_notice', notices))
                  for entry in group if entry.get('manualFile')
              ],
              'notices': rows}
    if write:
        save(root / REPORT, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='仓库根目录')
    parser.add_argument('--post-id', help='只检查一篇祈愿公告')
    parser.add_argument('--check-only', action='store_true', help='只打印检查结果，不写文件')
    parser.add_argument('--strict', action='store_true', help='发现冲突时返回非零状态；正常等待不会失败')
    args = parser.parse_args(argv)
    if args.post_id and not re.fullmatch(r'\d+', args.post_id):
        parser.error('--post-id 必须是数字')
    result = assemble(args.root.resolve(), args.post_id, not args.check_only)
    print(json.dumps(result['counts'], ensure_ascii=False, indent=2))
    for row in result['notices']:
        if row['status'] != 'ready_candidate':
            print(f"{row['postId']}: {row['status']}: {', '.join(row['issues'])}")
    return 1 if args.strict and (result['sourceErrors'] or any(r['status'] == 'conflict' for r in result['notices'])) else 0


if __name__ == '__main__':
    raise SystemExit(main())
