# SKILLNULL

[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/privacy.yml)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-6f42c1)](https://agentskills.io/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

*A production-minded rule set and deterministic safety toolkit for reliable AI-assisted software development.*

面向 AI 编程助手的开发与交付规则集。把代码改动边界、问题排查、工程实践和交付验证整理成可复用的约束，适用于个人开发与团队协作。

## 包含内容

- [主规则](SKILL.md)：命名、代码组织、兼容性、性能、隐私保护与交付要求。
- [专项规则](rules/)：重复问题深查、路由与容器导航稳定性。
- [工程参考](references/)：吸顶锚点、混合字体对齐、自适应字号与首屏性能优化。
- [门禁脚本](scripts/skillnull_gate.py)：动态读取规则与引用，要求开发前和交付前逐条审查，并保留源码、import、资源路径及 diff 检查。
- [行为评测](evals/skillnull/evals.json)：覆盖作用域、删除授权、重复失败、隐私边界和非开发任务等关键场景。

规则和参考可供 Codex、Cursor 等能够读取本地指令的助手使用。门禁脚本针对 Codex 的事件协议；其他助手需要单独适配。静态检查覆盖有限，交付仍须验证原始操作路径。

## 使用

1. 将整个仓库保存在本机固定目录，保留 `SKILL.md`、`rules/`、`references/` 和 `scripts/` 的相对位置。
2. 在助手的全局指令或技能入口中引用该目录的 `SKILL.md`，要求开发前完整读取，并按触发条件读取专项文件。规则在全局维护，无需复制到每个业务仓库。
3. 本机路径、内部知识库、私有项目映射和环境约定放到根目录的 `SKILL.local.md`。该文件已被 Git 忽略；存在时须与主规则一并读取。

仓库本身不会自动安装全局指令或 Hook。通过软链接接入时，链接应指向整个仓库，确保相对引用和本地扩展可访问。

## 可选门禁

运行依赖：Python 3.10+、Git、ripgrep（`rg`）。仅阅读规则无需安装脚本依赖。

在本机 Hook 配置中，以 Python 调用 `scripts/skillnull_gate.py` 的绝对路径，并传入事件 JSON。脚本从标准输入读取、向标准输出返回 JSON，支持以下事件：

| 事件 | 检查 |
| --- | --- |
| `UserPromptSubmit`、`SessionStart`、`PostCompact` | 重读规则及递归引用，建立或保留会话基线 |
| `PreToolUse` | 重读规则；编辑前校验逐条计划，检查危险删除及部分破坏性命令 |
| `PostToolUse` | 重读规则，发现文件变动，复查空源码、资源路径与 diff |
| `Stop` | 校验最新规则与工作区对应的逐条交付证据；再次触发仍检查 |

脚本按自身真实位置查找 `SKILL.md`、可选 `SKILL.local.md` 和递归引用的本地 Markdown。规则条目与版本由实际内容生成，不固定条数、编号或具体措辞；缺失引用、越界引用与损坏状态不能视为通过。非 Git 目录同样加载规则。Hook 配置中的安装路径由使用者在本机维护，不纳入公共规则。

工具事件的门禁组不设 `matcher`，以覆盖命名空间工具及嵌套调用；保留其他 Hook。支持该字段的宿主可对上下文事件设置 `additionalContextLimit: 0`。脚本自身限制注入长度，较大的规则包改为要求分页完整读取，不发送截断规则。部分专用工具不经过宿主 Hook，因此 Hook 不能作为完整安全边界。

开发任务按 Hook 给出的会话命令运行 `snapshot`，通过 `--offset`、`--limit` 读完 `total_rules` 条。修改前向 `review` 的标准输入提交 JSON：`phase: "plan"`、当前 `policy_revision`、`workspace_revision` 和 `entries`。每条条目包含 `id`、`status`、`reason`、`evidence`；计划状态为 `planned` 或 `not_applicable`。交付前使用 `phase: "delivery"`，状态为 `verified` 或 `not_applicable`，附实际验证证据。不得批量填充空泛结论，也不能用“已读取”代替验证。

规则或引用变化会使旧审查失效；交付审查后的文件或暂存区变化也须重审。条目遗漏、重复、未知、缺证据或仍为待处理状态均阻止通过。真实阻塞允许交付审查标记 `outcome: "incomplete"`、对应条目标记 `blocked` 并提供证据；最终答复须明确未完成。普通非开发问答无需启动审查。

确定性检查继续执行；逐条审查只能强制覆盖、版本和证据字段，不能证明任意自然语言要求的语义执行百分之百正确。语义条款仍由代理核对条件、实际操作和结果，不应宣称脚本已自动验证所有规则。

### 防蒸馏边界

本项目不通过关键词匹配或整轮禁用工具拦截蒸馏；这类方案容易绕过，也会误伤正常维护。公开仓库、已分发文件及已注入模型上下文的内容均不具备保密性。真正需要保护的内容必须保留在本地确定性程序或受控推理环境中，模型只能接收不含私有原文的必要判定结果。

`.privacy.local.json` 只由本地隐私扫描器读取，不会加载进 Skill 上下文。它适合保存需要阻断发布的专属词，不适合保存仍需远程模型理解和执行的完整知识。后者若要保密，只能使用本地模型、受控服务或不向模型提供该知识。

## 验证与贡献

在仓库根目录运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_project.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 scripts/check_private_content.py --history --require-private-terms
git diff --check
```

项目校验器检查目录契约、规则编号、文档链接、评测结构、不可变 CI Action 引用及本地配置隔离。CI 另用固定版本的 Agent Skills 参考实现检查 `SKILL.md`。行为评测目前是可审查的验收契约，不冒充模型基准分数；模型对比应在隔离工作区执行并保存环境、模型和运行次数。

新增规则应说明触发条件、执行约束和验收标准。通用方法保留完整原理与适用边界；文件名、正文、示例、注释与待发布历史均应检查脱敏。公司信息、真实业务名称、内部地址、个人路径及凭据不得进入公开内容，本机专属信息保存在已忽略的本地扩展中。

## 私有内容门禁

- 本地词库：在已忽略的 `.privacy.local.json` 中保存 JSON 字符串数组，填写需要阻断的公司、项目、模块、域名及其他内部标识；勿提交该文件。POSIX 系统须限制为仅当前用户可读写，例如 `chmod 600 .privacy.local.json`。
- 提交检查：执行 `git config --local core.hooksPath .githooks` 启用本仓库 Hook。已有 Hook 时先合并其调用，避免覆盖。提交前扫描暂存区实际内容和历史，提交说明另行检查。
- CI：GitHub Actions 在 push、pull request 和手动运行时扫描当前文件及完整历史。将同一词库配置为仓库 Secret `PRIVATE_CONTENT_TERMS_JSON`，并在分支保护中将 `Private content` 设为必需检查。

检查覆盖专属词、个人绝对路径、内网地址、常见凭据格式及误跟踪的本地配置。二进制、过大文件和软链接需要人工审查，默认阻断。日志不输出命中文本，私有文件名会隐藏。词库缺失或历史不完整也会阻断。

扫描器支持 `--format json`，便于外部门禁读取稳定字段。Hook 不持久化原始提示词，只保存删除授权判定、检查基线、版本和审查证据，并在成功结束时清除会话状态。证据须简洁脱敏，不得包含密钥、用户隐私或私有词库；扫描词库不会注入模型上下文。

Fork PR 无法读取仓库 Secret，完整检查会阻断；维护者须先审查变更，再通过受信任分支运行。不要用 `pull_request_target` 执行未审查代码来绕过限制。本地 Hook 可被跳过，CI 在推送后运行，因此首次公开前仍须本地审查。通用经验还须确认成果归属及保密约定，自动扫描无法识别所有未知业务语义。

## 安全边界

规则文本与公开脚本不具备保密性。Codex Hook 会读取 Git 工作区、执行本地 `git`/`rg` 并写入权限受限的会话状态；隐私扫描器读取 Git 内容和本地词库；项目校验器读取仓库文档与评测文件。它们均不主动联网。CI 安装固定提交版本的公开校验器，任何第三方依赖升级都应经代码审查。

## 开源协议

本项目的规则、文档和脚本采用 [MIT License](LICENSE)。允许使用、修改和再分发；分发时须保留版权与许可声明。完整条款以 `LICENSE` 为准。
