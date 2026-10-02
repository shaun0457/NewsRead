# EasyRead 界面英文化：给子 agent 的说明

仓库：E:\CursorProject\easyread（Windows，Git Bash 和 PowerShell 都有；Python 用 `.venv/Scripts/python.exe`）。
EasyRead 是本地论文阅读器：把英文论文翻成中文阅读，带划线、笔记、问 AI。现在界面全是中文，要做到：中文系统显示中文，其他系统显示英文。

## 基础设施（已经做好，不要改这些文件）
- 前端：`PR.t("中文原文")` 返回当前语言的文字；带变量写占位符 `PR.t("已导入 {n} 篇", { n: count })`。中文原文就是词典的键。
- 后端：`from .i18n import tr`，`tr("中文 {name}", name=x)`。
- HTML 文件里写死的中文不用改，会自动按整句对照替换（但你负责的 JS 生成的 HTML 字符串要套 PR.t）。
- 英文词典：每组写自己的文件 `easyread/web/i18n/parts/<组名>.json`，格式 `{"中文原文": "English", ...}`，键必须和代码里 PR.t / tr 的第一个参数逐字相同（包括占位符和标点）。不要碰 `easyread/web/i18n/en.json`，最后由主会话合并。
- 检查脚本：`.venv/Scripts/python.exe scripts/i18n_check.py`，它列出"没套 PR.t / tr"的中文字符串（带文件和行号）和"缺英文"的词条。只看你负责的文件那几行（用 grep 过滤）。

## 怎么改
1. 用户能看到的中文字符串都套上 PR.t / tr。模板字符串 `` `已导入 ${n} 篇` `` 改成 `PR.t("已导入 {n} 篇", { n })`。PR.t 的第一个参数必须是普通字符串字面量（双引号或单引号），不能是模板字符串、不能是变量或拼接，否则检查脚本认不出来。
2. 拼接出来的句子尽量改成整句带占位符，不要把半句话分开翻（英文语序不同）。
3. 生成 HTML 的地方：`"<b>" + PR.t("标题") + "</b>"`；如果译文里需要 HTML，可以把 HTML 放进词条（PR.t 返回的是原样字符串），但要保证中英两边标签一致。变量如果是用户内容，在填之前照原来的方式 PR.esc。
4. 不该翻译的中文：在那一行行末加注释 `// i18n-ok`（Python 用 `# i18n-ok`），比如：
   - 和后端输出、存盘数据做比较/匹配的字符串、正则（翻了会坏逻辑）；
   - 发给大模型的提示词；
   - 论文内容本身相关的（例如默认的中文文件名可以保留中文也可以翻，自己判断）。
   拿不准时宁可保守：比较用的值保留原样，只在"显示"的那一步翻。
5. 后端特别注意：有些中文是状态值，会存盘或被前端拿去比较，不能直接 tr（会让中英文切换后对不上）。只 tr 最终显示给人看的消息（报错 message、提示文字）。`raise ...Error("中文")` 这种会显示到界面上的报错要 tr。日志（log.xxx）不翻。
6. 注释不用翻译，也不要改。不要重构、不要改无关代码，保持原来的写法和风格。
7. 改完跑：`node --check <每个改过的 js>`；后端组跑 `PYTHONUTF8=1 .venv/Scripts/python.exe -m unittest discover tests`。最后跑一次检查脚本，确认你负责的文件里"没套"的为 0，且你的词条在 parts 文件里都有英文。
8. 不要 git commit / checkout / stash，不要改你负责范围以外的文件（parts 文件除外）。别的组同时在改其他文件。

## 英文文案风格
- 简短、自然的软件界面英文，句首大写（Sentence case），按钮用动词（"Import", "Retry failed pages"）。不要直译中文的客气话。
- 中文全角标点换成英文标点；中文里的 “” 换成 ""，……换成 …
- 产品名照旧：EasyRead、Claude Code、Codex、DeepSeek、Ollama 等。

## 术语表（各组统一）
| 中文 | English |
|---|---|
| 文献库 | Library |
| 论文 | Paper |
| 阅读页 | Reader |
| 译文 | Translation |
| 原文 | Original / English original（看上下文） |
| 对照 | Bilingual |
| 原页 | Original page（侧栏标题可用 "Page"） |
| 问 AI | Ask AI |
| 笔记 | Notes / Note |
| 划线 / 荧光笔 | Highlight |
| 下划线 | Underline |
| 提问 | Question |
| 页边 / 页边讨论 | Margin / margin discussion |
| 分类 | Folder |
| 在读 / 未读 / 已读 / 星标 | Reading / Unread / Done / Starred |
| 回收站 | Trash |
| 导入 | Import |
| 翻译引擎 | Translation engine |
| 模型 | Model |
| 设置 | Settings |
| 快捷键 | Keyboard shortcuts |
| 读英文原文 | Read the English original |
| 翻译成中文 | Translate to Chinese |
| 只译正文 | Main text only |
| 指定页 | Page range |
| 术语表 | Glossary |
| 用量 / 额度 | Usage / Quota |
| 重新翻译 | Retranslate |
| 失败的页 | Failed pages |
| 离线版（单文件 HTML） | Offline HTML |
| 黄 / 绿 / 蓝 / 红 | Yellow / Green / Blue / Red |

## 最后回报
用 5 行以内告诉主会话：改了哪些文件、加了多少词条、哪些地方加了 i18n-ok 以及原因、有没有拿不准的地方。
