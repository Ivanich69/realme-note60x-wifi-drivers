# wifi4-v1.0.0

Первый публичный выпуск USB Wi-Fi стека для Realme Note 60x `RMX3938` на
`RMX3938export_15_C.13`.

## В выпуске

- точный kernel `Image` с Full LTO и CFI;
- драйверы RTL8812AU/RTL8814AU, RTL8188EUS, RTL8812BU/RTL8822BU, AR9271 и
  MT7612U;
- 14 подписанных загружаемых модулей;
- firmware для AR9271 и MT7612U;
- Magisk/NetErnels-совместимый ZIP с ручной загрузкой драйверов;
- полные соответствующие исходники, конфигурация, ABI и build recipes;
- host-only инструмент для воспроизведения проверенного boot из собственного
  штатного C.13 boot image.

## Подтверждённый результат

На целевом устройстве подтверждены загрузка ядра, появление драйверов в
NetErnels и работа внешнего Wi-Fi интерфейса, включая monitor mode и frame
injection. Все поддерживаемые семейства адаптеров отдельно не тестировались.

## Контрольные суммы

```text
c7a1a7e7a6d9784d00e7d8f0c18f5ee072b5f006e8696162d2405ac515d305db  Image
946399c4a7a1b02cec28249f936603f53a0151f850c0d38dfae41547aa43ebba  android-common-0c6055fd2d8b95ec88db7bfd79bfd1e471592215.tar.gz
7237ba8851a1ddafb69a24d7751c6d7a917a74da8b3d54694c5ab38f3153c992  realme-note60x-wifi4-driver-sources-and-config.tar.gz
610c83d49709af3890951995c9b016c2c1f050a14f81c44a0d0cefcf6debf2f5  realme-note60x-wifi4-magisk.zip
```

Из собственного точного `boot_b` C.13 и релизного `Image` упаковщик создаёт:

```text
7c67c4b876c7710b2248dca9f7bbe9942087c44365baf7be1cc39cdd83c700a7  realme-note60x-wifi4-boot.img
```

## Совместимость

Используйте выпуск только с `RMX3938export_15_C.13`. Модули предназначены
только для парного релизного ядра. После OTA требуется новый аудит и новая
сборка.

Штатный boot image Realme в релиз не входит. Инструменты проекта не выполняют
прошивку и не обращаются к телефону.
