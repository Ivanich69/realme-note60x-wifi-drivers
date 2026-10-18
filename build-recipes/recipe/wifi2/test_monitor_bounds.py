"""Compile actual patched length-check prefixes in a host-only C harness.

This does not load drivers, send packets, or model the rest of a driver. It
checks boundary rejection and the copies/skips preceding allocation. Requires
a native C compiler; no compiler or WSL is started implicitly by this script.
"""

import argparse
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent

HEADER = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
#define unlikely(x) (x)
#define WLAN_HDR_A3_LEN 24
#define MAX_XMIT_EXTBUF_SZ 1536
struct ieee80211_radiotap_header { u8 it_version, pad; uint16_t len; uint32_t present; };
struct sk_buff { unsigned len; const u8 *data; };
typedef struct sk_buff _pkt;
struct pkt_file { struct sk_buff *pkt; unsigned position; };
static void _rtw_open_pktfile(struct sk_buff *skb, struct pkt_file *file) {
    file->pkt = skb; file->position = 0;
}
static unsigned _rtw_pktfile_read(struct pkt_file *file, u8 *destination, unsigned count) {
    assert(file->position <= file->pkt->len);
    assert(count <= file->pkt->len - file->position);
    if (destination) memcpy(destination, file->pkt->data + file->position, count);
    file->position += count;
    return count;
}
static unsigned ieee80211_get_radiotap_len(const u8 *data) { return data[2] | (data[3] << 8); }
'''

BODY = r'''
static void check_case(int (*fn)(struct sk_buff *), unsigned packet_size,
                       unsigned header_size, unsigned version, int expected) {
    u8 *data = calloc(packet_size > 8 ? packet_size : 8, 1);
    assert(data);
    data[0] = version; data[2] = header_size & 255; data[3] = header_size >> 8;
    struct sk_buff packet = {packet_size, data};
    int actual = fn(&packet);
    if (actual != expected) {
        fprintf(stderr, "boundary case failed: packet=%u header=%u result=%d expected=%d\n",
                packet_size, header_size, actual, expected);
        abort();
    }
    free(data);
}
static void common_cases(int (*fn)(struct sk_buff *)) {
    check_case(fn, 0, 0, 0, -1);
    check_case(fn, 7, 8, 0, -1);
    check_case(fn, 32, 0, 0, -1);
    check_case(fn, 32, 1, 0, -1);
    check_case(fn, 32, 7, 0, -1);
    check_case(fn, 32, 33, 0, -1);
    check_case(fn, 8, 8, 0, -1);
    check_case(fn, 31, 8, 0, -1);
    check_case(fn, 32, 8, 0, 24);
    check_case(fn, 33, 8, 0, 25);
    check_case(fn, 32, 8, 1, -1);
    check_case(fn, 8 + MAX_XMIT_EXTBUF_SZ - TXDESC_OFFSET, 8, 0,
               MAX_XMIT_EXTBUF_SZ - TXDESC_OFFSET);
    check_case(fn, 9 + MAX_XMIT_EXTBUF_SZ - TXDESC_OFFSET, 8, 0, -1);
}
int main(void) {
    common_cases(check_au);
    common_cases(check_eu);
    check_case(check_au, 255 + 24, 255, 0, 24);
    check_case(check_au, 256 + 24, 256, 0, 24);
    check_case(check_au, 257 + 24, 257, 0, -1);
    check_case(check_au, 65535 + 24, 65535, 0, -1);
    check_case(check_eu, 257 + 24, 257, 0, 24);
    check_case(check_eu, 65535 + 24, 65535, 0, 24);
    puts("32 monitor length/copy boundary cases passed");
    return 0;
}
'''


def generate():
    fragments = [HEADER]
    for driver, name in [("rtl8812au", "check_au"), ("rtl8188eus", "check_eu")]:
        source = (HERE / "sources/drivers" / driver / "core/rtw_xmit.c").read_text()
        start = source.index("s32 rtw_monitor_xmit_entry(")
        start = source.index("\tif (unlikely(skb->len < sizeof(struct ieee80211_radiotap_header)))", start)
        stop = source.index("\n\t// NOTE:" if name == "check_au" else "\n\tpmgntframe = alloc_mgtxmitframe", start)
        declarations = "int len = skb->len, rtap_len; struct pkt_file pktfile = {0};\n"
        if name == "check_au":
            declarations += "u8 rtap_buf[256]; struct ieee80211_radiotap_header *rtap_hdr; int rtap_remain;\n"
        else:
            declarations += "struct ieee80211_radiotap_header rtap_hdr;\n"
        fragments.append(f"static int {name}(struct sk_buff *skb) {{\n" + declarations +
                         source[start:stop] + "\nassert(pktfile.position == skb->len - len);\n"
                         "return len;\nfail: return -1;\n}\n")
    return "\n".join(fragments) + BODY


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", help="Explicit native compiler path; never auto-launches WSL")
    parser.add_argument("--generate-only", action="store_true")
    args = parser.parse_args()
    directory = HERE / "bounds-test"
    directory.mkdir(exist_ok=True)
    source = directory / "monitor_bounds.c"
    source.write_text(generate(), encoding="utf-8")
    if args.generate_only:
        print(json.dumps({"generated": str(source), "compiled": False}))
        return
    if not args.compiler:
        parser.error("--compiler is required unless --generate-only is specified")
    results = []
    for offset in (32, 40, 48, 64):
        executable = directory / f"monitor-bounds-{offset}"
        command = [args.compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra",
                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                   f"-DTXDESC_OFFSET={offset}", str(source), "-o", str(executable)]
        subprocess.run(command, check=True, timeout=60)
        run = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=15)
        results.append({"descriptor_offset": offset, "stdout": run.stdout.strip()})
    (directory / "results.json").write_text(json.dumps({"passed": True, "boundary_cases": 128,
        "address_and_undefined_behavior_sanitizers": True, "results": results,
        "scope": "Actual pre-allocation source prefixes; no radio/device operations"}, indent=2) + "\n")
    print(json.dumps({"passed": True, "cases": 128}))


if __name__ == "__main__":
    main()
