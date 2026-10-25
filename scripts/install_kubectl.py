"""Install the checksum-pinned kubectl client used by the VPC bootstrap job."""
import argparse
import hashlib
import json
import os
import platform
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install(directory):
    lock = json.loads((ROOT / "deploy/codebuild/toolchain.lock.json").read_text())
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise RuntimeError("The platform bootstrap toolchain targets Linux amd64")
    with urllib.request.urlopen(lock["kubectl"]["url"], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != lock["kubectl"]["sha256"]:
        raise RuntimeError("kubectl checksum mismatch")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "kubectl"
    target.write_bytes(data)
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

