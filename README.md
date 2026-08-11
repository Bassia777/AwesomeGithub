# GitHub Trending 每日中文摘要

本项目每天抓取 GitHub Trending 全球、全语言日榜的前 5 个仓库，补充仓库信息，生成简体中文摘要，并通过 Gmail SMTP 发送 HTML 邮件。成功发送后，它会把当天的 Markdown 和 JSON 报告保存到仓库，供长期查询和连续上榜天数计算。

## 运行行为

一次正常运行依次执行：

1. 抓取 `https://github.com/trending?since=daily`，最多重试 3 次，并要求解析出恰好 5 个有效仓库。
2. 使用 GitHub API 补充仓库 README 等信息；单个仓库补充失败时继续使用 Trending 页面已有数据。
3. 读取前一天的 JSON 历史，计算每个仓库的连续上榜天数。
4. 为每个仓库生成不超过 200 个汉字的中文摘要。
5. 渲染并发送 HTML 日报邮件。
6. 仅在邮件发送成功后写入 `reports/history`；GitHub Actions 随后只提交该目录的变更。

日报展示仓库排名、名称与链接、主要语言、Star 数、连续上榜状态和中文摘要。默认范围固定为 `global/all-languages/daily`。

## 架构与 AI 降级策略

程序入口是 `github-trending-digest`。主要模块职责如下：

- `trending`：抓取并解析 GitHub Trending 页面。
- `repository`：通过 GitHub API 补充仓库资料。
- `summarizer`：调用 AI 服务并校验中文摘要。
- `renderer`：生成 HTML 邮件和 Markdown 历史报告。
- `mailer`：通过 `smtp.gmail.com:465` 分别投递邮件。
- `history`：读取连续上榜信息并安全保存 JSON/Markdown 文件。
- `app`：组织上述步骤，并在异常时发送故障通知。

AI 摘要按以下顺序降级：

1. Gemini（默认模型 `gemini-2.5-flash`）
2. GitHub Models（默认模型 `openai/gpt-4.1-mini`）
3. DeepSeek（默认模型 `deepseek-chat`）
4. 仓库原始描述；没有描述时使用固定兜底文本

某个 AI 服务网络异常、鉴权失败、响应格式无效或摘要质量不合格时，会自动尝试下一个服务。GitHub Models 直接使用 Actions 内置的 `GITHUB_TOKEN` 和 `models: read` 权限，不需要创建额外 Secret。

## 必需的 GitHub Actions Secrets

在仓库的 **Settings → Secrets and variables → Actions → New repository secret** 中配置：

| Secret | 用途 |
| --- | --- |
| `GEMINI_API_KEY` | Gemini API 密钥 |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `GMAIL_USERNAME` | 用于发信的完整 Gmail 地址，例如 `digest.sender@gmail.com` |
| `GMAIL_APP_PASSWORD` | Gmail 应用专用密码，不是 Google 账号登录密码 |
| `MAIL_TO` | 一个或多个收件地址，多个地址使用英文逗号分隔 |

当前配置校验要求以上 Secret 均为非空值。`GITHUB_TOKEN` 由 GitHub Actions 自动提供，请勿自行创建同名 Secret。

`MAIL_TO` 单个收件人示例：

```text
reader@example.com
```

多个收件人示例：

```text
alice@example.com,bob@example.com,team@example.org
```

多个收件人会收到彼此独立的私密邮件；每封邮件的 `To` 只包含当前收件人，因此收件人互相看不到地址。重复地址会按不区分大小写的方式去重。

## 配置 Gmail 应用专用密码

1. 登录用于发信的 Google 账号，并启用两步验证。
2. 打开 Google 账号的“应用专用密码”页面。
3. 为本项目新建一个应用专用密码，例如命名为 `GitHub Trending Daily`。
4. 将生成的应用专用密码保存为仓库 Secret `GMAIL_APP_PASSWORD`，将完整 Gmail 地址保存为 `GMAIL_USERNAME`。
5. 如果 Google Workspace 管理员禁用了应用专用密码，需要先联系管理员启用，或改用允许 SMTP 应用登录的账号。

不要在 Issue、提交、日志或聊天中提供真实密码和密钥。本项目的配置过程不需要任何人查看你的真实 Gmail 密码或应用专用密码。

## 本地安装与测试

需要 Python 3.12 或更高版本：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
python -m pytest
```

本地执行真实抓取和发信前，在当前 shell 中设置环境变量。请使用自己的值，不要把真实值提交到仓库：

```bash
export GITHUB_TOKEN='<github-token>'
export GEMINI_API_KEY='<gemini-api-key>'
export DEEPSEEK_API_KEY='<deepseek-api-key>'
export GMAIL_USERNAME='digest.sender@gmail.com'
export GMAIL_APP_PASSWORD='<gmail-app-password>'
export MAIL_TO='reader@example.com'
github-trending-digest
```

也可以把这些 `export` 语句保存在本地 `.env` 后手动加载；`.env` 已被忽略，但仍应限制文件权限并避免复制其内容到终端日志。项目本身不会自动读取 `.env`。

## 第一次手动运行

完成 Secrets 配置后：

1. 打开仓库的 **Actions** 页面。
2. 选择 **GitHub Trending Daily Digest**。
3. 点击 **Run workflow**，选择默认分支并确认运行。
4. 查看测试、生成与发送、历史提交三个步骤的日志，并确认收件箱收到日报。

工作流会明确检出默认分支；即使手动触发时选择了其他 ref，日报历史也只会写回默认分支。

## 定时、时区与可能延迟

工作流使用 `0 0 * * *`，即每天 **00:00 UTC** 触发，对应 **Asia/Shanghai 08:00**。GitHub Actions 的 cron 使用 UTC，不会读取操作系统时区。

GitHub 托管的定时任务可能因平台排队、维护或高峰负载延迟数分钟甚至更久；08:00 是计划触发时间，不是严格送达保证。可以随时通过 **Run workflow** 补跑。工作流设置了 15 分钟超时，同一时间只允许一个 `github-trending-daily` 任务运行，已运行任务不会被新任务取消。

## 历史文件

每次成功发送后会生成：

```text
reports/history/YYYY-MM-DD.json
reports/history/YYYY-MM-DD.md
```

JSON 保存完整结构化数据，包括生成时间、榜单范围、仓库字段、摘要来源和连续上榜天数；Markdown 便于直接在 GitHub 阅读。连续上榜天数只参考紧邻前一天的有效 JSON 报告，缺失、损坏或日期不连续时从 1 天重新计算。

GitHub Actions 只执行 `git add -- reports/history`，没有历史变化时正常退出，不会产生空提交。推送发生冲突时会有限次数拉取并 rebase；无法安全合并时任务失败，不会强制覆盖远端更新。

## 正常与失败行为

正常情况下，测试先通过，然后抓取、摘要、发送邮件并保存历史。只有 `github-trending-digest` 成功退出后，工作流才会提交历史文件。

任一主要阶段失败时，程序会尝试向 `MAIL_TO` 发送主题为“GitHub 热榜日报运行异常”的故障邮件，其中包含失败阶段、尝试次数、已脱敏错误、可能原因和当前 Actions 运行链接。故障运行返回非零状态，不会提交新的历史报告。

有两个需要注意的边界情况：

- 正常日报发送成功、但历史保存失败时，收件人仍会收到日报，随后还会收到故障通知；工作流失败且不会提交不完整历史。
- Gmail 登录或 SMTP 本身不可用时，故障通知也可能无法发送，此时应以 GitHub Actions 日志为准。

## 故障排查

### SMTP 或 Gmail 鉴权失败

- 确认 `GMAIL_USERNAME` 是完整 Gmail 地址，且与创建应用专用密码的账号一致。
- 确认使用的是应用专用密码，而不是 Google 账号登录密码；复制时避免多余空格。
- 确认账号已开启两步验证，Workspace 策略允许应用专用密码。
- 检查 Gmail 是否拒绝登录、收件地址是否有效，以及网络是否能访问 `smtp.gmail.com:465`。
- 修改 Secret 后重新执行 **Run workflow**，不要把 Secret 值打印到日志。

### Trending 页面结构变化

解析器当前依赖 GitHub Trending 的 `article.Box-row` 条目、`h2` 仓库链接、描述段落、`itemprop="programmingLanguage"` 和指向 `/stargazers` 的链接。如果 GitHub 调整页面结构，日志可能出现“expected 5 valid trending repositories”或三次抓取失败。此时应保存不含私人信息的页面结构样本，更新解析器与测试 fixture，而不是降低“必须恰好 5 个仓库”的校验。

### AI 服务降级或摘要来源异常

- 检查 Gemini 和 DeepSeek 密钥是否有效、额度是否充足、API 是否可访问。
- 确认工作流权限包含 `models: read`；GitHub Models 使用内置 `GITHUB_TOKEN`，无需额外密钥。
- 单个提供方失败通常会自动降级。历史 JSON 中的 `summary_source` 可用于确认实际来源。
- 如果所有 AI 服务失败，日报仍可使用仓库描述发送；这属于预期降级，不一定会让 Actions 失败。

### 查看 GitHub Actions 日志

进入 **Actions → GitHub Trending Daily Digest → 对应运行**，按步骤检查：依赖安装、完整测试、生成与发送、历史提交。故障邮件中的 Actions 链接也会指向对应运行。若历史推送失败，重点查看是否存在分支保护、`contents: write` 权限被组织策略覆盖，或远端更新导致 rebase 冲突。

## 安全说明

- 永远不要在代码、README、Issue、PR、提交信息、测试数据或 Actions 日志中输出真实 Secret。
- 使用 GitHub Actions Secrets 保存凭据，并定期轮换 API 密钥和 Gmail 应用专用密码。
- 不要在命令中启用会回显环境变量值的调试模式，例如在加载真实 Secret 后执行 `set -x`。
- 如怀疑 Secret 泄露，应立即在对应服务撤销并重新生成，而不只是从 Git 历史中删除文本。
