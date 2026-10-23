"""近五个版本十篇米游社真实预告的离线回归测试。"""
import json
import unittest
from pathlib import Path
from scripts.transform.build_genshin_wish_preview_zh_cn import build, ACCOUNT_ARCHIVE, ROOT

# 预期值人工核对自官方账号历史归档的 raw_list_entry.post.structured_content。
# 元组：版本、期数、postId、开始时间/日期、结束时间、五星角色、五星武器、四星武器。
CASES = [["7.1",1,"78324485","2026-09-23","2026-10-13T17:59:00+08:00",["薇斯纳","沃雅妮莎"],["蝶变","漩流颂歌"],[]],["7.1",2,"78879329","2026-10-13T18:00:00+08:00","2026-11-03T14:59:00+08:00",["丝柯克","爱可菲"],["苍耀","香韵奏者"],[]],["7.0",1,"77350703","2026-08-12","2026-09-01T17:59:00+08:00",["奥黛塔","阿蕾奇诺"],["白湖冬羽","赤月之形"],[]],["7.0",2,"77910704","2026-09-01T18:00:00+08:00","2026-09-22T14:59:00+08:00",["菲林斯","伊涅芙"],["血染荒城","支离轮光"],[]],["月之八",1,"76328614","2026-07-01","2026-07-21T17:59:00+08:00",["桑多涅","茜特菈莉"],["超越之匙","祭星者之望"],["西风剑","祭礼弓"]],["月之八",2,"76834102","2026-07-21T18:00:00+08:00","2026-08-11T14:59:00+08:00",["哥伦比娅","雷电将军"],["帷间夜曲","薙草之稻光"],["祭礼剑","西风猎弓"]],["月之七",1,"75425444","2026-05-20","2026-06-09T17:59:00+08:00",["尼可","杜林"],["尘光七谕","黑蚀"],["织月者的曙色","幽夜华尔兹"]],["月之七",2,"75880451","2026-06-09T18:00:00+08:00","2026-06-30T14:59:00+08:00",["洛恩","玛薇卡"],["灾悔","焚曜千阳"],["暗巷闪光","暗巷的酒与诗","暗巷猎手"]],["月之六",1,"74418358","2026-04-08","2026-04-28T17:59:00+08:00",["莉奈娅","恰斯卡"],["霜结的誓金枝","星鹫赤羽"],[]],["月之六",2,"74965073","2026-04-28T18:00:00+08:00","2026-05-19T14:59:00+08:00",["菈乌玛","奈芙尔"],["纺夜天镜","真语秘匣"],[]]]

class RealWishPreviewTest(unittest.TestCase):
    def test_ten_official_archived_posts(self):
        missing = [post_id for _, _, post_id, *_ in CASES
                   if not (ACCOUNT_ARCHIVE / f'{post_id}.json').is_file()]
        if missing:
            self.skipTest(f'历史归档样本未包含在检出数据中：{len(missing)} 篇；保留断言待样本恢复')
        for version, phase, post_id, start, end, characters, weapons, four_weapons in CASES:
            with self.subTest(version=version, phase=phase, post_id=post_id):
                source = ACCOUNT_ARCHIVE / f"{post_id}.json"
                raw = json.loads(source.read_text(encoding="utf-8"))
                actual = build(raw, post_id=post_id,
                               source_file=source.relative_to(ROOT).as_posix())
                self.assertEqual((actual["version"], actual["phase"]), (version, phase))
                self.assertEqual(actual["source"]["postId"], post_id)
                self.assertEqual(actual["time"]["endAt"], end)
                if phase == 1:
                    self.assertEqual(actual["time"]["startRaw"][:10], start.replace("-", "/"))
                    self.assertEqual(actual["time"]["startCondition"], "after_version_update")
                    self.assertIsNone(actual["time"]["startAt"])
                else:
                    self.assertEqual(actual["time"]["startAt"], start)
                for field, names in (("fiveStarCharacters", characters),
                                     ("fiveStarWeapons", weapons),
                                     ("fourStarWeapons", four_weapons)):
                    self.assertEqual([item["name"] for item in actual["up"][field]], names)
                self.assertEqual(actual["up"]["fourStarCharacters"], [])
                self.assertFalse(actual["review"]["warnings"])

if __name__ == "__main__":
    unittest.main()
