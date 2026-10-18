"""Download pinned public sources/toolchain onto the PC. No execution."""

import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".reference/realme-note60x/kernel-build-inputs"
OUT.mkdir(exist_ok=True)
PINS = [
    ("common-0c6055fd2d8b.tar.gz",
     "https://android.googlesource.com/kernel/common/+archive/0c6055fd2d8b95ec88db7bfd79bfd1e471592215.tar.gz"),
    ("clang-r450784e-9f759dee.tar.gz",
     "https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/9f759dee5cdc5f85d076c642a192f6a9232f7058/clang-r450784e.tar.gz"),
]


def fetch(name, url):
    destination = OUT / name
    record_path = OUT / (name + ".json")
    if destination.exists() and record_path.exists():
        record = json.loads(record_path.read_text())
        if hashlib.sha256(destination.read_bytes()).hexdigest() == record["sha256"]:
            print(json.dumps({"file": name, "reused": True}), flush=True)
            return
        raise ValueError(f"Existing archive differs: {name}")
    pending = OUT / (name + ".partial")
    digest = hashlib.sha256()
    count, checkpoint = 0, 0
    started = time.monotonic()
    with urllib.request.urlopen(url, timeout=60) as response, pending.open("wb") as stream:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            count += len(block)
            if count > 2 * 1024 ** 3:
                raise ValueError("Archive exceeds 2 GiB limit")
            digest.update(block)
            stream.write(block)
            if count - checkpoint >= 64 * 1024 ** 2:
                print(json.dumps({"file": name, "downloaded_MiB": count // 1024 ** 2}), flush=True)
                checkpoint = count
    pending.rename(destination)
    record = {"file": name, "url": url, "bytes": count,
              "sha256": digest.hexdigest(), "elapsed_seconds": round(time.monotonic() - started, 2)}
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    for archive in PINS:
        fetch(*archive)
    tools_pin = ROOT / "build/realme-note60x/build-tools-pin.json"
    if tools_pin.exists():
        tools = json.loads(tools_pin.read_text())
        fetch("build-tools-linux-x86-083e34d8.tar.gz", tools["archive_url"])
