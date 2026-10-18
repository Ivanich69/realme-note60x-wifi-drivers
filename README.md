# Realme Note 60x USB Wi-Fi drivers

Unofficial external USB Wi-Fi support for the Realme Note 60x (`RMX3938`) on
`RMX3938export_15_C.13` (Android 15).

The project pairs a rebuilt Android 13 GKI 5.15 kernel with loadable USB Wi-Fi
modules. The published source variant is `wifi4-cfi-runtime`, built with Full
LTO and CFI-compatible callback wrappers.

## Supported driver families

| Chipset family | Module | Monitor/injection path |
| --- | --- | --- |
| RTL8812AU / RTL8814AU | `88XXau.ko` | Present in the aircrack-ng driver |
| RTL8188EUS | `8188eu.ko` | Present in the aircrack-ng driver |
| RTL8812BU / RTL8822BU | `88x2bu.ko` | Present in the imported driver |
| AR9271 | `ath9k_htc.ko` | Native mac80211 path |
| MT7612U | `mt76x2u.ko` | Native mac80211 path |

The module package has been reported to load on the target phone. Individual
adapter revisions, USB power delivery, firmware loading, monitor mode and frame
injection still need testing with the specific adapter being used.

## Exact target

- Device: Realme Note 60x (`RMX3938`)
- Firmware: `RMX3938export_15_C.13`
- Kernel base: Android common kernel commit
  `0c6055fd2d8b95ec88db7bfd79bfd1e471592215`
- Kernel tag: `android13-5.15-2025-03_r2`
- Expected release: `5.15.178-android13-8-00006-g0c6055fd2d8b-ab13363910`
- Compiler: Android Clang `r450784e`, pinned in
  `provenance/clang-source-pin.json`

These modules are ABI-, configuration- and signer-specific. They are not
generic modules for other Realme firmware or other 5.15 kernels.

## Repository contents

- `drivers/` — exact imported and modified Realtek driver trees.
- `config/` — final kernel configuration and ABI symbol list.
- `patches/` — compatibility and callback-CFI patches.
- `build-recipes/` — scripts and validation data used for the build.
- `module-template/` — source files for the Magisk/NetErnels module package;
  compiled modules and firmware are release assets.
- `provenance/` — source pins, hashes and the final build manifest.
- `licenses/` — firmware and regulatory database license notices.

No stock `boot.img`, partition dump, NV data, FDL loader, device identifier or
OEM firmware image is included in this repository.

## Source and releases

Each binary release should contain all of the following assets:

1. `realme-note60x-wifi4-magisk.zip` — the module package.
2. `realme-note60x-wifi4-driver-sources-and-config.tar.gz` — exact external
   driver sources, configuration and historical build recipes.
3. `android-common-0c6055fd2d8b95ec88db7bfd79bfd1e471592215.tar.gz` — the
   complete base kernel source used for the build.
4. `SHA256SUMS.txt` — checksums for all release assets.

See [BUILDING.md](BUILDING.md) for source layout and reproducibility notes.

## Responsible use

Monitor mode and frame injection are dual-use capabilities. Use them only on
networks and equipment you own or are explicitly authorized to test. This
repository is intended for driver development, interoperability testing and
authorized security research. It is not affiliated with or endorsed by
Realme, Google, MediaTek, Qualcomm, Kali Linux or the driver maintainers.

## License

Kernel and driver code is distributed under GPL-2.0 terms. Firmware remains
under its separate license in `licenses/`. See [THIRD_PARTY.md](THIRD_PARTY.md)
before redistributing binaries.

