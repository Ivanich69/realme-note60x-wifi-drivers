# wifi4-v1.0.0

[English](RELEASE_NOTES_wifi4-v1.0.0_EN.md) |
[Русский](RELEASE_NOTES_wifi4-v1.0.0.md)

First public release of the external USB Wi-Fi stack for the Realme Note 60x
`RMX3938` running `RMX3938export_15_C.13`.

## Included in this release

- exact Full LTO and CFI kernel `Image`;
- RTL8812AU/RTL8814AU, RTL8188EUS, RTL8812BU/RTL8822BU, AR9271 and MT7612U
  driver support;
- 14 signed loadable modules;
- firmware for AR9271 and MT7612U;
- Magisk/NetErnels-compatible companion ZIP with guarded manual loading;
- complete corresponding source, final configuration, ABI records and build
  recipes;
- host-only tool that reproduces the reviewed boot image from a user-owned
  exact C.13 stock boot.

## Confirmed behavior

The target device has confirmed kernel boot, module visibility in NetErnels
and external Wi-Fi operation, including monitor mode and frame injection. Not
every listed adapter family and hardware revision has been tested separately.

## Release checksums

```text
c7a1a7e7a6d9784d00e7d8f0c18f5ee072b5f006e8696162d2405ac515d305db  Image
946399c4a7a1b02cec28249f936603f53a0151f850c0d38dfae41547aa43ebba  android-common-0c6055fd2d8b95ec88db7bfd79bfd1e471592215.tar.gz
7237ba8851a1ddafb69a24d7751c6d7a917a74da8b3d54694c5ab38f3153c992  realme-note60x-wifi4-driver-sources-and-config.tar.gz
610c83d49709af3890951995c9b016c2c1f050a14f81c44a0d0cefcf6debf2f5  realme-note60x-wifi4-magisk.zip
```

The host-only repacker produces the following result from the exact released
`Image` and the accepted user-owned C.13 stock boot:

```text
7c67c4b876c7710b2248dca9f7bbe9942087c44365baf7be1cc39cdd83c700a7  realme-note60x-wifi4-boot.img
```

## Compatibility boundary

Use this release only with `RMX3938export_15_C.13`. The module ZIP is specific
to the paired release kernel. A firmware update requires a fresh ABI,
configuration and boot compatibility review.

The release does not redistribute a Realme stock boot image. Project tooling
does not flash a phone or access a physical device.
