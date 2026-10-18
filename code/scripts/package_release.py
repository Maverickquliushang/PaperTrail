"""Archive an already validated delivery, using an explicit public-file scope."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / 'code'
TREES = (
    '.github/workflows', 'docs', 'code/scripts', 'code/tests', 'code/web',
    'code/local/backend', 'code/local/tests', 'code/local/frontend/src',
    'code/local/frontend/tests',
)
FILES = (
    '.gitattributes', '.gitignore', 'README.md', 'CHANGELOG.md', 'project-env.ps1',
    'code/project-env.ps1', 'code/package.json', 'code/config/catalog.json',
    'code/local/README.md', 'code/local/.env.example', 'code/local/.gitignore',
    'code/local/pyproject.toml', 'code/local/uv.lock', 'code/local/project-env.ps1',
    'code/local/setup.ps1', 'code/local/start.ps1', 'code/local/launch.ps1',
    'code/local/启动PaperTrail.cmd', 'code/local/停止PaperTrail.cmd',
    'code/local/frontend/index.html', 'code/local/frontend/package.json',
    'code/local/frontend/package-lock.json', 'code/local/frontend/tsconfig.json',
    'code/local/frontend/vite.config.ts', 'code/local/frontend/playwright.config.ts',
)
EXCLUDED = {'.tmp', '.cache', '__pycache__', '.venv', 'node_modules', '.secrets', 'AGENTS.md'}


def public_files():
    paths = {ROOT / name for name in FILES}
    for name in TREES:
        paths.update(p for p in (ROOT / name).rglob('*') if p.is_file())
    result = []
    for p in sorted(paths):
        relative = p.relative_to(ROOT)
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT):
            raise ValueError(f'External or symbolic file: {relative}')
        if EXCLUDED.intersection(relative.parts) or p.suffix == '.pyc' or relative.as_posix() == 'docs/validation.md':
            continue
        if p.name.startswith('.env') and p.name != '.env.example':
            raise ValueError(f'Private configuration in archive scope: {relative}')
        if not p.is_file():
            raise FileNotFoundError(relative)
        result.append(p)
    return result


def write_zip(target, files, base):
    expected = {p.relative_to(base).as_posix() for p in files}
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in files:
            archive.write(p, p.relative_to(base).as_posix())
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == expected
        assert archive.testzip() is None
    with target.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return f'{digest}  {target.name}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation-report', required=True, help='Path relative to project root')
    args = parser.parse_args()
    report = (ROOT / args.validation_report).resolve()
    if not report.is_relative_to(ROOT / 'output') or not report.is_file():
        parser.error('A completed public validation report under output/ is required.')
    version = tomllib.loads((CODE / 'local/pyproject.toml').read_text())['project']['version']
    for name in ['package.json', 'package-lock.json']:
        package = json.loads((CODE / 'local/frontend' / name).read_text())
        assert package['version'] == version, 'Frontend version is out of sync'
    lock = tomllib.loads((CODE / 'local/uv.lock').read_text())
    assert next(p['version'] for p in lock['package'] if p['name'] == 'papertrail') == version
    destination = ROOT / 'versions' / f'v{version}'
    destination.mkdir(exist_ok=False)
    source = public_files()
    static = [p for p in source if p.is_relative_to(CODE / 'web')]
    hashes = [write_zip(destination / f'PaperTrail-v{version}-source.zip', source, ROOT),
              write_zip(destination / f'PaperTrail-v{version}-web.zip', static, CODE / 'web')]
    (destination / 'SHA256SUMS.txt').write_text('\n'.join(hashes)+'\n', encoding='utf-8')
    notes = (f'# PaperTrail v{version}\n\n'
             '当前源码位于 code/。本次归档对应 CHANGELOG 同版本条目。\n\n'
             f'源码包 {len(source)} 个文件；静态站点包 {len(static)} 个文件。ZIP 文件列表与 CRC 已校验，SHA-256 见同目录校验文件。\n\n'
             '源码恢复：解压到独立项目目录，按 README 与 code/local/README 安装锁定依赖。'
             '本地版需要 Python 3.11–3.13、Node.js 20.19+ 或 22.12+、uv；未生成本地版独立免安装运行包。\n\n'
             '静态包解压后可部署到静态托管，或用 python -m http.server 本地预览；不要直接双击 HTML。'
             '后续自动采集需要源码包中的 GitHub Actions，静态 ZIP 自身不会更新。\n\n'
             '不包含个人配置、飞书绑定、虚拟环境或开发缓存。仅包含公开论文元数据，不包含论文 PDF。\n\n'
             '## 验证记录\n\n' + report.read_text(encoding='utf-8') + '\n')
    (destination / 'RELEASE_NOTES.md').write_text(notes, encoding='utf-8')
    index = ROOT / 'versions/INDEX.md'
    prefix = index.read_text(encoding='utf-8') if index.exists() else '# 已验证版本\n\nZIP 仅保存在维护者本地，不提交普通 Git 仓库。\n\n'
    entry = f'- [v{version}](v{version}/RELEASE_NOTES.md)：统一 code/ 结构与两版发布入口；校验见 [SHA256SUMS](v{version}/SHA256SUMS.txt)。\n'
    index.write_text(prefix + entry, encoding='utf-8')
    print(f'Archived {len(source)} source files and {len(static)} web files to versions/v{version}/')


if __name__ == '__main__':
    main()
