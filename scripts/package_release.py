"""Build audited release assets from tracked files in a clean Git checkout."""
import argparse
import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    def git(*cmd):
        return subprocess.check_output(['git', '-C', str(root), *cmd])
    if git('status', '--porcelain', '--untracked-files=no').strip():
        raise SystemExit('Commit all tracked changes before packaging.')
    manifest = json.loads((root/'extension/extension.json').read_text(encoding='utf8'))
    version = manifest['version']
    package = root/'extension/build/dist'/f"{manifest['name']}_v{version}.eext"
    with zipfile.ZipFile(package) as z:
        assert z.testzip() is None
        packaged = json.loads(z.read('extension.json'))
        assert packaged == manifest
        assert packaged['uuid'] == '614d6f012b51458ab00809eca0f34305'
        for item in ('dist/index.js','dist/notes.js','dist/panel.js','iframe/notes.html','iframe/notes.css','iframe/index.html','iframe/panel.css','images/logo.png','LICENSE','NOTICE'):
            assert item in z.namelist(), item
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package, output/package.name)
    commit = git('rev-parse', 'HEAD').decode().strip()
    timestamp = time.gmtime(int(git('show','-s','--format=%ct','HEAD')))[0:6]
    members = git('ls-files','-z').decode().split('\0')
    selected = [p for p in members if p and (p.startswith(('backend/','knowledge/','docs/')) or p in {'scripts/start_backend.py','CONTRIBUTING.md','README.md','LICENSE','NOTICE','THIRD_PARTY_NOTICES.md','CHANGELOG.md','SECURITY.md'})]
    backend = output/f'pcb-workbench-backend-v{version}.zip'
    with zipfile.ZipFile(backend, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(selected):
            assert '.env' not in Path(name).parts and not any(x in Path(name).parts for x in ('output','.venv','__pycache__'))
            info=zipfile.ZipInfo(name,timestamp);info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,git('show',f'HEAD:{name}'))
        info=zipfile.ZipInfo('BUILD_COMMIT.txt',timestamp)
        z.writestr(info,commit+'\n')
    with zipfile.ZipFile(backend) as z:
        assert z.testzip() is None
    assets = [output/package.name,backend]
    (output/'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in assets),encoding='ascii')
    print(json.dumps({'version':version,'commit':commit,'assets':[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in assets]},indent=2))


if __name__ == '__main__':
    main()
