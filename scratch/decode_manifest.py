"""Dump the element tree of a binary AXML manifest, with all attributes and
typed values, so we can eyeball exactly what PackageParser will see inside the
APK we ship (especially the injected accessibility <service>)."""
import struct
import sys
import zipfile

import axml

ATTR_TYPE_NAMES = {
    0x00: "ATTR_NULL", 0x01: "ATTR_REFERENCE", 0x02: "ATTR_ATTRIBUTE",
    0x03: "ATTR_STRING", 0x04: "ATTR_FLOAT", 0x05: "ATTR_DIMENSION",
    0x06: "ATTR_FRACTION", 0x10: "ATTR_INT_DEC", 0x11: "ATTR_INT_HEX",
    0x12: "ATTR_INT_BOOLEAN", 0x13: "ATTR_INT_COLOR_ARGB8",
    0x14: "ATTR_INT_COLOR_RGB8", 0x15: "ATTR_INT_COLOR_ARGB4",
    0x16: "ATTR_INT_COLOR_RGB4",
}


def dump(data, out):
    chunks = axml.read_file(data)
    pool = None
    for (ct, hsize, csize, co) in chunks:
        if ct == axml.TYPE_STRING_POOL:
            pool = axml.parse_string_pool(data, co)
            break
    if pool is None:
        raise SystemExit("no string pool")
    strings = pool["strings"]

    def s(i):
        return strings[i] if 0 <= i < len(strings) else f"<idx {i}>"

    res_map = None
    for (ct, hsize, csize, co) in chunks:
        if ct == axml.TYPE_RES_MAP:
            n = (csize - 8) // 4
            res_map = struct.unpack_from(f"<{n}I", data, co + 8)
            break

    depth = 0
    for (ct, hsize, csize, co) in chunks:
        if ct == axml.TYPE_START_TAG:
            ns, name = struct.unpack_from("<II", data, co + 16)
            attr_start, attr_size, attr_count, id_ix, class_ix, style_ix = \
                struct.unpack_from("<HHHHHH", data, co + 32)
            print("  " * depth + f"<{s(name)}>"
                  + (f" ns={s(ns)}" if ns != 0xFFFFFFFF else ""), file=out)
            aoff = co + 32 + attr_start
            for k in range(attr_count):
                ans, aname, raw = struct.unpack_from("<III", data, aoff + k * 20)
                tv_size, tv_res0, tv_type, tv_data = struct.unpack_from(
                    "<HBB I", data, aoff + k * 20 + 12)
                tn = ATTR_TYPE_NAMES.get(tv_type, f"type{tv_type}")
                pretty = ""
                if tv_type == 0x03:
                    pretty = f'"{s(tv_data)}"'
                elif tv_type in (0x10, 0x11, 0x12):
                    pretty = str(tv_data)
                elif tv_type == 0x01:
                    pretty = f"@res {tv_data:#x}"
                rid = res_map[aname] if res_map is not None and aname < len(res_map) else 0
                print("  " * (depth + 1)
                      + f"{s(ans)}:{s(aname)} [res {rid:#010x}] "
                      + f"= {tn} data={pretty} raw={raw:#x}", file=out)
            depth += 1
        elif ct == axml.TYPE_END_TAG:
            depth -= 1
        elif ct == axml.TYPE_START_NS:
            pass
        elif ct == axml.TYPE_END_NS:
            pass
        elif ct == axml.TYPE_EOF:
            pass
        else:
            pass


def main():
    apk = sys.argv[1]
    with zipfile.ZipFile(apk) as z:
        data = z.read("AndroidManifest.xml")
    with open(sys.argv[1] + ".manifest.txt", "w", encoding="utf-8") as f:
        dump(data, f)
    print(f"dumped -> {apk}.manifest.txt")


if __name__ == "__main__":
    main()