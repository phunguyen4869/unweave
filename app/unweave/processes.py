"""Child processes that never outlive the app or a cancel.

On POSIX each child gets its own session, so its process group (the CLI plus any
FFmpeg it starts) can be signalled as one. Windows has no process groups to kill:
`terminate()` stops only the direct child, and nothing stops anything when the app
itself dies. There each child goes into a Job Object marked kill-on-close, which
ends the whole tree on cancel and, because the handle closes with this process,
also when the app crashes or is ended from Task Manager.
"""

import os
import signal
import subprocess
import sys
import weakref

_kernel32 = None


def _windows_api():
    global _kernel32
    if _kernel32 is None:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        _kernel32 = kernel32
    return _kernel32


def _kill_on_close_job():
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("per_process_user_time", ctypes.c_int64), ("per_job_user_time", ctypes.c_int64),
                    ("limit_flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_process_limit", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority_class", wintypes.DWORD),
                    ("scheduling_class", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                    ("process_memory_limit", ctypes.c_size_t), ("job_memory_limit", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    kernel32 = _windows_api()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    info.basic.limit_flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # extended limits
        kernel32.CloseHandle(job)
        return None
    return job


def popen(command, **options) -> subprocess.Popen:
    """subprocess.Popen whose whole tree `stop()` can end."""
    if os.name == "posix":
        options.setdefault("start_new_session", True)
    else:
        options.pop("start_new_session", None)
    process = subprocess.Popen(command, **options)
    if sys.platform == "win32" and getattr(process, "_handle", None) is not None:
        try:
            job = _kill_on_close_job()
        except OSError:
            job = None
        # The child runs briefly before it is assigned; the CLI spends its first
        # second importing, so nothing it starts escapes the job in practice.
        if job and _windows_api().AssignProcessToJobObject(job, int(process._handle)):
            process._unweave_job = job
            # Closing the handle ends whatever is still in the job, so it must live
            # exactly as long as the Popen that owns it.
            weakref.finalize(process, _windows_api().CloseHandle, job)
        elif job:
            _windows_api().CloseHandle(job)
    return process


def stop(process: subprocess.Popen, force: bool = False) -> None:
    """End `process` and everything it started. Safe on a process that already exited."""
    # On POSIX and in a Windows job, children may outlive an exited parent.
    if process.poll() is not None and os.name != "posix" and not getattr(process, "_unweave_job", None):
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif getattr(process, "_unweave_job", None):
            _windows_api().TerminateJobObject(process._unweave_job, 1)
        elif force:
            process.kill()
        else:
            process.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass
