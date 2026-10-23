"""原神版本公告转换回归测试。"""
import unittest
from scripts.transform.build_genshin_version_update_zh_cn import build, output_filename

HTML = """<p>〓补偿范围〓</p><p>2026/09/26 06:00</p>
<p>〓更新时间〓</p><p>2026/09/23 06:00开始，预计5个小时完成。</p>
<p>〓本次更新内容〓</p>
<p>一、全新角色</p>
<div class="ql-fold"><p>「雪宴之锋·薇斯纳(风)」（★5）</p><p>◇武器：单手剑</p></div>
<p>二、全新装备</p><p>1. 限定武器</p>
<div class="ql-fold"><p>「单手剑·蝶变」（★5）</p></div>
<p>2. 活动武器</p><p>「单手剑·银釭」（★4）</p>
<p>三、全新剧情</p><p>「错误角色·误判(火)」（★5）</p>
<p>〓问题修复〓</p><p>2026/10/16 06:00</p>"""

def sample():
    return {"retcode": 0, "data": {"post": {"post": {
        "post_id": "78335167", "game_id": 2,
        "subject": "「往冥府的安魂歌」7.1版本更新说明",
        "content": HTML,
        "structured_content": '[{"insert":"一、全新角色\\n二、全新装备\\n"}]',
        "created_at": 1790118018, "updated_at": 1791744736
    }}}}

class VersionUpdateTest(unittest.TestCase):
    def test_output_filename_marks_notice_type_and_locale(self):
        self.assertEqual(output_filename("7.1"), "version-update_zh-CN_7.1.json")
        self.assertEqual(output_filename("月之八"), "version-update_zh-CN_月之八.json")

    def test_folded_html_and_scope(self):
        result = build(sample(), post_id="78335167", source_file="posts/78335167.json")
        self.assertEqual(result["version"], "7.1")
        self.assertEqual(result["maintenance"]["startAt"], "2026-09-23T06:00:00+08:00")
        self.assertEqual(result["maintenance"]["estimatedEndAt"], "2026-09-23T11:00:00+08:00")
        self.assertEqual([x["name"] for x in result["newCharacters"]], ["薇斯纳"])
        self.assertEqual([x["acquisition"] for x in result["newWeapons"]], ["wish", "event"])
        self.assertEqual(result["review"]["warnings"], [])

    def test_reject_unrelated_notice(self):
        data = sample()
        data["data"]["post"]["post"]["subject"] = "7.1版本更新维护预告"
        with self.assertRaises(ValueError):
            build(data, post_id="78335167", source_file="posts/78335167.json")

    def test_missing_html_is_error(self):
        data = sample()
        data["data"]["post"]["post"]["content"] = ""
        with self.assertRaises(ValueError):
            build(data, post_id="78335167", source_file="posts/78335167.json")

    def test_missing_sections_warns(self):
        data = sample()
        data["data"]["post"]["post"]["content"] = "<p>〓更新时间〓</p><p>2026/09/23 06:00开始。</p>"
        result = build(data, post_id="78335167", source_file="posts/78335167.json")
        self.assertTrue(result["review"]["warnings"])
        self.assertEqual(result["newWeapons"], [])

if __name__ == "__main__":
    unittest.main()
