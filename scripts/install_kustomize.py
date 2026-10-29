#!/usr/bin/env python3
"""Install the pinned Kustomize binary after checking its release SHA256."""
import argparse
import hashlib
import json
import os
import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def install(directory, tool="kustomize"):
    lock = json.loads((ROOT / 'deploy/kubernetes/toolchain.lock.json').read_text())[tool]
    system = platform.system().lower()
    machine = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    name = f"kustomize_v{lock['version']}_{system}_{machine}.tar.gz" if tool == "kustomize" else f"kubeconform-{system}-{machine}.tar.gz"
    asset = lock['assets'].get(name)
    if not asset or len(asset['sha256']) != 64:
        raise RuntimeError('This platform has no verified Kustomize archive in toolchain.lock.json')
    directory = Path(directory).expanduser().resolve(); directory.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(asset['url'], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != asset['sha256']:
        raise RuntimeError('Kustomize archive checksum mismatch')
    import io
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        member = archive.getmember(tool)
        if not member.isfile(): raise RuntimeError('Invalid Kustomize archive')
        binary = directory / tool
        binary.write_bytes(archive.extractfile(member).read())
    binary.chmod(0o755)
    if os.environ.get('GITHUB_PATH'):
        with open(os.environ['GITHUB_PATH'], 'a') as path_file: path_file.write(str(directory) + '\n')
    print(binary)
    return binary

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--directory', default=str(ROOT / 'deploy/generated/tools'))
    p.add_argument('--tool', choices=['kustomize', 'kubeconform'], default='kustomize')
    a=p.parse_args();install(a.directory,a.tool)
