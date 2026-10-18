"""Publish the host build report and integrity manifest after validation."""

import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/realme-note60x/gki-wifi1"
BUILD = Path(__file__).resolve().parent


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def parse_config(path):
    result = {}
    for line in path.read_text().splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            result[line[2:-11]] = "n"
    return result


def main():
    summary = json.loads((OUT / "validation-summary.json").read_text())
    signatures = json.loads((OUT / "signature-validation.json").read_text())
    capabilities = json.loads((OUT / "driver-capabilities.json").read_text())
    assert summary["saved_vendor_boot_ABI_verified"]
    assert signatures["regulatory_db_signature_verified_with_kernel_certificates"]
    assert len(signatures["modules"]) == summary["module_count"]
    assert len(capabilities["drivers"]) == 5
    assert all(row["PKCS7_signature_verified"] for row in signatures["modules"])
    with tarfile.open(OUT / "sources/driver-sources-and-config.tar.gz") as archive:
        names = archive.getnames()
        assert not any(Path(name).name == "signing_key.pem" for name in names)
    stock, current = parse_config(BUILD / "stock-gki.config"), parse_config(OUT / "kernel.config")
    changes = [{"config": key, "stock": stock.get(key, "n"), "built": current.get(key, "n")}
               for key in sorted(stock.keys() | current.keys())
               if stock.get(key, "n") != current.get(key, "n")]
    (OUT / "config-diff.json").write_text(json.dumps(changes, indent=2) + "\n")
    image_size = (OUT / "Image").stat().st_size
    image_sha = sha(OUT / "Image")
    boot_sha = sha(OUT / "boot-unsigned.img")
    report = f"""# Realme Note 60x: сборка Wi-Fi GKI wifi1

13 октября 2026 года, время пользователя Europe/Moscow.

**Ядро и комплект модулей собраны и проверены на ПК.** Цель — Realme Note 60x
RMX3938, штатная Android 15 / RMX3938export_15_C.13. Устройство в ходе этой
сборки не использовалось. Установка, загрузка и тесты радио не выполнялись.

База: [AOSP android13-5.15-2025-03_r2](https://android.googlesource.com/kernel/common/+/0c6055fd2d8b95ec88db7bfd79bfd1e471592215),
коммит совпадает со строкой штатного ядра. Название ветки android13 — поколение
Android Common Kernel, а не замена установленной Android 15.
Clang r450784e / 14.0.7 совпадает с компилятором штатной конфигурации.
Полные исходники базы сохранены в `.reference/realme-note60x/kernel-build-inputs`;
отдельное дерево WSL — `/home/sad1/wifi-kernel-realme-note60x/common`.

## Состав

| Чипсет | Драйвер | Форма |
| --- | --- | --- |
| RTL8812AU | 88XXau | Подписанный модуль |
| RTL8188EUS | 8188eu | Подписанный модуль |
| RTL8812BU / RTL8822BU | 88x2bu | Подписанный модуль |
| MT7612U | mt76x2u, mt76 | Подписанные модули |
| AR9271 | ath9k_htc, ath9k_hw/common | Подписанные модули |

Всего экспортировано {summary['module_count']} модулей, включая cfg80211/mac80211
и остальные модули профиля GKI. USB-драйверы находятся в отдельных `.ko`,
поэтому один `boot-unsigned.img` не содержит полный комплект поддержки адаптеров.

Для каждого целевого драйвера проверены USB ID и реализация monitor/TX.
В ELF Realtek и mac80211 присутствуют обработчики передачи из monitor mode.
Это подтверждение реализации и включения в сборку; приём, смена каналов и
успешная инъекция на физических адаптерах **не проверены**.

В 88x2bu сохранено исправление monitor TX: дополнительные байты radiotap
пропускаются без копирования в фиксированный 32-байтовый буфер; размер
802.11 кадра ограничивается размером буфера драйвера. Для RTL8188EUS
исправлены тип флагов памяти `gfp_t` и лишние скобки в проверке скорости USB.
Платформенное автоопределение x86 отключено, включены ARM64 little-endian
и cfg80211. Monitor mode остаётся включённым у трёх Realtek.

В RTL8812AU исправлены неинициализированные указатели в устаревших RX helpers,
чтение пользовательского буфера и начальные значения параметров канала/BA.
Общий `CONFIG_CFG80211_WEXT` выключен, поскольку его дополнительные поля
изменяли CRC штатного MMC vendor hook. Управление мониторным интерфейсом
сохраняется через nl80211. CRC не подменялись; объект vendor hooks пересоздан
из актуальной конфигурации с учётом зависимостей genksyms.
В трёх Realtek активированы ветви для перенесённого в ACK API MLO/puncturing:
операции ключей, смены канала и остановки AP имеют фактические сигнатуры этого
ядра. `LINUX_VERSION_CODE` не изменялся, CFI не отключался. Для RTL8814A
исправлено всегда истинное условие проверки числа радиотрактов.
Неподдерживаемые RF path/rate в PHYDM возвращают `INVALID_TXAGC_DATA`,
не выполняя чтение регистра с неинициализированным адресом или маской.
В список сохраняемых экспортов ядра добавлены `kernel_read`, `kernel_write`
и `filp_open`, требуемые Realtek. У RTL8188EUS объявлен импорт VFS namespace.
В PHYDM исправлены проверки допустимых диапазонов TX power offset и выбор
диагностического коэффициента HT/VHT; штатные ошибки компилятора не подавлялись.

## Проверки

- AArch64 Image и ELF; gzip соответствует исходному Image.
- Встроенная конфигурация полностью совпадает с файлом сборки.
- Используется Thin LTO; сохранены CFI, BTF, MODVERSIONS и MODULE_SIG_PROTECT.
- Сопоставлены {summary['vendor_imports_checked']} CRC импортов 167 модулей
  из сохранённого vendor_boot: отсутствующих символов и несовпадений нет.
- Все импорты новых модулей сверены с Module.symvers, проверены USB ID.
- Все {summary['module_count']} подписи PKCS7 проверены OpenSSL; новый
  сертификат подписи и оригинальный публичный сертификат присутствуют в Image.
- Firmware MT7612U/AR9271 совпадает с ранее закреплёнными исходниками.
- Подпись regulatory.db подтверждена сертификатами выбранного ядра.
- boot-unsigned.img имеет заголовок v4, ramdisk отсутствует, ядро совпадает
  с Image, размер 64 МиБ соответствует сохранённому boot_b.

Строка kernelrelease сохранена штатной:
`5.15.178-android13-8-00006-g0c6055fd2d8b-ab13363910`.
Кастомная сборка определяется SHA256 и manifest; `uname -r` сам по себе
не отличит её от оригинального GKI. Сохранённые vendor-модули могут иметь
другую строку версии; проверка здесь основана на их MODVERSIONS/CRC.

## Ограничения

Модули из super (vendor/system_dlkm), включая штатный Wi-Fi-стек, отсутствуют
в имеющейся резервной копии. Их CRC, CFI и совместимость с новым cfg80211
не проверены. Проверка сохранённого vendor_boot не покрывает весь набор
модулей прошивки и не гарантирует загрузку или сохранение встроенного Wi-Fi.

boot-unsigned.img создан без OEM AVB footer/подписи и без старой дополнительной
GKI boot signature. Производитель эту сборку не сертифицировал; принятие
образа загрузчиком не проверялось. init_boot с Magisk и vendor_boot не изменялись.
Закрытый ключ новых модулей остаётся в WSL и не включён в пакет.

## Файлы

Каталог: `F:\\wifi_work\\artifacts\\realme-note60x\\gki-wifi1`.

- `Image` — {image_size} байт, SHA256 `{image_sha}`.
- `Image.gz` — сжатое ядро.
- `boot-unsigned.img` — 67 108 864 байт, SHA256 `{boot_sha}`.
- `wifi-modules-and-firmware.tar.gz` — модули, firmware и лицензии.
- `modules/`, `firmware/` — тот же комплект отдельными файлами.
- `vmlinux`, `System.map`, `Module.symvers`, `kernel.config` — данные сборки.
- `sources/driver-sources-and-config.tar.gz` — исходники драйверов и рецепт.
- `sources/realtek-compat.patch` — изменения относительно закреплённых Git-коммитов;
  исходные и итоговые хеши каждого изменённого файла проверены при упаковке.
- `validation-summary.json`, `vendor-abi-validation.json`, `module-validation.json`,
  `signature-validation.json`, `driver-capabilities.json` — результаты проверок.
- `SHA256SUMS.json` — размер и SHA256 каждого экспортированного файла.

Рецепт повторения: [build/realme-note60x/README.md](F:/wifi_work/build/realme-note60x/README.md).
Работа завершена на готовых файлах.
"""
    (OUT / "BUILD_REPORT.md").write_text(report, encoding="utf-8")
    (ROOT / "diagnostics/REALME_KERNEL_WIFI1_REPORT.md").write_text(report, encoding="utf-8")
    summary["module_signatures_verified"] = True
    summary["regulatory_db_signature_verified"] = True
    summary["all_host_checks_complete"] = True
    (OUT / "validation-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    manifest = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.json":
            manifest.append({"file": path.relative_to(OUT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    (OUT / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for row in manifest:
        path = OUT / row["file"]
        assert path.stat().st_size == row["bytes"] and sha(path) == row["sha256"]
    state = json.loads((BUILD / "STATE.json").read_text())
    state.update({"phase": "complete: compiled and validated host artifacts",
                  "current_exec_session": None, "artifact_dir": str(OUT), "host_checks_complete": True,
                  "physical_device_accessed": False, "stop_after_artifacts": True})
    state['MMC_hook_CRC_correction']['complete_final_ABI_check_pending'] = False
    state['final_vendor_ABI'] = {'saved_vendor_modules': 167,
                                'matched_imports': summary['vendor_imports_checked'],
                                'missing_symbols': [], 'CRC_mismatches': []}
    (BUILD / "STATE.json").write_text(json.dumps(state, indent=2) + "\n")
    print(json.dumps({"artifact_dir": str(OUT), "manifest_entries_verified": len(manifest),
                      "Image_bytes": image_size, "Image_sha256": image_sha,
                      "boot_unsigned_sha256": boot_sha, "modules": summary['module_count']}))


if __name__ == "__main__":
    main()
