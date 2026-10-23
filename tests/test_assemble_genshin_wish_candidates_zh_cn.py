"""简体中文原神单池候选整合回归测试（不联网）。"""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from scripts.transform.assemble_genshin_wish_candidates_zh_cn import assemble, OUTPUT


class AssembleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.end = '2026-11-03T14:59:00+08:00'
        self.start = '2026-10-13T18:00:00+08:00'
        self.ver = {'game': 'genshin', 'locale': 'zh-CN', 'noticeType': 'version_update',
                    'version': '7.1', 'maintenance': {'startAt': '2026-09-23T06:00:00+08:00'},
                    'source': {'postId': '101', 'url': 'https://example.com/101'}}
        self.pv = {'game': 'genshin', 'locale': 'zh-CN', 'noticeType': 'wish_preview',
                   'version': '7.1', 'phase': 2,
                   'time': {'startAt': self.start, 'endAt': self.end},
                   'up': {'fiveStarCharacters': [{'name': '甲'}, {'name': '乙'}],
                          'fiveStarWeapons': [{'name': '丙'}, {'name': '丁'}]},
                   'source': {'postId': '102', 'url': 'https://example.com/102'}}
        self.no = {'game': 'genshin', 'locale': 'zh-CN', 'noticeType': 'wish_notice',
                   'bannerName': '独立祈愿A', 'poolType': 'character_event', 'variant': None,
                   'up': {'fiveStarCharacters': [{'name': '甲'}],
                          'fourStarCharacters': [{'name': '戊'}, {'name': '己'}, {'name': '庚'}],
                          'fiveStarWeapons': [], 'fourStarWeapons': []},
                   'selectable': None,
                   'time': {'startAt': self.start, 'endAt': self.end, 'startCondition': None},
                   'imageTimeRecognition': {'status': 'recognized',
                                            'times': {'startAt': self.start, 'endAt': self.end}},
                   'source': {'postId': '103', 'url': 'https://example.com/103'},
                   'review': {'warnings': []}}
        self.store('version-updates/version-update_zh-CN_7.1.json', self.ver)
        self.store('wish-previews/wish-preview_zh-CN_7.1-phase-2.json', self.pv)
        self.store('wish-notices/wish-notice_zh-CN_103.json', self.no)
        self.write('public/item-mappings/genshin/zh-CN.json',
                   {x: i + 100 for i, x in enumerate('甲乙丙丁戊己庚')})

    def write(self, p, data):
        file = self.root / p
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return file

    def store(self, p, data):
        return self.write('data/derived/genshin/' + p, data)

    def check(self, write=False):
        return assemble(self.root, write=write)['notices'][0]

    def test_one_notice_ready_even_without_other_banners(self):
        r = self.check(write=True)
        self.assertEqual(r['status'], 'ready_candidate')
        self.assertEqual((r['version'], r['phase']), ('7.1', 2))
        draft = json.loads((self.root / OUTPUT / 'v1-candidate_zh-CN_103.json').read_text())
        self.assertEqual(draft['v1Draft']['category'], 'character')
        self.assertEqual(draft['v1Draft']['featured']['fiveStar'][0]['itemId'], '100')
        self.assertEqual(draft['v1Draft']['regions'][0]['endAt'], '2026-11-03T15:00:00+08:00')

    def test_missing_update_preview_ocr_waits(self):
        (self.root / 'data/derived/genshin/version-updates/version-update_zh-CN_7.1.json').unlink()
        self.assertEqual(self.check()['issues'], ['waiting_version_update'])
        self.store('version-updates/version-update_zh-CN_7.1.json', self.ver)
        (self.root / 'data/derived/genshin/wish-previews/wish-preview_zh-CN_7.1-phase-2.json').unlink()
        self.assertEqual(self.check()['issues'], ['unmatched_end_time'])
        self.store('wish-previews/wish-preview_zh-CN_7.1-phase-2.json', self.pv)
        n = deepcopy(self.no)
        n['imageTimeRecognition']['status'] = 'unresolved'
        self.store('wish-notices/wish-notice_zh-CN_103.json', n)
        self.assertEqual(self.check()['issues'], ['waiting_ocr_end_time'])

    def test_reused_character_cannot_override_end_time(self):
        pv = deepcopy(self.pv)
        pv['version'] = '7.2'
        pv['time']['endAt'] = '2026-12-15T17:59:00+08:00'
        self.store('version-updates/version-update_zh-CN_7.2.json', dict(self.ver, version='7.2'))
        self.store('wish-previews/wish-preview_zh-CN_7.2-phase-1.json', pv)
        self.assertEqual(self.check()['version'], '7.1')

    def test_duplicate_end_time_conflicts(self):
        self.store('wish-previews/wish-preview_zh-CN_7.2-phase-1.json',
                   dict(self.pv, version='7.2'))
        self.assertEqual(self.check()['issues'], ['ambiguous_end_time'])

    def test_five_star_mismatch_detected_after_time_match(self):
        n = deepcopy(self.no)
        n['up']['fiveStarCharacters'] = [{'name': '不在预告中的角色'}]
        self.store('wish-notices/wish-notice_zh-CN_103.json', n)
        r = self.check()
        self.assertEqual((r['version'], r['phase']), ('7.1', 2))
        self.assertEqual(r['issues'], ['five_star_preview_conflict'])

    def test_ocr_and_notice_time_conflict(self):
        n = deepcopy(self.no)
        n['time']['endAt'] = '2026-11-04T14:59:00+08:00'
        self.store('wish-notices/wish-notice_zh-CN_103.json', n)
        self.assertEqual(self.check()['issues'], ['ocr_notice_end_conflict'])

    def test_special_pool_does_not_need_preview_up(self):
        n = deepcopy(self.no)
        n['poolType'], n['variant'] = 'chronicled', 'special_recollection'
        n['up'] = {k: [] for k in n['up']}
        n['selectable'] = {'fiveStarCharacters': ['甲'], 'fiveStarWeapons': ['丙']}
        self.store('wish-notices/wish-notice_zh-CN_103.json', n)
        self.assertEqual(self.check()['status'], 'ready_candidate')

    def test_noncritical_manual_name_difference_does_not_block_candidate(self):
        self.write('manual/notices/genshin/zh-CN/miyoushe/103.json',
                   {'format': 'genshin-notice-manual-v1', 'postId': '103',
                    'data': {'bannerName': '人工祈愿名'}})
        row = self.check(write=True)
        self.assertEqual(row['status'], 'ready_candidate')
        self.assertEqual([d['field'] for d in row['warningDifferences']], ['bannerName'])
        self.assertEqual(row['blockingDifferences'], [])
        self.assertTrue((self.root / OUTPUT / 'v1-candidate_zh-CN_103.json').exists())

    def test_critical_manual_up_difference_blocks_candidate(self):
        self.write('manual/notices/genshin/zh-CN/miyoushe/103.json',
                   {'format': 'genshin-notice-manual-v1', 'postId': '103',
                    'data': {'up': {'fiveStarCharacters': [{'name': '不匹配'}]}}})
        row = self.check(write=True)
        self.assertEqual(row['status'], 'conflict')
        self.assertIn('manual_auto_mismatch', row['issues'])
        self.assertFalse((self.root / OUTPUT / 'v1-candidate_zh-CN_103.json').exists())

    def test_second_pool_can_arrive_later(self):
        n = deepcopy(self.no)
        n['source'] = {'postId': '104', 'url': 'https://example.com/104'}
        n['poolType'] = 'character_event_2'
        n['up']['fiveStarCharacters'] = [{'name': '乙'}]
        self.store('wish-notices/wish-notice_zh-CN_104.json', n)
        self.assertEqual(assemble(self.root, write=False)['counts']['statuses'],
                         {'ready_candidate': 2})

    def test_duplicate_pool_slot_stops_both(self):
        n = deepcopy(self.no)
        n['source'] = {'postId': '104', 'url': 'https://example.com/104'}
        self.store('wish-notices/wish-notice_zh-CN_104.json', n)
        result = assemble(self.root, write=True)
        self.assertEqual(result['counts']['statuses'], {'conflict': 2})
        self.assertFalse((self.root / OUTPUT / 'v1-candidate_zh-CN_103.json').exists())

    def test_missing_item_id_is_warning(self):
        self.write('public/item-mappings/genshin/zh-CN.json', {})
        self.assertIn('missing_item_ids', self.check()['warnings'])

    def test_stale_candidate_is_removed(self):
        self.check(write=True)
        n = deepcopy(self.no)
        n['imageTimeRecognition']['status'] = 'unresolved'
        self.store('wish-notices/wish-notice_zh-CN_103.json', n)
        self.check(write=True)
        self.assertFalse((self.root / OUTPUT / 'v1-candidate_zh-CN_103.json').exists())


class CurrentRepositoryTest(unittest.TestCase):
    def test_current_repository_notices_do_not_crash_assembly(self):
        root = Path(__file__).resolve().parents[1]
        if not (root / 'data/derived/genshin/wish-notices/wish-notice_zh-CN_78782590.json').exists():
            self.skipTest('缺少真实仓库样本')
        r = assemble(root, write=False)
        self.assertGreaterEqual(r['counts']['noticeFiles'], 28)
        self.assertEqual(sum(r['counts']['statuses'].values()), r['counts']['evaluatedNotices'])
        self.assertTrue(any(x['postId'] == '78782590' for x in r['notices']))


if __name__ == '__main__':
    unittest.main()
