#!/usr/bin/env python3
"""Install the pinned Helm (or kubeconform) binary after checking its SHA256 against deploy/helm/toolchain.lock.json."""
import argparse
import hashlib
import io
import json
import os
import platform
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def install(directory, tool="helm"):
    lock = json.loads((ROOT / 'deploy/helm/toolchain.lock.json').read_text())[tool]
    system = platform.system().lower()
    machine = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    name = f"helm-v{lock['version']}-{system}-{machine}.tar.gz" if tool == "helm" else f"kubeconform-{system}-{machine}.tar.gz"
    asset = lock['assets'].get(name)
    if not asset or len(asset['sha256']) != 64:
        raise RuntimeError('This platform has no verified ' + tool + ' archive in deploy/helm/toolchain.lock.json')
    directory = Path(directory).expanduser().resolve(); directory.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(asset['url'], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != asset['sha256']:
        raise RuntimeError(tool + ' archive checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        # Helm archives hold linux-amd64/helm; kubeconform holds kubeconform at the top level.
        member = next((m for m in archive.getmembers() if m.isfile() and Path(m.name).name == tool), None)
        if member is None: raise RuntimeError('Invalid ' + tool + ' archive')
        binary = directory / tool
        binary.write_bytes(archive.extractfile(member).read())
    binary.chmod(0o755)
    if os.environ.get('GITHUB_PATH'):
        with open(os.environ['GITHUB_PATH'], 'a') as path_file: path_file.write(str(directory) + '\n')
    print(binary)
    return binary

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--directory', default=str(ROOT / 'deploy/generated/tools'))
    p.add_argument('--tool', choices=['helm', 'kubeconform'], default='helm')
    a = p.parse_args(); install(a.directory, a.tool)
