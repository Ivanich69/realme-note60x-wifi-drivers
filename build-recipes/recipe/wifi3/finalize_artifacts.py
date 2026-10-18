"""Finalize the validated monitor-CFI refinement without device interaction."""
import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ART = ROOT / 'artifacts/realme-note60x/gki-wifi3-cfi-monitor'
OUT = ROOT / 'artifacts/realme-note60x/wifi3-reviewed'
BASE = ROOT / 'artifacts/realme-note60x/gki-wifi2-full-lto'

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')

def main():
    review = read(OUT / 'review.json')
    assert review['all_host_checks_complete'] and not review['device_operations']
    assert review['expanded_callback_CFI']['passed']
    assert not review['expanded_callback_CFI']['mismatches']
    assert len(review['expanded_callback_CFI']['comparisons']) == 156
    assert sum(r['table_emitted'] for r in review['expanded_callback_CFI']['comparisons']) == 152
    assert sha(ART / 'Image') == sha(BASE / 'Image')
    assert sha(OUT / 'boot.img') == sha(ROOT / 'artifacts/realme-note60x/wifi2-reviewed/boot.img')
    assert sha(OUT / 'realme-note60x-wifi3-magisk.zip') == review['companion']['sha256']
    # Ensure all previously published wifi2 files are preserved byte for byte.
    old_rows = read(BASE / 'SHA256SUMS.json')
    for row in old_rows:
        assert sha(BASE / row['file']) == row['sha256'], row['file']
    preserved = {'passed': True, 'wifi2_manifest_entries_verified': len(old_rows),
                 'boot_identical_to_wifi2': True, 'core_Image_identical_to_wifi2': True}
    write(ART / 'wifi2-preservation-validation.json', preserved)
    with tarfile.open(ART / 'sources/driver-sources-and-config.tar.gz') as archive:
        assert not any(Path(r.name).name == 'signing_key.pem' for r in archive)
    text = f'''# Realme Note 60x wifi3: исправление CFI monitor-интерфейса

Цель: RMX3938, прошивка RMX3938export_15_C.13. Работа выполнена только на ПК.

В RTL8188EUS и RTL8812BU найдено несовпадение Clang CFI для
`rtw_cfg80211_monitor_if_xmit_entry`: возврат `int` отличается от `netdev_tx_t`,
который требует `net_device_ops.ndo_start_xmit`. Такое несовпадение может вызвать
сбой проверки CFI при вызове обработчика. Причина прежних зависаний этим не доказана.
Та же сигнатура исправлена в RTL8812AU; его отдельная monitor-таблица в этой
конфигурации удаляется оптимизатором, поэтому исправление там относится к исходникам.

Изменены только три сигнатуры функций в `os_dep/linux/ioctl_cfg80211.c`.
Тела функций, настройки ядра и предыдущие исправления wifi2 сохранены.

**Ядро и boot.img побайтно совпадают с wifi2.** Пересобраны три внешних модуля;
результат находится в новом ZIP. Старые артефакты wifi2 не изменены.
Сохранены RTL8812AU, RTL8188EUS, RTL8812BU/RTL8822BU, MT7612U и AR9271.

Проверено на ПК:

- CFI-типы 156 назначений в net_device_ops, cfg80211_ops и ethtool_ops:
  152 назначения в сохранённых LLVM-таблицах проверены по настоящим объектам;
  ещё четыре из неиспользуемой monitor-таблицы AU проверены по объявлениям;
- до исправления найдены три несовпадения, два в сохранённых таблицах;
  после исправления несовпадений нет;
- подписи всех 17 модулей и regulatory.db, USB ID, BTF/CFI, импорты/CRC;
- совместимость с 323 сохранёнными штатными модулями;
- содержимое и порядок загрузки 14 модулей в ZIP, три файла firmware;
- целостность boot/AVB двумя инструментами, отрицательный тест повреждения;
- все {len(old_rows)} файлов опубликованной wifi2 совпадают с её манифестом.

128 ASan/UBSan-проверок границ передачи из wifi2 относятся к неизменённым участкам
`core/rtw_xmit.c`; они сохранены как доказательство предыдущего этапа и не
выдаются за новый тест изменённых monitor-обработчиков.

| Файл | Содержимое |
|---|---|
| `boot.img` | Тот же образ wifi2, 64 МиБ; нового ядра в нём нет |
| `realme-note60x-wifi3-magisk.zip` | Обновлённые Wi-Fi-модули и firmware |
| `review.json` | Подробные проверки и ограничения |
| `SHA256SUMS.txt` | Хеши комплекта |

SHA256 boot.img: `{review['image']['sha256']}`

SHA256 ZIP: `{review['companion']['sha256']}`

Автозагрузка модулей выключена. ZIP предназначен для сохранённого ядра Full LTO
с конфигурацией `{review['image']['config_sha256']}`.

**Ограничения:** загрузка на телефоне и работа адаптеров не проверялись.
OEM-подписи у boot.img нет; хеши не доказывают принятие образа загрузчиком.
Независимое восстановление после незагружаемого ядра не подтверждено.
Аудит не охватывает все таймеры, workqueue, USB, WEXT, все обратные вызовы
внутри драйверов и все возможные ошибки памяти. Гарантии отсутствия сбоев нет.

Телефон не опрашивался и не изменялся. Настройки WSL на этом этапе не менялись.
Исходники, патчи, модули и манифест: `../gki-wifi3-cfi-monitor/`.
Рецепт: `build/realme-note60x/wifi3/`; аудит: `../wifi3-audit/` рядом с рецептом.
'''
    for path in [OUT / 'README.md', ART / 'BUILD_REPORT.md', ROOT / 'diagnostics/REALME_KERNEL_WIFI3_REPORT.md']:
        path.write_text(text, encoding='utf-8')
    summary = read(ART / 'validation-summary.json')
    summary.update({'all_host_checks_complete': True, 'expanded_callback_CFI_verified': True,
                    'core_Image_reused_unchanged_from_wifi2': True, 'physical_device_accessed': False})
    write(ART / 'validation-summary.json', summary)
    records = [{'file': p.relative_to(ART).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
               for p in sorted(ART.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS.json']
    write(ART / 'SHA256SUMS.json', records)
    (OUT / 'SHA256SUMS.txt').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(OUT.iterdir())
        if p.is_file() and p.name != 'SHA256SUMS.txt'), encoding='ascii')
    write(HERE / 'STATUS.json', {'complete': True, 'core_Image_reused_unchanged': True,
        'compiled_driver_modules': 3, 'callbacks_audited': 156, 'compiled_callbacks_audited': 152,
        'CFI_mismatches': 0, 'hardware_tested': False, 'device_operations': [],
        'artifacts': str(ART), 'package': str(OUT), 'wifi2_preserved': True})
    print(json.dumps({'complete': True, 'artifacts': str(ART), 'package': str(OUT),
                      'core_Image_unchanged': True, 'manifest_entries': len(records)}))

if __name__ == '__main__':
    main()
