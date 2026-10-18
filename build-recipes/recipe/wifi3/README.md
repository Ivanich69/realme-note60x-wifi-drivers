# wifi3: CFI отдельного monitor-интерфейса

Работа выполняется только на ПК. Никаких ADB, FDL, fastboot, перезагрузок,
записи разделов или установки в рецепте нет.

Расширенный аудит находится в `../wifi3-audit/`. Он извлекает через Clang AST
реальные таблицы net_device_ops, cfg80211_ops и ethtool_ops и использует те же
компилятор, заголовки и флаги, что записаны в Kbuild `.cmd`. Числовые CFI-типы
сверяются с настоящими предлинковочными LLVM-объектами. Пробники сохраняются
отдельно; их предупреждение C2x об отсутствии имён параметров отключено только
для пробников. Защита CFI драйверов не отключается и не смягчается.

Аудит выявил возврат int вместо netdev_tx_t в трёх функциях
rtw_cfg80211_monitor_if_xmit_entry. Две таблицы присутствуют в объектах EU/BU;
таблица AU в текущем профиле удаляется оптимизатором. Дальнейшие результаты
должны показывать ноль несовпадений, включая объявления неиспользуемой таблицы.

`prepare_host.py` закрепляет базовый архив wifi2, три изменённых файла и патч.
`build_modules.py` создаёт отдельные копии out/stage и драйверов, собирает три
модуля одним заданием, сохраняя ядро, его конфигурацию и ключ подписи из локальной
wifi2. Приватный ключ нужен только локально; в экспорт он не попадает.
`export_artifacts.py` формирует отдельный набор gki-wifi3-cfi-monitor после аудита.

Порядок проверок:

1. `python prepare_host.py` на ПК после аудита исходной wifi2.
2. Linux: `python3 build_modules.py`.
3. Linux: `python3 ../wifi3-audit/audit_callbacks.py --variant wifi3-cfi-monitor`.
4. Linux: `python3 export_artifacts.py`.
5. Общий `validate_artifacts.py --output <gki-wifi3-cfi-monitor> --lto full`.
6. `compare_realme_phone_modules.py` с явными `--artifacts` и `--output`.
7. Linux: `verify_signatures.py` с REALME_ARTIFACTS и отдельным REALME_SIGNATURE_TEMP.
8. `package_realme_wifi_magisk.py --variant wifi3 --version-code 3` с явными путями.
9. `package_realme_wifi2.py --variant wifi3` с явными --artifacts и --output.
10. `finalize_artifacts.py`.

boot.img остаётся побайтно равным wifi2: изменены модули, а не базовое ядро.
Ни одна проверка на ПК не подтверждает успешную загрузку или работу радио.
