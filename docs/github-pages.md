# GitHub 网页版部署

## 使用本仓库部署

1. 将整个仓库放到自己的 GitHub 账号，默认分支为 `main`。不要仅上传 `web/`，因为采集任务还需要 `scripts/`、配置和 `local/backend/`。
2. 打开 Settings → Pages → Build and deployment → Source，选择 **GitHub Actions**。
3. 在 Actions 页面启用工作流，打开 **Update papers and deploy**，点击 **Run workflow**。首次运行会采集论文并部署；可在日志看到每个来源的成功或失败。
4. 部署完成后，通过 Settings → Pages 或工作流的 deployment 链接打开网站。项目站点通常位于 `https://用户名.github.io/仓库名/`。
5. 默认每天北京时间 09:00 计划刷新，无需保持本地电脑开启。GitHub 排队可能延迟，不提供准点保证。

Fork 后将 README 和 `web/index.html` 中的源仓库、站点链接改成自己的地址。站点资源本身使用相对路径，兼容仓库子路径。

## 调整来源与数量

编辑 `config/catalog.json`：

- `mode`：固定为 `ai_latest`，按公共 AI 分类采集，没有个人主题。
- `sources`：五个来源中的一个或多个。
- `lookback_days`：论文库日期窗口，1–30 天，默认 30。
- `candidate_limit`：每个上游列表的候选上限，1–100，默认 100；合并后每来源保留本轮最新至多该数量。
- `recommendation_limit`：每专区每日上限，1–10，默认 10。
- `history_days`：保留推荐历史并用于去重的天数，1–90，默认 30。

修改保存后会触发工作流。每日推荐仅选来源标注日期为当天的论文，最多 10 篇，不以旧论文补足。访客不能在页面修改全站配置。旧的主题模式数据不会迁移到 AI 分类模式。

修改时间需要编辑 `.github/workflows/pages.yml` 的 cron。默认 `0 1 * * *` 是 UTC 01:00，即北京时间 09:00。

## OpenAlex 密钥和访问限制

需要密钥时，在 Settings → Secrets and variables → Actions → New repository secret 中添加 **OPENALEX_API_KEY**。工作流只在采集步骤读取，不写入网页或 JSON。没有配置时仍尝试访问，遇到拒绝或限流会明确报告，不伪装成空搜索结果。

来源接口、配额、GitHub Actions / Pages 的可用性和额度可能变化；请参考提供方说明。公共仓库长期无活动可能停用定时任务，需要重新启用。GitHub Free 支持公共仓库 Pages，私有仓库 Pages 取决于套餐。

## 更新失败与持久化

工作流仅把公开 `web/data/catalog.json` 提交回仓库，保留窗口内论文和推荐历史；仅部署 `web/`。需要 Actions 对内容的写入权限；若分支保护阻止机器人写入，需由仓库所有者配置允许的更新流程。不要通过关闭所有保护来排查。

单个来源失败：保留其旧论文库、显示失败和最后成功更新时间，其他来源继续更新。所有来源失败：部署明确失败状态和保留的旧库，日志给出警告，不伪造新论文；首次运行全失败时站点显示空库。

工作流被终止或部署失败时，上次已部署网站继续存在，页面更新时间用于判断新鲜度。源 API 报错不是 GitHub Pages 本身故障。

## 本地预览静态站点

在仓库根目录执行 `python -m http.server 8787 --bind 127.0.0.1 --directory web`，访问 `http://127.0.0.1:8787/`。这仅用于开发预览，线上不需要该服务器。不要直接双击 HTML 文件，因为浏览器会限制读取 JSON。

## 官方参考

- [GitHub Pages 自定义工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub Actions 定时事件与限制](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Actions Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

## 公共 AI 采集范围

- arXiv：`cs.AI / cs.LG / cs.CL / cs.CV / cs.NE / stat.ML` 分类，首次提交日期降序。
- OpenAlex：主主题属于 Artificial Intelligence 子领域（ID 1702），发表日期降序。
- 顶会索引：11 个 AI 会议的 OpenAlex 论文集，收录有限，非会议官网全集。
- Hugging Face：当前和窗口起始月份的 Daily Papers 社区列表，取有限候选，按论文原始 `publishedAt` 筛日期。社区收录日期不代替论文发表日期。
- OpenReview：最近两年 ICLR、ICML、NeurIPS 已录用主会列表，取有限候选，按 `pdate`（录用日期）筛选。旧 API v1 会议可能缺失。

来源日期按其原始日历日期展示；并不统一转换为北京时间。北京时间只决定采集计划和“当天”日期标签。来源收录延迟或候选上限可能造成遗漏，页面不宣称覆盖当日全部 AI 论文。

浏览器关键词只用于当前页面筛选，不写入站点配置、地址或推荐数据；无统计脚本，不上传搜索历史。公共论文内容中可能自然出现任意研究术语，不代表维护者的个人偏好。

分类接口参考：[arXiv API](https://info.arxiv.org/help/api/user-manual.html)、[OpenAlex 子领域](https://help.openalex.org/data/subfields/)、[Hugging Face OpenAPI](https://huggingface.co/.well-known/openapi.json)、[OpenReview 已录用论文](https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-get-all-notes-for-submissions-reviews-rebuttals-etc)。
