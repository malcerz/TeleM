"""ETAP 5W — Windows handle-type enumerator (ctypes, current process only).

Enumerates all handles of THIS process and counts them by object-type name
using NtQuerySystemInformation(SystemExtendedHandleInformation) +
NtQueryObject(ObjectTypeInformation).  Lets us see exactly which handle
types grow across exports (spec 14).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
SystemExtendedHandleInformation = 64
ObjectTypeInformation = 2

MAX_HANDLE_SNAPSHOT = 1 << 20


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


class PUBLIC_OBJECT_TYPE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TypeName", UNICODE_STRING),
        ("Reserved", wintypes.ULONG * 22),
    ]


def _query_type_name(handle: int) -> str:
    info = PUBLIC_OBJECT_TYPE_INFORMATION()
    # first call to get needed size
    size = wintypes.ULONG(0)
    buf = ctypes.create_string_buffer(4096)
    res = ntdll.NtQueryObject(
        ctypes.c_void_p(handle), ObjectTypeInformation,
        buf, 4096, ctypes.byref(size),
    )
    if res != 0:
        return "?"
    # parse UNICODE_STRING from the buffer
    us = UNICODE_STRING.from_buffer(buf, 0)
    if not us.Buffer:
        return "?"
    try:
        return ctypes.wstring_at(us.Buffer, us.Length // 2)
    except Exception:
        return "?"


def handle_type_counts() -> dict:
    """Return Counter of handle type names for the current process."""
    from collections import Counter

    import os as _os
    our_pid = _os.getpid()
    # We don't know size upfront; the system handle table is a few MB.
    size = 1 << 24  # 16 MB
    while True:
        buf = ctypes.create_string_buffer(size)
        needed = ctypes.c_ulong(0)
        res = ntdll.NtQuerySystemInformation(
            SystemExtendedHandleInformation, buf, size, ctypes.byref(needed)
        )
        if res == 0:
            break
        if res == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, int(needed.value) + (1 << 20))
            continue
        return {"__error__": f"0x{res & 0xFFFFFFFF:08X}"}

    # parse header: first ULONG_PTR = number of handles
    count = ctypes.c_ulonglong.from_buffer(buf, 0).value
    entry_size = ctypes.sizeof(SYSTEM_HANDLE_ENTRY_EX)
    entries = []
    for i in range(count):
        off = 16 + i * entry_size  # ULONG_PTR count (8) + ULONG_PTR reserved (8)
        if off + entry_size > size:
            break
        e = SYSTEM_HANDLE_ENTRY_EX.from_buffer(buf, off)
        if e.UniqueProcessId == our_pid:
            entries.append(e)

    counter = Counter()
    for e in entries:
        tname = _query_type_name(e.HandleValue)
        counter[tname] += 1
    counter["_TOTAL"] = len(entries)
    return counter


if __name__ == "__main__":
    import json
    counts = handle_type_counts()
    print(json.dumps(counts, indent=2))
