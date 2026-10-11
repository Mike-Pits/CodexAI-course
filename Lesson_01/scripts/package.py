"""Explicit allowlist: excludes secrets, quota data, caches and virtualenv."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
files = ['README.md', 'AGENTS.md', 'DEPLOY.md', 'CHECKS.md', '.env.example', '.gitignore', '.dockerignore',
         'requirements.txt', 'requirements-dev.txt', 'Dockerfile', 'compose.yaml',
         'compose.local.yaml', 'Caddyfile']
files += [str(p.relative_to(root)) for folder in ('app', 'scripts', 'tests')
          for p in (root / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts
          and p.suffix in ('.py', '.json', '.txt', '.html', '.css', '.js')]
out = root / 'dist' / 'tochka-opory-lesson01.zip'
out.parent.mkdir(exist_ok=True)
with ZipFile(out, 'w', ZIP_DEFLATED) as archive:
    for name in sorted(files):
        archive.write(root / name, f'tochka-opory/{name}')
print(out)
