# PaperTrail · 论文踪迹

从一个问题，发现新的论文线索。提供 **本地完整版** 和 **GitHub 网页版**，按需要选择。

- **[打开网页版](https://Maverickquliushang.github.io/PaperTrail/)**：无需安装，浏览论文库和每日推荐。
- **[安装本地版](code/local/README.md)**：实时访问论文来源，独立配置推荐，可选飞书群聊。
- [网页版部署说明](docs/github-pages.md) · [功能对比](docs/editions.md)

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

## 最快开始

**只想浏览论文：** 打开上方网页版，选择来源专区，留空浏览最新 AI 论文，或输入关键词。默认日期从新到旧，也可选择 BM25。“每日推荐”按论文日期浏览；顶会提供“按年浏览”。会议进度卡片也可点击进入对应会议。

**想要实时检索：** 下载仓库，在 `code/local/` 中按[本地说明](code/local/README.md)安装 Python、Node.js、uv 及锁定依赖，然后双击 `启动PaperTrail.cmd`。

**想拥有自己的站点：** Fork 仓库，启用 Actions，将 Settings → Pages → Source 设置为 GitHub Actions，手动运行 `Update papers and deploy`。编辑 `code/config/catalog.json` 调整来源与数量。详见[部署说明](docs/github-pages.md)。

## 论文与推荐边界

公共版不预设个人研究主题。顶会累计库同时检查 11 个会议官方公开清单与 DBLP 历史索引，无需 OpenAlex Key；官网列出的论文不必等待正式出版或 DBLP 收录。顶会可按会议年份筛选，官网与 DBLP 分别显示覆盖状态，任一入口完成不代表全会议已收齐。OpenAlex 是独立学术索引专区，仍按发表日期筛选。OpenReview 默认“已录用”，可切换“公开投稿”。累计论文库不设统一起始日期；每日日期列表补齐收录范围内的零记录日期并标注“暂无收录”。没有具体日期的记录不补造月日。

来源日期不晚于北京时间当天；DBLP 仅提供年份时保留年份，不伪造月日，不参与精确日期筛选或当日推荐。arXiv 展示首次提交日期（UTC），OpenReview 已录用展示录用日期，其他公开投稿展示创建日期，其他来源使用发表日期；这些日期含义不同。来源更新可能延迟，09:00 采集也无法覆盖全天后续发布的论文。失败会明确显示，旧数据不会伪装成新采集结果。详见[网页版覆盖说明](docs/github-pages.md)。

计划北京时间每天 09:00 运行，GitHub Actions 可能排队延迟；公共仓库长期无活动时，定时任务可能被停用。见 [GitHub 定时任务文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 仓库结构

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

当前版本以 `code/local/pyproject.toml` 为准，现为 **0.2.0**；沿用已有 API 版本，统一此前滞后的包元数据，不升级依赖。目录迁移说明见 [结构说明](docs/project-structure.md)，验证与归档见 [版本索引](versions/INDEX.md)。`versions/` 只保存交付快照，不在其中继续开发。

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
