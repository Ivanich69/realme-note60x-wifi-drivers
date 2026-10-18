# Building and source correspondence

[English](BUILDING.md) | [Русский](BUILDING_RU.md)

This document is for developers who want to verify the origin of the release
artifacts or repeat the `wifi4-cfi-runtime` build.

Ordinary users do not need to compile the kernel. The exact `Image` is a
release asset, and [`tools/repack_own_boot.py`](tools/repack_own_boot.py)
reproduces the reviewed boot image from a user-owned C.13 stock boot.

## Pinned source revisions

| Component | Repository | Commit |
| --- | --- | --- |
| Android common kernel | `https://android.googlesource.com/kernel/common` | `0c6055fd2d8b95ec88db7bfd79bfd1e471592215` |
| Android Clang | `https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86` | `9f759dee5cdc5f85d076c642a192f6a9232f7058` |
| rtl8812au | `https://github.com/aircrack-ng/rtl8812au.git` | `734485506a30d6237c2deaad666a19f8ca5379f2` |
| rtl8188eus | `https://github.com/aircrack-ng/rtl8188eus.git` | `af3bf004458f76b7aec33e9ba552cd382ed1f5c3` |
| rtl8812bu | `https://github.com/morrownr/88x2bu-20210702.git` | `d31ffa827bb95b8a436c2a469b5163b634ac4333` |

The base kernel tag is `android13-5.15-2025-03_r2`. Machine-readable pins are
stored in [`SOURCE_MANIFEST.json`](SOURCE_MANIFEST.json) and
[`provenance/`](provenance/).

## Complete corresponding source

The release splits the source into two archives because the Android common
tree is large:

1. `android-common-0c6055fd2d8b95ec88db7bfd79bfd1e471592215.tar.gz`
   contains the complete pinned kernel/common tree.
2. `realme-note60x-wifi4-driver-sources-and-config.tar.gz` contains the final
   external driver trees, kernel configuration, ABI list, patches and build
   recipes.

The second archive overlays the kernel work tree as follows:

```text
drivers/rtl8812au  -> external RTL8812AU/RTL8814AU module source
drivers/rtl8188eus -> external RTL8188EUS module source
drivers/rtl8812bu  -> external RTL8812BU/RTL8822BU module source
kernel.config      -> final .config
abi_symbollist.raw -> ABI input
```

The native mac80211, ath9k_htc and mt76x2u sources come from the pinned Android
common archive.

## Toolchain and build resources

Compiler identity:

```text
Android (8508608, based on r450784e) clang version 14.0.7
Target: x86_64-unknown-linux-gnu
```

The final kernel uses Full LTO. The successful build intentionally limited
parallelism to one build job and one linker thread because the final `vmlinux`
link has a high memory peak. Approximately 28.5 GiB of RAM and 16 GiB of swap
were available at build start.

## Historical build recipes

[`build-recipes/`](build-recipes/) preserves the actual project stages:

- `baseline-recipe/` — initial GKI and vendor ABI preparation;
- `recipe/wifi2/` — Full LTO and the initial TX-path CFI fixes;
- `recipe/wifi3/` — monitor callback CFI fixes;
- `recipe/wifi4/` — final runtime callback wrappers;
- `recipe/*-audit/` — source and compiled-object callback audits;
- `recipe/shared/` — common artifact, signature and AVB checks;
- `recipe/tools/avbtool.py` — pinned AOSP avbtool.

These scripts are retained as build evidence. Some refer to the original
`/mnt/f/wifi_work` WSL build root and must be parameterized for a new checkout.
They contain no automatic phone deployment or flashing step.

## Final configuration and ABI records

- [`config/kernel.config`](config/kernel.config) — final kernel configuration;
- [`config/abi_symbollist.raw`](config/abi_symbollist.raw) — ABI symbol list;
- [`abi/Module.symvers`](abi/Module.symvers) — exported symbol versions;
- [`abi/module-signing-cert.x509`](abi/module-signing-cert.x509) — public
  certificate matched to the released kernel and modules.

No private module-signing key is published.

## wifi4 source changes

The final changes are summarized by:

- [`patches/realtek-compat.patch`](patches/realtek-compat.patch);
- [`patches/runtime-callback-cfi.patch`](patches/runtime-callback-cfi.patch).

They adapt the external Realtek drivers to the target Android 5.15 APIs and
fix callback type mismatches that become fatal under Control Flow Integrity.
The radio algorithms were not broadly rewritten; the modifications focus on
kernel API boundaries, typed wrappers and callback registration sites.

## Artifact validation

The final host-side validation included:

- kernel release and configuration checks;
- ABI comparison against the stock vendor module set;
- imports/CRC, vermagic, BTF and CFI checks;
- PKCS#7 module signatures and certificate binding;
- dependency ordering for the 14 modules inside the ZIP;
- integrity checks for all three firmware payloads;
- 128 monitor TX boundary test cases;
- an audit of 1337 callback assignments across the external drivers;
- rebuilt LLVM object inspection for the modified sources;
- AVB hash-footer verification with a negative corruption test;
- confirmation that no partition image is embedded in the module ZIP.

Exact inputs and changed-file hashes are recorded in
[`provenance/build-manifest.json`](provenance/build-manifest.json) and
[`provenance/source-changes.json`](provenance/source-changes.json).

## Why a fresh build may have a different SHA-256

The complete source can reproduce the functionality, but a fresh build is not
automatically byte-identical. The result may vary because of:

- build timestamps and absolute paths;
- host tool versions;
- generated headers;
- a newly generated module-signing key;
- archive ordering and metadata.

A new signing key changes both the kernel and every signed `.ko`. Modules
signed by a new random key cannot be paired with the released `Image`.

Use the released `Image` and the repacker below when exact binary identity is
required.

## Repacking a user-owned C.13 boot image

### Windows

```powershell
python .\tools\repack_own_boot.py `
  .\boot_b-stock-C13.img `
  .\Image `
  .\out\realme-note60x-wifi4-boot.img
```

### Linux / WSL

```bash
./tools/repack-own-boot.sh \
  ./boot_b-stock-C13.img \
  ./Image \
  ./out/realme-note60x-wifi4-boot.img
```

Accepted inputs:

```text
stock boot SHA256: 4432fa1827b9f4cb12816d646d6b4be08b10d65537bda9f5d2c10b554a53bf4f
kernel Image SHA256: c7a1a7e7a6d9784d00e7d8f0c18f5ee072b5f006e8696162d2405ac515d305db
```

Expected output:

```text
size:   67108864 bytes
SHA256: 7c67c4b876c7710b2248dca9f7bbe9942087c44365baf7be1cc39cdd83c700a7
AVB:    hash footer, algorithm NONE, verified by bundled avbtool
```

The tool works entirely on the host. It has no device connection, deployment
or flashing code.

## Publication boundaries

The repository deliberately excludes:

- the Realme stock boot image and OEM ramdisk;
- full or partial user partition dumps;
- NV, IMEI and serial-number data;
- firmware-specific FDL loaders;
- private signing keys;
- third-party APK files.

Wi-Fi firmware is distributed separately from the GPL code under the notices
listed in [`THIRD_PARTY.md`](THIRD_PARTY.md) and [`licenses/`](licenses/).
