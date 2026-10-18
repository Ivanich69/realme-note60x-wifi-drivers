"""Verify and unpack one pinned archive into a new host build directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    record = json.loads(Path(str(args.archive) + ".json").read_text())
    digest = hashlib.sha256()
    with args.archive.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    assert args.archive.stat().st_size == record["bytes"]
    assert digest.hexdigest() == record["sha256"]
    destination = args.destination.resolve()
    marker = destination / ".host-source-archive.json"
    if marker.exists():
        assert json.loads(marker.read_text())["sha256"] == record["sha256"]
        print(json.dumps({"destination": str(destination), "reused": True}), flush=True)
        return
    assert not destination.exists() or not any(destination.iterdir()), "Destination is not empty"
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.archive, "r:gz") as archive:
        members = archive.getmembers()
        assert len(members) < 150000
        total = 0
        for member in members:
            name = PurePosixPath(member.name)
            assert not name.is_absolute() and ".." not in name.parts
            assert member.isdir() or member.isfile() or member.issym() or member.islnk()
            member.mode &= 0o777
            if member.isfile():
                assert member.size < 1024 ** 3
                total += member.size
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                assert not link.is_absolute()
                base = name.parent if member.issym() else PurePosixPath(".")
                normalized = os.path.normpath(str(base / link))
                assert normalized != ".." and not normalized.startswith("../")
        assert total < 8 * 1024 ** 3
        archive.extractall(destination, members=members)
    marker.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"destination": str(destination), "files": len(members),
                      "uncompressed_bytes": total, "sha256": digest.hexdigest()}), flush=True)


if __name__ == "__main__":
    main()
