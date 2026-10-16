"""验证日志位置提示、写入失败后的切换及多进程追加；所有文件均放在 temp。"""
import os
from pathlib import Path
import shutil
import subprocess
import uuid


def main():
    repo = Path(__file__).resolve().parent.parent
    root = repo / 'temp' / ('log-location-test-' + uuid.uuid4().hex[:10])
    for architecture in ('Win32', 'x64'):
        for blocked_count in range(5):
            case = root / architecture / str(blocked_count)
            working = case / 'working'
            executable = case / 'bin' / 'e-packager.exe'
            local = case / 'local'
            temporary = case / 'temporary'
            for directory in (working, executable.parent, local, temporary):
                directory.mkdir(parents=True)
            shutil.copy2(repo / 'bin' / architecture / 'Release' / 'e-packager.exe', executable)
            candidates = [working / 'e-packager.log', executable.parent / 'e-packager.log',
                          local / 'e-packager' / 'logs' / 'e-packager.log',
                          temporary / 'e-packager' / 'logs' / 'e-packager.log']
            # 用同名目录稳定模拟无法创建日志，避免依赖管理员权限或修改 ACL。
            for path in candidates[:blocked_count]:
                path.mkdir(parents=True)
            environment = dict(os.environ, LOCALAPPDATA=str(local), TEMP=str(temporary), TMP=str(temporary))
            trace = working / 'e2txt_trace.log'
            trace.write_bytes(b'previous-trace-session\r\n' * 1000)
            old_trace = trace.read_bytes()
            version = subprocess.run([str(executable), '--version'], cwd=working, env=environment,
                                     capture_output=True, timeout=30)
            assert version.returncode == 0
            assert not any(path.is_file() for path in candidates)
            assert trace.read_bytes() == old_trace
            result = subprocess.run([str(executable), '--help'], cwd=working, env=environment,
                                    capture_output=True, timeout=30)
            (case / 'stderr.txt').write_bytes(result.stderr)
            assert result.returncode == 0, result.stderr
            assert trace.read_bytes() == b''
            stderr = result.stderr.decode('utf-8')
            if blocked_count == 4:
                assert '日志写入失败:' in stderr
                assert all(str(path) in stderr for path in candidates)
                assert not any(path.is_file() for path in candidates)
                continue
            expected = candidates[blocked_count]
            assert '日志文件: ' + str(expected) in stderr, stderr
            if blocked_count:
                assert 'log_fallback:' in stderr and 'Win32 error=' in stderr
            data = expected.read_bytes()
            assert b'command_begin:' in data and b'command_end: exit_code=0' in data
            # 连续运行清空历史内容，文件不会随运行次数增长。
            for _ in range(4):
                with expected.open('ab') as output:
                    output.write(b'previous-session-marker\r\n' * 1000)
                process = subprocess.run([str(executable), '--help'], cwd=working, env=environment,
                                         capture_output=True, timeout=30)
                assert process.returncode == 0
                assert b'previous-session-marker' not in expected.read_bytes()
            data = expected.read_bytes()
            assert data.count(b'\xef\xbb\xbf') == 1
            assert b'\n' not in data.replace(b'\r\n', b'')
            assert data.count(b'command_begin:') == 1
            assert data.count(b'command_end: exit_code=0') == 1
            assert all(' [pid=' in line for line in data.decode('utf-8-sig').splitlines())
            # 编译解码辅助进程沿用本次日志，不清空父进程记录。
            workers = [subprocess.Popen([str(executable), '--log-worker', '--help'], cwd=working,
                                       env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                       for _ in range(4)]
            for worker in workers:
                worker.communicate(timeout=30)
                assert worker.returncode == 0
            appended = expected.read_bytes()
            assert appended.startswith(data)
            assert appended.count(b'\xef\xbb\xbf') == 1
            assert appended.count(b'command_end: exit_code=0') == 5
        # 真正触发解包跟踪：主命令重置，辅助进程保留同一次运行的跟踪。
        working = root / architecture / 'trace-decode'
        working.mkdir()
        tool = repo / 'bin' / architecture / 'Release' / 'e-packager.exe'
        source = working / 'input.e'
        shutil.copy2(repo / 'eproj' / 'e-console-exe-new-proj.e', source)
        trace = working / 'e2txt_trace.log'
        for index, worker in enumerate((False, True, False)):
            trace.write_bytes(b'trace-marker\r\n')
            command = [str(tool)] + (['--log-worker'] if worker else [])
            result = subprocess.run(command + ['unpack', str(source), str(working / ('output-' + str(index))), '--main-only'],
                                    cwd=working, capture_output=True, timeout=30)
            assert result.returncode == 0, result.stderr
            data = trace.read_bytes()
            assert (b'trace-marker' in data) == worker
            assert b'BuildDependencies begin' in data and b'BuildProgramPages end' in data
        # 清空失败可诊断，不阻断主命令。
        trace.unlink()
        trace.mkdir()
        result = subprocess.run([str(tool), '--help'], cwd=working, capture_output=True, timeout=30)
        assert result.returncode == 0
        assert b'trace_log_reset_failed:' in result.stderr
        assert b'trace_log_reset_failed:' in (working / 'e-packager.log').read_bytes()
        print('PASS ' + architecture + ': location reporting, all fallback paths, total failure, version, session reset', flush=True)
    print(root)


if __name__ == '__main__':
    main()
