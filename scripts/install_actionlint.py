"""Install the checksum-pinned actionlint binary used by CI."""
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


def install(directory):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise RuntimeError("The CI actionlint toolchain targets Linux amd64")
    lock = json.loads((ROOT / "deploy/codebuild/actionlint.lock.json").read_text())
    with urllib.request.urlopen(lock["url"], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != lock["sha256"]:
        raise RuntimeError("actionlint archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = archive.getmember("actionlint")
        if not member.isfile():
            raise RuntimeError("Invalid actionlint archive")
        binary = archive.extractfile(member).read()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "actionlint"
    target.write_bytes(binary)
    target.chmod(0o755)
    if os.environ.get("GITHUB_PATH"):
        with open(os.environ["GITHUB_PATH"], "a") as stream:
            stream.write(str(directory.resolve()) + "\n")
    print(target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    install(parser.parse_args().directory)

