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
- `community_feed_days`：Hugging Face 社区列表的抓取月份回溯，1–30 天，默认 30；仅用于选择要读取的月份，不限制检索日期，也不淘汰历史论文。
- `candidate_limit`：非会议来源近期种子列表的请求大小，1–100；会议历史另用游标/偏移量持续翻页；arXiv 和 OpenAlex 当日列表也单独翻页。此配置不限制论文库总量和每日展示数量。
- `history_days`：保留推荐历史并用于去重的天数，1–90，默认 30。

修改保存后会触发工作流。每日推荐仅选来源标注日期为当天的论文，不限制展示篇数，不以旧论文补足。访客不能在页面修改全站配置。旧的主题模式数据不会迁移到 AI 分类模式。

修改时间需要编辑 `.github/workflows/pages.yml` 的 cron。默认 `0 1 * * *` 是 UTC 01:00，即北京时间 09:00。

## OpenAlex 密钥和访问限制

需要密钥时，在 Settings → Secrets and variables → Actions → New repository secret 中添加 **OPENALEX_API_KEY**。工作流只在采集步骤读取，不写入网页或 JSON。没有配置时仍尝试访问，遇到拒绝或限流会明确报告，不伪装成空搜索结果。

来源接口、配额、GitHub Actions / Pages 的可用性和额度可能变化；请参考提供方说明。公共仓库长期无活动可能停用定时任务，需要重新启用。GitHub Free 支持公共仓库 Pages，私有仓库 Pages 取决于套餐。

## 更新失败与持久化

工作流把公开 `web/data/catalog.json` 及 `web/data/papers/` 分片提交回仓库，累计保留历史论文，并保留配置天数内的推荐历史；仅部署 `web/`。需要 Actions 对内容的写入权限；若分支保护阻止机器人写入，需由仓库所有者配置允许的更新流程。不要通过关闭所有保护来排查。

单个来源失败：保留其历史论文库、显示失败和最后成功更新时间，其他来源继续更新。所有来源失败：部署明确失败状态和保留的旧库，日志给出警告，不伪造新论文；首次运行全失败时站点显示空库。

工作流被终止或部署失败时，上次已部署网站继续存在，页面更新时间用于判断新鲜度。源 API 报错不是 GitHub Pages 本身故障。

## 本地预览静态站点

在仓库根目录执行 `python -m http.server 8787 --bind 127.0.0.1 --directory web`，访问 `http://127.0.0.1:8787/`。这仅用于开发预览，线上不需要该服务器。不要直接双击 HTML 文件，因为浏览器会限制读取 JSON。

## 官方参考

- [GitHub Pages 自定义工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub Actions 定时事件与限制](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Actions Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

## 公共 AI 采集范围

- arXiv：`cs.AI / cs.LG / cs.CL / cs.CV / cs.NE / stat.ML` 分类，首次提交日期降序，不设近期时间窗口。
- OpenAlex：主主题属于 Artificial Intelligence 子领域（ID 1702），发表日期降序，无起始日期限制。
- 顶会索引：11 个会议使用 DBLP 官方 SPARQL 知识图谱，按论文标识排序后逐页采集，不设起始日期。排除 DBLP 明确标注的 workshop、Findings、演示、教程和整本论文集记录；索引分类不是独立录用核验。来源收录有限，非会议官网全集。
- Hugging Face：当前和窗口起始月份的 Daily Papers 社区列表，取有限候选，按论文原始 `publishedAt` 筛日期。社区收录日期不代替论文发表日期。
- OpenReview：已录用读取最近两年 ICLR、ICML、NeurIPS 主会列表；公开投稿读取上一年、本年、下一年会议公开的投稿入口（兼顾下一届提前投稿）。每个会议年度和状态取有限候选，不设 30 天日期窗口。已录用使用 `pdate`，其他状态使用 `cdate`（创建日期，不代表首次公开日期）。从会议组声明的 venueid 映射识别状态，不确定时标记未知；只读公开记录，不访问私有投稿，旧 API v1 会议可能缺失。

来源日期按其原始日历日期展示；并不统一转换为北京时间。北京时间只决定采集计划和“当天”日期标签。来源收录延迟或候选上限可能造成遗漏，页面不宣称覆盖当日全部 AI 论文。

浏览器关键词只用于当前页面筛选，不写入站点配置、地址或推荐数据；无统计脚本，不上传搜索历史。公共论文内容中可能自然出现任意研究术语，不代表维护者的个人偏好。

分类接口参考：[arXiv API](https://info.arxiv.org/help/api/user-manual.html)、[OpenAlex 子领域](https://help.openalex.org/data/subfields/)、[Hugging Face OpenAPI](https://huggingface.co/.well-known/openapi.json)、[OpenReview 已录用论文](https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-get-all-notes-for-submissions-reviews-rebuttals-etc)。

## 历史论文与二级目录

检索库没有统一的 30 天限制。每次有限取数后，已收录记录持续保留；因此“不设起始日期”不等于一次导入全部历史论文。新建站点可能只覆盖各接口返回的候选，页面顶部显示总收录量，来源面板分别报告各会议和索引的状态。

顶会路由示例：`#/conferences/search/all`、`#/conferences/search/CVPR`、`#/conferences/daily/ICML`。切换检索/推荐保留会议选择，刷新或分享链接也保留二级目录。每日展示全部符合当天日期的已采集论文；日期下拉框按当前来源和会议显示去重篇数。切换来源保留搜索/推荐模式及已选日期。

OpenReview 路由：`#/openreview/search/accepted`（默认）、`#/openreview/search/public`。公开投稿包含所有已采集的公开状态，并非只有在审。综合搜索默认排除仅由 OpenReview 提供且未录用的记录；若同一论文也由 arXiv 等来源收录，仍可在相应来源检索。公开投稿的每日列表单独保存、无篇数截断，不表示录用或质量认可。

DBLP 仅有年份的记录显示“年份（仅年份）”，不补造日期；排序使用年份，设置精确开始/结束日期时排除此类记录。DBLP 通常无摘要，只能匹配其提供的标题；通过 DOI 与其他索引精确合并后可能获得摘要。参考 [DBLP 搜索 API](https://dblp.org/faq/13501473.html) 和 [DBLP 元数据许可](https://dblp.org/db/about/copyright.html)。

访问验证页、429 或拒绝访问会显示失败；DBLP 出现验证时本轮停止后续 DBLP 请求，不绕过验证，其他索引继续采集。即使自动采集失败，二级目录中的 DBLP 历年目录链接仍可用于手动浏览。

## 历史补采与增量更新

会议收录总数无上限。DBLP 官方 SPARQL 接口 `https://sparql.dblp.org/sparql` 每页 500 条，按稳定论文标识使用 keyset 分页。只查询指定会议流中的 Inproceedings，并排除明确标注的 workshop / Findings 等。顶会历史库不再请求 OpenAlex，不需要 OpenAlex Key；单独的 OpenAlex AI 专区仍是独立来源。

每轮最多运行 10 分钟以留出保存和部署时间，各会议轮流读取一页，已完成页面和断点共同保存。来源返回限流或访问错误时暂停后次日重试。每天 09:00 分页检查 DBLP 索引并按唯一标识增量合并；DBLP 没有在这里提供变更流，因此扫描到已收录论文时更新元数据，新标识才增加收录数量，不把重扫说成新增。当前图谱遍历完成不代表会议官网全集。

Actions 每小时 UTC 第 17 分钟检查可续接的历史补采，已完成或尚在退避期则跳过。本地版在程序运行期间每小时续接，两版使用相同的分页器和独立数据目录。

论文按会议分组、每 500 条写一个内容寻址 JSON 分片，选择单会议只加载涉及的分片；全来源检索仍需加载全部已收录数据。收录数是去重后的论文数；进度中的“检查条数”可能包含重复或被排除记录，不能当作新增数。

每日列表不再裁剪为 10 篇。采集不完整会在日期数量旁明确标注；数量是本站实际取得的数据，不能视为所有来源当日发表总数。

官方接口说明：[DBLP SPARQL 服务](https://blog.dblp.org/2024/09/09/introducing-our-public-sparql-query-service/)。DBLP 通常仅提供年份，不能据此判断当天发表；不会伪造日期来填充每日推荐。
