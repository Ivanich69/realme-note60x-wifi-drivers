# Сборка и соответствие исходников

**Русский** | [English](BUILDING.md)

Этот документ предназначен для разработчиков, которые хотят проверить
происхождение артефактов или повторить сборку `wifi4-cfi-runtime`.

Для обычного пользователя повторная компиляция не нужна: точный `Image`
публикуется в релизе, а [`tools/repack_own_boot.py`](tools/repack_own_boot.py)
воспроизводит проверенный boot из собственного штатного образа C.13.

## Закреплённые исходники

| Компонент | Репозиторий | Commit |
| --- | --- | --- |
| Android common kernel | `https://android.googlesource.com/kernel/common` | `0c6055fd2d8b95ec88db7bfd79bfd1e471592215` |
| Android Clang | `https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86` | `9f759dee5cdc5f85d076c642a192f6a9232f7058` |
| rtl8812au | `https://github.com/aircrack-ng/rtl8812au.git` | `734485506a30d6237c2deaad666a19f8ca5379f2` |
| rtl8188eus | `https://github.com/aircrack-ng/rtl8188eus.git` | `af3bf004458f76b7aec33e9ba552cd382ed1f5c3` |
| rtl8812bu | `https://github.com/morrownr/88x2bu-20210702.git` | `d31ffa827bb95b8a436c2a469b5163b634ac4333` |

Тег базового ядра: `android13-5.15-2025-03_r2`.

Полные машинные пины находятся в [`SOURCE_MANIFEST.json`](SOURCE_MANIFEST.json)
и [`provenance/`](provenance/).

## Соответствующие исходники релиза

Исходники разделены на два архива из-за их размера:

1. `android-common-0c6055fd2d8b95ec88db7bfd79bfd1e471592215.tar.gz` —
   полное базовое дерево kernel/common.
2. `realme-note60x-wifi4-driver-sources-and-config.tar.gz` — итоговые внешние
   драйверы, `.config`, ABI symbol list, патчи и рецепты.

После распаковки второй архив накладывается на рабочее дерево следующим
образом:

```text
drivers/rtl8812au  -> внешний модуль RTL8812AU/RTL8814AU
drivers/rtl8188eus -> внешний модуль RTL8188EUS
drivers/rtl8812bu  -> внешний модуль RTL8812BU/RTL8822BU
kernel.config      -> итоговый .config
abi_symbollist.raw -> ABI input
```

Исходники `mac80211`, `ath9k_htc` и `mt76x2u` входят в закреплённое дерево
Android common kernel.

## Toolchain и ресурсы

Использованный компилятор:

```text
Android (8508608, based on r450784e) clang version 14.0.7
Target: x86_64-unknown-linux-gnu
```

Сборка выполнялась с Full LTO. Чтобы избежать чрезмерного параллельного
потребления памяти, использовались:

```text
build jobs:      1
linker threads:  1
```

На старте успешной сборки было доступно около 28,5 ГиБ RAM и 16 ГиБ swap.
Главный пик памяти возникает во время финальной Full LTO линковки `vmlinux`.

## Исторические рецепты

Каталог [`build-recipes/`](build-recipes/) сохраняет несколько этапов проекта:

- `baseline-recipe/` — первоначальная подготовка GKI и ABI;
- `recipe/wifi2/` — Full LTO и первые CFI-исправления TX path;
- `recipe/wifi3/` — CFI-исправления monitor callbacks;
- `recipe/wifi4/` — итоговые runtime callback wrappers;
- `recipe/*-audit/` — статические и compiled-object аудиты;
- `recipe/shared/` — упаковка, AVB и общая проверка артефактов;
- `recipe/tools/avbtool.py` — закреплённый AOSP avbtool.

Сценарии сохранены как доказательство фактического процесса. Некоторые из них
содержат исходный build root `/mnt/f/wifi_work` и абсолютные пути WSL. Для
нового окружения эти пути нужно заменить. Рецепты не содержат автоматической
прошивки или развёртывания на устройство.

## Итоговая конфигурация и ABI

- [`config/kernel.config`](config/kernel.config) — конфигурация ядра;
- [`config/abi_symbollist.raw`](config/abi_symbollist.raw) — ABI symbol list;
- [`abi/Module.symvers`](abi/Module.symvers) — версии экспортируемых символов;
- [`abi/module-signing-cert.x509`](abi/module-signing-cert.x509) — публичный
  сертификат, соответствующий релизному ядру и модулям.

Приватный ключ подписи в репозиторий и релиз не включён.

## Патчи wifi4

Основные изменения собраны в:

- [`patches/realtek-compat.patch`](patches/realtek-compat.patch);
- [`patches/runtime-callback-cfi.patch`](patches/runtime-callback-cfi.patch).

Они адаптируют внешние Realtek-драйверы к целевому Android 5.15 API и
устраняют несовпадения типов callbacks, которые становятся критичными при CFI.
Алгоритмы обработки радиокадров не переписаны; изменения сосредоточены на
границах kernel API, wrapper-функциях и совместимости типов.

## Проверки артефактов

Итоговый цикл включал:

- проверку kernel release и конфигурации;
- сопоставление ABI со штатными vendor-модулями;
- imports/CRC, vermagic, BTF и CFI для модулей;
- PKCS#7-подписи модулей и привязку к сертификату ядра;
- порядок зависимостей 14 модулей в ZIP;
- целостность трёх firmware payload;
- 128 boundary-тестов monitor TX path;
- аудит 1337 callback assignments во внешних драйверах;
- повторную проверку изменённых LLVM objects;
- AVB hash footer, официальный `verify_image` и негативный corruption test;
- проверку, что модульный ZIP не содержит образов разделов.

Подробные входы и хеши изменённых файлов находятся в
[`provenance/build-manifest.json`](provenance/build-manifest.json) и
[`provenance/source-changes.json`](provenance/source-changes.json).

## Почему новая сборка может отличаться по SHA-256

Соответствующие исходники позволяют повторить функциональную сборку, но не
обещают автоматически получить идентичные байты. На результат влияют:

- время и путь сборки;
- версия host-инструментов;
- generated headers;
- новый приватный ключ подписи модулей;
- порядок и параметры архивирования.

Новый ключ меняет одновременно ядро и `.ko` файлы. Поэтому нельзя подписать
новые модули случайным ключом и использовать их с релизным `Image`.

Для получения точного опубликованного результата используйте релизный `Image`
и описанный ниже host-only упаковщик.

## Упаковка собственного stock boot

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

Инструмент принимает только:

- stock boot SHA-256
  `4432fa1827b9f4cb12816d646d6b4be08b10d65537bda9f5d2c10b554a53bf4f`;
- kernel `Image` SHA-256
  `c7a1a7e7a6d9784d00e7d8f0c18f5ee072b5f006e8696162d2405ac515d305db`.

Ожидаемый результат:

```text
bytes:  67108864
SHA256: 7c67c4b876c7710b2248dca9f7bbe9942087c44365baf7be1cc39cdd83c700a7
AVB:    hash footer, algorithm NONE, verified by bundled avbtool
```

Сценарий создаёт файл только на компьютере. Он не подключается к устройству и
не содержит команд установки.

## Ограничения публикации

Репозиторий намеренно не содержит:

- штатный boot/ramdisk Realme;
- полные или частичные дампы пользовательских разделов;
- NV/IMEI/серийные данные;
- FDL loaders из прошивки устройства;
- приватные ключи подписи;
- APK-файлы сторонних приложений.

Firmware для Wi-Fi адаптеров распространяется отдельно от GPL-кода на
условиях, перечисленных в [`THIRD_PARTY.md`](THIRD_PARTY.md) и
[`licenses/`](licenses/).
