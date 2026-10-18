# Building and source correspondence

This repository preserves the source and scripts used for the
`wifi4-cfi-runtime` build. The historical recipes were captured from the
original WSL build workspace and some of them contain the original
`/mnt/f/wifi_work` path. Those paths are build-root variables, not required
device paths; change them to the location of your checkout before running the
recipes.

## Source layout

The complete corresponding source is split into two release archives:

- Android common kernel at commit
  `0c6055fd2d8b95ec88db7bfd79bfd1e471592215`;
- the exact final external driver trees, final kernel configuration, ABI list,
  patches and build recipes.

The driver archive overlays the kernel working tree as follows:

```text
drivers/rtl8812au -> external module source
drivers/rtl8188eus -> external module source
drivers/rtl8812bu -> external module source
kernel.config -> final .config
abi_symbollist.raw -> ABI input
```

Native `mac80211`, `ath9k_htc` and `mt76x2u` sources come from the pinned
Android common kernel archive. The three Realtek trees in this repository are
already at their final modified state.

## Toolchain

Use the Android Clang tree pinned by `provenance/clang-source-pin.json`:

```text
repository: https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86
commit: 9f759dee5cdc5f85d076c642a192f6a9232f7058
directory: clang-r450784e
```

The original build used WSL, one build job and one linker thread because Full
LTO has a high peak-memory requirement.

## Important limitations

- A newly generated module-signing key changes the kernel and module bytes.
- The published package only matches its paired kernel configuration and
  signer.
- A source rebuild is not expected to be byte-for-byte identical when build
  timestamps or generated signing keys differ.
- This repository does not contain an OEM ramdisk or a redistributable stock
  boot image.

The exact source hashes and changed-file hashes are recorded in
`provenance/build-manifest.json` and `provenance/source-changes.json`.

