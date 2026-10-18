"""Publish wifi2 reports/checksums after all host validation has succeeded."""

import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ART = ROOT / "artifacts/realme-note60x/gki-wifi2-full-lto"
BUNDLE = ROOT / "artifacts/realme-note60x/wifi2-reviewed"


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    review = read(BUNDLE / "review.json")
    assert review["all_host_checks_complete"] and review["cached_ABI_incompatibilities"] == 0
    assert review["bounds_tests"]["passed"] and review["bounds_tests"]["boundary_cases"] == 128
    assert review["TX_callback_CFI"]["passed"]
    assert review["compiled_TX_callback_CFI"]["passed"]
    signatures = read(ART / "signature-validation.json")
    assert len(signatures["modules"]) == 17 and all(r["PKCS7_signature_verified"] for r in signatures["modules"])
    assert signatures["regulatory_db_signature_verified_with_kernel_certificates"]
    with tarfile.open(ART / "sources/driver-sources-and-config.tar.gz") as archive:
        assert not any(Path(m.name).name == "signing_key.pem" for m in archive.getmembers())
    image, companion = review["image"], review["companion"]
    assert sha(BUNDLE / image["file"]) == image["sha256"]
    assert sha(BUNDLE / companion["file"]) == companion["sha256"]
    text = f"""# Realme Note 60x wifi2 — проверенная на ПК сборка

Цель: RMX3938, RMX3938export_15_C.13. Сборка и проверки выполнены только на ПК.

| Файл | Содержимое |
|---|---|
| `boot.img` | Ядро Full LTO, boot v4, 67 108 864 байта, AVB без подписи |
| `realme-note60x-wifi2-magisk.zip` | 14 модулей и три файла firmware для этой конфигурации |
| `review.json` | Проверки и ограничения |
| `SHA256SUMS.txt` | Контрольные суммы файлов комплекта |

Исправлены проверки длины в monitor TX RTL8812AU и RTL8188EUS: границы
radiotap/буфера кадра проверяются до копирования; в RTL8188EUS убран цикл
с потенциально отрицательной длиной и инициализировано состояние читателя.
Проверки охватывают кадры с заголовком не короче 24 байт. RTL8812AU отклоняет
radiotap длиннее своего 256-байтового локального буфера.

Для RTL8188EUS и RTL8812BU исправлены Linux-прототипы TX-обработчиков:
возврат `netdev_tx_t` соответствует `ndo_start_xmit` и ожидаемому Clang CFI-типу.
Проверены декларации всех трёх Realtek-драйверов; прежний тип `int` различается
с ожидаемым CFI-типом. Проверка не охватывает все обратные вызовы драйверов.

Thin LTO заменён на Full LTO — тот же режим, что в штатной конфигурации.
CFI, BTF, MODVERSIONS и защита подписей модулей сохранены. Это сокращает
различия параметров сборки, но не доказывает причину какого-либо зависания.

Сохранены RTL8812AU, RTL8188EUS, RTL8812BU/RTL8822BU, MT7612U и AR9271.
Monitor mode и передача из monitor-интерфейса присутствуют в исходниках и
сборке. Практическая работа с адаптерами на этом Realme не проверялась.

На ПК прошли:

- 128 граничных C-проверок исправленных участков с ASan/UBSan;
- проверка CFI-типов трёх TX-обработчиков Clang 14 с отрицательным контролем и сверкой реально скомпилированных LLVM-объектов;
- проверка Image, gzip, встроенной конфигурации, CFI/BTF и USB ID;
- сравнение импортов/CRC с сохранёнными штатными модулями: {review['cached_core_module_checks']} записи без несовместимостей;
- проверка подписей 17 собранных модулей и подписи regulatory.db;
- проверка зависимостей и содержимого ZIP; его конфигурационный хеш совпадает с новым ядром;
- проверка AVB двумя инструментами; копия с повреждённым байтом отвергается.

Для wifi2 подготовлен новый ZIP. Прежний ZIP wifi1 не является комплектом
этой сборки. Штатный cfg80211 используется как внешний поставщик символов;
автоматическая загрузка драйверов в ZIP выключена.

SHA256 boot.img:
`{image['sha256']}`

SHA256 ZIP:
`{companion['sha256']}`

Исходники, конфигурация, Image/Image.gz, vmlinux, модули и полный манифест:
`../gki-wifi2-full-lto/`. Рецепт: `build/realme-note60x/wifi2/` в рабочем каталоге.
Исходный B сохранён отдельно в `../stock-boot-b-restore-review/boot_b-original-C13.img`.

**OEM-подписи у boot.img нет.** Правильные хеши не подтверждают принятие
образа загрузчиком. Строгая аутентификация сохранённой штатной цепочки не
выполняется; поведение разблокированного Realme с этим образом не доказано.
Загрузка ядра, работа radio/monitor/injection и независимый путь восстановления
после незагружаемого ядра не проверены. Гарантии загрузки и отсутствия сбоев нет.

По отдельному разрешению пользователя WSL выделено 28 GiB RAM и 16 GiB swap;
для применения настроек WSL перезапущен, исходный .wslconfig сохранён.
Существующие артефакты wifi1 сохранены. Телефон не опрашивался и не изменялся.
Работа завершена на файлах.
"""
    (BUNDLE / "README.md").write_text(text, encoding="utf-8")
    (ART / "BUILD_REPORT.md").write_text(text, encoding="utf-8")
    (ROOT / "diagnostics/REALME_KERNEL_WIFI2_REPORT.md").write_text(text, encoding="utf-8")
    summary = read(ART / "validation-summary.json")
    summary.update({"module_signatures_verified": True, "regulatory_db_signature_verified": True,
                    "bounds_tests_passed": 128, "cached_core_module_checks": review["cached_core_module_checks"],
                    "all_host_checks_complete": True})
    write(ART / "validation-summary.json", summary)
    records = [{"file": p.relative_to(ART).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)}
               for p in sorted(ART.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.json"]
    write(ART / "SHA256SUMS.json", records)
    for record in records:
        assert sha(ART / record["file"]) == record["sha256"]
    names = [p.name for p in sorted(BUNDLE.iterdir()) if p.is_file() and p.name != "SHA256SUMS.txt"]
    (BUNDLE / "SHA256SUMS.txt").write_text("".join(f"{sha(BUNDLE / name)}  {name}\n" for name in names), encoding="ascii")
    state = read(HERE / "STATUS.json")
    state.update({"phase": "complete: wifi2 Full LTO and source hardening built and host-validated",
                  "compiled": True, "unified_exec_session": None, "host_checks_complete": True,
                  "artifact_directory": str(ART), "bundle_directory": str(BUNDLE),
                  "boot_sha256": image["sha256"], "zip_sha256": companion["sha256"],
                  "hardware_tested": False, "phone_contacted": False, "WSL_configuration_changed": True,
                  "WSL_restarted_with_user_authorization": True})
    state.update({"pending_CFI_correction": None, "do_not_export_intermediate_build": False,
                  "compiled_TX_callback_CFI_verified": True,
                  "running_build_input_revision": None})
    write(HERE / "STATUS.json", state)
    # Track the current host candidate without changing historical device evidence.
    history = ROOT / "artifacts/realme-note60x/wifi1-install/execution-state.json"
    previous = read(history)
    previous["current_host_candidate"] = {"directory": str(BUNDLE), "image": image["file"],
        "sha256": image["sha256"], "variant": "wifi2-full-lto", "AVB_algorithm": "NONE",
        "OEM_signature_present": False, "host_integrity_checks_pass": True,
        "hardware_boot_verified": False, "radio_monitor_injection_tested": False,
        "saved_chain_authentication_satisfied": False,
        "report": str(ROOT / "diagnostics/REALME_KERNEL_WIFI2_REPORT.md")}
    previous["current_scope"] = "wifi2 host-only build and artifact checks complete; no phone interaction performed or authorized in this build"
    previous["pending_device_authorization"] = None
    write(history, previous)
    print(json.dumps({"artifacts": str(ART), "bundle": str(BUNDLE), "manifest_entries_verified": len(records),
                      "boot_sha256": image["sha256"], "companion_sha256": companion["sha256"],
                      "hardware_tested": False}, indent=2))


if __name__ == "__main__":
    main()
