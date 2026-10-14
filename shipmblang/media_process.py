"""Own the complete native worker tree, including renderer grandchildren."""
import os
import signal
import subprocess


class ProcessTree:
    def __init__(self, process):
        self.process, self.handle = process, None
        if os.name == 'nt':
            import ctypes as c
            from ctypes import wintypes as w
            class Basic(c.Structure):
                _fields_ = [('process_time', c.c_longlong), ('job_time', c.c_longlong), ('flags', w.DWORD),
                            ('min_working', c.c_size_t), ('max_working', c.c_size_t), ('active', w.DWORD),
                            ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
            class IO(c.Structure):
                _fields_ = [(n, c.c_ulonglong) for n in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
            class Limits(c.Structure):
                _fields_ = [('basic', Basic), ('io', IO), ('process_memory', c.c_size_t),
                            ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]
            kernel = c.WinDLL('kernel32', use_last_error=True)
            kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
            kernel.CreateJobObjectW.restype = w.HANDLE
            kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
            kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
            kernel.CloseHandle.argtypes = [w.HANDLE]
            kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
            self.kernel = kernel
            handle = kernel.CreateJobObjectW(None, None)
            limits = Limits()
            limits.basic.flags = 0x2000 | 0x200 | 0x8  # kill on close, job memory, active process cap
            limits.basic.active = 64
            limits.job_memory = 4 * 1024 ** 3
            if not handle or not kernel.SetInformationJobObject(handle, 9, c.byref(limits), c.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, w.HANDLE(process._handle)):
                if handle:
                    kernel.CloseHandle(handle)
                process.kill()
                process.wait()
                raise OSError(c.get_last_error(), 'Cannot contain the media worker process tree.')
            self.handle = handle

    def close(self):
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        elif os.name != 'nt':
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)


def spawn(command, **options):
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(command, **flags, **options)
    return process, ProcessTree(process)
