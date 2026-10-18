# 论文来源接口与覆盖边界

核对日期：2026-10-18。以下为本次实际接入方式；外部来源的可用性、收录和接口限制可能变化。

| 来源 | 接口 | 查询与日期语义 | 覆盖与状态 |
| --- | --- | --- | --- |
| arXiv | `https://export.arxiv.org/api/query` | 输入拆为关键词，以 `all:` 和 AND 组合；`submittedDate` 日期区间按 UTC；支持相关性和首次提交日期排序 | 读取 `totalResults`，每次取前 N 条；总数超过 N 时显示覆盖受限 |
| OpenAlex | `https://api.openalex.org/works` | `search.title_and_abstract`（仅标题/摘要，不匹配全文零散提及）；`from_publication_date` / `to_publication_date`；可按 `publication_date` 排序 | 读取 `meta.count`，每次取前 N 条；不做自动翻页；可选密钥仅由后端通过 Authorization 发送 |
| Hugging Face | `https://huggingface.co/api/papers/search` | `q` 和 `limit=120`；在响应候选中按 `paper.publishedAt` 筛日期，再取前 N 条 | 关键词/语义混合搜索；仅 Hub 收录论文，非全量学术库；日期排序只在候选内，总命中数未知，始终说明覆盖受限 |

Hugging Face 搜索不同于 `/api/daily_papers` 列表；本版不通过抓取若干天 Daily Papers 假装执行全库搜索。摘要使用论文原始 `summary`，不以来源提供的 `ai_summary` 冒充摘要。社区提交时间仅在明确提供 `submittedOnDailyAt` 时记录。

arXiv 的 `published` 是首次提交时间，`updated` 是版本更新时间。OpenAlex 的 `updated_date` 是索引维护时间，不作为论文更新日期。来源缺少会刊、摘要或日期时保留缺失状态，不推断或补造。

## 顶会扩展

- `conferences` 通道：使用 DBLP 官方 SPARQL 知识图谱，按会议流查询主会论文标题。覆盖 11 个会议；累计库每页 500 条、保存断点，不限制收录总量。本地实时搜索仍按用户单次请求数量返回。DBLP 只提供年份时保留年份，不补造具体日期；设置精确日期筛选时明确提示该通道不支持。
- `openreview` 通道：`https://api2.openreview.net/notes/search`，实际验证 `term`、`content=all`、`source=forum`、`group=ICLR.cc/ICML.cc/NeurIPS.cc`、`limit=100`。逐组请求，仅保留 `venueid` 精确为 `会议域名/年份/Conference` 的主会论文，排除拒稿、撤稿、workshop 和回复。使用公开 `pdate` 作为筛选日期，`cdate` 单独保存；不把会议年份伪造成日期。每会候选上限 100，日期筛选与排序在候选内，API v1 历史会议可能缺失；总符合条件数量未知。
- OpenReview 官方依据：[搜索接口](https://docs.openreview.net/reference/api-v2/openapi-definition)、[按 venueid 区分已录用与拒稿等状态](https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-get-all-notes-for-submissions-reviews-rebuttals-etc)。实际请求无登录可返回公开记录。
- DBLP 与 OpenAlex 是独立来源；通过明确 DOI 等标识合并，不混用来源 ID。
- DBLP 普通搜索接口可能返回访问验证页；本版使用已实测的官方知识图谱接口 `https://sparql.dblp.org/sparql`，不绕过验证页。

## 结果合并和排序

- 使用规范化 DOI、去除版本号的 arXiv ID 和来源内标识进行精确关联；保留完整来源记录与版本链接。
- OpenAlex 的 arXiv DOI 或明确 arxiv.org 论文地址可关联对应 arXiv ID；标题相似不作为身份依据。
- 支持通过第三条记录连接已有的两个标识分组，合并后仍保留各来源证据。
- 相关性采用排名融合：每个来源贡献 `1 / (60 + 该来源排名)`，同来源取最佳排名。分数仅用于排序，不是事实核验、模型评分或跨接口原始得分比较。
- 日期排序使用展示记录日期；优先使用本次结果，再按 arXiv、OpenReview、顶会索引、OpenAlex、Hugging Face 选择展示记录。不同来源日期含义可能不同，详情中逐来源说明。

## 网络与缓存

- 每源独立请求；arXiv 请求启动至少间隔 3.1 秒，同来源串行，其他来源互不等待。
- 网络超时、429 和暂时性 5xx 最多重试一次；长 Retry-After 不在当前任务中强行重试。请求超时 22 秒，单来源整体等待上限 65 秒。
- 401/403、超时、连接失败、异常响应和真正的空结果分别处理；异常信息不回显密钥或上游响应正文。
- 同一查询与筛选条件的来源结果缓存最多预览 24 小时，每次检索仍实时刷新；失败保留明确标记的旧记录。每源缓存原子替换，损坏缓存不阻止检索。
- 任务状态、缓存与来源结果都不代表阅读全文；本版只获取元数据和摘要，不下载 PDF。

## 官方依据

- [arXiv API 用户手册](https://info.arxiv.org/help/api/user-manual.html)：查询、Atom 字段、日期过滤与请求间隔。
- [OpenAlex 认证](https://help.openalex.org/api/authentication/)：当前基本查询可无密钥使用，密钥为可选；以实际错误响应为准。
- [OpenAlex 过滤](https://help.openalex.org/api/filtering/)：发表日期区间。
- [Hugging Face Hub API](https://huggingface.co/docs/hub/api) 及 [官方 OpenAPI](https://huggingface.co/.well-known/openapi.json)：本次实际读取的 `/api/papers/search` 参数为 `q`（最长 250 字符）和 `limit`（1–120），未列出日期或翻页参数。

访问公开接口的验证不保证未来所有网络环境都可访问。当前实现未启用代理自动配置、账号注册、付费额度或任何消息推送。

## 每日规则排序

每个主题每个通道至多 50 条实时结果，先按可靠标识符合并。排序分数为：45 × 标题关键词覆盖率 + 25 × min(1, 来源融合分 × 61 / 4) + 20 × 1/(1 + 距最新来源日期天数/7) + 10（存在会议记录时）。日期分采用各来源保留的日期，不能视为统一发表时间。先排除去重窗口内已推荐的论文，按配置篇数展示（0 表示展示全部已取得的匹配结果）；成功但覆盖受限的查询不保证全量，跨来源缺少共同标识时不按标题强行去重。

## 日期与关键词范围

所有来源的日期上限为用户结束日期与北京时间今天的较早值。OpenAlex 匹配标题和摘要；DBLP 顶会通道匹配标题，只有年份时不参与精确日期筛选；日期过滤之外，本地再次检查来源日期。关键词匹配不保证论文主旨属于某个研究领域，用户可组合多个关键词缩小范围。
