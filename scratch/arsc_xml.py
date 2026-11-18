"""
Minimal resources.arsc reader: enumerate the 'xml' type's entries and map each
to (resourceId -> keyName). Used to pick a SAFE victim resource whose file bytes
are replaced with the generated accessibility config, and to report the id that
the injected manifest <meta-data android:resource="@..."> must carry.

Resource id scheme: (packageId << 24) | (typeId << 16) | entryIndex, where
typeId is the 1-based index of "xml" in the type-name string pool. Follows
ResTable / ResTable_type from AOSP ResourceTypes.h.
"""
import struct


def _pool_strings(data, off, size):
    """Decode the ResStringPool at `off` (chunk size `size`). Supports UTF-8 and
    UTF-16 pools, no styles."""
    ncount, _scount, flags, sstart, _srend = struct.unpack_from("<IIIII", data, off + 8)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from("<%dI" % ncount, data, off + 28) if ncount else ()
    base = off + sstart
    end = off + size
    out = []
    for o in offsets:
        p = base + o
        if p >= end:
            out.append(None)
            continue
        if utf8:
            b = data[p]
            p += 1
            if b & 0x80:
                p += 1  # char length (2-byte form) - not needed here
            b = data[p]
            p += 1
            if b & 0x80:
                blen = ((b & 0x7F) << 8) | data[p]
                p += 1
            else:
                blen = b
            out.append(data[p:p + blen].decode("utf-8", "replace"))
        else:
            ulen = struct.unpack_from("<H", data, p)[0]
            p += 2
            out.append(data[p:p + ulen * 2].decode("utf-16-le", "replace"))
    return out


def enum_xml_resources(arsc):
    """-> dict {resource_id: key_name} for every non-empty entry of the 'xml'
    type in the table (dedup across configs)."""
    typ = struct.unpack_from("<H", arsc, 0)[0]
    assert typ == 0x0002, "not a resources table (chunk type %#x)" % typ
    total = struct.unpack_from("<I", arsc, 4)[0]

    pkgs = []
    off = 12
    while off < total:
        word, csize = struct.unpack_from("<II", arsc, off)
        typ = word & 0xFFFF
        if csize <= 0:
            break
        if typ == 0x0200:  # ResTable_package
            pkgs.append((off, csize))
        off += csize
    if not pkgs:
        raise SystemExit("resources.arsc: no package chunk found")

    poff, psize = pkgs[0]
    pkg_hsize = struct.unpack_from("<H", arsc, poff + 2)[0]
    pkg_id = struct.unpack_from("<I", arsc, poff + 8)[0]
    # Modern ResTable_package (AOSP): name is uint16_t[128] = 256 bytes of
    # UTF-16, so the offset fields start at 268 (name ends there) and the
    # package header is 288 bytes (0x120) incl. typeIdOffset. Reading them at
    # the old 140/148 landed inside the UTF-16 name (all zeros in ASCII).
    type_str_off = struct.unpack_from("<I", arsc, poff + 268)[0]
    key_str_off = struct.unpack_from("<I", arsc, poff + 276)[0]

    t_size = struct.unpack_from("<I", arsc, poff + type_str_off + 4)[0]
    k_size = struct.unpack_from("<I", arsc, poff + key_str_off + 4)[0]
    t_strs = _pool_strings(arsc, poff + type_str_off, t_size)
    k_strs = _pool_strings(arsc, poff + key_str_off, k_size)

    xml_type_id = None
    for i, s in enumerate(t_strs):
        if s == "xml":
            xml_type_id = i + 1  # type ids are 1-based indices of type names
            break
    if xml_type_id is None:
        return {}

    out = {}
    co = poff + pkg_hsize  # first sub-chunk (usually the typeStrings pool)
    while co < poff + psize:
        word, csize = struct.unpack_from("<II", arsc, co)
        typ = word & 0xFFFF
        if csize <= 0:
            break
        if typ == 0x0201:  # ResTable_type
            tid = arsc[co + 8]
            if tid == xml_type_id:
                # Per AOSP LoadedArsc.cpp: the entry-offset array starts at
                # chunk + headerSize, and each array value is relative to
                # chunk + entriesStart (the entry-data region).
                hsize = word >> 16
                entry_count = struct.unpack_from("<I", arsc, co + 12)[0]
                entries_start = struct.unpack_from("<I", arsc, co + 16)[0]
                offs = co + hsize
                for idx in range(entry_count):
                    rel = struct.unpack_from("<I", arsc, offs + 4 * idx)[0]
                    if rel == 0xFFFFFFFF:
                        continue
                    eoff = co + entries_start + rel
                    if eoff + 8 > len(arsc):
                        continue
                    key = struct.unpack_from("<I", arsc, eoff + 4)[0]
                    name = k_strs[key] if key < len(k_strs) else None
                    if name is None:
                        continue
                    rid = (pkg_id << 24) | (xml_type_id << 16) | idx
                    out[rid] = name
        co += csize
    return out


def _chunk_type_name(typ):
    return {0x0001: "string pool", 0x0002: "table", 0x0200: "package",
            0x0201: "type", 0x0202: "type spec", 0x0203: "library"}.get(typ, "0x%x" % typ)


def main():
    """Diagnostic: dump the real structure of a base.apk's resources.arsc so a
    parser bug is visible instead of a bare 'no entries'. Run:
        python scratch\\arsc_xml.py              (uses scratch\\apk_build\\base.apk)
        python scratch\\arsc_xml.py <any.apk>"""
    import os
    import sys
    import zipfile

    apk = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "apk_build", "base.apk")
    with zipfile.ZipFile(apk) as z:
        arsc = z.read("resources.arsc")
    print("== resources.arsc: %d bytes from %s" % (len(arsc), apk))
    total = struct.unpack_from("<I", arsc, 4)[0]
    print("declared table size: %#x" % total)

    off = 12
    while off < total:
        word, csize = struct.unpack_from("<II", arsc, off)
        typ, hsize = word & 0xFFFF, word >> 16
        if csize <= 0:
            print("  @%#x size<=0 - stop" % off)
            break
        print("  top chunk @%#x %-12s hsize=%#x size=%#x" % (off, _chunk_type_name(typ), hsize, csize))
        if typ == 0x0200:
            pkg_id = struct.unpack_from("<I", arsc, off + 8)[0]
            raw_name = arsc[off + 12: off + 12 + 256]
            name = raw_name.decode("utf-16-le", "replace").split("\x00")[0]
            tso = struct.unpack_from("<I", arsc, off + 268)[0]
            kso = struct.unpack_from("<I", arsc, off + 276)[0]
            print("    package id=%#x name=%r typeStrings@%#x keyStrings@%#x hsize=%#x"
                  % (pkg_id, name, tso, kso, hsize))
            _dump_package(arsc, off, csize, hsize, tso, kso)
        off += csize


def _dump_package(arsc, poff, psize, hsize, tso, kso):
    t_size = struct.unpack_from("<I", arsc, poff + tso + 4)[0]
    k_size = struct.unpack_from("<I", arsc, poff + kso + 4)[0]
    t_flags = struct.unpack_from("<I", arsc, poff + tso + 16)[0]
    k_flags = struct.unpack_from("<I", arsc, poff + kso + 16)[0]
    t = _pool_strings(arsc, poff + tso, t_size)
    k = _pool_strings(arsc, poff + kso, k_size)
    print("    typeStrings: n=%d flags=%#x : %s" % (len(t), t_flags, ", ".join(map(str, t))))
    print("    keyStrings:  n=%d flags=%#x : %s" % (len(k), k_flags, ", ".join(map(str, k[:20]))))

    xml_id = None
    for i, s in enumerate(t):
        if s == "xml":
            xml_id = i + 1
    print("    derived xml type id: %s" % xml_id)

    co = poff + hsize
    while co < poff + psize and co < len(arsc):
        word, csize = struct.unpack_from("<II", arsc, co)
        typ = word & 0xFFFF
        if csize <= 0:
            print("    @%#x size<=0 - stop" % co)
            break
        if typ == 0x0202:
            print("    typeSpec @%#x id=%#x entryCount=%d"
                  % (co, arsc[co + 8], struct.unpack_from("<I", arsc, co + 12)[0]))
        elif typ == 0x0201:
            hsize = word >> 16
            tid = arsc[co + 8]
            ec = struct.unpack_from("<I", arsc, co + 12)[0]
            es = struct.unpack_from("<I", arsc, co + 16)[0]
            print("    type @%#x hsize=%#x id=%#x entryCount=%d entriesStart=%#x"
                  % (co, hsize, tid, ec, es))
            offs = co + hsize
            sample = [struct.unpack_from("<I", arsc, offs + 4 * i)[0] for i in range(min(ec, 12))]
            print("      offset sample:", ["%#x" % v for v in sample])
            if xml_id is not None and tid == xml_id:
                for i in range(ec):
                    rel = struct.unpack_from("<I", arsc, offs + 4 * i)[0]
                    if rel == 0xFFFFFFFF:
                        continue
                    eoff = co + es + rel
                    if eoff + 8 > len(arsc):
                        print("      entry %d -> eoff %#x OUT OF RANGE" % (i, eoff))
                        continue
                    key = struct.unpack_from("<I", arsc, eoff + 4)[0]
                    print("      entry %d -> key idx %d -> %r"
                          % (i, key, k[key] if key < len(k) else None))
        co += csize


if __name__ == "__main__":
    main()