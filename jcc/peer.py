"""Which Windows account is on the other end of a local connection.

JARVIS listens on this computer only, but on a PC with several Windows accounts another signed-in
person could still reach it. The window page carries the access token, so it is only handed to
programs running as the same Windows account as JARVIS itself.
"""
from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes


def _account_of(pid: int) -> str | None:
    """The account (as a SID string) that owns a process, or None if it cannot be read."""
    kernel32, advapi32 = ctypes.windll.kernel32, ctypes.windll.advapi32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    process = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(wintypes.HANDLE(process), 0x0008, ctypes.byref(token)):
            return None
        try:
            size = wintypes.DWORD()
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value or 256)
            if not advapi32.GetTokenInformation(token, 1, buffer, len(buffer), ctypes.byref(size)):
                return None
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]   # TOKEN_USER begins with a pointer to the SID
            text = ctypes.c_wchar_p()
            if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(text)):
                return None
            try:
                return text.value
            finally:
                kernel32.LocalFree(text)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(process))


def _owner_of_connection(client_port: int, server_port: int) -> int | None:
    """The process id that opened the connection from 127.0.0.1:client_port to 127.0.0.1:server_port."""
    iphlpapi = ctypes.windll.iphlpapi
    size = wintypes.DWORD(0)
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 4, 0)   # IPv4, connections with their owning process
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value + 4096)
        size = wintypes.DWORD(len(buffer))
        if iphlpapi.GetExtendedTcpTable(buffer, ctypes.byref(size), False, 2, 4, 0) == 0:
            break
    else:
        return None
    count = struct.unpack_from("<I", buffer, 0)[0]
    loopback = struct.unpack("<I", bytes((127, 0, 0, 1)))[0]
    for index in range(count):
        _, local_address, local_port, remote_address, remote_port, pid = struct.unpack_from("<IIIIII", buffer, 4 + index * 24)
        local, remote = ((local_port & 0xFF) << 8) | ((local_port >> 8) & 0xFF), ((remote_port & 0xFF) << 8) | ((remote_port >> 8) & 0xFF)
        if local == client_port and remote == server_port and local_address == loopback and remote_address == loopback:
            return pid
    return None


def answered_by_me(client_port: int, server_port: int) -> bool | None:
    """The same question asked from the calling side: is the program that answers on server_port this account's own?
    True if it is, False if it belongs to another account, None if unknown. To be asked while the connection is open.

    (Seen from the answering program, the connection runs from its port to the caller's: the same table, read the
    other way round.)"""
    return same_user(server_port, client_port)


def same_user(client_port: int, server_port: int) -> bool | None:
    """True if the caller runs as the same Windows account, False if it is another account, None if unknown."""
    if os.name != "nt":
        return None
    try:
        pid = _owner_of_connection(int(client_port), int(server_port))
        if not pid:
            return None
        theirs, mine = _account_of(pid), _account_of(os.getpid())
        if not theirs or not mine:
            # A process we may not even look at belongs to someone else (or to the system).
            return False if mine and not theirs else None
        return theirs == mine
    except (OSError, ValueError, struct.error, AttributeError):
        return None
