"""Windows loopback-forward provenance. No credential is sent before this check."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import threading

_cache = {}
_lock = threading.Lock()

def validate_ssh_arguments(executable, argv, peer, port):
    expected = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/OpenSSH/ssh.exe"
    if os.path.normcase(str(Path(executable).resolve())) != os.path.normcase(str(expected.resolve())):
        raise PermissionError("Local forward is not owned by the expected SSH executable")
    options, keys, forwards = {}, [], []
    index = 1
    while index < len(argv):
        item = argv[index]
        if item in ("-o", "-i", "-L"):
            index += 1
            if index >= len(argv): raise PermissionError("Incomplete SSH argument")
            val = argv[index]
            if item == "-o":
                name, sep, value = val.partition("=")
                name = name.lower()
                if not sep or name in options: raise PermissionError("Ambiguous SSH options")
                options[name] = value
            elif item == "-i": keys.append(val)
            else: forwards.append(val)
        index += 1
    normal = lambda p: os.path.normcase(str(Path(p).resolve()))
    if (len(keys) != 1 or normal(keys[0]) != normal(peer["key_file"])
            or forwards != [f"127.0.0.1:{port}:127.0.0.1:{port}"]
            or argv[-1] != peer["user"] + "@" + peer["host"]
            or options.get("stricthostkeychecking") != "yes"
            or options.get("batchmode") != "yes"
            or options.get("exitonforwardfailure") != "yes"
            or normal(options.get("userknownhostsfile", "")) != normal(peer["known_hosts_file"])
            or "-N" not in argv):
        raise PermissionError("SSH forward does not match the pinned transport profile")
    return True

def listener_pid(port):
    if os.name != "nt": raise PermissionError("This transport profile requires Windows ownership verification")
    ip = ctypes.WinDLL("iphlpapi", use_last_error=True)
    size = wintypes.DWORD()
    get = ip.GetExtendedTcpTable
    get.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    get.restype = wintypes.DWORD
    result = get(None, ctypes.byref(size), False, 2, 3, 0)
    if result != 122 or not 4 <= size.value <= 4_000_000:
        raise PermissionError("TCP ownership unavailable")
    data = ctypes.create_string_buffer(size.value)
    if get(data, ctypes.byref(size), False, 2, 3, 0) != 0:
        raise PermissionError("TCP ownership unavailable")
    count = struct.unpack_from("=I", data)[0]
    owners = []
    for index in range(count):
        state, addr, local_port, _, _, owner = struct.unpack_from("=6I", data, 4 + index * 24)
        if (state == 2 and socket.ntohs(local_port & 0xffff) == port
                and socket.inet_ntoa(struct.pack("=I", addr)) == "127.0.0.1"):
            owners.append(owner)
    if len(owners) != 1: raise PermissionError("Expected one loopback listener")
    return owners[0]

def owner_identity(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    handle = kernel.OpenProcess(0x1000,False,pid)
    if not handle: raise PermissionError("Forward owner is unavailable")
    try:
        buf=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(32768)
        if not kernel.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)):
            raise PermissionError("Forward owner image unavailable")
        expected=Path(os.environ.get("WINDIR","C:/Windows"))/"System32/OpenSSH/ssh.exe"
        if os.path.normcase(str(Path(buf.value).resolve())) != os.path.normcase(str(expected.resolve())):
            raise PermissionError("Loopback listener is not the expected SSH process")
        stamps=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[ctypes.byref(x) for x in stamps]):
            raise PermissionError("Forward owner generation unavailable")
        return (pid,(stamps[0].dwHighDateTime<<32)+stamps[0].dwLowDateTime)
    finally:kernel.CloseHandle(handle)


def windows_argv(command):
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    values = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not values: raise PermissionError("SSH command-line unavailable")
    try: return [values[i] for i in range(count.value)]
    finally: kernel.LocalFree(ctypes.cast(values, ctypes.c_void_p))

def verify_peer(peer, port):
    # Called after HTTPConnection.connect(), before any authorization header.
    # A later listener replacement cannot inherit this already-established TCP stream.
    owner = listener_pid(port)
    generation = owner_identity(owner)
    with _lock:
        record = _cache.get(generation)
        if record is None:
            command = (
                "$ErrorActionPreference='Stop';"
                f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={owner}';"
                "@{executable=$p.ExecutablePath;command=$p.CommandLine;created=$p.CreationDate.ToString('o')}"
                "|ConvertTo-Json -Compress")
            powershell = str(Path(os.environ.get("WINDIR","C:/Windows"))/"System32/WindowsPowerShell/v1.0/powershell.exe")
            result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, timeout=3, check=True,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if len(result.stdout) > 20000: raise PermissionError("Bounded SSH metadata exceeded")
            record = json.loads(result.stdout)
            record["argv"] = windows_argv(record["command"])
            # Cache only successful pinned validation; ownership is checked on every connection.
            validate_ssh_arguments(record["executable"], record["argv"], peer, port)
            _cache.clear()
            _cache[generation] = record
        validate_ssh_arguments(record["executable"], record["argv"], peer, port)
    return True
