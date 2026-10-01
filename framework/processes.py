"""Contain optimizer descendants across supervisor and optimizer exits."""

import os
import signal
import subprocess

import psutil


class ProcessTree:
    """Windows Job Object or POSIX process group, independent of ancestry polling."""

    def __init__(self):
        self.closed = False
        self.handle = None
        self.process = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self.ctypes = ctypes
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            self.kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.OpenThread.restype = wintypes.HANDLE
            self.kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.kernel.ResumeThread.argtypes = [wintypes.HANDLE]
            class BasicLimits(ctypes.Structure):
                _fields_ = [("per_process", ctypes.c_int64), ("per_job", ctypes.c_int64),
                            ("flags", wintypes.DWORD), ("minimum", ctypes.c_size_t),
                            ("maximum", ctypes.c_size_t), ("active", wintypes.DWORD),
                            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                            ("scheduling", wintypes.DWORD)]
            class ExtendedLimits(ctypes.Structure):
                _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                            ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]
            self.handle = self.kernel.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())

    def launch(self, argv, **kwargs):
        if os.name != "nt":
            self.process = subprocess.Popen(argv, start_new_session=True, **kwargs)
            return self.process
        # Assign the job before Python or any tool subprocess can execute.
        self.process = subprocess.Popen(argv, creationflags=0x4 | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW, **kwargs)
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, int(self.process._handle)):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            thread_id = psutil.Process(self.process.pid).threads()[0].id
            thread = self.kernel.OpenThread(0x2, False, thread_id)
            if not thread:
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            try:
                if self.kernel.ResumeThread(thread) == -1:
                    raise self.ctypes.WinError(self.ctypes.get_last_error())
            finally:
                self.kernel.CloseHandle(thread)
        except Exception:
            self.process.kill()
            self.process.wait()
            self.close()
            raise
        return self.process

    def members(self):
        if not self.process:
            return []
        if os.name == "nt":
            # Basic process ID list: two DWORD counts followed by ULONG_PTR IDs.
            buffer = self.ctypes.create_string_buffer(65536)
            if not self.kernel.QueryInformationJobObject(self.handle, 3, buffer, len(buffer), None):
                return []
            count = self.ctypes.c_ulong.from_buffer(buffer, 4).value
            ids = (self.ctypes.c_size_t * count).from_buffer(buffer, 8)
            result = []
            for pid in ids:
                try:
                    result.append(psutil.Process(pid))
                except psutil.Error:
                    pass
            return result
        result = []
        for process in psutil.process_iter():
            try:
                if os.getpgid(process.pid) == self.process.pid:
                    result.append(process)
            except (OSError, psutil.Error):
                pass
        return result

    def close(self):
        if self.closed:
            return
        self.closed = True
        members = self.members() if self.process else []
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        elif self.process and os.name != "nt":
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        _, remaining = psutil.wait_procs(members, timeout=3)
        if os.name != "nt" and remaining:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            psutil.wait_procs(remaining, timeout=3)
