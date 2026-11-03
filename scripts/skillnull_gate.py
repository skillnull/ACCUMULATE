#!/usr/bin/env python3
"""Global Codex hook gate for the non-negotiable SKILLNULL rules."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


SKILL_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"
LOCAL_SKILL_PATH = SKILL_PATH.with_name("SKILL.local.md")
STATE_ROOT = Path.home() / ".codex" / "state" / "skillnull-gate"
MAX_CONTEXT_BYTES = 6000
SOURCE_SUFFIXES = {
	".c",
	".cc",
	".cpp",
	".css",
	".go",
	".h",
	".hpp",
	".html",
	".java",
	".js",
	".jsx",
	".kt",
	".less",
	".mjs",
	".py",
	".rb",
	".rs",
	".sass",
	".scss",
	".swift",
	".ts",
	".tsx",
	".vue",
}
STATIC_RESOURCE_SUFFIXES = {
	".css",
	".html",
	".jsx",
	".less",
	".sass",
	".scss",
	".tsx",
	".vue",
}
STATIC_RESOURCE_PATTERNS = (
	(
		re.compile(
			r"(?<![:.@\[\w-])(?P<kind>src|href)\s*=\s*"
			r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
			re.IGNORECASE | re.DOTALL,
		),
		"attribute",
	),
	(
		re.compile(
			r"(?P<kind>url)\(\s*(?P<quote>[\"']?)"
			r"(?P<value>.*?)(?P=quote)\s*\)",
			re.IGNORECASE | re.DOTALL,
		),
		"style",
	),
)
REMOVAL_WORDS = re.compile(
	r"删除|移除|废弃|下线|清空|重写|替换|remove|delete|deprecate|rewrite|replace",
	re.IGNORECASE,
)
REMOVAL_DENIAL_WORDS = re.compile(
	r"(?:不要|不得|不能|不可|不需要|无需|禁止|避免)\s*"
	r"(?:删除|移除|废弃|下线|清空|重写|替换)"
	r"|(?:do\s+not|don't|must\s+not|without)\s+"
	r"(?:remove|delete|deprecate|rewrite|replace)",
	re.IGNORECASE,
)
IMPORT_PATTERN = re.compile(
	r"\bimport\s+(?:type\s+)?(.+?)\s+from\s+[\"'][^\"']+[\"']\s*;?",
	re.DOTALL,
)
DESTRUCTIVE_COMMANDS = (
	re.compile(r"(?:^|[;&|]\s*)git\s+(?:reset|clean|checkout|restore)\b", re.IGNORECASE),
	re.compile(r"(?:^|[;&|]\s*)(?:rm|truncate)\b", re.IGNORECASE),
	re.compile(r"(?:^|[;&|]\s*)(?:sed\s+-i|perl\s+-pi)\b", re.IGNORECASE),
	re.compile(
		r">>?\s*[^\s]+\.(?:c|cc|cpp|css|go|h|hpp|html|java|js|jsx|kt|less|mjs|py|rb|rs|sass|scss|swift|ts|tsx|vue)\b",
		re.IGNORECASE,
	),
)


def emit(payload: dict[str, Any]) -> None:
	json.dump(payload, sys.stdout, ensure_ascii=False)
	sys.stdout.write("\n")


def run_git(cwd: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
	return subprocess.run(
		["git", *arguments],
		cwd=cwd,
		capture_output=True,
		text=True,
		check=False,
	)


def find_repo_root(cwd_value: str | None) -> Path | None:
	if not cwd_value:
		return None
	cwd = Path(cwd_value).expanduser()
	if not cwd.exists():
		return None
	result = run_git(cwd, ["rev-parse", "--show-toplevel"])
	if result.returncode != 0:
		return None
	return Path(result.stdout.strip()).resolve()


def state_path(session_id: str) -> Path:
	digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
	return STATE_ROOT / f"{digest}.json"


def load_state(session_id: str) -> dict[str, Any]:
	path = state_path(session_id)
	try:
		state = json.loads(path.read_text(encoding="utf-8"))
		if not isinstance(state, dict):
			raise ValueError("会话状态必须是对象")
		return state
	except FileNotFoundError:
		return {}


def save_state(session_id: str, state: dict[str, Any]) -> None:
	STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
	if os.name != "nt":
		STATE_ROOT.chmod(0o700)
	path = state_path(session_id)
	with tempfile.NamedTemporaryFile(
		mode="w", encoding="utf-8", dir=STATE_ROOT, delete=False
	) as temporary_file:
		temporary_path = Path(temporary_file.name)
		try:
			json.dump(state, temporary_file, ensure_ascii=False, indent=2)
			temporary_file.flush()
			temporary_path.replace(path)
		finally:
			temporary_path.unlink(missing_ok=True)


def clear_state(session_id: str) -> None:
	try:
		state_path(session_id).unlink()
	except FileNotFoundError:
		pass


def diff_check_lines(repo_root: Path) -> list[str]:
	result = run_git(repo_root, ["diff", "--check"])
	return sorted(line for line in result.stdout.splitlines() if line.strip())


def working_tree_zero_sources(repo_root: Path) -> list[str]:
	return sorted({
		str(target.relative_to(repo_root.resolve()))
		for target in working_tree_paths(repo_root)
		if target.suffix.lower() in SOURCE_SUFFIXES and target.stat().st_size == 0
	})


def workspace_files(workspace: Path) -> list[Path]:
	paths: list[Path] = []
	for directory, folders, files in os.walk(workspace):
		folders[:] = [name for name in folders if name not in {
			".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv"
		} and not (Path(directory) / name).resolve().is_relative_to(STATE_ROOT.resolve())]
		paths.extend(Path(directory) / name for name in files)
	return paths


def working_tree_paths(repo_root: Path) -> list[Path]:
	result = run_git(
		repo_root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
	)
	if result.returncode != 0:
		if find_repo_root(str(repo_root)) is not None:
			raise OSError("无法读取 Git 工作区状态")
		return [target for target in workspace_files(repo_root) if target.is_file()]
	paths: list[Path] = []
	status_entries = iter(result.stdout.split("\0"))
	for status_entry in status_entries:
		if len(status_entry) < 4:
			continue
		target = normalize_target(repo_root, status_entry[3:])
		if "R" in status_entry[:2] or "C" in status_entry[:2]:
			next(status_entries, None)
		if target and target.exists() and target.is_file():
			paths.append(target)
	return paths


def static_resource_path_errors(repo_root: Path) -> list[str]:
	repo_root = repo_root.resolve()
	errors: list[str] = []
	for target in working_tree_paths(repo_root):
		if target.suffix.lower() not in STATIC_RESOURCE_SUFFIXES:
			continue
		content = target.read_text(encoding="utf-8", errors="replace")
		for pattern, reference_type in STATIC_RESOURCE_PATTERNS:
			for match in pattern.finditer(content):
				value = match.group("value").strip()
				if value.lower().startswith("data:") or not re.search(r"\s", value):
					continue
				line_number = content.count("\n", 0, match.start("value")) + 1
				relative_target = target.relative_to(repo_root)
				errors.append(
					f"{relative_target}:{line_number} "
					f"{reference_type} {match.group('kind').lower()}"
				)
	return sorted(set(errors))


def markdown_blocks(content: str) -> list[tuple[int, str]]:
	"""Keep every prose/list/code block; interpret no rule-specific keywords."""
	blocks: list[tuple[int, str]] = []
	current_lines: list[str] = []
	start_line = 1
	fence = ""
	frontmatter = content.startswith("---\n")
	for line_number, line in enumerate(content.splitlines(), 1):
		if frontmatter:
			if line_number > 1 and line.strip() == "---":
				frontmatter = False
			continue
		fence_match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
		if fence_match:
			marker = fence_match.group(1)
			if not fence:
				fence = marker
			elif marker[0] == fence[0] and len(marker) >= len(fence):
				fence = ""
		elif not fence:
			is_heading = bool(re.match(r"^#{1,6}\s", line))
			is_item = bool(re.match(r"^\s{0,3}(?:\d+[.)]|[-+*])\s+", line))
			if not line.strip() or is_heading or is_item:
				if current_lines:
					blocks.append((start_line, "\n".join(current_lines).strip()))
					current_lines = []
				if not line.strip() or is_heading:
					continue
		if not current_lines:
			start_line = line_number
		current_lines.append(line)
	if current_lines:
		blocks.append((start_line, "\n".join(current_lines).strip()))
	return blocks


def load_rule_bundle() -> dict[str, Any]:
	"""Discover the current policy graph from the installation, never the project."""
	root = SKILL_PATH.resolve().parent
	pending = [SKILL_PATH.resolve()]
	if LOCAL_SKILL_PATH.exists():
		pending.append(LOCAL_SKILL_PATH.resolve())
	sources: dict[str, str] = {}
	rules: list[dict[str, Any]] = []
	while pending:
		target = pending.pop(0)
		try:
			relative_path = target.relative_to(root).as_posix()
		except ValueError as error:
			raise ValueError("规则引用越出全局安装目录") from error
		if target.suffix.lower() != ".md":
			raise ValueError("规则引用必须指向 Markdown 文件")
		if relative_path in sources:
			continue
		content = target.read_text(encoding="utf-8")
		if not content.strip():
			raise ValueError("规则文件为空")
		sources[relative_path] = content
		headings: list[tuple[int, str]] = []
		sections: dict[int, list[str]] = {}
		fence = ""
		for line_number, line in enumerate(content.splitlines(), 1):
			fence_match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
			if fence_match:
				marker = fence_match.group(1)
				if not fence:
					fence = marker
				elif marker[0] == fence[0] and len(marker) >= len(fence):
					fence = ""
			heading = re.match(r"^(#{1,6})\s+(.+)$", line) if not fence else None
			if heading:
				level = len(heading.group(1))
				headings = [item for item in headings if item[0] < level]
				headings.append((level, heading.group(2)))
			sections[line_number] = [title for heading_level, title in headings]
		for line_number, text in markdown_blocks(content):
			digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
			rules.append({
				"id": f"{relative_path}:{line_number}:{digest}",  # Source-bound review key.
				"source": relative_path,  # Path relative to the global installation.
				"line": line_number,  # First line of this policy block.
				"section": sections[line_number],  # Conditions and prohibitions in headings.
				"text": text,  # Current requirement, including its conditions.
			})
		for raw_link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
			link = urlsplit(raw_link.strip().strip("<>"))
			if link.scheme or link.netloc or not link.path:
				continue
			linked_path = Path(unquote(link.path))
			if linked_path.suffix.lower() == ".md":
				pending.append((target.parent / linked_path).resolve())
	if not rules:
		raise ValueError("规则文件不含可审查内容")
	fingerprint = hashlib.sha256(json.dumps(
		sources, ensure_ascii=False, sort_keys=True
	).encode("utf-8")).hexdigest()
	return {
		"revision": fingerprint,  # Digest of every discovered rule source.
		"sources": sources,  # Complete current Markdown, keyed by relative path.
		"rules": rules,  # Review units discovered without fixed numbers or counts.
	}


def load_skill_context(bundle: dict[str, Any] | None = None) -> str:
	bundle = bundle or load_rule_bundle()
	return "\n\n".join(
		f"--- SKILLNULL 来源：{relative_path} ---\n\n{content}"
		for relative_path, content in bundle["sources"].items()
	)


def workspace_revision(workspace: Path) -> str:
	"""Bind delivery reviews to actual files and staging, excluding hook state."""
	workspace = workspace.resolve()
	digest = hashlib.sha256()
	repo_root = find_repo_root(str(workspace))
	if repo_root:
		for arguments in (["rev-parse", "HEAD"], ["diff", "--cached", "--binary"]):
			result = run_git(repo_root, arguments)
			digest.update(result.stdout.encode("utf-8"))
		result = run_git(repo_root, [
			"ls-files", "-z", "--modified", "--deleted", "--others", "--exclude-standard"
		])
		if result.returncode:
			raise OSError("无法读取工作区文件状态")
		paths = [repo_root / value for value in result.stdout.split("\0") if value]
	else:
		paths = workspace_files(workspace)
	for target in sorted(set(paths)):
		if target.resolve().is_relative_to(STATE_ROOT.resolve()):
			continue
		digest.update(str(target.relative_to(workspace)).encode("utf-8"))
		if target.is_symlink():
			digest.update(os.readlink(target).encode("utf-8"))
		elif target.is_file():
			with target.open("rb") as source_file:
				for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
					digest.update(chunk)
		else:
			digest.update(b"<deleted>")
	return digest.hexdigest()


def review_failures(
	review: Any, bundle: dict[str, Any], phase: str, revision: str
) -> list[str]:
	if not isinstance(review, dict):
		return [f"缺少 {phase} 逐条审查"]
	if review.get("phase") != phase:
		return ["审查阶段不匹配"]
	if review.get("policy_revision") != bundle["revision"]:
		return ["规则已变动，旧审查失效"]
	if phase == "delivery" and review.get("workspace_revision") != revision:
		return ["工作区已变动，须重新验证并审查"]
	entries = review.get("entries")
	if not isinstance(entries, list):
		return ["逐条审查 entries 必须是数组"]
	known_ids = {rule["id"] for rule in bundle["rules"]}
	seen_ids: set[str] = set()
	failures: list[str] = []
	accepted = {"planned", "not_applicable"} if phase == "plan" else {
		"verified", "not_applicable"
	}
	if phase == "delivery" and review.get("outcome") == "incomplete":
		accepted.add("blocked")
	for entry in entries:
		if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
			failures.append("逐条审查条目必须含字符串 id")
			continue
		rule_id = entry["id"]
		if rule_id not in known_ids or rule_id in seen_ids:
			failures.append("逐条审查含未知或重复规则")
		seen_ids.add(rule_id)
		if entry.get("status") not in accepted:
			failures.append(f"规则尚未通过审查：{rule_id}")
		for field in ("reason", "evidence"):
			value = entry.get(field)
			if not isinstance(value, str) or not value.strip():
				failures.append(f"规则缺少 {field}：{rule_id}")
	missing = known_ids - seen_ids
	if missing:
		failures.append(f"漏审 {len(missing)} 条规则：{sorted(missing)[0]}")
	return list(dict.fromkeys(failures))


def review_instructions(session_id: str, workspace: Path) -> str:
	command = shlex.join([
		sys.executable, str(Path(__file__).resolve()), "review",
		"--session", session_id, "--cwd", str(workspace),
	])
	return (
		"开发任务须完整读取最新规则，可分段读取来源文件，"
		"或运行下列命令的 snapshot 子命令（将 review 改为 snapshot）。"
		"获取动态规则 id、policy_revision 和 workspace_revision；"
		"snapshot 支持 --offset 与 --limit 分页，必须读完 total_rules 条。"
		"按每条原文判断触发条件，禁止批量填充或以已读取代替遵守。\n"
		f"{command}\n"
		"review 从标准输入接收 JSON：phase 为 plan 或 delivery，"
		"同时提交 policy_revision、workspace_revision、entries。"
		"每条 entries 含 id、status、reason、evidence。"
		"开发前 status 用 planned 或 not_applicable，说明执行计划及适用依据；"
		"交付前用 verified 或 not_applicable，给出实际检查证据或不适用依据。"
		"未验证、失败或阻塞不得标 verified，须继续处理或如实报告未完成。"
		"确实无法完成时，delivery 可用 outcome=incomplete 与 status=blocked，"
		"逐项列出阻塞证据，最终答复必须明确未完成。"
		"语义条款由代理据证审查，脚本仅校验覆盖、版本与必填证据，不证明语义正确。"
		"审查仅存全局会话状态，不写业务仓库，不提交密钥、个人数据或私有词库。"
		"普通非开发问答不启用审查，不运行无关命令。"
	)


def is_read_only_tool(payload: dict[str, Any]) -> bool:
	"""Retain a narrow diagnostic path when policy or state cannot be loaded."""
	tool_name = str(payload.get("tool_name") or "").lower()
	if tool_name in {"read", "read_file", "list_directory", "glob", "grep"}:
		return True
	if tool_name not in {"bash", "exec_command"}:
		return False
	text = extract_tool_text(payload)
	if re.search(r"[;&|<>`$\n]", text):
		return False
	try:
		arguments = shlex.split(text)
	except ValueError:
		return False
	if not arguments:
		return False
	if arguments[0] in {"cat", "head", "tail", "pwd", "wc", "ls", "rg", "readlink"}:
		return not any(argument.startswith(("--pre", "--hostname-bin")) for argument in arguments)
	return len(arguments) > 1 and arguments[0] == "git" and arguments[1] in {
		"status", "diff", "log", "show", "ls-files", "rev-parse"
	} and not any(argument.startswith(("--output", "--ext-diff", "--textconv")) for argument in arguments)


def extract_prompt(payload: dict[str, Any]) -> str:
	for key in ("prompt", "user_prompt", "message"):
		value = payload.get(key)
		if isinstance(value, str):
			return value
	return ""


def has_removal_authorization(prompt: str) -> bool:
	return bool(REMOVAL_WORDS.search(prompt)) and not REMOVAL_DENIAL_WORDS.search(
		prompt
	)


def extract_tool_text(payload: dict[str, Any]) -> str:
	tool_input = payload.get("tool_input")
	if isinstance(tool_input, str):
		return tool_input
	if not isinstance(tool_input, dict):
		return ""
	for key in ("patch", "input", "command", "cmd", "code"):
		value = tool_input.get(key)
		if isinstance(value, str):
			return value
	return json.dumps(tool_input, ensure_ascii=False)


def normalize_target(repo_root: Path, raw_target: str) -> Path | None:
	repo_root = repo_root.resolve()
	target = Path(raw_target.strip())
	resolved = target.resolve() if target.is_absolute() else (repo_root / target).resolve()
	try:
		resolved.relative_to(repo_root)
	except ValueError:
		return None
	return resolved


def parse_patch_sections(patch_text: str) -> list[dict[str, Any]]:
	sections: list[dict[str, Any]] = []
	current_section: dict[str, Any] | None = None
	for line in patch_text.splitlines():
		header_match = re.match(r"\*\*\* (Update|Delete|Add) File: (.+)$", line)
		if header_match:
			if current_section:
				sections.append(current_section)
			current_section = {
				"operation": header_match.group(1).lower(),
				"target": header_match.group(2).strip(),
				"removed": [],
				"added": [],
			}
			continue
		if not current_section or line.startswith("@@"):
			continue
		if line.startswith("-") and not line.startswith("---"):
			current_section["removed"].append(line[1:])
		elif line.startswith("+") and not line.startswith("+++"):
			current_section["added"].append(line[1:])
	if current_section:
		sections.append(current_section)
	return sections


def imported_names(content: str) -> set[str]:
	names: set[str] = set()
	for import_clause in IMPORT_PATTERN.findall(content):
		clause = import_clause.strip()
		default_match = re.match(r"([A-Za-z_$][\w$]*)", clause)
		if default_match:
			names.add(default_match.group(1))
		namespace_match = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", clause)
		if namespace_match:
			names.add(namespace_match.group(1))
		named_match = re.search(r"\{(.*?)\}", clause, flags=re.DOTALL)
		if not named_match:
			continue
		for imported_item in named_match.group(1).split(","):
			item = re.sub(r"^\s*type\s+", "", imported_item.strip())
			if not item:
				continue
			alias_parts = re.split(r"\s+as\s+", item)
			local_name = alias_parts[-1].strip()
			if re.fullmatch(r"[A-Za-z_$][\w$]*", local_name):
				names.add(local_name)
	return names


def projected_content(
	content: str, removed_lines: list[str], added_lines: list[str]
) -> str:
	projected_lines = content.splitlines()
	for removed_line in removed_lines:
		try:
			projected_lines.remove(removed_line)
		except ValueError:
			continue
	projected_lines.extend(added_lines)
	return "\n".join(projected_lines)


def removed_import_still_used(
	content: str, removed_lines: list[str], added_lines: list[str]
) -> str | None:
	removed_names = imported_names("\n".join(removed_lines))
	if not removed_names:
		return None
	projected = projected_content(content, removed_lines, added_lines)
	remaining_imports = imported_names(projected)
	usage_content = IMPORT_PATTERN.sub("", projected)
	for removed_name in sorted(removed_names - remaining_imports):
		if re.search(rf"(?<![\w$]){re.escape(removed_name)}(?![\w$])", usage_content):
			return removed_name
	return None


def exported_names(content: str) -> set[str]:
	patterns = (
		r"\bexport\s+(?:declare\s+)?(?:const|let|var|function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
		r"\bexport\s*\{([^}]+)\}",
	)
	names = set(re.findall(patterns[0], content))
	for export_group in re.findall(patterns[1], content, flags=re.DOTALL):
		for item in export_group.split(","):
			name = re.split(r"\s+as\s+", item.strip())[0].strip()
			if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
				names.add(name)
	return names


def reference_tokens(target: Path, content: str) -> set[str]:
	tokens = exported_names(content)
	component_name = target.parent.name if target.stem == "index" else target.stem
	if len(component_name) >= 4:
		tokens.add(component_name)
	return {token for token in tokens if len(token) >= 4}


def find_references(repo_root: Path, target: Path, content: str) -> list[str]:
	repo_root = repo_root.resolve()
	tokens = reference_tokens(target, content)
	if not tokens:
		return []
	references: list[str] = []
	for token in sorted(tokens):
		result = subprocess.run(
			[
				"rg",
				"-n",
				"--fixed-strings",
				"--glob",
				"!.git/**",
				"--glob",
				f"!{target.relative_to(repo_root)}",
				token,
				str(repo_root),
			],
			capture_output=True,
			text=True,
			check=False,
		)
		for line in result.stdout.splitlines()[:5]:
			references.append(line.replace(str(repo_root) + os.sep, ""))
		if references:
			break
	return references


def deny_pretool(reason: str) -> dict[str, Any]:
	return {
		"hookSpecificOutput": {
			"hookEventName": "PreToolUse",
			"permissionDecision": "deny",
			"permissionDecisionReason": reason,
		}
	}


def check_patch(
	repo_root: Path, patch_text: str, removal_authorized: bool
) -> tuple[str | None, list[str]]:
	repo_root = repo_root.resolve()
	touched: list[str] = []
	for section in parse_patch_sections(patch_text):
		target = normalize_target(repo_root, section["target"])
		if target is None:
			continue
		relative_target = str(target.relative_to(repo_root))
		touched.append(relative_target)
		if target.suffix.lower() not in SOURCE_SUFFIXES:
			continue
		operation = section["operation"]
		content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
		removed_count = len(section["removed"])
		added_count = len(section["added"])
		current_line_count = len(content.splitlines())
		missing_import = removed_import_still_used(
			content, section["removed"], section["added"]
		)
		if missing_import:
			return (
				f"SKILLNULL 门禁：{relative_target} 删除 import 后仍使用 "
				f"{missing_import}，已阻止。",
				touched,
			)
		if operation == "delete":
			references = find_references(repo_root, target, content)
			if references:
				return (
					f"SKILLNULL 门禁：禁止删除仍被引用的源码 {relative_target}。"
					f"引用示例：{references[0]}",
					touched,
				)
			if not removal_authorized:
				return (
					f"SKILLNULL 门禁：删除源码 {relative_target} 未得到当前用户请求的明确授权。",
					touched,
				)
		if (
			operation == "update"
			and current_line_count > 0
			and removed_count >= current_line_count
			and added_count == 0
		):
			return (
				f"SKILLNULL 门禁：补丁会清空源码 {relative_target}，已阻止。"
				"如确需删除，请使用明确的整文件删除并先消除全部引用。",
				touched,
			)
		large_shrink = (
			current_line_count >= 20
			and removed_count >= 20
			and removed_count >= current_line_count / 2
			and added_count * 3 < removed_count
		)
		if large_shrink and not removal_authorized:
			return (
				f"SKILLNULL 门禁：{relative_target} 将大幅缩减"
				f"（删 {removed_count} 行、增 {added_count} 行），但当前请求未明确要求删除/重写。",
				touched,
			)
	return None, touched


def current_gate_failures(repo_root: Path, state: dict[str, Any]) -> list[str]:
	repo_root = repo_root.resolve()
	failures: list[str] = []
	baseline_diff_errors = set(state.get("baseline_diff_check", []))
	new_diff_errors = [
		line for line in diff_check_lines(repo_root) if line not in baseline_diff_errors
	]
	if new_diff_errors:
		failures.append(f"新增 diff 格式错误：{new_diff_errors[0]}")
	baseline_resource_errors = set(state.get("baseline_resource_path_errors", []))
	new_resource_errors = [
		error
		for error in static_resource_path_errors(repo_root)
		if error not in baseline_resource_errors
	]
	if new_resource_errors:
		failures.append(
			f"静态资源路径包含未编码空白：{new_resource_errors[0]}"
		)
	baseline_zero_sources = set(state.get("baseline_zero_sources", []))
	for relative_target in working_tree_zero_sources(repo_root):
		if relative_target not in baseline_zero_sources:
			failures.append(f"源码被清空：{relative_target}")
	for relative_target in state.get("touched_files", []):
		target = normalize_target(repo_root, relative_target)
		if not target or target.suffix.lower() not in SOURCE_SUFFIXES:
			continue
		if target.exists() and target.stat().st_size == 0:
			failures.append(f"源码被清空：{relative_target}")
	return list(dict.fromkeys(failures))


def payload_workspace(payload: dict[str, Any]) -> Path:
	cwd = Path(payload.get("cwd") or os.getcwd()).expanduser().resolve()
	return find_repo_root(str(cwd)) or cwd


def initial_state(workspace: Path) -> dict[str, Any]:
	is_repository = find_repo_root(str(workspace)) is not None
	return {
		"workspace": str(workspace),  # Workspace to which this session is bound.
		"baseline_workspace": workspace_revision(workspace),  # Original file state.
		"baseline_diff_check": diff_check_lines(workspace) if is_repository else [],
		"baseline_resource_path_errors": static_resource_path_errors(workspace),
		"baseline_zero_sources": working_tree_zero_sources(workspace),
		"touched_files": [],  # Explicit patch targets used by safety checks.
		"active": False,  # Only development reviews or observed edits activate audits.
	}


def session_state(session_id: str, workspace: Path) -> dict[str, Any]:
	state = load_state(session_id)
	if state and "workspace" not in state:
		state = {**initial_state(workspace), **state}
	if state and state.get("workspace") != str(workspace):
		raise ValueError("会话工作目录变动，须重新建立本轮基线")
	if state:
		if not isinstance(state.get("baseline_workspace"), str) or not isinstance(state.get("active"), bool):
			raise ValueError("会话基线损坏")
		for field in ("baseline_diff_check", "baseline_resource_path_errors", "baseline_zero_sources", "touched_files"):
			values = state.get(field)
			if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
				raise ValueError("会话检查基线损坏")
	return state or initial_state(workspace)


def rule_context(
	state: dict[str, Any], bundle: dict[str, Any], session_id: str,
	workspace: Path, force: bool = False,
) -> str:
	if not force and state.get("skill_hash") == bundle["revision"]:
		return ""
	state["skill_loaded"] = True
	state["skill_hash"] = bundle["revision"]
	context = (
		"全局 SKILLNULL 动态门禁：逐条遵守以下最新规则及其适用条件。"
		"新增、删改、引用变更会使旧审查失效。\n"
		+ review_instructions(session_id, workspace)
		+ "\n\n" + load_skill_context(bundle)
	)
	if len(context.encode("utf-8")) > MAX_CONTEXT_BYTES:
		return (
			"全局 SKILLNULL — 编写与迭代守则：规则包超过注入上限。"
			"以下仅为加载指令，不是规则摘要。必须通过 snapshot 分页完整读取"
			"全部规则与本机扩展，再逐条审查；不能只看首尾预览。\n"
			+ review_instructions(session_id, workspace)
		)
	return context


def context_output(event: str, context: str) -> dict[str, Any]:
	return {"hookSpecificOutput": {
		"hookEventName": event,  # Event receiving this model-visible context.
		"additionalContext": context,  # Current rules or actionable gate failures.
	}} if context else {}


def handle_user_prompt(payload: dict[str, Any]) -> dict[str, Any]:
	workspace = payload_workspace(payload)
	session_id = str(payload.get("session_id") or "unknown-session")
	state = session_state(session_id, workspace)
	prompt = extract_prompt(payload)
	if REMOVAL_DENIAL_WORDS.search(prompt):
		state["removal_authorized"] = False
	elif has_removal_authorization(prompt):
		state["removal_authorized"] = True
	bundle = load_rule_bundle()
	context = rule_context(state, bundle, session_id, workspace, force=True)
	save_state(session_id, state)
	return context_output(str(payload.get("hook_event_name") or "UserPromptSubmit"), context)


def handle_pre_tool(payload: dict[str, Any]) -> dict[str, Any]:
	repo_root = payload_workspace(payload)
	session_id = str(payload.get("session_id") or "unknown-session")
	state = session_state(session_id, repo_root)
	bundle = load_rule_bundle()
	context = rule_context(state, bundle, session_id, repo_root)
	tool_name = str(payload.get("tool_name") or "").lower()
	tool_text = extract_tool_text(payload)
	is_patch = "apply_patch" in tool_name
	is_edit = is_patch or tool_name in {"edit", "write"}
	if is_edit:
		failures = review_failures(state.get("plan"), bundle, "plan", "")
		if failures:
			save_state(session_id, state)
			result = deny_pretool("SKILLNULL 门禁：" + "；".join(failures)
				+ "。先按动态清单完成开发前审查。\n"
				+ review_instructions(session_id, repo_root))
			if context:
				result["hookSpecificOutput"]["additionalContext"] = context
			return result
	if tool_name in {"bash", "exec_command"} or tool_name.endswith("__exec_command"):
		for destructive_pattern in DESTRUCTIVE_COMMANDS:
			if destructive_pattern.search(tool_text):
				return deny_pretool(
					"SKILLNULL 门禁：已阻止直接破坏或原地重写命令。"
					"请先核对影响与引用，再用可审查的 apply_patch 执行。"
				)
	if is_patch:
		reason, touched = check_patch(
			repo_root, tool_text, bool(state.get("removal_authorized"))
		)
		state["touched_files"] = sorted(
			set(state.get("touched_files", [])) | set(touched)
		)
		if reason:
			return deny_pretool(reason)
	save_state(session_id, state)
	return context_output("PreToolUse", context)


def handle_post_tool(payload: dict[str, Any]) -> dict[str, Any]:
	repo_root = payload_workspace(payload)
	session_id = str(payload.get("session_id") or "unknown-session")
	state = session_state(session_id, repo_root)
	bundle = load_rule_bundle()
	context = rule_context(state, bundle, session_id, repo_root)
	if workspace_revision(repo_root) != state["baseline_workspace"]:
		state["active"] = True
	failures = current_gate_failures(repo_root, state)
	if failures:
		context += "\nSKILLNULL 门禁未通过：" + "；".join(failures)
	save_state(session_id, state)
	return context_output("PostToolUse", context.strip())


def handle_stop(payload: dict[str, Any]) -> dict[str, Any]:
	repo_root = payload_workspace(payload)
	session_id = str(payload.get("session_id") or "unknown-session")
	if not load_state(session_id):
		return {"decision": "block", "reason": "SKILLNULL 会话基线缺失，不能判定交付通过。"}
	state = session_state(session_id, repo_root)
	bundle = load_rule_bundle()
	revision = workspace_revision(repo_root)
	failures = current_gate_failures(repo_root, state)
	if state.get("active") or revision != state["baseline_workspace"]:
		failures.extend(review_failures(state.get("plan"), bundle, "plan", revision))
		failures.extend(review_failures(state.get("delivery"), bundle, "delivery", revision))
	if not failures:
		clear_state(session_id)
		return {}
	return {
		"decision": "block",
		"reason": "SKILLNULL 全局门禁阻止结束：" + "；".join(failures[:8])
			+ "。原有基线和审查状态继续保留；不得跳过后续结束检查。\n"
			+ review_instructions(session_id, repo_root),
	}


def handle_review_cli() -> int:
	import argparse

	parser = argparse.ArgumentParser(description="Review the current dynamic policy.")
	parser.add_argument("action", choices=("snapshot", "review"))
	parser.add_argument("--session", required=True)
	parser.add_argument("--cwd", type=Path, default=Path.cwd())
	parser.add_argument("--offset", type=int, default=0)
	parser.add_argument("--limit", type=int, default=10)
	options = parser.parse_args()
	workspace = payload_workspace({"cwd": str(options.cwd)})
	bundle = load_rule_bundle()
	state = session_state(options.session, workspace)
	revision = workspace_revision(workspace)
	if options.action == "snapshot":
		if options.offset < 0 or options.limit < 1:
			raise ValueError("分页范围无效")
		emit({
			"policy_revision": bundle["revision"],  # Current complete policy digest.
			"workspace_revision": revision,  # Actual working files and staged changes.
			"total_rules": len(bundle["rules"]),  # Read all pages before reviewing.
			"offset": options.offset,  # Start index of the current page.
			"rules": bundle["rules"][options.offset:options.offset + options.limit],
			# Dynamically discovered IDs and full requirements on the selected page.
		})
		return 0
	review = json.load(sys.stdin)
	phase = review.get("phase") if isinstance(review, dict) else None
	if phase not in {"plan", "delivery"}:
		raise ValueError("phase 必须是 plan 或 delivery")
	failures = review_failures(review, bundle, phase, revision)
	if phase == "delivery":
		failures.extend(review_failures(state.get("plan"), bundle, "plan", revision))
		failures.extend(current_gate_failures(workspace, state))
	if failures:
		emit({
			"status": "rejected",  # Review was not recorded.
			"failures": failures,  # Requirements preventing acceptance.
		})
		return 1
	state[phase] = review
	state["active"] = True
	save_state(options.session, state)
	emit({
		"status": "accepted",  # Review was recorded for this session.
		"phase": phase,  # Accepted review stage.
		"rule_count": len(bundle["rules"]),  # Complete required coverage.
	})
	return 0


def main() -> int:
	if len(sys.argv) > 1:
		try:
			return handle_review_cli()
		except (OSError, ValueError, TypeError) as error:
			emit({"status": "rejected", "error": error.__class__.__name__})
			return 1
	try:
		payload = json.load(sys.stdin)
	except (ValueError, OSError):
		print("SKILLNULL 门禁输入无效，未完成校验。", file=sys.stderr)
		return 2
	if not isinstance(payload, dict):
		print("SKILLNULL 门禁输入必须是 JSON 对象。", file=sys.stderr)
		return 2
	event_name = str(payload.get("hook_event_name") or "")
	handlers = {
		"SessionStart": handle_user_prompt,
		"PostCompact": handle_user_prompt,
		"UserPromptSubmit": handle_user_prompt,
		"PreToolUse": handle_pre_tool,
		"PostToolUse": handle_post_tool,
		"Stop": handle_stop,
	}
	handler = handlers.get(event_name)
	try:
		emit(handler(payload) if handler else {})
	except (OSError, ValueError, TypeError) as error:
		reason = "SKILLNULL 门禁校验失败：" + error.__class__.__name__
		if event_name == "PreToolUse":
			if is_read_only_tool(payload):
				emit(context_output(event_name, reason + "。仅允许只读诊断，请先恢复规则或状态。"))
			else:
				emit(deny_pretool(reason + "。恢复规则或状态后重试；本次工具尚未执行。"))
		elif event_name == "Stop":
			emit({"decision": "block", "reason": reason})
		else:
			emit(context_output(event_name, reason))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
