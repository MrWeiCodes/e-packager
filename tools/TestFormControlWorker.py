"""测试常驻属性工作进程的复用、崩溃/超时恢复及父进程退出后的回收。"""
import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--driver', type=Path, required=True, help='x64 FormControlWorkerSessionTest.exe')
    parser.add_argument('--fixture', type=Path, required=True, help='x86 FormControlWorkerFailureTest.fne')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    root = repo / 'temp' / ('worker-session-test-' + uuid.uuid4().hex[:10])
    root.mkdir()
    driver = root / 'worker-driver.exe'
    shutil.copy2(args.driver, driver)
    shutil.copy2(repo / 'bin/Win32/Release/e-packager.exe', root / 'e-packager-x86.exe')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    for mode in ('normal', 'crash', 'timeout', 'parent-exit'):
        cwd = root / mode
        cwd.mkdir()
        result = subprocess.run([str(driver), str(args.fixture.resolve()), mode], cwd=cwd,
                                capture_output=True, timeout=45)
        (cwd / 'stdout.log').write_bytes(result.stdout)
        (cwd / 'stderr.log').write_bytes(result.stderr)
        assert result.returncode == 0, (mode, result.stderr)
        log = (cwd / 'e-packager.log').read_text(encoding='utf-8-sig')
        pids = re.findall(r'property_worker_started: worker_pid=(\d+)', log)
        assert len(pids) == (2 if mode in ('crash', 'timeout') else 1), (mode, log)
        if mode != 'parent-exit':
            assert log.count('property_worker_request:') == (8 if mode in ('crash', 'timeout') else 7), log
        for pid in pids:
            handle = kernel.OpenProcess(0x100000, False, int(pid))
            if handle:
                try:
                    assert kernel.WaitForSingleObject(handle, 5000) == 0, (mode, pid, 'worker still alive')
                finally:
                    kernel.CloseHandle(handle)
        parent_pid = re.search(r'\[pid=(\d+)', log)[1]
        leftovers = list(Path(tempfile.gettempdir()).glob('e-packager-property-' + parent_pid + '-*'))
        if mode == 'parent-exit':
            # 异常退出无需依赖析构，Job 杀掉工作进程；测试清理其未及删除的消息目录。
            for path in leftovers:
                assert path.resolve().parent == Path(tempfile.gettempdir()).resolve()
                shutil.rmtree(path)
        else:
            assert not leftovers, leftovers
        print('PASS worker ' + mode, flush=True)
    print(root)


if __name__ == '__main__':
    main()
