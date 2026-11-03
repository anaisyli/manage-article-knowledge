"""SKFB-019: 30/35 carry the same outline identity as 10, in recovery, rewrite and the writing gate."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recover_article_package as recovery  # noqa: E402
from template_contract import parse_field, validate_task_templates  # noqa: E402
from writing_bridge import upsert_field  # noqa: E402

MATERIAL = "30_本篇知识库资料.md"
INDEX = "35_写作素材来源索引.md"
IDENTITY = {"大纲ID": "OUT-1", "大纲版本": "v1", "重写模式": "same_outline"}


def request(identity=IDENTITY) -> str:
    return ("# 文章知识需求\n\n- 文章ID：ART-001\n- 当前版本：v2\n- 任务模式：outline_refresh\n"
            + "".join(f"- {label}：{value}\n" for label, value in identity.items()))


def identity_errors(errors: list[str]) -> list[str]:
    return [error for error in errors if error.startswith((MATERIAL, INDEX)) and "必须与10一致" in error]


class WritingGateIdentityTests(unittest.TestCase):
    def make_task(self, root: Path, material_identity: dict, index_identity: dict) -> Path:
        task = root / "04_文章任务/10_进行中/ART-001_Test"
        task.mkdir(parents=True)
        (task / "10_文章知识需求.md").write_text(request(), encoding="utf-8")
        for name, identity in ((MATERIAL, material_identity), (INDEX, index_identity)):
            (task / name).write_text(
                f"# 文件\n\n- 文章ID：ART-001\n- 文章版本：v2\n"
                + "".join(f"- {label}：{value}\n" for label, value in identity.items()),
                encoding="utf-8",
            )
        return task

    def test_missing_identity_in_30_and_35_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp), {}, {})
            errors = identity_errors(validate_task_templates(task))
        self.assertEqual(sorted(errors), sorted(
            f"{name}：{label}必须与10一致" for name in (MATERIAL, INDEX) for label in IDENTITY
        ))

    def test_mismatched_identity_is_rejected_and_matching_identity_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp), {**IDENTITY, "大纲版本": "v2"}, IDENTITY)
            self.assertEqual(identity_errors(validate_task_templates(task)), [f"{MATERIAL}：大纲版本必须与10一致"])
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp), IDENTITY, IDENTITY)
            self.assertEqual(identity_errors(validate_task_templates(task)), [])

    def test_reuse_precheck_skips_only_the_30_35_identity_check(self):
        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp), {}, {})
            strict = validate_task_templates(task)
            relaxed = validate_task_templates(task, package_identity=False)
        self.assertEqual(identity_errors(relaxed), [])
        self.assertEqual(sorted(relaxed), sorted(set(strict) - set(identity_errors(strict))))

    def test_reuse_bundle_check_carries_the_same_exemption(self):
        # The bundle check reruns the template check; without the flag every pre-identity task failed reuse.
        from article_state import article_package_errors

        with tempfile.TemporaryDirectory() as temp:
            task = self.make_task(Path(temp), {}, {})
            strict = article_package_errors(task)
            relaxed = article_package_errors(task, package_identity=False)
        self.assertTrue(identity_errors(strict))
        self.assertEqual(identity_errors(relaxed), [])
        self.assertEqual(sorted(relaxed), sorted(set(strict) - set(identity_errors(strict))))


class RecoveryIdentityTests(unittest.TestCase):
    def test_rendered_30_copies_identity_from_10(self):
        claim = SimpleNamespace(title="测试事实", claim_id="CLM-1", identity_context=None, expected_lines=["Fact."])
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / "04_文章任务/10_进行中/ART-001_Test"
            task.mkdir(parents=True)
            (task / "10_文章知识需求.md").write_text(request(), encoding="utf-8")
            with patch.object(recovery, "_mapping_claims", return_value=[claim]):
                material = recovery._render_minimal_material(task, Path(temp), recovery.RecoveryResult())
        self.assertIsNotNone(material)
        for label, value in IDENTITY.items():
            self.assertEqual(parse_field(material, label), value)

    def test_identity_lines_never_invent_values_missing_from_10(self):
        self.assertEqual(recovery._outline_identity_lines(request({})), "")
        self.assertEqual(recovery._outline_identity_lines(request({"大纲ID": "OUT-1"})), "- 大纲ID：OUT-1\n")

    def test_metadata_sync_adds_identity_to_existing_30_and_35(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp)
            (task / "10_文章知识需求.md").write_text(request(), encoding="utf-8")
            for name in (MATERIAL, INDEX):
                (task / name).write_text("# 文件\n\n- 文章ID：ART-001\n- 文章版本：v1\n", encoding="utf-8")
            recovery._sync_metadata(task)
            for name in (MATERIAL, INDEX):
                text = (task / name).read_text(encoding="utf-8")
                with self.subTest(name=name):
                    for label, value in IDENTITY.items():
                        self.assertEqual(parse_field(text, label), value)


    def test_metadata_sync_moves_35_with_the_lines_inserted_into_30(self):
        import hashlib

        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp)
            (task / "10_文章知识需求.md").write_text(request(), encoding="utf-8")
            (task / MATERIAL).write_text("# 文件\n\n- 文章ID：ART-001\n- 文章版本：v1\n\n> 证据正文\n", encoding="utf-8")
            (task / INDEX).write_text(
                "# 文件\n\n- 文章ID：ART-001\n- 文章版本：v1\n- 写作素材SHA-256：old\n\n"
                "## 写作素材到正式知识映射\n\n| 证据正文行开始 | 证据正文行结束 |\n|---:|---:|\n| 6 | 6 |\n",
                encoding="utf-8")
            recovery._sync_metadata(task)
            material = (task / MATERIAL).read_text(encoding="utf-8").splitlines()
            index = (task / INDEX).read_text(encoding="utf-8")
            line = material.index("> 证据正文") + 1
            self.assertGreater(line, 6)  # the inserted header fields pushed the evidence down
            self.assertIn(f"| {line} | {line} |", index)
            self.assertEqual(parse_field(index, "写作素材SHA-256"),
                             hashlib.sha256((task / MATERIAL).read_bytes()).hexdigest())

    def test_metadata_sync_never_rewrites_a_permitted_30(self):
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp)
            (task / "10_文章知识需求.md").write_text(request(), encoding="utf-8")
            (task / "writing_ready.json").write_text("{}", encoding="utf-8")
            for name in (MATERIAL, INDEX):
                (task / name).write_text("# 文件\n\n- 文章ID：ART-001\n- 文章版本：v1\n", encoding="utf-8")
            before = {name: (task / name).read_bytes() for name in (MATERIAL, INDEX)}
            recovery._sync_metadata(task)
            self.assertEqual({name: (task / name).read_bytes() for name in (MATERIAL, INDEX)}, before)


class RewriteIdentityTests(unittest.TestCase):
    def test_revision_staging_is_not_a_second_task(self):
        # The rewrite stages the new version next to the old task; the batch gate must still see one task.
        from sync_website_evidence import current_tasks

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            done = project / "04_文章任务/40_已完成/ART-001_Test"
            staging = project / "04_文章任务/10_进行中/.revision-1a2b3c4d"
            for folder in (done, staging):
                folder.mkdir(parents=True)
                (folder / "10_文章知识需求.md").write_text(request(), encoding="utf-8")
            self.assertEqual(current_tasks(project, include_completed=True), {"ART-001": done})

    def test_remap_follows_inserted_lines_and_refuses_changed_evidence(self):
        from article_state import remap_material_lines

        index = "## 写作素材到正式知识映射\n\n| 开始 | 结束 |\n|---:|---:|\n| 3 | 4 |\n\n## 其他\n\n| 3 | 4 |\n"
        old = "# 文件\n\n> 证据一\n> 证据二\n"
        moved = remap_material_lines(index, old, old.replace("# 文件\n", "# 文件\n- 大纲ID：X\n- 大纲版本：v1\n"))
        self.assertIn("| 5 | 6 |", moved)
        self.assertTrue(moved.endswith("| 3 | 4 |\n"))  # tables outside the mapping section are left alone
        with self.assertRaisesRegex(ValueError, "证据正文已改变"):
            remap_material_lines(index, old, old.replace("证据一", "证据甲"))

    def test_upsert_inserts_missing_field_after_anchor_and_replaces_existing(self):
        text = "# 文件\n\n- 文章ID：ART-001\n- 文章版本：v2\n- 模板版本：T\n"
        inserted = upsert_field(text, "大纲ID", "OUT-1", after="文章版本")
        self.assertEqual(inserted, "# 文件\n\n- 文章ID：ART-001\n- 文章版本：v2\n- 大纲ID：OUT-1\n- 模板版本：T\n")
        self.assertEqual(upsert_field(inserted, "大纲ID", "OUT-2", after="文章版本").count("大纲ID"), 1)
        self.assertIn("- 大纲ID：OUT-2", upsert_field(inserted, "大纲ID", "OUT-2", after="文章版本"))
        with self.assertRaises(ValueError):
            upsert_field("# 文件\n", "大纲ID", "OUT-1", after="文章版本")


if __name__ == "__main__":
    unittest.main()
