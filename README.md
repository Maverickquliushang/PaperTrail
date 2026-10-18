# PaperTrail · 论文踪迹

从一个问题，发现新的论文线索。提供 **本地完整版** 和 **GitHub 网页版**，按需要选择。

- **[打开网页版](https://Maverickquliushang.github.io/PaperTrail/)**：无需安装，浏览论文库和每日推荐。
- **[安装本地版](local/README.md)**：实时访问论文来源，独立配置推荐，可选飞书群聊。
- [网页版部署说明](docs/github-pages.md) · [功能对比](docs/editions.md)

## 两种版本的区别

| | 本地版 `local/` | 网页版 `web/` |
|---|---|---|
| 运行方式 | Windows 本机 React + FastAPI | GitHub Pages 静态 HTML / CSS / JavaScript |
| 需要开电脑吗 | 服务运行期间需要 | 不需要，GitHub Actions 定时采集 |
| 搜索范围 | 每次向选择的来源发起实时请求 | 搜索已采集的标题、摘要；不是全站实时检索 |
| 检索排序 | 来源相关性融合、日期、标题 | 浏览器 BM25、日期、标题 |
| 来源 | arXiv、OpenAlex、Hugging Face、顶会索引、OpenReview | 同五个采集通道，各来源限额和收录范围仍适用 |
| 每日推荐 | 可在网页修改主题、时间、篇数及去重设置 | 公共 AI 分类；09:00、每专区当日最多 10 篇 |
| 个人偏好 | 本机保存，包含独立专区配置与历史 | 站点共享同一论文库；访客筛选不会改变全站计划 |
| 飞书机器人 | 可选；自行创建应用、授权、绑定 | **不包含** |
| 中文输入 | 飞书入口提供术语转换；网页实时搜索使用所填关键词 | 检索框提供常见中文术语转换，未知限定明确提示 |
| AI / 向量检索 | 未接入 | 未接入 |

两个版本不要求同时运行，也不共享个人配置。本仓库的 `local/` 是干净的源代码发行版，不包含开发者的密钥、聊天信息、绑定关系或推荐历史。首次安装需自行配置。

## 最快开始

**只想浏览论文：** 打开上方网页版，选择来源专区，留空浏览最新 AI 论文，或输入关键词。默认日期从新到旧，也可选择 BM25。点击“每日推荐”切换日期，查看已生成记录。

**想要实时检索：** 下载仓库，在 `local/` 中按[本地说明](local/README.md)安装 Python、Node.js、uv 及锁定依赖，然后双击 `启动PaperTrail.cmd`。

**想拥有自己的站点：** Fork 仓库，启用 Actions，将 Settings → Pages → Source 设置为 GitHub Actions，手动运行 `Update papers and deploy`。编辑 `config/catalog.json` 调整来源与数量。详见[部署说明](docs/github-pages.md)。

## 论文与推荐边界

公共版不预设个人研究主题。采集 AI 分类、AI 会议和社区论文列表，保留最近 30 天的有限候选。每日推荐仅选来源标注日期为当天的论文，每来源最多 10 篇；当天无新论文时不使用旧论文补足。论文检索页仍可浏览近期记录。

日期不晚于北京时间当天。arXiv 展示首次提交日期（UTC），OpenReview 展示录用日期，其他来源使用发表日期；这些日期含义不同。来源更新可能延迟，09:00 采集也无法覆盖全天后续发布的论文。失败会明确显示，旧数据不会伪装成新采集结果。详见[网页版覆盖说明](docs/github-pages.md)。

计划北京时间每天 09:00 运行，GitHub Actions 可能排队延迟；公共仓库长期无活动时，定时任务可能被停用。见 [GitHub 定时任务文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 仓库结构

```text
local/                     本地完整版的源代码、依赖锁与启动器
web/                       纯静态网页；唯一发布到 Pages 的目录
web/data/                  公共论文元数据、推荐历史与中文术语表
scripts/update_catalog.py  Actions 批量采集，不启动服务或飞书
config/catalog.json        站点所有者的公开采集配置
.github/workflows/         每日采集部署、双版本自动测试
tests/                     网页检索与采集回归测试
docs/                      版本选择和部署说明
```

浏览器端无服务端依赖。**每日采集任务使用 Python**，复用本地版来源适配器，在 GitHub Actions 执行后结束；它不是长期运行的后端。无数据库、无模型 API、无第三方 CDN 脚本。

论文内容及链接的权利属于各自作者与提供方，本项目不托管论文 PDF。
