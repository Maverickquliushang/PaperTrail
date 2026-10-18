# 项目结构与版本维护

PaperTrail 是一个项目，提供本地 React + FastAPI 和 GitHub Pages 静态网页两种运行方式。`code/` 是唯一当前开发入口；两版通过同级共享采集器与网页累计库复用功能，不建立嵌套 Git 仓库。

## 本次整理

原 `local/`、`web/`、`scripts/`、`tests/`、`config/`、Node 测试清单及环境脚本整体移入 `code/`。内部相对关系保持，论文数据及采集断点原样移动。原 `local/docs/` 整理到根目录 `docs/local/`。`.git/` 与 `.github/` 留在根目录。

私人原始运行目录与这个公开发行工作区是同一产品的不同用途副本。此次整理公开发行工作区，不导入私人密钥、绑定、推荐历史或配置，也不覆盖仍在使用的私人副本。下载者只需本仓库，不依赖那个私人目录。

## 环境与命令

根目录 `project-env.ps1` 只转调 `code/project-env.ps1`；两者从自身路径推导位置，可重复加载。两版共享开发命令在 `code/` 执行。本地版命令在 `code/local/` 执行并加载该目录环境，依赖位于 `.venv/` 与 `frontend/node_modules/`。它们属于 `code/` 内的实际应用目录，不另复制开发环境。

- 静态页面预览：仓库根目录 `python -m http.server 8787 --bind 127.0.0.1 --directory code/web`。
- 共享测试：`code/` 中 `npm test`、`uv run --project local --locked python -m unittest discover -s tests -p 'test_*.py'`。
- 后端测试：`code/local/` 中 `uv run --locked python -m pytest -q --basetemp .tmp/pytest`。
- 本地前端构建：`code/local/frontend/` 中 `npm run build`。
- 本地启动：`code/local/start.ps1` 或同目录双击启动器；安装命令见本地版 README。

GitHub Actions 的运行目录同步改为 `code/`，只发布 `code/web/`，线上 URL 不增加 `/code/web/`。使用旧版的启动快捷方式时，请重新指向 `code/local/启动PaperTrail.cmd`。

## 版本与归档

版本号权威来源为 `code/local/pyproject.toml`。后端 API 直接读取；前端 package.json、package-lock.json 和 uv.lock 的本项目版本需同步。修复用补丁号、新增兼容功能用次版本号；纯整理不自动升级版本。此次沿用现有 API 的 0.2.0 并纠正包元数据仍为 0.1.0 的不一致。

开发中先记入 CHANGELOG 的“未发布”。通过对应测试后在 `output/` 写公开验证报告，然后从任意工作目录执行：

```powershell
& <项目根目录>\code\local\.venv\Scripts\python.exe <项目根目录>\code\scripts\package_release.py --validation-report output/layout-verification.md
```

脚本生成 `versions/v版本号/` 下的源码 ZIP、静态网页 ZIP、版本说明和 SHA256SUMS.txt，检查 ZIP 内容及校验和并更新索引。归档已存在时拒绝覆盖；历史版本不直接修改。源码包按明确目录和文件范围选取，排除 AGENTS、私人配置、开发依赖、缓存、临时文件和历史归档。静态包包含公开论文库，不包含后端或飞书。

本地版没有独立免安装运行包，源码归档仍需按锁文件安装依赖。ZIP 默认不提交普通 Git 仓库；索引、说明和哈希可提交，包仅保存在维护者本地。归档不等于创建 GitHub Release。
