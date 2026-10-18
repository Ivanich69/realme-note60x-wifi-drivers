"""Validate and seal wifi4 host artifacts. No device modes or deployment."""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'diagnostics'))
from analyze_realme_b_preserving_exit import verify_manifest

ART = ROOT / 'artifacts/realme-note60x/gki-wifi4-cfi-runtime'
OUT = ROOT / 'artifacts/realme-note60x/wifi4-reviewed'
BASE = ROOT / 'artifacts/realme-note60x/gki-wifi3-cfi-monitor'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def seal(folder):
    rows = [{'file': path.relative_to(folder).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)}
            for path in sorted(folder.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS.json']
    write(folder / 'SHA256SUMS.json', rows)
    assert verify_manifest(folder) == len(rows)
    return len(rows)


def refresh_archived_recipes():
    """Include final reviewed host recipes rather than initial generated copies."""
    bundle = ART / 'sources/driver-sources-and-config.tar.gz'
    replacements = {'recipe/wifi4/' + path.name: path for path in HERE.iterdir()
                    if path.is_file() and path.suffix in ('.py', '.json', '.md', '.patch')
                    and path.name not in ('SHA256SUMS.json', 'STATUS.json')}
    replacements.update({'recipe/wifi4/shared/' + name: ROOT / 'diagnostics' / name
                         for name in ('package_realme_wifi_magisk.py', 'package_realme_wifi2.py')})
    replacements['recipe/wifi4/shared/verify_signatures.py'] = HERE.parent / 'verify_signatures.py'
    temporary = bundle.with_name('driver-sources-and-config.finalizing.tar.gz')
    assert not temporary.exists()
    seen = set()
    with tarfile.open(bundle) as source, tarfile.open(temporary, 'w:gz') as target:
        for member in source:
            assert member.isfile() and member.name not in seen
            seen.add(member.name)
            data = replacements.pop(member.name).read_bytes() if member.name in replacements else source.extractfile(member).read()
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
        for name, path in sorted(replacements.items()):
            data = path.read_bytes()
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), 0o644
            target.addfile(member, io.BytesIO(data))
    temporary.replace(bundle)


def main():
    review = read(OUT / 'review.json')
    runtime = read(ART / 'runtime-CFI-validation.json')
    before = read(ART / 'runtime-CFI-before.json')
    network = read(ART / 'callback-CFI-validation.json')
    assert review['all_host_checks_complete'] and not review['device_operations']
    assert runtime['passed'] and not runtime['mismatches'] and runtime['source_count'] == 462
    assert not runtime['device_contacted'] and not runtime['limited_run'] and not runtime['marker_only']
    assert len(before['mismatches']) == 11 and before['callbacks'] == 1337
    assert runtime['callbacks'] >= before['callbacks'] and runtime['compiled_definition_checks'] >= before['compiled_definition_checks']
    fixed = []
    for old in before['mismatches']:
        found = [row for row in runtime['comparisons'] if row['source'] == old['source'] and
                 row['function'] == old['function'] + '_cfi' and row['expected_CFI']['ids'] == old['expected_CFI']['ids']]
        assert found and all(row['matches'] and row['compiled_definition_checked'] for row in found), old['function']
        fixed.append({'driver': old['driver'], 'source': old['source'], 'old_function': old['function'],
                      'new_callback': old['function'] + '_cfi', 'expected_CFI_ids_preserved': old['expected_CFI']['ids']})
    assert network['passed'] and len(network['comparisons']) == 156 and not network['mismatches']
    signatures = read(ART / 'signature-validation.json')
    assert len(signatures['modules']) == 17 and all(row['PKCS7_signature_verified'] for row in signatures['modules'])
    assert signatures['signers_selected_only_from_explicit_kernel_certificate_files']
    assert signatures['regulatory_db_signature_verified_with_kernel_certificates']
    negative = read(ART / 'signature-binding-negative.json')
    assert negative['cases_passed'] == 2 and not negative['phone_contacted']
    assert negative['module_sha256'] == sha(ART / 'modules' / negative['module'])
    assert sha(ART / 'Image') == sha(BASE / 'Image') == 'c7a1a7e7a6d9784d00e7d8f0c18f5ee072b5f006e8696162d2405ac515d305db'
    assert sha(ART / 'kernel.config') == sha(BASE / 'kernel.config') == '513cad42f78dee45b7892917cc7c080971734d990b866243fabeece1c22bcb8b'
    assert sha(OUT / 'boot.img') == sha(ROOT / 'artifacts/realme-note60x/wifi3-reviewed/boot.img') == '7c67c4b876c7710b2248dca9f7bbe9942087c44365baf7be1cc39cdd83c700a7'
    module_changes = [path.name for path in (ART / 'modules').glob('*.ko') if sha(path) != sha(BASE / 'modules' / path.name)]
    assert set(module_changes) == {'88XXau.ko', '8188eu.ko', '88x2bu.ko'}
    for path in (ART / 'firmware').rglob('*'):
        if path.is_file():
            assert sha(path) == sha(BASE / 'firmware' / path.relative_to(ART / 'firmware'))
    with tarfile.open(ART / 'sources/driver-sources-and-config.tar.gz') as archive:
        assert all(member.isfile() and Path(member.name).name != 'signing_key.pem' for member in archive)
    assert verify_manifest(BASE) == 74
    assert verify_manifest(ROOT / 'artifacts/realme-note60x/misc-b-recovery-v6') == 47
    summary = read(ART / 'validation-summary.json')
    summary.update({'all_host_checks_complete': True, 'runtime_callback_CFI_verified': True,
                    'core_Image_reused_unchanged_from_wifi3': True, 'physical_device_accessed': False})
    write(ART / 'validation-summary.json', summary)
    proof = {'recorded_utc': datetime.now(timezone.utc).isoformat(), 'host_only': True, 'phone_contacted': False,
             'baseline_sources': before['source_count'], 'baseline_callback_assignments': before['callbacks'],
             'baseline_mismatches': 11, 'fixed_callbacks': fixed,
             'callback_assignments_after': runtime['callbacks'],
             'compiled_definition_checks_after': runtime['compiled_definition_checks'],
             'fresh_AST_sources': runtime.get('fresh_AST_sources'),
             'expected_CFI_reuse_proof': runtime.get('expected_CFI_reuse_proof'),
             'network_table_checks': 156, 'CFI_mismatches_after': 0,
             'changed_modules': sorted(module_changes), 'kernel_and_config_unchanged': True,
             'all_adapter_firmware_unchanged': True, 'all_module_signers_bound_to_kernel_certificate': True,
             'explicit_signer_positive_negative_checks_passed': 2,
             'wifi3_manifest_files_unchanged': 74, 'misc_B_v6_manifest_files_verified': 47,
             'hardware_boot_or_radio_tested': False, 'independent_failed_A_recovery_proven': False}
    write(ART / 'wifi4-preservation-validation.json', proof)
    text = f'''# Realme Note 60x wifi4: точные типы callback при включённом CFI

Цель — RMX3938, RMX3938export_15_C.13. Этот этап полностью выполнен на ПК:
телефон не опрашивался и не менялся, WSL не перезапускалась и не перенастраивалась.

Полный аудит wifi3 охватил 462 скомпилированных исходника трёх внешних драйверов
и таблицы их заголовков: 1337 назначений callbacks. Для 1322 назначений проверены
реальные LLVM-определения; оставшиеся 15 относятся к неиспользуемым либо внешним
функциям и проверены на уровне объявлений. Найдены 11 несовпадений, все с реальными
определениями. Они не устанавливают причину прошлых зависаний телефона.

Исправлены 6 регистраций tasklet: ядро требует `void(unsigned long)`, старые
функции имели `void(void *)`. Добавлены точные обёртки с переводом контекста
обратно в указатель. Ещё 5 активных назначений в очередь команд получили
`void(void *)` обёртки для функций `void(_adapter *)`. Старые тела обработки
кадров, таймауты и логика питания не менялись. В выключенном proc-файле BU
аналогичные две PHY-обёртки подготовлены на уровне исходников.

Пересобраны `88XXau.ko`, `8188eu.ko`, `88x2bu.ko`; CFI и Full LTO сохранены.
Сохранены RTL8812AU, RTL8188EUS, RTL8812BU/RTL8822BU, AR9271 и MT7612U.
Остальные 14 модулей и firmware совпадают с wifi3 побайтно.

**Ядро и boot.img не изменились.** Исправления находятся в новом ZIP модулей.
SHA256 boot.img: `7c67c4b876c7710b2248dca9f7bbe9942087c44365baf7be1cc39cdd83c700a7`.
SHA256 ZIP: `{sha(OUT / 'realme-note60x-wifi4-magisk.zip')}`.

После сборки подтверждены все 11 исправленных назначений с прежними ожидаемыми
CFI ID и новыми реальными определениями. Проверено {runtime['callbacks']} назначений,
из них {runtime['compiled_definition_checks']} с реальными определениями; несовпадений нет.
В повторном проходе AST пересмотрены {runtime.get('fresh_AST_sources')} изменённых исходников.
Ожидания для остальных переиспользованы только после побайтной проверки заголовков,
исходников и нормализованных флагов Kbuild. Все новые LLVM-объекты проверены заново.
Отдельный свежий аудит сетевых таблиц проверил ещё 156 назначений; он частично
пересекается с полным проходом и не суммируется с ним как независимые тесты.

Также выполнены свежие проверки 17 модулей: импортов/CRC, vermagic, BTF/CFI,
USB ID, подписей и их соответствия сертификату в ядре. Для выбора signer
использован `-nointern`; сертификат из самого PKCS7 не подменяет заданный.
Положительная проверка правильного certfile и отрицательная другого прошли.
Сверены зависимости и порядок 14 модулей в ZIP, три firmware, сохранённая ABI
323 штатных модулей, boot/AVB двумя инструментами и отрицательный тест порчи.
128 прежних ASan/UBSan тестов неизменённых TX-границ сохранены как старое доказательство;
новым тестом добавленных обёрток они не выдаются.

Сборка и проверки не устанавливают успешный запуск ядра на оборудовании,
приём/инъекцию кадров, USB-питание, отсутствие гонок или корректность всех
динамических callbacks. Автозагрузка модулей выключена. В boot.img нет OEM-подписи;
его принятие загрузчиком Realme не доказано. В сохранённом init_boot_a Magisk
не обнаружен, поэтому root после выбора A не подтверждён. Прежний RAM-тест
новое ядро не запускал; независимое аварийное восстановление A→B не доказано.

Отдельно подготовлен `misc-b-recovery-v6`: 66 локальных проверок прошли,
устранены шесть нежелательных принятий Virtual A/B из v5. На телефоне v6
не выполнялась; аппаратный тест прежней v4 доказывает только тот проход B→B.

Файлы сборки и проверки запечатаны SHA256. Работа остановлена на артефактах
по STRICT KERNEL BUILD MODE; разрешение на прошивку, выбор A или новые чтения
телефона из этого результата не следует.
'''
    for path in (OUT / 'README.md', ART / 'BUILD_REPORT.md', ROOT / 'diagnostics/REALME_KERNEL_WIFI4_REPORT.md'):
        path.write_text(text, encoding='utf-8')
    (HERE / 'README.md').write_text(text, encoding='utf-8')
    refresh_archived_recipes()
    counts = {'artifacts': seal(ART), 'package': seal(OUT), 'recipe': seal(HERE)}
    # Do not overwrite historical initial-generation hashes after review edits.
    # The final recipe manifest above attests the reviewed source versions.
    state_path = ROOT / 'artifacts/realme-note60x/wifi1-install/execution-state.json'
    state = read(state_path)
    assert state['active_device_authorization']['completed'] and not state['active_device_authorization']['same_task_authorization_still_active']
    state['phase'] = 'Host checks complete: wifi4 typed callback modules validated; wifi3 core retained; hardware tests pending separate authorization'
    state['current_scope'] = 'STRICT KERNEL BUILD MODE; host-only work complete; no current phone authorization'
    state['latest_host_wifi4'] = {**proof, 'artifacts': str(ART), 'package': str(OUT),
                                 'report': 'diagnostics/REALME_KERNEL_WIFI4_REPORT.md', 'manifests': counts,
                                 'boot_sha256': sha(OUT / 'boot.img'), 'ZIP_sha256': sha(OUT / 'realme-note60x-wifi4-magisk.zip')}
    write(state_path, state)
    print(json.dumps({'host_checks_complete': True, 'manifests': counts, 'runtime_CFI_callbacks': runtime['callbacks'],
                      'CFI_mismatches': 0, 'phone_contacted': False, 'boot_sha256': sha(OUT / 'boot.img'),
                      'ZIP_sha256': sha(OUT / 'realme-note60x-wifi4-magisk.zip')}, indent=2))


if __name__ == '__main__':
    main()
