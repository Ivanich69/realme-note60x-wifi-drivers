# Realme Note 60x RMX3938 C.13: GKI Wi-Fi build

Работа выполняется только на ПК. Рецепты не содержат команд доступа к
телефону или развёртывания.

База: Android Common Kernel `android13-5.15-2025-03_r2`, коммит
`0c6055fd2d8b95ec88db7bfd79bfd1e471592215`. Это коммит в строке
сохранённого штатного ядра C.13. Android Clang r450784e / 14.0.7
совпадает с компилятором, указанным в конфигурации штатного ядра.

Профиль `wifi1` содержит cfg80211/mac80211, MT7612U (`mt76x2u`),
AR9271 (`ath9k_htc`) и отдельные внешние модули RTL8812AU, RTL8188EUS,
RTL8812BU/RTL8822BU. Используется модульная форма, чтобы избежать конфликтов
глобальных символов трёх vendor-драйверов Realtek. Отдельный firmware нужен
MT7612U/AR9271; regulatory.db нужна общему Wi-Fi-стеку.

`CONFIG_CFG80211_WEXT` выключен: его дополнительные поля меняют CRC штатного
MMC vendor hook. Управление мониторным интерфейсом доступно через nl80211.
При пересоздании конфигурации объект vendor hooks принудительно регенерируется:
обычные зависимости препроцессора не полностью учитывают заголовки genksyms.
В трёх Realtek выбран API MLO/puncturing, уже перенесённый в это ядро.
Сигнатуры обработчиков адаптированы без изменения `LINUX_VERSION_CODE`,
приведения указателей операций к несовместимым типам или отключения CFI.

Сохранены CFI, BTF, MODVERSIONS и MODULE_SIG_PROTECT. Вместо штатного Full LTO
используется Thin LTO: первый проход Full LTO исчерпал 16 ГБ RAM и 4 ГБ swap
WSL. Линковщик ограничен двумя задачами; команды перезапуска WSL не выполнялись.
В доверенные сертификаты добавлен публичный сертификат модулей,
извлечённый из сохранённого штатного Image. Закрытые ключи с телефона
не извлекались. Закрытый ключ новых модулей создаёт обычная host-сборка
Kbuild; он остаётся в каталоге WSL и не включается в артефакты.
Список сохраняемых экспортов дополнен `kernel_read`, `kernel_write`,
`filp_open`, используемыми Realtek; импорты VFS namespace объявлены явно.

Строка kernelrelease сохраняется штатной для набора модулей. Кастомный
результат идентифицируется каталогом `gki-wifi1`, manifest и SHA256;
одна строка `uname` не отличит его от штатного GKI.

Каталог WSL: `/home/sad1/wifi-kernel-realme-note60x`.
Артефакты: `F:\wifi_work\artifacts\realme-note60x\gki-wifi1`.
Журнал: `F:\wifi_work\logs\realme-note60x-wifi1-build.log`.

Для повторения на этом ПК:

```powershell
python -B .\build\realme-note60x\inspect_stock.py
python -B .\build\realme-note60x\fetch_archives.py
wsl -d Ubuntu -- bash /mnt/f/wifi_work/build/realme-note60x/prepare_sources.sh
wsl -d Ubuntu -- python3 /mnt/f/wifi_work/build/realme-note60x/prepare_archive.py /mnt/f/wifi_work/.reference/realme-note60x/kernel-build-inputs/clang-r450784e-9f759dee.tar.gz /home/sad1/wifi-kernel-realme-note60x/clang-r450784e
wsl -d Ubuntu -- python3 /mnt/f/wifi_work/build/realme-note60x/prepare_archive.py /mnt/f/wifi_work/.reference/realme-note60x/kernel-build-inputs/build-tools-linux-x86-083e34d8.tar.gz /home/sad1/wifi-kernel-realme-note60x/build-tools
wsl -d Ubuntu -- dpkg-deb --extract /mnt/f/wifi_work/.reference/realme-note60x/kernel-build-inputs/cpio_2.15+dfsg-1ubuntu2.1_amd64.deb /home/sad1/wifi-kernel-realme-note60x/host-tools
wsl -d Ubuntu -- bash /mnt/f/wifi_work/build/realme-note60x/configure.sh
wsl -d Ubuntu -- bash /mnt/f/wifi_work/build/realme-note60x/run_build.sh
wsl -d Ubuntu -- bash /mnt/f/wifi_work/build/realme-note60x/stage_artifacts.sh
wsl -d Ubuntu -- python3 /mnt/f/wifi_work/build/realme-note60x/audit_capabilities.py
python -B .\build\realme-note60x\validate_artifacts.py
wsl -d Ubuntu -- python3 /mnt/f/wifi_work/build/realme-note60x/verify_signatures.py
python -B .\build\realme-note60x\finalize.py
```

`configure.sh` заново создаёт `.config`; выполняйте его перед новым
профилем, а не во время текущей компиляции. `run_build.sh` по умолчанию
использует две задачи, не останавливает WSL и не меняет её настройки.
Утилита `cpio` распакована отдельно в `host-tools/usr/bin`, без системной
установки. Наличие этого локального инструмента необходимо IKHEADERS.

Проверка ABI охватывает 167 модулей из сохранённого `vendor_boot` и 1835
их импортов из ядра/набора GKI. Модули из `super` (включая штатный
Wi-Fi-стек vendor/system_dlkm) в имеющейся резервной копии отсутствуют.
Полная совместимость этих модулей пока не может быть проверена на ПК.

Monitor mode и пути TX проверяются в исходниках/ELF. Работа конкретных
адаптеров, инъекция в эфире и загрузка телефона этим профилем не проверялись.
Финальный отчёт отделяет результаты сборки от аппаратных проверок.
