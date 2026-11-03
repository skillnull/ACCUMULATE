from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
		self.original_state_root = skillnull_gate.STATE_ROOT
		skillnull_gate.STATE_ROOT = self.repo_root / ".state"
		self.policy_path = self.write_source(
			"policy/SKILL.md", "# SKILLNULL — 编写与迭代守则\n\n1. **要求**：检查当前任务。\n"
		)
		self.local_path = self.policy_path.with_name("SKILL.local.md")
		self.skill_patch = mock.patch.object(skillnull_gate, "SKILL_PATH", self.policy_path)
		self.local_patch = mock.patch.object(skillnull_gate, "LOCAL_SKILL_PATH", self.local_path)
		self.skill_patch.start()
		self.local_patch.start()

	def tearDown(self) -> None:
		self.skill_patch.stop()
		self.local_patch.stop()
		skillnull_gate.STATE_ROOT = self.original_state_root
		self.temporary_directory.cleanup()

	def write_source(self, relative_path: str, content: str) -> Path:
		target = self.repo_root / relative_path
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_text(content, encoding="utf-8")
		return target

	def start_session(self, session_id: str = "dynamic-session") -> dict:
		return skillnull_gate.handle_user_prompt({
			"hook_event_name": "UserPromptSubmit", "session_id": session_id,
			"cwd": str(self.repo_root), "prompt": "维护开发规则执行机制",
		})

	def record_review(self, phase: str, session_id: str = "dynamic-session") -> None:
		bundle = skillnull_gate.load_rule_bundle()
		state = skillnull_gate.load_state(session_id)
		state[phase] = {
			"phase": phase,
			"policy_revision": bundle["revision"],
			"workspace_revision": skillnull_gate.workspace_revision(self.repo_root),
			"entries": [{
				"id": rule["id"], "status": "planned" if phase == "plan" else "verified",
				"reason": "隔离测试的示例审查，验证协议而非声称模型遵循。",
				"evidence": "测试提供的规则源与工作区快照。",
			} for rule in bundle["rules"]],
		}
		state["active"] = True
		skillnull_gate.save_state(session_id, state)

	def stop_session(self, **extra: object) -> dict:
		return skillnull_gate.handle_stop({
			"session_id": "dynamic-session", "cwd": str(self.repo_root), **extra,
		})

	def pre_tool(self, name: str = "apply_patch", text: str = "") -> dict:
		return skillnull_gate.handle_pre_tool({
			"session_id": "dynamic-session", "cwd": str(self.repo_root),
			"tool_name": name, "tool_input": {"command": text},
		})

	def test_future_rule_invalidates_plan_before_edit_without_script_change(self) -> None:
		self.start_session()
		self.record_review("plan")
		with self.policy_path.open("a", encoding="utf-8") as policy_file:
			policy_file.write("2. **未来约束**：交付需核对任意新增条件。\n")
		output = self.pre_tool()
		self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
		self.assertIn("未来约束", output["hookSpecificOutput"]["additionalContext"])
		self.assertIn("旧审查失效", output["hookSpecificOutput"]["permissionDecisionReason"])

	def test_rule_rewrite_and_removal_invalidate_delivery(self) -> None:
		self.start_session()
		self.record_review("plan")
		self.record_review("delivery")
		for replacement in ("1. **要求**：新的限制。\n", "无需编号的最新限制。\n"):
			with self.subTest(replacement=replacement):
				self.policy_path.write_text(replacement, encoding="utf-8")
				self.assertIn("旧审查失效", self.stop_session()["reason"])

	def test_reference_graph_is_recursive_and_cycles_are_deduplicated(self) -> None:
		self.policy_path.write_text("[专项](rules/details.md)\n", encoding="utf-8")
		self.write_source("policy/rules/details.md", "[主规则](../SKILL.md)\n\n必须核对真实入口。\n")
		self.local_path.write_text("本机扩展约束。\n", encoding="utf-8")
		bundle = skillnull_gate.load_rule_bundle()
		self.assertEqual(len(bundle["sources"]), 3)
		self.assertIn("必须核对真实入口", skillnull_gate.load_skill_context(bundle))
		previous_revision = bundle["revision"]
		self.write_source("policy/rules/details.md", "必须核对另一个入口。\n")
		self.assertNotEqual(previous_revision, skillnull_gate.load_rule_bundle()["revision"])

	def test_local_extension_creation_and_deletion_are_live_changes(self) -> None:
		self.start_session()
		self.record_review("plan")
		self.local_path.write_text("本机新增约束。\n", encoding="utf-8")
		self.assertIn("本机新增约束", self.pre_tool("Bash", "pwd")["hookSpecificOutput"]["additionalContext"])
		self.record_review("plan")
		self.local_path.unlink()
		self.assertEqual(self.pre_tool()["hookSpecificOutput"]["permissionDecision"], "deny")

	def test_missing_or_escaping_rule_links_are_rejected(self) -> None:
		for link in ("missing.md", "../../outside.md"):
			with self.subTest(link=link):
				self.policy_path.write_text(f"[约束]({link})\n", encoding="utf-8")
				with self.assertRaises((OSError, ValueError)):
					skillnull_gate.load_rule_bundle()

	def test_numbered_examples_inside_code_fences_do_not_split_rules(self) -> None:
		content = "---\nname: sample\n---\n# Title\n\n1. **约束**：检查。\n\n```text\n1. example\n\n2. example\n```\n\n- 下一条。\n"
		blocks = skillnull_gate.markdown_blocks(content)
		self.assertEqual(len(blocks), 3)
		self.assertIn("2. example", blocks[1][1])
		self.assertNotIn("name: sample", str(blocks))

	def test_missing_or_pending_evidence_never_counts_as_complete(self) -> None:
		self.start_session()
		self.record_review("delivery")
		bundle = skillnull_gate.load_rule_bundle()
		review = skillnull_gate.load_state("dynamic-session")["delivery"]
		for broken_entry in ({}, {"status": "pending"}, {"reason": ""}, {"evidence": ""}):
			with self.subTest(broken_entry=broken_entry):
				candidate = json.loads(json.dumps(review))
				if broken_entry:
					candidate["entries"][0].update(broken_entry)
				else:
					candidate["entries"] = []
				self.assertTrue(skillnull_gate.review_failures(candidate, bundle, "delivery", review["workspace_revision"]))

	def test_unknown_and_duplicate_entries_are_rejected(self) -> None:
		self.start_session()
		self.record_review("plan")
		bundle = skillnull_gate.load_rule_bundle()
		review = skillnull_gate.load_state("dynamic-session")["plan"]
		for extra_id in (review["entries"][0]["id"], "nonexistent-rule"):
			candidate = json.loads(json.dumps(review))
			candidate["entries"].append({**candidate["entries"][0], "id": extra_id})
			self.assertTrue(skillnull_gate.review_failures(candidate, bundle, "plan", ""))

	def test_end_gate_cannot_be_skipped_on_second_stop(self) -> None:
		self.start_session()
		self.record_review("plan")
		for stop_hook_active in (False, True):
			output = self.stop_session(stop_hook_active=stop_hook_active)
			self.assertEqual(output["decision"], "block")
			self.assertIn("delivery", output["reason"])

	def test_delivery_is_invalidated_by_untracked_source_edit(self) -> None:
		self.start_session()
		self.record_review("plan")
		self.write_source("src/new.py", "value = 1\n")
		self.record_review("delivery")
		self.write_source("src/new.py", "value = 2\n")
		self.assertIn("工作区已变动", self.stop_session()["reason"])

	def test_complete_review_allows_stop_and_clears_private_state(self) -> None:
		self.start_session()
		self.record_review("plan")
		self.record_review("delivery")
		self.assertEqual(self.stop_session(), {})
		self.assertFalse(skillnull_gate.state_path("dynamic-session").exists())

	def test_shell_edits_activate_review_even_without_explicit_plan(self) -> None:
		self.start_session()
		self.write_source("src/new.py", "value = 1\n")
		output = self.stop_session()
		self.assertIn("缺少 plan", output["reason"])
		self.assertIn("缺少 delivery", output["reason"])

	def test_missing_state_cannot_be_treated_as_a_passing_stop(self) -> None:
		self.assertEqual(self.stop_session()["decision"], "block")

	def test_legacy_state_preserves_removal_authorization_and_baseline(self) -> None:
		skillnull_gate.save_state("dynamic-session", {"removal_authorized": True, "baseline_zero_sources": ["src/old.py"]})
		state = skillnull_gate.session_state("dynamic-session", self.repo_root)
		self.assertTrue(state["removal_authorized"])
		self.assertEqual(state["baseline_zero_sources"], ["src/old.py"])
		self.assertEqual(state["workspace"], str(self.repo_root))

	def test_non_git_workspace_still_loads_rules_and_blocks_empty_sources(self) -> None:
		with tempfile.TemporaryDirectory() as workspace_directory:
			workspace = Path(workspace_directory).resolve()
			output = skillnull_gate.handle_user_prompt({"session_id": "non-git", "cwd": str(workspace)})
			self.assertIn("SKILLNULL", output["hookSpecificOutput"]["additionalContext"])
			(workspace / "empty.py").write_text("", encoding="utf-8")
			failures = skillnull_gate.current_gate_failures(workspace, skillnull_gate.load_state("non-git"))
			self.assertIn("源码被清空：empty.py", failures)

	def test_non_git_existing_empty_file_is_preserved_as_baseline(self) -> None:
		with tempfile.TemporaryDirectory() as workspace_directory:
			workspace = Path(workspace_directory).resolve()
			(workspace / "existing.py").write_text("", encoding="utf-8")
			skillnull_gate.handle_user_prompt({"session_id": "non-git-existing", "cwd": str(workspace)})
			state = skillnull_gate.load_state("non-git-existing")
			self.assertEqual(skillnull_gate.current_gate_failures(workspace, state), [])

	def test_corrupt_state_returns_explicit_denial_in_hook_protocol(self) -> None:
		skillnull_gate.save_state("dynamic-session", {"workspace": str(self.repo_root.resolve())})
		payload = {"hook_event_name": "PreToolUse", "session_id": "dynamic-session",
			"cwd": str(self.repo_root), "tool_name": "apply_patch", "tool_input": {"command": ""}}
		with (
			mock.patch.object(sys, "argv", [str(SCRIPT_PATH)]),
			mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
			mock.patch.object(skillnull_gate, "emit") as emit,
		):
			self.assertEqual(skillnull_gate.main(), 0)
			self.assertEqual(emit.call_args.args[0]["hookSpecificOutput"]["permissionDecision"], "deny")

	def test_snapshot_and_review_cli_use_current_adjacent_sources(self) -> None:
		self.start_session()
		self.record_review("plan")
		review = skillnull_gate.load_state("dynamic-session")["plan"]
		arguments = ["review", "--session", "dynamic-session", "--cwd", str(self.repo_root)]
		with (
			mock.patch.object(sys, "argv", [str(SCRIPT_PATH), *arguments]),
			mock.patch.object(sys, "stdin", io.StringIO(json.dumps(review))),
			mock.patch.object(skillnull_gate, "emit") as emit,
		):
			self.assertEqual(skillnull_gate.handle_review_cli(), 0)
			emit.assert_called_once()
		self.assertTrue(skillnull_gate.load_state("dynamic-session")["active"])

	def test_policy_failure_retains_only_narrow_read_only_diagnostics(self) -> None:
		for command, allowed in (("cat SKILL.md", True), ("pwd", True), ("cat file; rm file", False), ("python3 script.py", False), ("rg --pre sh value", False)):
			with self.subTest(command=command):
				self.assertEqual(skillnull_gate.is_read_only_tool({"tool_name": "Bash", "tool_input": {"command": command}}), allowed)

	def test_snapshot_preserves_prohibition_context_in_headings(self) -> None:
		self.policy_path.write_text("# 约束\n\n## 已排除的方向\n\n- 用替代字体掩盖问题。\n", encoding="utf-8")
		rule = skillnull_gate.load_rule_bundle()["rules"][0]
		self.assertEqual(rule["section"], ["约束", "已排除的方向"])

	def test_large_rules_require_paging_without_sending_a_truncated_body(self) -> None:
		self.policy_path.write_text("# 约束\n\n" + "必须核对真实验收条件。" * 1000, encoding="utf-8")
		context = self.start_session()["hookSpecificOutput"]["additionalContext"]
		self.assertLess(len(context.encode("utf-8")), skillnull_gate.MAX_CONTEXT_BYTES)
		self.assertIn("snapshot", context)
		self.assertNotIn("必须核对真实验收条件", context)

	def test_installed_hook_and_review_cli_enforce_live_rule_changes(self) -> None:
		installed_script = self.write_source("installed/scripts/skillnull_gate.py", SCRIPT_PATH.read_text(encoding="utf-8"))
		installed_policy = self.write_source("installed/SKILL.md", "# 约束\n\n1. 检查目标。\n")
		environment = {**os.environ, "HOME": str(self.repo_root), "PYTHONDONTWRITEBYTECODE": "1"}

		def invoke(arguments: list[str], payload: dict | None = None) -> tuple[int, dict]:
			result = subprocess.run(
				[sys.executable, str(installed_script), *arguments],
				input=json.dumps(payload or {}, ensure_ascii=False), capture_output=True,
				text=True, env=environment, cwd=self.repo_root / "src", check=False,
			)
			return result.returncode, json.loads(result.stdout)

		common = {"session_id": "installed-test", "cwd": str(self.repo_root)}
		invoke([], {**common, "hook_event_name": "UserPromptSubmit"})
		cli = ["--session", "installed-test", "--cwd", str(self.repo_root)]

		def submit(phase: str, snapshot: dict) -> int:
			return invoke(["review", *cli], {
				"phase": phase, "policy_revision": snapshot["policy_revision"],
				"workspace_revision": snapshot["workspace_revision"],
				"entries": [{"id": rule["id"], "status": "planned" if phase == "plan" else "verified",
					"reason": "隔离安装协议测试。", "evidence": "当前测试源与快照。"} for rule in snapshot["rules"]],
			})[0]

		return_code, snapshot = invoke(["snapshot", *cli])
		self.assertEqual(submit("plan", snapshot), 0)
		installed_policy.write_text("# 约束\n\n1. 检查目标。\n2. 新增任意未来条件。\n", encoding="utf-8")
		return_code, denied = invoke([], {**common, "hook_event_name": "PreToolUse", "tool_name": "functions.apply_patch", "tool_input": {"command": ""}})
		self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
		self.assertEqual(submit("plan", snapshot), 1)
		return_code, snapshot = invoke(["snapshot", *cli, "--offset", "0", "--limit", "20"])
		self.assertEqual(snapshot["total_rules"], 2)
		self.assertEqual(submit("plan", snapshot), 0)
		self.assertEqual(submit("delivery", snapshot), 0)
		self.write_source("src/value.py", "value = 1\n")
		return_code, blocked = invoke([], {**common, "hook_event_name": "Stop", "stop_hook_active": True})
		self.assertEqual(blocked["decision"], "block")
		return_code, snapshot = invoke(["snapshot", *cli])
		self.assertEqual(submit("delivery", snapshot), 0)
		self.assertEqual(invoke([], {**common, "hook_event_name": "Stop", "stop_hook_active": True})[1], {})

	def test_blocks_patch_that_empties_source_file(self) -> None:
		self.write_source("src/hooks.ts", "export const useQuery = () => 1;\n")
		patch_text = """*** Begin Patch
*** Update File: src/hooks.ts
@@
-export const useQuery = () => 1;
*** End Patch
"""
		reason, touched = skillnull_gate.check_patch(
			self.repo_root, patch_text, False
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
			self.repo_root, patch_text, False
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
			self.repo_root, patch_text, True
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
			self.repo_root, patch_text, False
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
			self.repo_root, patch_text, True
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

	def test_blocks_unencoded_whitespace_in_static_resource_path(self) -> None:
		self.write_source(
			"src/index.html",
			'<script src=". /dist/device.es.js"></script>\n',
		)
		failures = skillnull_gate.current_gate_failures(
			self.repo_root,
			{
				"baseline_diff_check": [],
				"baseline_resource_path_errors": [],
				"baseline_zero_sources": [],
				"touched_files": [],
			},
		)
		self.assertEqual(
			failures,
			[
				"静态资源路径包含未编码空白："
				"src/index.html:1 attribute src"
			],
		)

	def test_allows_normalized_and_dynamic_resource_paths(self) -> None:
		self.write_source(
			"src/index.html",
			'<script src="./dist/device.es.js"></script>\n'
			'<img :src="assetBase + fileName">\n',
		)
		self.assertEqual(
			skillnull_gate.static_resource_path_errors(self.repo_root), []
		)

	def test_blocks_unencoded_whitespace_in_style_url(self) -> None:
		self.write_source(
			"src/index.css", '.hero { background: url("./hero image.png"); }\n'
		)
		self.assertEqual(
			skillnull_gate.static_resource_path_errors(self.repo_root),
			["src/index.css:1 style url"],
		)

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
			env={**os.environ, "HOME": str(self.repo_root)},
		)
		output = json.loads(result.stdout)
		self.assertEqual(
			output["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
		)
		self.assertIn(
			"SKILLNULL — 编写与迭代守则",
			output["hookSpecificOutput"]["additionalContext"],
		)

	def test_state_keeps_only_the_removal_decision(self) -> None:
		session_id = "state-privacy-test-session"
		skillnull_gate.handle_user_prompt(
			{
				"session_id": session_id,
				"cwd": str(self.repo_root),
				"prompt": "删除不再需要的旧文件",
			}
		)
		state = skillnull_gate.load_state(session_id)
		self.assertNotIn("prompt", state)
		self.assertTrue(state["removal_authorized"])
		if os.name != "nt":
			state_mode = stat.S_IMODE(
				skillnull_gate.state_path(session_id).stat().st_mode
			)
			self.assertEqual(state_mode, 0o600)

	def test_negated_removal_is_not_authorized(self) -> None:
		self.assertFalse(skillnull_gate.has_removal_authorization("不要删除任何文件"))
		self.assertFalse(skillnull_gate.has_removal_authorization("do not delete files"))
		self.assertTrue(skillnull_gate.has_removal_authorization("删除旧文件"))

	def test_successful_stop_removes_session_state(self) -> None:
		session_id = "completed-session"
		skillnull_gate.handle_user_prompt(
			{
				"session_id": session_id,
				"cwd": str(self.repo_root),
				"prompt": "修改代码",
			}
		)
		self.assertTrue(skillnull_gate.state_path(session_id).exists())
		self.assertEqual(
			skillnull_gate.handle_stop(
				{"session_id": session_id, "cwd": str(self.repo_root)}
			),
			{},
		)
		self.assertFalse(skillnull_gate.state_path(session_id).exists())

	def test_prompt_wording_does_not_disable_normal_tool_use(self) -> None:
		session_id = "normal-tool-use-test-session"
		self.addCleanup(
			skillnull_gate.state_path(session_id).unlink, missing_ok=True
		)
		prompt_output = skillnull_gate.handle_user_prompt(
			{
				"hook_event_name": "UserPromptSubmit",
				"session_id": session_id,
				"cwd": str(self.repo_root),
				"prompt": "修改 Skill 与系统提示词相关的输出格式",
			}
		)
		context = prompt_output["hookSpecificOutput"]["additionalContext"]
		self.assertIn("SKILLNULL — 编写与迭代守则", context)

		tool_output = skillnull_gate.handle_pre_tool(
			{
				"hook_event_name": "PreToolUse",
				"session_id": session_id,
				"cwd": str(self.repo_root),
				"tool_name": "exec_command",
				"tool_input": {"cmd": "pwd"},
			}
		)
		self.assertEqual(tool_output, {})

	def test_relocated_hook_loads_adjacent_rules_through_symlink(self) -> None:
		relocated_script = self.write_source(
			"relocated/scripts/skillnull_gate.py",
			SCRIPT_PATH.read_text(encoding="utf-8"),
		)
		self.write_source("relocated/SKILL.md", "portable main rules\n")
		local_rules = self.write_source(
			"relocated/SKILL.local.md", "portable local rules\n"
		)
		self.write_source(
			"relocated/.privacy.local.json", '["private-sentinel"]\n'
		)
		linked_directory = self.repo_root / "linked-skill"
		linked_directory.symlink_to(relocated_script.parent.parent, target_is_directory=True)
		payload = json.dumps(
			{
				"hook_event_name": "UserPromptSubmit",
				"session_id": "relocated-test-session",
				"cwd": str(self.repo_root),
				"prompt": "检查规则加载",
			}
		)
		for include_local in (True, False):
			with self.subTest(include_local=include_local):
				if not include_local:
					local_rules.unlink()
				result = subprocess.run(
					[sys.executable, str(linked_directory / "scripts/skillnull_gate.py")],
					input=payload,
					cwd=self.repo_root / "src",
					capture_output=True,
					text=True,
					check=True,
					env={**os.environ, "HOME": str(self.repo_root)},
				)
				context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
				self.assertIn("portable main rules", context)
				self.assertEqual("portable local rules" in context, include_local)
				self.assertNotIn("private-sentinel", context)
				self.assertNotIn("## 本地知识库", context)


if __name__ == "__main__":
	unittest.main()
