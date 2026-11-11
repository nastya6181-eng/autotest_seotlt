"""Настройки всех сайтов в sites/ соответствуют схемам checks/core/schemas/ — опечатка видна на PR, а не после прогона."""
import glob
import json
import os
import unittest

import yaml
from jsonschema import Draft202012Validator

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCHEMAS = os.path.join(ROOT, "checks", "core", "schemas")
FILES = {  # файл настроек сайта → схема
    "content/project.yml": "content-project",
    "design/pages.yml": "design-pages",
    "frontend/scenarios.yml": "frontend-scenarios",
    "backend/endpoints.yml": "backend-endpoints",
    "integrations/integrations.yml": "integrations",
}


def validator(name):
    with open(os.path.join(SCHEMAS, f"{name}.schema.json"), encoding="utf-8") as f:
        return Draft202012Validator(json.load(f))


def errors(path, name):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    return [f"{'/'.join(map(str, e.path)) or '(корень)'}: {e.message}" for e in validator(name).iter_errors(data)]


class SiteConfigsTest(unittest.TestCase):
    def test_all_site_configs_match_schemas(self):
        checked = 0
        for rel, name in FILES.items():
            for path in sorted(glob.glob(os.path.join(ROOT, "sites", "*", rel))):
                with self.subTest(path=os.path.relpath(path, ROOT)):
                    self.assertEqual(errors(path, name), [])
                    checked += 1
        self.assertGreater(checked, 5)

    def test_schemas_catch_typos(self):
        v = validator("design-pages")
        self.assertTrue(list(v.iter_errors([{"page": "/", "design": "main.json", "tolerence": 10}])))  # опечатка в ключе
        self.assertTrue(list(v.iter_errors([{"page": "//evil.ru/", "design": "main.json"}])))
        v = validator("content-project")
        self.assertTrue(list(v.iter_errors({"severity": {"links.redirect": "of"}})))
        self.assertFalse(list(v.iter_errors({"severity": {"links.redirect": "off"}, "max_pages": 300})))


if __name__ == "__main__":
    unittest.main()
