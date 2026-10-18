"""Apply scoped driver compatibility fixes on the host, retaining CFI."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path('/home/sad1/wifi-kernel-realme-note60x')
HOST = Path('/mnt/f/wifi_work/build/realme-note60x')


def main():
    whitelist_path = ROOT / 'abi_symbollist.raw'
    whitelist = set(whitelist_path.read_text().splitlines())
    required_file_helpers = {'kernel_read', 'kernel_write', 'filp_open'}
    if not required_file_helpers.issubset(whitelist):
        whitelist.update(required_file_helpers)
        whitelist_path.write_text('\n'.join(sorted(whitelist)) + '\n')
    path = ROOT / 'drivers/rtl8812au/include/rtw_recv.h'
    before = path.read_text()
    text = before
    text = text.replace('\t_buffer *buf_desc;\n', '\t_buffer *buf_desc = NULL;\n')
    text = text.replace('\tu8 *buf_star;\n', '\tu8 *buf_star = NULL;\n')
    text = text.replace('return\tprecv_frame->u.hdr.rx_head;', 'return precv_frame ? precv_frame->u.hdr.rx_head : NULL;')
    text = text.replace('return\tprecv_frame->u.hdr.rx_data;', 'return precv_frame ? precv_frame->u.hdr.rx_data : NULL;')
    if before != text:
        path.write_text(text)
    manifest_path = HOST / 'source-changes.json'
    changes = json.loads(manifest_path.read_text())
    if before != text:
        relative = str(path.relative_to(ROOT))
        old = next((row for row in changes if row['file'] == relative), None)
        if old:
            old['after_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        else:
            changes.append({'file': relative, 'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
                            'after_sha256': hashlib.sha256(text.encode()).hexdigest()})
    debug_path = ROOT / 'drivers/rtl8812au/core/rtw_debug.c'
    before_debug = debug_path.read_text()
    debug = before_debug
    start = debug.index('ssize_t proc_set_tx_deauth(')
    end = debug.index('\nssize_t ', start + 1)
    body = debug[start:end]
    old = 'if (buffer && !copy_from_user(tmp, buffer, sizeof(tmp))) {'
    if old in body:
        body = body.replace('char tmp[16];', 'char tmp[16] = {0};')
        body = body.replace(old, 'if (!buffer || copy_from_user(tmp, buffer, count))\n\t\treturn -EFAULT;\n\t{')
        debug = debug[:start] + body + debug[end:]
        debug_path.write_text(debug)
        relative = str(debug_path.relative_to(ROOT))
        changes.append({'file': relative, 'before_sha256': hashlib.sha256(before_debug.encode()).hexdigest(),
                        'after_sha256': hashlib.sha256(debug.encode()).hexdigest()})
    for name in ('rtl8812au', 'rtl8812bu'):
        mlme_path = ROOT / 'drivers' / name / 'core/rtw_mlme_ext.c'
        mlme_before = mlme_path.read_text()
        mlme = re.sub(r'\bu16\s+BA_starting_seqctrl;', 'u16 BA_starting_seqctrl = 0;', mlme_before)
        mlme = mlme.replace('u8 back_ch, back_bw, back_ch_offset;',
            'u8 back_ch = rtw_get_oper_ch(padapter);\n'
            '\t\tu8 back_bw = rtw_get_oper_bw(padapter);\n'
            '\t\tu8 back_ch_offset = rtw_get_oper_choffset(padapter);')
        mlme = mlme.replace('if ((padapter->tdlsinfo.link_established == _TRUE))',
                            'if (padapter->tdlsinfo.link_established == _TRUE)')
        if mlme != mlme_before:
            mlme_path.write_text(mlme)
            relative = str(mlme_path.relative_to(ROOT))
            prior = next((row for row in changes if row['file'] == relative), None)
            if prior:
                prior['after_sha256'] = hashlib.sha256(mlme.encode()).hexdigest()
            else:
                changes.append({'file': relative, 'before_sha256': hashlib.sha256(mlme_before.encode()).hexdigest(),
                                'after_sha256': hashlib.sha256(mlme.encode()).hexdigest()})
    # This pinned ACK 5.15 tree backports MLO and puncturing APIs from later
    # upstream kernels. Select existing driver branches from actual headers,
    # rather than falsifying LINUX_VERSION_CODE or casting operation pointers.
    cfg_header = (ROOT / 'common/include/net/cfg80211.h').read_text()
    assert 'unsigned int link_id, u8 count,' in cfg_header
    assert 'bool quiet, u16 punct_bitmap);' in cfg_header
    assert 'links[IEEE80211_MLD_MAX_NUM_LINKS]' in cfg_header
    feature = 'RTW_ACK_CFG80211_BACKPORT'
    for name in ('rtl8812au', 'rtl8188eus', 'rtl8812bu'):
        cfg_path = ROOT / 'drivers' / name / 'os_dep/linux/ioctl_cfg80211.c'
        cfg_before = cfg_path.read_text()
        cfg = cfg_before
        if '#define ' + feature not in cfg:
            cfg = ('/* Pinned android13-5.15 ACK: MLO/puncturing cfg80211 backports. */\n'
                   '#define ' + feature + ' 1\n' + cfg)
            for version in ('5, 19, 0', '5, 19, 2', '6, 0, 0', '6, 1, 0', '6, 3, 0'):
                check = 'LINUX_VERSION_CODE >= KERNEL_VERSION(' + version + ')'
                cfg = cfg.replace(check, '(' + check + ' || defined(' + feature + '))')
            cfg = cfg.replace('struct cfg80211_roam_info roam_info;',
                              'struct cfg80211_roam_info roam_info = {0};')
            if name == 'rtl8812au':
                cfg = cfg.replace('roam_info.channel =', 'roam_info.links[0].channel =')
                cfg = cfg.replace('roam_info.bssid =', 'roam_info.links[0].bssid =')
        if cfg != cfg_before:
            cfg_path.write_text(cfg)
            relative = str(cfg_path.relative_to(ROOT))
            prior = next((row for row in changes if row['file'] == relative), None)
            if prior:
                prior['after_sha256'] = hashlib.sha256(cfg.encode()).hexdigest()
            else:
                changes.append({'file': relative, 'before_sha256': hashlib.sha256(cfg_before.encode()).hexdigest(),
                                'after_sha256': hashlib.sha256(cfg.encode()).hexdigest()})
    hal_path = ROOT / 'drivers/rtl8812au/hal/rtl8814a/rtl8814a_hal_init.c'
    hal_before = hal_path.read_text()
    hal = hal_before.replace('pHalData->rf_type != RF_1T2R || pHalData->rf_type != RF_1T1R',
                             'pHalData->rf_type != RF_1T2R && pHalData->rf_type != RF_1T1R')
    if hal != hal_before:
        hal_path.write_text(hal)
        changes.append({'file': str(hal_path.relative_to(ROOT)),
                        'before_sha256': hashlib.sha256(hal_before.encode()).hexdigest(),
                        'after_sha256': hashlib.sha256(hal.encode()).hexdigest()})
    for name in ('rtl8812au', 'rtl8188eus', 'rtl8812bu'):
        api_path = ROOT / 'drivers' / name / 'hal/phydm/phydm_api.c'
        if not api_path.exists():
            continue
        api_before = api_path.read_text()
        api = api_before
        api = api.replace('power_offset > -8 || power_offset < 7',
                          'power_offset >= -8 && power_offset <= 7')
        api = api.replace('power_offset > -16 || power_offset < 15',
                          'power_offset >= -16 && power_offset <= 15')
        marker = 'u8 config_phydm_read_txagc_n('
        if marker in api:
            start = api.index(marker)
            end = api.index('\n}', start) + 2
            body = api[start:end]
            body = body.replace('PHYDM_DBG(dm, ODM_PHY_CONFIG, "Invalid HWrate!\\n");\n\t\t\tbreak;',
                                'PHYDM_DBG(dm, ODM_PHY_CONFIG, "Invalid HWrate!\\n");\n\t\t\treturn INVALID_TXAGC_DATA;')
            body = body.replace('PHYDM_DBG(dm, ODM_PHY_CONFIG, "Invalid RF path!!\\n");\n\t}',
                                'PHYDM_DBG(dm, ODM_PHY_CONFIG, "Invalid RF path!!\\n");\n\t\treturn INVALID_TXAGC_DATA;\n\t}')
            api = api[:start] + body + api[end:]
        if api != api_before:
            api_path.write_text(api)
            relative = str(api_path.relative_to(ROOT))
            prior = next((row for row in changes if row['file'] == relative), None)
            if prior:
                prior['after_sha256'] = hashlib.sha256(api.encode()).hexdigest()
            else:
                changes.append({'file': relative,
                                'before_sha256': hashlib.sha256(api_before.encode()).hexdigest(),
                                'after_sha256': hashlib.sha256(api.encode()).hexdigest()})
    eus_usb = ROOT / 'drivers/rtl8188eus/os_dep/linux/usb_intf.c'
    eus_before = eus_usb.read_text()
    namespace = 'VFS_internal_I_am_really_a_filesystem_and_am_NOT_a_driver'
    if 'MODULE_IMPORT_NS(' + namespace + ')' not in eus_before:
        eus_after = eus_before + '\nMODULE_IMPORT_NS(' + namespace + ');\n'
        eus_usb.write_text(eus_after)
        changes.append({'file': str(eus_usb.relative_to(ROOT)),
                        'before_sha256': hashlib.sha256(eus_before.encode()).hexdigest(),
                        'after_sha256': hashlib.sha256(eus_after.encode()).hexdigest()})
    debug_path = ROOT / 'drivers/rtl8188eus/hal/phydm/phydm_debug.c'
    debug_before = debug_path.read_text()
    debug = debug_before
    for old_condition in ('rx_ht != 2 || rx_ht != 1', 'rx_ht != 2 && rx_ht != 1'):
        debug = debug.replace(old_condition, 'rx_ht == 2 || rx_ht == 1')
    if debug != debug_before:
        debug_path.write_text(debug)
        relative = str(debug_path.relative_to(ROOT))
        prior = next((row for row in changes if row['file'] == relative), None)
        if prior:
            prior['after_sha256'] = hashlib.sha256(debug.encode()).hexdigest()
        else:
            changes.append({'file': relative,
                            'before_sha256': hashlib.sha256(debug_before.encode()).hexdigest(),
                            'after_sha256': hashlib.sha256(debug.encode()).hexdigest()})
    dm_path = ROOT / 'drivers/rtl8812bu/hal/hal_dm.c'
    dm_before = dm_path.read_text()
    dm = dm_before.replace('if ((pregpriv->wifi_spec == 1))', 'if (pregpriv->wifi_spec == 1)')
    if dm != dm_before:
        dm_path.write_text(dm)
        changes.append({'file': str(dm_path.relative_to(ROOT)),
                        'before_sha256': hashlib.sha256(dm_before.encode()).hexdigest(),
                        'after_sha256': hashlib.sha256(dm.encode()).hexdigest()})
    halmac_path = ROOT / 'drivers/rtl8812bu/hal/hal_halmac.c'
    halmac_before = halmac_path.read_text()
    halmac = halmac_before.replace('|| (status != HALMAC_CMD_PROCESS_ERROR)',
                                   '&& (status != HALMAC_CMD_PROCESS_ERROR)')
    if halmac != halmac_before:
        halmac_path.write_text(halmac)
        changes.append({'file': str(halmac_path.relative_to(ROOT)),
                        'before_sha256': hashlib.sha256(halmac_before.encode()).hexdigest(),
                        'after_sha256': hashlib.sha256(halmac.encode()).hexdigest()})
    manifest_path.write_text(json.dumps(changes, indent=2) + '\n')
    print('Scoped Realtek fixes applied; pinned ACK cfg80211 API branches selected.')


if __name__ == '__main__':
    main()
