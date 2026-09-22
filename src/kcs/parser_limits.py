"""Hard memory ceiling for the disposable parser process only."""

import sys


def limit_memory(byte_limit=512 * 1024 * 1024):
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (byte_limit, byte_limit))
        return None
    import ctypes as c
    from ctypes import wintypes as w

    # Microsoft JOBOBJECT_EXTENDED_LIMIT_INFORMATION; SIZE_T follows pointer width.
    class Basic(c.Structure):
        _fields_ = [
            ("process_time", c.c_longlong),
            ("job_time", c.c_longlong),
            ("flags", w.DWORD),
            ("minimum_ws", c.c_size_t),
            ("maximum_ws", c.c_size_t),
            ("active_processes", w.DWORD),
            ("affinity", c.c_size_t),
            ("priority", w.DWORD),
            ("scheduling", w.DWORD),
        ]

    class Limits(c.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", c.c_ulonglong * 6),
            ("process_memory", c.c_size_t),
            ("job_memory", c.c_size_t),
            ("peak_process", c.c_size_t),
            ("peak_job", c.c_size_t),
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [c.c_void_p, w.LPCWSTR], w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    kernel.SetInformationJobObject.restype = w.BOOL
    kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = (
        [w.HANDLE, w.HANDLE],
        w.BOOL,
    )
    kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], w.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise RuntimeError("parser_memory_limit_unavailable")
    limits = Limits()
    limits.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.process_memory = byte_limit
    if not kernel.SetInformationJobObject(
        handle, 9, c.byref(limits), c.sizeof(limits)
    ) or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise RuntimeError("parser_memory_limit_unavailable")
    # Keep the OS handle open until this disposable process exits.
    return handle
