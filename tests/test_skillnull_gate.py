from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
	Path(__file__).resolve().parents[1] / "scripts" / "skillnull_gate.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("skillnull_gate", SCRIPT_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
skillnull_gate = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(skillnull_gate)


class SkillnullGateTest(unittest.TestCase):
	def setUp(self) -> None:
		self.temporary_directory = tempfile.TemporaryDirectory()
		self.repo_root = Path(self.temporary_directory.name)
		subprocess.run(["git", "init", "-q", str(self.repo_root)], check=True)
		(self.repo_root / "src").mkdir()

	def tearDown(self) -> None:
		self.temporary_directory.cleanup()

	def write_source(self, relative_path: str, content: str) -> Path:
		target = self.repo_root / relative_path
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_text(content, encoding="utf-8")
		return target

	def test_blocks_patch_that_empties_source_file(self) -> None:
		self.write_source("src/hooks.ts", "export const useQuery = () => 1;\n")
		patch_text = """*** Begin Patch
*** Update File: src/hooks.ts
@@
-export const useQuery = () => 1;
*** End Patch
"""
		reason, touched = skillnull_gate.check_patch(
			self.repo_root, patch_text, "修复页面"
		)
		self.assertIn("清空源码", reason)
		self.assertEqual(touched, ["src/hooks.ts"])

	def test_allows_small_scoped_edit(self) -> None:
		self.write_source("src/value.ts", "export const value = 1;\n")
		patch_text = """*** Begin Patch
*** Update File: src/value.ts
@@
-export const value = 1;
+export const value = 2;
*** End Patch
"""
		reason, touched = skillnull_gate.check_patch(
			self.repo_root, patch_text, "更新数值"
		)
		self.assertIsNone(reason)
		self.assertEqual(touched, ["src/value.ts"])

	def test_blocks_deleting_referenced_source(self) -> None:
		self.write_source("src/hooks.ts", "export const useQuery = () => 1;\n")
		self.write_source(
			"src/page.ts", 'import { useQuery } from "./hooks";\nuseQuery();\n'
		)
		patch_text = """*** Begin Patch
*** Delete File: src/hooks.ts
*** End Patch
"""
		reason, _touched = skillnull_gate.check_patch(
			self.repo_root, patch_text, "删除旧 hooks"
		)
		self.assertIn("仍被引用", reason)

	def test_blocks_removing_import_that_is_still_used(self) -> None:
		self.write_source(
			"src/page.ts",
			'import { useQuery } from "./hooks";\nexport const value = useQuery();\n',
		)
		patch_text = """*** Begin Patch
*** Update File: src/page.ts
@@
-import { useQuery } from "./hooks";
*** End Patch
"""
		reason, _touched = skillnull_gate.check_patch(
			self.repo_root, patch_text, "修改页面"
		)
		self.assertIn("删除 import 后仍使用 useQuery", reason)

	def test_allows_removing_import_and_its_only_usage(self) -> None:
		self.write_source(
			"src/page.ts",
			'import { useQuery } from "./hooks";\nexport const value = useQuery();\n',
		)
		patch_text = """*** Begin Patch
*** Update File: src/page.ts
@@
-import { useQuery } from "./hooks";
-export const value = useQuery();
+export const value = 1;
*** End Patch
"""
		reason, _touched = skillnull_gate.check_patch(
			self.repo_root, patch_text, "替换查询逻辑"
		)
		self.assertIsNone(reason)

	def test_stop_blocks_new_empty_touched_source(self) -> None:
		target = self.write_source("src/empty.ts", "")
		state = {
			"baseline_diff_check": [],
			"baseline_zero_sources": [],
			"touched_files": [str(target.relative_to(self.repo_root))],
		}
		failures = skillnull_gate.current_gate_failures(self.repo_root, state)
		self.assertIn("源码被清空：src/empty.ts", failures)

	def test_detects_empty_source_created_outside_apply_patch(self) -> None:
		self.write_source("src/empty.ts", "")
		failures = skillnull_gate.current_gate_failures(
			self.repo_root,
			{
				"baseline_diff_check": [],
				"baseline_zero_sources": [],
				"touched_files": [],
			},
		)
		self.assertEqual(failures, ["源码被清空：src/empty.ts"])

	def test_hook_output_is_valid_json(self) -> None:
		payload = json.dumps(
			{
				"hook_event_name": "UserPromptSubmit",
				"session_id": "test-session",
				"cwd": str(self.repo_root),
				"prompt": "修改代码",
			}
		)
		result = subprocess.run(
			["python3", str(SCRIPT_PATH)],
			input=payload,
			capture_output=True,
			text=True,
			check=True,
		)
		output = json.loads(result.stdout)
		self.assertEqual(
			output["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
		)
		self.assertIn(
			"SKILLNULL — 编写与迭代守则",
			output["hookSpecificOutput"]["additionalContext"],
		)


if __name__ == "__main__":
	unittest.main()
