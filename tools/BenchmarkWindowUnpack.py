"""交替比较旧版与当前版窗口解包，检查输出源码/XML 相同并记录辅助进程数量。"""
import argparse
import json
from pathlib import Path
import re
import statistics
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--before-root', type=Path, required=True,
                        help='包含 before-Win32/e-packager.exe 和 before-x64/e-packager.exe 的目录')
    parser.add_argument('--architecture', choices=('Win32', 'x64', 'both'), default='both')
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    assert args.rounds > 0
    repo = Path(__file__).resolve().parent.parent
    source = (args.input or repo / 'eproj/e-window-exe-full+otherFne.e').resolve()
    root = repo / 'temp' / ('window-benchmark-' + uuid.uuid4().hex[:10])
    root.mkdir()
    report = {'input': str(source), 'rounds': args.rounds, 'architectures': {}}
    architectures = ('Win32', 'x64') if args.architecture == 'both' else (args.architecture,)
    for architecture in architectures:
        stats = {'before': [], 'after': []}
        reference = None
        for iteration in range(args.rounds):
            for label in ('before', 'after'):
                tool = ((args.before_root / ('before-' + architecture) / 'e-packager.exe') if label == 'before'
                        else repo / 'bin' / architecture / 'Release/e-packager.exe').resolve()
                cwd = root / architecture / (label + '-' + str(iteration))
                cwd.mkdir(parents=True)
                started = time.perf_counter()
                result = subprocess.run([str(tool), 'unpack', str(source), str(cwd / 'workspace'), '--main-only'],
                                        cwd=cwd, capture_output=True, timeout=300)
                elapsed = time.perf_counter() - started
                (cwd / 'stdout.log').write_bytes(result.stdout)
                (cwd / 'stderr.log').write_bytes(result.stderr)
                assert result.returncode == 0, (architecture, label, result.stderr)
                log = (cwd / 'e-packager.log').read_text(encoding='utf-8-sig')
                src = cwd / 'workspace/src'
                files = {str(p.relative_to(src)): p.read_bytes() for p in src.rglob('*') if p.is_file()}
                if reference is None:
                    reference = files
                assert files == reference, (architecture, label, 'source/XML changed')
                row = {'seconds': elapsed, 'processes_in_log': len(set(re.findall(r'\[pid=(\d+)', log))),
                       'worker_starts': log.count('property_worker_started:'),
                       'worker_requests': log.count('property_worker_request:')}
                if label == 'after':
                    assert row['worker_starts'] == 1, row
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
