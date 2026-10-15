"""逐页加注释，验证 EC 双架构语义回包及可选的真实 IDE 模块编译。"""
import argparse
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from TestModuleRoundtripAudit import audit, hashes, invoke, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ide', type=Path)
    parser.add_argument('--launcher', type=Path)
    args = parser.parse_args()
    if bool(args.ide) != bool(args.launcher):
        parser.error('--ide 与 --launcher 必须同时提供')
    source = args.input.resolve()
    if source.suffix.lower() != '.ec' or not source.is_file() or not source.stat().st_size:
        parser.error('--input 必须是非空 EC 文件')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'inputs').mkdir()
    original = hashes(source)
    shutil.copy2(source, output / 'inputs' / source.name)
    item = dict(id=1, relative=source.name, **original)
    repo = Path(__file__).resolve().parents[1]
    options = SimpleNamespace(output=output, bin_root=repo / 'bin', timeout=180)
    results = []
    for arch in ('Win32', 'x64'):
        row = audit(options, item, arch)
        if row['status'] == 'passed' and args.ide:
            root = Path(row['directory'])
            artifact = root / ('ec-regression-' + arch + '.ec')
            report = root / 'compile-result.json'
            command = invoke([args.launcher, 'headless-compile', args.ide,
                              root / 'edited.e', artifact, '--target', 'ecom',
                              '--result', report, '--timeout', '120'], root, 'compile', 150)
            result = json.loads(report.read_text(encoding='utf-8-sig')) if report.exists() else {}
            row['compile_verified'] = bool(command['status'] == 'ok' and result.get('ok') and
                result.get('compile_result', {}).get('artifact_verified') and
                artifact.is_file() and artifact.stat().st_size)
            if not row['compile_verified']:
                row['issues'].append('ide_compile_failed')
                row['status'] = 'failed'
            save(root / 'result.json', row)
        results.append(row)
        print(f'{arch}: {row["status"]}; pages={len(row.get("modified_pages", []))}; issues={row["issues"]}', flush=True)
    summary = dict(originals_unchanged=hashes(source) == original, results=results)
    save(output / 'results.json', summary)
    return int(not summary['originals_unchanged'] or any(r['status'] != 'passed' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
