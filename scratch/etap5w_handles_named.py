"""ETAP 5W — Windows handle enumerator with object NAMES (ctypes).

Same as etap5w_handles but also queries ObjectNameInformation so we can see
whether leaking Event/Mutant/Section/Thread handles are named (typically
MF/AMF/platform) or unnamed (typically driver-created).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from collections import Counter

ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
SystemExtendedHandleInformation = 64
ObjectTypeInformation = 2
ObjectNameInformation = 1


class SYSTEM_HANDLE_ENTRY_EX(ctypes.Structure):
    _fields_ = [
        ("Object", ctypes.c_void_p),
        ("UniqueProcessId", ctypes.c_void_p),
        ("HandleValue", ctypes.c_void_p),
        ("GrantedAccess", wintypes.DWORD),
        ("CreatorBackTraceIndex", wintypes.WORD),
        ("ObjectTypeIndex", wintypes.WORD),
        ("HandleAttributes", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


def _query_type_name(handle: int) -> str:
    buf = ctypes.create_string_buffer(4096)
    res = ntdll.NtQueryObject(ctypes.c_void_p(handle), ObjectTypeInformation,
                              buf, 4096, None)
    if res != 0:
        return "?"
    us = UNICODE_STRING.from_buffer(buf, 0)
    if not us.Buffer:
        return "?"
    try:
        return ctypes.wstring_at(us.Buffer, us.Length // 2)
    except Exception:
        return "?"


def _query_name(handle: int) -> str:
    buf = ctypes.create_string_buffer(8192)
    res = ntdll.NtQueryObject(ctypes.c_void_p(handle), ObjectNameInformation,
                              buf, 8192, None)
    if res != 0:
        return ""
    us = UNICODE_STRING.from_buffer(buf, 0)
    if not us.Buffer or us.Length == 0:
        return ""
    try:
        return ctypes.wstring_at(us.Buffer, us.Length // 2)
    except Exception:
        return ""


def handle_types_with_names() -> list:
    """Return list of (type_name, object_name) for this process's handles."""
    import os as _os
    our_pid = _os.getpid()
    size = 1 << 24
    while True:
        buf = ctypes.create_string_buffer(size)
        needed = ctypes.c_ulong(0)
        res = ntdll.NtQuerySystemInformation(
            SystemExtendedHandleInformation, buf, size, ctypes.byref(needed))
        if res == 0:
            break
        if res == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, int(needed.value) + (1 << 20))
            continue
        return [("__error__", f"0x{res & 0xFFFFFFFF:08X}")]
    count = ctypes.c_ulonglong.from_buffer(buf, 0).value
    entry_size = ctypes.sizeof(SYSTEM_HANDLE_ENTRY_EX)
    out = []
    for i in range(count):
        off = 16 + i * entry_size
        if off + entry_size > size:
            break
        e = SYSTEM_HANDLE_ENTRY_EX.from_buffer(buf, off)
        if e.UniqueProcessId == our_pid:
            out.append((_query_type_name(e.HandleValue), _query_name(e.HandleValue)))
    return out


def summarize_named(types_filter=("Event", "Mutant", "Thread", "Section")):
    """Count handles by type and dump the named ones."""
    handles = handle_types_with_names()
    counts = Counter(t for t, _ in handles)
    named = Counter()
    named_examples = {}
    for t, n in handles:
        if t in types_filter and n:
            named[t] += 1
            named_examples.setdefault(t, []).append(n)
    return counts, named, named_examples


if __name__ == "__main__":
    counts, named, examples = summarize_named()
    print("TOTAL", counts.get("_TOTAL", sum(counts.values())))
    for t, c in counts.most_common(15):
        print(f"  {t:22s} {c}")
    print("named:")
    for t, c in named.most_common(10):
        print(f"  {t:22s} {c}  e.g. {examples.get(t, [])[:3]}")
