"""1.3 新界面的英文插值必须保留参数，词典不能被重复键静默覆盖。"""
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseI18nTest(unittest.TestCase):
    def test_english_dictionary_has_no_duplicate_keys(self):
        pairs = json.loads((ROOT / "easyread/web/i18n/en.json").read_text(encoding="utf-8"), object_pairs_hook=list)
        keys = [key for key, _ in pairs]
        self.assertEqual(len(keys), len(set(keys)))

    def test_new_feature_translations_preserve_named_parameters(self):
        en = json.loads((ROOT / "easyread/web/i18n/en.json").read_text(encoding="utf-8"))
        sources = ["common/page-cap.js", "library/settings-cloud.js", "library/cite-export.js", "common/cite.js"]
        for source in sources:
            code = (ROOT / "easyread/web/js" / source).read_text(encoding="utf-8")
            for key in re.findall(r'PR\.t\("([^"\n]+)"', code):
                with self.subTest(source=source, key=key):
                    self.assertTrue(en.get(key))
                    self.assertEqual(set(re.findall(r"\{\w+\}", key)), set(re.findall(r"\{\w+\}", en[key])))
                    self.assertIsNone(re.search("[一-鿿]", en[key]))
