#!/usr/bin/env python3
"""Build the reviewed RMX3938 C.13 wifi4 boot image on the host only."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


PARTITION_SIZE = 67_108_864
PAGE_SIZE = 4_096
EXPECTED_STOCK_SHA256 = (
    "4432fa1827b9f4cb12816d646d6b4be08b10d65537bda9f5d2c10b554a53bf4f"
)
EXPECTED_IMAGE_SHA256 = (
    "c7a1a7e7a6d9784d00e7d8f0c18f5ee072b5f006e8696162d2405ac515d305db"
)
EXPECTED_OUTPUT_SHA256 = (
    "7c67c4b876c7710b2248dca9f7bbe9942087c44365baf7be1cc39cdd83c700a7"
)
AVB_SALT = "e573fa787f00107fe0f36e7b0dcbab42f56e3e957c691f3a39be7c64b83877fe"
AVB_PROPERTIES = (
    "com.android.build.boot.os_version:13",
    "com.android.build.boot.fingerprint:"
    "realme/RMX3938/RE6095:13/TP1A.220624.014/U.R4T2.1763369163:"
    "user/release-keys",
    "com.android.build.boot.security_patch:2025-04-05",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"ERROR: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def run_avbtool(avbtool: Path, *arguments: object) -> None:
    command = [sys.executable, str(avbtool), *map(str, arguments)]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        details = (result.stdout + result.stderr).strip()
        fail(f"avbtool failed ({result.returncode}): {details}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Combine the exact released wifi4 kernel Image with a user-owned "
            "RMX3938 C.13 stock boot image. This host-only tool never accesses "
            "or flashes a phone."
        )
    )
    parser.add_argument("stock_boot", type=Path, help="exact stock C.13 boot image")
    parser.add_argument("kernel_image", type=Path, help="released wifi4 Image")
    parser.add_argument("output_boot", type=Path, help="output boot image")
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    stock_path = args.stock_boot.resolve()
    image_path = args.kernel_image.resolve()
    output_path = args.output_boot.resolve()
    repository = Path(__file__).resolve().parents[1]
    avbtool = repository / "build-recipes" / "recipe" / "tools" / "avbtool.py"

    require(stock_path.is_file(), f"stock boot image not found: {stock_path}")
    require(image_path.is_file(), f"kernel Image not found: {image_path}")
    require(avbtool.is_file(), f"bundled avbtool not found: {avbtool}")
    require(output_path not in (stock_path, image_path), "output must not overwrite an input")

    stock = stock_path.read_bytes()
    image = image_path.read_bytes()
    require(len(stock) == PARTITION_SIZE, "stock boot must be exactly 64 MiB")
    require(
        digest(stock) == EXPECTED_STOCK_SHA256,
        "stock boot does not match RMX3938export_15_C.13 boot_b",
    )
    require(
        digest(image) == EXPECTED_IMAGE_SHA256,
        "kernel Image does not match the wifi4 release",
    )
    require(image[56:60] == b"ARM\x64", "kernel file has no ARM64 Image magic")

    header = bytearray(stock[:PAGE_SIZE])
    require(header[:8] == b"ANDROID!", "input has no Android boot magic")
    require(struct.unpack_from("<I", header, 40)[0] == 4, "expected boot header v4")
    require(struct.unpack_from("<I", header, 12)[0] == 0, "expected an empty boot ramdisk")
    require(
        struct.unpack_from("<I", header, 1580)[0] == 0,
        "expected no embedded GKI boot signature",
    )
    struct.pack_into("<I", header, 8, len(image))

    raw = header + image
    raw.extend(bytes((-len(raw)) % PAGE_SIZE))
    require(len(raw) < PARTITION_SIZE - 69_632, "insufficient room for AVB metadata")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wifi4-repack-", dir=output_path.parent) as work:
        # avbtool resolves the descriptor name "boot" to boot.img during
        # verification, so keep this exact basename inside the temporary dir.
        temporary_output = Path(work) / "boot.img"
        temporary_output.write_bytes(raw)
        command = [
            "add_hash_footer",
            "--image",
            temporary_output,
            "--partition_size",
            PARTITION_SIZE,
            "--partition_name",
            "boot",
            "--hash_algorithm",
            "sha256",
            "--algorithm",
            "NONE",
            "--salt",
            AVB_SALT,
            "--flags",
            0,
            "--rollback_index",
            0,
            "--rollback_index_location",
            0,
        ]
        for item in AVB_PROPERTIES:
            command.extend(("--prop", item))
        run_avbtool(avbtool, *command)
        run_avbtool(avbtool, "verify_image", "--image", temporary_output)

        final = temporary_output.read_bytes()
        require(len(final) == PARTITION_SIZE, "unexpected output size")
        require(
            final[PAGE_SIZE : PAGE_SIZE + len(image)] == image,
            "kernel payload changed during packaging",
        )
        output_sha256 = digest(final)
        require(
            output_sha256 == EXPECTED_OUTPUT_SHA256,
            "output differs from the reviewed working boot image",
        )
        os.replace(temporary_output, output_path)

    print(f"Created and verified: {output_path}")
    print(f"SHA256: {EXPECTED_OUTPUT_SHA256}")
    print("Host-only operation complete. No device was accessed.")


if __name__ == "__main__":
    main()
