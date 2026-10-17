"""交替比较旧版与当前版解包，检查工程产物相同并记录阶段耗时和辅助进程数量。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import time
import uuid


def timing_seconds(lines, field, divisor):
    values = [int(match[1]) for line in lines if (match := re.search(field + r'=(\d+)', line))]
    return sum(values) / divisor if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--before-root', type=Path, required=True,
                        help='包含 before-Win32/e-packager.exe 和 before-x64/e-packager.exe 的目录')
    parser.add_argument('--architecture', choices=('Win32', 'x64', 'both'), default='both')
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--main-only', action='store_true', help='只解包主工程；默认与普通 unpack 一样处理依赖')
    args = parser.parse_args()
    assert args.rounds > 0
    repo = Path(__file__).resolve().parent.parent
    source = (args.input or repo / 'eproj/e-window-exe-full+otherFne.e').resolve()
    root = repo / 'temp' / ('window-benchmark-' + uuid.uuid4().hex[:10])
    root.mkdir()
    report = {'input': str(source), 'rounds': args.rounds, 'main_only': args.main_only, 'architectures': {}}
    architectures = ('Win32', 'x64') if args.architecture == 'both' else (args.architecture,)
    for architecture in architectures:
        stats = {'before': [], 'after': []}
        reference = None
        artifact_reference = None
        for iteration in range(args.rounds):
            for label in ('before', 'after'):
                tool = ((args.before_root / ('before-' + architecture) / 'e-packager.exe') if label == 'before'
                        else repo / 'bin' / architecture / 'Release/e-packager.exe').resolve()
                cwd = root / architecture / (label + '-' + str(iteration))
                cwd.mkdir(parents=True)
                started = time.perf_counter()
                command = [str(tool), 'unpack', str(source), str(cwd / 'workspace')]
                if args.main_only:
                    command.append('--main-only')
                result = subprocess.run(command,
                                        cwd=cwd, capture_output=True, timeout=300)
                elapsed = time.perf_counter() - started
                (cwd / 'stdout.log').write_bytes(result.stdout)
                (cwd / 'stderr.log').write_bytes(result.stderr)
                assert result.returncode == 0, (architecture, label, result.stderr)
                log = (cwd / 'e-packager.log').read_text(encoding='utf-8-sig', errors='replace')
                src = cwd / 'workspace/src'
                files = {str(p.relative_to(src)): p.read_bytes() for p in src.rglob('*') if p.is_file()}
                if reference is None:
                    reference = files
                assert files == reference, (architecture, label, 'source/XML changed')
                # 工作区自带工具应随版本更新，其余主工程和依赖产物必须逐字节一致。
                artifacts = {p.relative_to(cwd / 'workspace').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (cwd / 'workspace').rglob('*') if p.is_file() and not
                             (p.parent.name == 'tool' and p.name in ('e-packager.exe', 'e-packager-x86.exe'))}
                if artifact_reference is None:
                    artifact_reference = artifacts
                assert artifacts == artifact_reference, (architecture, label, 'project/dependency artifacts changed',
                    [key for key in artifacts.keys() | artifact_reference.keys()
                     if artifacts.get(key) != artifact_reference.get(key)])
                row = {'seconds': elapsed, 'processes_in_log': len(set(re.findall(r'\[pid=(\d+)', log))),
                       'worker_starts': log.count('property_worker_started:'),
                       'worker_requests': log.count('property_worker_request:')}
                requests = [line for line in log.splitlines() if 'property_worker_request:' in line]
                row['worker_failed_requests'] = sum('ok=false' in line for line in requests)
                row['request_seconds'] = timing_seconds(requests, 'elapsed_us', 1e6)
                if row['request_seconds'] is None:
                    row['request_seconds'] = timing_seconds(requests, 'elapsed_ms', 1000)
                row['worker_seconds'] = timing_seconds(requests, 'worker_us', 1e6)
                row['source_files'] = len(files)
                row['artifact_files'] = len(artifacts)
                row['stages'] = [dict(operation=m[1], stage=m[2], seconds=int(m[3]) / 1e6, source=m[4])
                                 for line in log.splitlines() if (m := re.search(
                                     r'operation_stage: operation=([^,]+), stage=([^,]+), elapsed_us=(\d+), source=(.*)', line))]
                if label == 'after':
                    assert row['worker_starts'] <= 1, row
                    assert not row['worker_requests'] or row['worker_starts'] == 1, row
                    assert not re.search(r'property_worker_request:.*ok=false', log), log
                stats[label].append(row)
                print(architecture, label, iteration + 1, round(elapsed, 3), 'seconds', flush=True)
        stats['average_seconds'] = {label: statistics.mean(row['seconds'] for row in rows)
                                    for label, rows in stats.items()}
        report['architectures'][architecture] = stats
    (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(root)


if __name__ == '__main__':
    main()
