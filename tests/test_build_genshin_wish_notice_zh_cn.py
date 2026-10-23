"""单篇米游社正式祈愿公告提取测试，禁止网络访问。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.transform.build_genshin_wish_notice_zh_cn import build, load_or_fetch, main

BODY = '''
<div class="ql-image"><img src="https://upload-bbs.miyoushe.com/first.png"></div>
<p>活动期间，旅行者可以在活动祈愿中获得更多角色与武器。</p>
<p>〓祈愿介绍〓</p>
<div class="ql-image"><img src="https://upload-bbs.miyoushe.com/second.png"></div>
<p>●活动期间，限定5星角色「明绚千韵·爱可菲(冰)」的祈愿获取概率将大幅提升！</p>
<p>●活动期间，4星角色「颂礼祝祭·塔利雅(水)」「浮金的誓愿·坎蒂丝(水)」「晴霜的标绘·米卡(冰)」的祈愿获取概率将大幅提升！</p>
<p>※ 以上角色中，限定角色不会进入「奔行世间」常驻祈愿。</p>
<p>※ 本祈愿属于「角色活动祈愿-2」，「角色活动祈愿」和「角色活动祈愿-2」的祈愿次数保底完全共享。</p>
<p>※ 祈愿开启期间，还将开启相应的「且试身手」角色试用活动。</p>
'''

def sample(content=BODY, pid='78782590'):
    return {"retcode":0, "data":{"post":{"post":{
        "game_id":2, "post_id":pid,
        "subject":"「莓色香颂」祈愿：「明绚千韵·爱可菲(冰)」概率UP！",
        "content":content, "created_at":1791446413, "updated_at":1791950607,
        "images":["https://upload-bbs.miyoushe.com/first.png", "https://upload-bbs.miyoushe.com/second.png"],
        "post_status":{"is_official":True}
    }}}}

class WishNoticeTest(unittest.TestCase):
    def test_real_notice_shape(self):
        d=build(sample(), post_id="78782590", source_file="posts/78782590.json")
        self.assertEqual(d["bannerName"], "莓色香颂")
        self.assertEqual(d["officialWishType"], "角色活动祈愿-2")
        self.assertEqual(d["poolType"], "character_event_2")
        self.assertEqual([x["name"] for x in d["up"]["fiveStarCharacters"]], ["爱可菲"])
        self.assertEqual([x["name"] for x in d["up"]["fourStarCharacters"]], ["塔利雅","坎蒂丝","米卡"])
        self.assertEqual([x["element"] for x in d["up"]["fourStarCharacters"]], ["水","水","冰"])
        self.assertEqual(d["up"]["fiveStarCharacters"][0]["limited"], True)
        self.assertEqual(d["rules"], {"limitedNotInStandard":True,"characterEventPityShared":True,"characterTrial":True})
        self.assertEqual(len(d["imageUrls"]),2)
        self.assertIsNone(d["version"])
        self.assertIsNone(d["phase"])
        self.assertIsNone(d["time"]["endAt"])
        self.assertTrue(any("配图" in x for x in d["review"]["warnings"]))

    def test_only_explicit_up_not_explanatory_mentions(self):
        d=build(sample(),post_id="78782590",source_file="test.json")
        self.assertEqual(len(d["up"]["fiveStarCharacters"]),1)
        self.assertEqual(d["up"]["fiveStarWeapons"],[])

    def test_reject_wrong_post_and_preview(self):
        with self.assertRaises(ValueError):
            build(sample(),post_id="123",source_file="test.json")
        data=sample()
        data["data"]["post"]["post"]["subject"]="7.1版本活动祈愿预告第二期"
        with self.assertRaises(ValueError):
            build(data,post_id="78782590",source_file="test.json")
        data=sample()
        data["data"]["post"]["post"]["game_id"]=3
        with self.assertRaises(ValueError):
            build(data,post_id="78782590",source_file="test.json")

    def test_explicit_time_only_and_delta_fallback(self):
        data=sample(content='<p>祈愿时间：2026/10/13 18:00 ~ 2026/11/03 14:59。</p>'+BODY)
        d=build(data,post_id="78782590",source_file="test.json")
        self.assertEqual(d["time"]["startAt"],"2026-10-13T18:00:00+08:00")
        self.assertEqual(d["time"]["endAt"],"2026-11-03T14:59:00+08:00")
        data=sample(content="")
        data["data"]["post"]["post"]["structured_content"]=json.dumps([
            {"insert":"●活动期间，限定5星角色「明绚千韵·爱可菲(冰)」的祈愿获取概率将大幅提升！\n"},
            {"insert":"※ 本祈愿属于「角色活动祈愿-2」"}
        ],ensure_ascii=False)
        d=build(data,post_id="78782590",source_file="test.json")
        self.assertEqual(d["source"]["textSource"],"structured_content")
        self.assertEqual(len(d["up"]["fiveStarCharacters"]),1)

    def test_weapon_notice_mixed_limited_and_standard_fourstars(self):
        p = sample()
        post = p["data"]["post"]["post"]
        post["subject"] = "「神铸赋形」：「单手剑·苍耀」「长柄武器·香韵奏者」概率UP"
        post["content"] = """
        <p>活动期间，旅行者可以在「神铸赋形」活动祈愿中获得更多武器与角色。</p>
        <p>●活动期间，限定5星武器「单手剑·苍耀」「长柄武器·香韵奏者」的祈愿获取概率将大幅提升！</p>
        <p>●活动期间，限定4星武器「单手剑·弥坚骨」、4星武器「双手剑·祭礼大剑」「长柄武器·西风长枪」「法器·流浪乐章」「弓·祭礼弓」的祈愿获取概率将大幅提升！</p>
        """
        d = build(p, post_id="78782590", source_file="test.json")
        self.assertEqual(d["bannerName"], "神铸赋形")
        self.assertEqual(d["poolType"], "weapon_event")
        self.assertEqual([x["name"] for x in d["up"]["fiveStarWeapons"]],
                         ["苍耀", "香韵奏者"])
        self.assertEqual([x["name"] for x in d["up"]["fourStarWeapons"]],
                         ["弥坚骨", "祭礼大剑", "西风长枪", "流浪乐章", "祭礼弓"])
        self.assertTrue(d["up"]["fourStarWeapons"][0]["limited"])
        self.assertIsNone(d["up"]["fourStarWeapons"][1]["limited"])

    def test_weapon_no_banner_name_in_title(self):
        p = sample()
        post = p["data"]["post"]["post"]
        post["subject"] = "祈愿：「长柄武器·血染荒城」「长柄武器·支离轮光」概率UP！"
        post["content"] = """
        <p>活动期间，旅行者可以在「神铸赋形」活动祈愿中获得更多武器与角色。</p>
        <p>●活动期间，限定5星武器「长柄武器·血染荒城」「长柄武器·支离轮光」的祈愿获取概率将大幅提升！</p>
        <p>●活动期间，4星武器「单手剑·笛剑」「双手剑·西风大剑」「长柄武器·西风长枪」「法器·昭心」「弓·绝弦」的祈愿获取概率将大幅提升！</p>
        """
        d = build(p, post_id="78782590", source_file="test.json")
        self.assertEqual(d["bannerName"], "神铸赋形")
        self.assertEqual(d["poolType"], "weapon_event")
        self.assertEqual(len(d["up"]["fourStarWeapons"]), 5)

    def test_special_recollection_only_selectable_not_up(self):
        p = sample()
        post = p["data"]["post"]["post"]
        post["subject"] = "「辉天的星告」祈愿：溯光祈愿开启！"
        post["content"] = """
        <p>●本期溯光祈愿的所有5星物品及4星物品范围：</p>
        <p>5星角色：梦见月瑞希/莱欧斯利/赛诺/八重神子/七七</p>
        <p>5星武器：寝正月初晴/金流监督/赤沙之杖/神乐之真意/天空之刃</p>
        <p>4星角色：布伦妮/叶洛亚/雅珂达</p>
        <p>4星武器：弓藏/祭礼弓/绝弦</p>
        <p>※ 本祈愿属于「溯光祈愿」，「集录祈愿」与「溯光祈愿」的祈愿次数保底完全共享。</p>
        """
        d = build(p, post_id="78782590", source_file="test.json")
        self.assertEqual(d["poolType"], "chronicled")
        self.assertEqual(d["variant"], "special_recollection")
        self.assertEqual(d["selectable"]["fiveStarCharacters"],
                         ["梦见月瑞希", "莱欧斯利", "赛诺", "八重神子", "七七"])
        self.assertEqual(d["up"]["fiveStarCharacters"], [])

    def test_reject_non_banner_activity_with_wish_in_text(self):
        p = sample()
        p["data"]["post"]["post"]["subject"] = (
            "「巡历雪境，凝铸锋锐」：自选邀请「奔行世间」常驻祈愿5星角色")
        with self.assertRaises(ValueError):
            build(p, post_id="78782590", source_file="test.json")

    def test_cache_and_one_post_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            archive=Path(td)/'posts'
            with patch('scripts.transform.build_genshin_wish_notice_zh_cn.ARCHIVE',archive):
                with patch('scripts.collect.collect_miyoushe_announcements.fetch',return_value=sample()) as f:
                    data,p=load_or_fetch('78782590')
                    f.assert_called_once_with('https://bbs-api.miyoushe.com/post/wapi/getPostFull',
                                              {'post_id':'78782590','gids':2})
                    self.assertTrue(p.is_file())
                    data2,_=load_or_fetch('78782590',offline=True)
                    self.assertEqual(data,data2)
                    with self.assertRaises(FileNotFoundError):
                        load_or_fetch('123',offline=True)

    def test_image_ocr_time_in_temporary_directory(self):
        from scripts.transform import recognize_genshin_wish_image_zh_cn as ocr
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            data = sample()
            urls = data["data"]["post"]["post"]["images"]
            for i, url in enumerate(urls, 1):
                payload = b"image content " + str(i).encode()
                (folder / f"image_zh-CN_78782590_{i:02d}.png").write_bytes(payload)
            records = []
            for i, url in enumerate(urls, 1):
                payload = (folder / f"image_zh-CN_78782590_{i:02d}.png").read_bytes()
                records.append({"url": url, "file": f"image_zh-CN_78782590_{i:02d}.png",
                                "bytes": len(payload), "sha256": sha256(payload).hexdigest()})
            (folder / "images_zh-CN_78782590.json").write_text(json.dumps({
                "format": "genshin-notice-images-v1", "game": "genshin",
                "locale": "zh-CN", "postId": "78782590", "sourceUrls": urls,
                "complete": True, "images": records
            }), encoding="utf-8")
            times = "祈愿时间\n2026/10/13 18:00\n~\n2026/11/03 14:59"
            with patch.object(ocr, "tesseract_text", side_effect=lambda image, psm: times if image.name.endswith("02.png") else ""):
                result = ocr.recognize_time(folder, "78782590", urls)
            self.assertEqual(result["status"], "recognized")
            self.assertEqual(result["times"]["startAt"], "2026-10-13T18:00:00+08:00")
            self.assertEqual(result["times"]["endAt"], "2026-11-03T14:59:00+08:00")
            with patch.object(ocr, "tesseract_text", return_value="2026/10/13 18:00"):
                unresolved = ocr.recognize_time(folder, "78782590", urls)
            self.assertIsNone(unresolved["times"])

    def test_cli_output_post_id_only(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            raw=folder/'raw.json'
            raw.write_text(json.dumps(sample(),ensure_ascii=False),encoding='utf-8')
            with patch('scripts.transform.build_genshin_wish_notice_zh_cn.OUTPUT', folder):
                self.assertEqual(main(['--post-id','78782590','--input',str(raw)]),0)
            out=json.loads((folder/'wish-notice_zh-CN_78782590.json').read_text(encoding='utf-8'))
            self.assertEqual(out['bannerName'],'莓色香颂')
            self.assertEqual(out['noticeType'], 'wish_notice')
            self.assertEqual(out['locale'], 'zh-CN')

if __name__ == '__main__':
    unittest.main()
