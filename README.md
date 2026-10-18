<p align="center">
  <img src="docs/assets/papertrail-banner.svg" alt="PaperTrail · 论文踪迹：从一个问题，发现新的论文线索" width="100%">
</p>

<h1 align="center">PaperTrail · 论文踪迹</h1>

<p align="center">
  从多处发现论文，在一处继续探索。<br>
  多源检索 · 顶会追踪 · 每日推荐 · 历史回看
</p>

<p align="center">
  <a href="https://Maverickquliushang.github.io/PaperTrail/"><strong>打开网页版 ↗</strong></a> &nbsp; · &nbsp;
  <a href="code/local/README.md"><strong>安装本地版</strong></a> &nbsp; · &nbsp;
  <a href="docs/github-pages.md">部署自己的站点</a>
</p>

<p align="center">
  <a href="#你可以用它做什么">功能一览</a> ·
  <a href="#两种版本的区别">版本选择</a> ·
  <a href="#三条开始路线">快速开始</a> ·
  <a href="#数据从哪里来又到哪里为止">数据边界</a> ·
  <a href="CHANGELOG.md">变更记录</a>
</p>

---

## 让论文线索连起来

一篇论文可能先出现在预印本平台，再进入会议公开清单，最后被学术索引收录。PaperTrail 把这些入口放在同一个工作台：按来源找论文，按会议追踪进展，按日期回看已收录内容。

**一个项目，两种使用方式。** 无需安装就能浏览公共论文库，也可以在自己的电脑上运行完整服务。

<table>
<tr>
<td width="50%" valign="top">

### ☁ 网页版 · 打开就看

适合日常浏览与分享。GitHub Pages 提供页面，GitHub Actions 定时采集，浏览器搜索已收录论文。

**无需安装 · 公共 AI 论文库 · 按日 / 按年回看**

[进入论文工作台 →](https://Maverickquliushang.github.io/PaperTrail/)

</td>
<td width="50%" valign="top">

### ⌂ 本地版 · 自己掌握

适合实时检索与个人配置。React + FastAPI 在本机运行，共享累计库能力，可按需连接飞书。

**实时来源请求 · 个人推荐配置 · 可选群聊入口**

[查看安装与启动说明 →](code/local/README.md)

</td>
</tr>
</table>

## 你可以用它做什么

| 线索 | 在 PaperTrail 中继续探索 |
| :--- | :--- |
| **01 / 跨来源发现** | 在 arXiv、OpenAlex、Hugging Face、顶会索引和 OpenReview 五个专区之间切换；累计库合并重复记录。 |
| **02 / 跟进会议** | 按会议进入二级目录，以 DBLP 历史索引和会议官网公开清单互补，查看收录数量与补采进度。 |
| **03 / 按时间回看** | 浏览全部日期或指定日期的已收录论文，显示明确篇数；顶会按年份浏览，历史内容持续保留。 |
| **04 / 找得更顺手** | 网页版支持标题、摘要 BM25 检索及常见中文术语转换，也能按日期或标题排序。 |
| **05 / 看清来源** | 查看原文、可用的 PDF 链接、来源状态和覆盖范围；OpenReview 分开呈现已录用与公开投稿。 |

> **每日推荐的含义：** 公共版按来源标注的论文日期展示已收录内容，符合条件的论文全部展示，不设“每专区最多 10 篇”。数量代表本站已收录量，不代表来源当日全部论文。本地版另支持个人主题推荐配置。

### 五个入口，各有所长

| 来源专区 | 主要用途 | 浏览时要知道 |
| :--- | :--- | :--- |
| **arXiv** | 追踪预印本与研究新线索 | 日期使用首次提交日期（UTC）。 |
| **OpenAlex** | 补充学术文献索引与发表信息 | 独立专区，使用发表日期；与 DBLP 会议索引不同。 |
| **Hugging Face** | 浏览社区收录的机器学习论文 | 社区收录范围有限，不能等同于全量论文。 |
| **顶会索引** | 联合会议官网公开清单与 DBLP 历史索引 | 按会议、年份浏览；公开清单可早于正式出版。 |
| **OpenReview** | 浏览评审平台的论文记录 | 默认已录用，可切换公开投稿；公开不等于已录用。 |

点击论文标题进入 PaperTrail 站内详情页，查看完整摘要、作者与来源时间记录；卡片底部保留“查看原文”和 PDF。阅读已展开摘要时，后台继续加载，但等待点击“更新列表”后才更新眼前的排序。

**会议目录** &nbsp; NeurIPS · ICML · ICLR · CVPR · ICCV · ECCV · ACL · EMNLP · AAAI · IJCAI · KDD

[查看来源接口说明](docs/local/source-apis.md) · [查看网页版采集与覆盖说明](docs/github-pages.md)

---

## 两种版本的区别

| | 本地版 `code/local/` | 网页版 `code/web/` |
|---|---|---|
| 运行方式 | Windows 本机 React + FastAPI | GitHub Pages 静态 HTML / CSS / JavaScript |
| 需要开电脑吗 | 服务运行期间需要 | 不需要，GitHub Actions 定时采集 |
| 搜索范围 | 实时检索 + 本机累计论文库（历史分页补采） | 搜索已采集的标题、摘要；不是全站实时检索 |
| 检索排序 | 来源相关性融合、日期、标题 | 浏览器 BM25、日期、标题 |
| 来源 | 同右；累计论文库共用会议分类、官网、DBLP、OpenReview 双入口 | 五个专区；顶会同时采集 DBLP 和官方公开清单，OpenReview 区分已录用与公开投稿 |
| 每日推荐 | 累计库支持全部日期和按日回看已收录论文；另有可配置主题的个人推荐 | 公共 AI 分类；09:00 更新；支持全部日期、各日篇数和历史回看 |
| 个人偏好 | 本机保存，包含独立专区配置与历史 | 站点共享同一论文库；访客筛选不会改变全站计划 |
| 飞书机器人 | 可选；自行创建应用、授权、绑定 | **不包含** |
| 中文输入 | 飞书入口提供术语转换；网页实时搜索使用所填关键词 | 检索框提供常见中文术语转换，未知限定明确提示 |
| AI / 向量检索 | 未接入 | 未接入 |

两版累计库共用采集和展示代码，包括历史断点续采、每日数量、会议分类和 OpenReview 双入口。本地版从工作台的“打开本地累计论文库”进入，数据独立保存在 `code/local/data/library/`。

两个版本不要求同时运行，也不共享个人配置。本仓库的 `code/local/` 是干净的源代码发行版，不包含开发者的密钥、聊天信息、绑定关系或推荐历史。首次安装需自行配置。

## 三条开始路线

**只想浏览论文：** 打开上方网页版，选择来源专区，留空浏览最新 AI 论文，或输入关键词。默认日期从新到旧，也可选择 BM25。“每日推荐”按论文日期浏览；顶会提供“按年浏览”。会议进度卡片也可点击进入对应会议。

**想要实时检索：** 下载仓库，在 `code/local/` 中按[本地说明](code/local/README.md)安装 Python、Node.js、uv 及锁定依赖，然后双击 `启动PaperTrail.cmd`。

**想拥有自己的站点：** Fork 仓库，启用 Actions，将 Settings → Pages → Source 设置为 GitHub Actions，手动运行 `Update papers and deploy`。编辑 `code/config/catalog.json` 调整公开采集配置。详见[部署说明](docs/github-pages.md)。

## 数据从哪里来，又到哪里为止

公共版不预设个人研究主题。顶会累计库同时检查 11 个会议官方公开清单与 DBLP 历史索引，无需 OpenAlex Key；官网列出的论文不必等待正式出版或 DBLP 收录。顶会可按会议年份筛选，官网与 DBLP 分别显示覆盖状态，任一入口完成不代表全会议已收齐。OpenAlex 是独立学术索引专区，仍按发表日期筛选。OpenReview 默认“已录用”，可切换“公开投稿”。累计论文库不设统一起始日期；每日日期列表补齐收录范围内的零记录日期并标注“暂无收录”。没有具体日期的记录不补造月日。

来源日期不晚于北京时间当天；DBLP 仅提供年份时保留年份，不伪造月日，不参与精确日期筛选或当日推荐。arXiv 展示首次提交日期（UTC），OpenReview 已录用展示录用日期，其他公开投稿展示创建日期，其他来源使用发表日期；这些日期含义不同。来源更新可能延迟，09:00 采集也无法覆盖全天后续发布的论文。失败会明确显示，旧数据不会伪装成新采集结果。详见[网页版覆盖说明](docs/github-pages.md)。

计划北京时间每天 09:00 运行，GitHub Actions 可能排队延迟；公共仓库长期无活动时，定时任务可能被停用。见 [GitHub 定时任务文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 给开发者的地图

```text
code/                       唯一当前开发入口
  local/                    React + FastAPI 本地版、依赖锁与启动器
  web/                      静态网页版及公开论文数据；仅此目录部署到 Pages
  scripts/                  两版共享采集器、版本打包脚本
  config/                   公开采集配置
  tests/                    共享采集与网页测试
  project-env.ps1           实际环境初始化逻辑
  .tmp/、.cache/            临时文件与工具缓存（不提交）
docs/                       设计、部署和本地版使用说明
output/                     本轮可公开验证报告；私人结果放 private/ 并忽略
versions/                   已验证版本索引、说明、哈希；ZIP 仅本地保存
.github/workflows/          必须位于仓库根的 GitHub CI 配置
README.md、CHANGELOG.md     项目入口和变更记录
project-env.ps1             转调 code/ 的便利入口
```

当前版本以 `code/local/pyproject.toml` 为准，现为 **0.3.0**；本次新增站内论文详情页，依赖版本保持不变。目录迁移说明见 [结构说明](docs/project-structure.md)，验证与归档见 [版本索引](versions/INDEX.md)。`versions/` 只保存交付快照，不在其中继续开发。

从仓库根目录开始开发：

```powershell
. .\project-env.ps1
Set-Location code
npm test
uv run --project local --locked python -m unittest discover -s tests -p 'test_*.py'
```

安装并启动本地版：在仓库根目录运行 `& .\code\local\setup.ps1`，完成后双击 `code/local/启动PaperTrail.cmd`。目录迁移前的 `local/` 路径及旧快捷方式需要改到 `code/local/`；网页 URL 和服务 API 保持不变。

浏览器端无服务端依赖。**每日采集任务使用 Python**，复用本地版来源适配器，在 GitHub Actions 执行后结束；它不是长期运行的后端。无数据库、无模型 API、无第三方 CDN 脚本。

论文内容及链接的权利属于各自作者与提供方，本项目不托管论文 PDF。
