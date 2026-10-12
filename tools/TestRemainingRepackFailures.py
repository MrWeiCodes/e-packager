"""复跑指定审计中的回包失败项，保留旧证据并验证新增注释及源码差异。"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re

from TestModuleRoundtripAudit import (append_comments, compare, decode_in_source_directory, hashes,
                                     inventory, invoke, save, unresolved_tokens)


def declaration_identities(workspace):
    """注释编辑不应改变页面、方法、变量及类型的原生身份。"""
    meta = json.loads((workspace / 'project/_meta.json').read_text(encoding='utf-8-sig'))
    snapshots = json.loads((workspace / 'project/.native_source_map.json').read_text(encoding='utf-8-sig'))
    assert len(meta['sourceFiles']) == len(snapshots)
    fields = ('classId', 'formId', 'baseClass', 'classVarIds', 'classVarTypes')
    method_fields = ('id', 'returnType', 'paramIds', 'paramTypes', 'localIds', 'localTypes')
    return {source['key']: {**{k: snapshot.get(k) for k in fields},
                           'methods': [{k: method.get(k) for k in method_fields} for method in snapshot['methods']]}
            for source, snapshot in zip(meta['sourceFiles'], snapshots)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--architectures', nargs='+', default=['Win32'])
    parser.add_argument('--ids', nargs='+', type=int)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--bin-root', type=Path, help='默认使用项目 bin 目录；包含 Win32/Release 和 x64/Release')
    parser.add_argument('--fresh-unpack', action='store_true', help='重新拆包副本并追加注释，不复用旧工作区')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    baseline = json.loads((args.baseline / 'results.json').read_text(encoding='utf-8-sig'))
    metadata = json.loads((args.baseline / 'run.json').read_text(encoding='utf-8-sig'))
    originals = Path(metadata['source'])
    selected = [r for r in baseline if r['arch'] == 'Win32' and
                (r['id'] in args.ids if args.ids else
                 r.get('stages', {}).get('semantic_pack', {}).get('status') == 'error')]
    bin_root = args.bin_root or repo / 'bin'
    binaries = {a: bin_root / f'{a}/Release/e-packager.exe' for a in set(args.architectures) | {'Win32'}}
    fingerprints = {a: hashes(p) for a, p in binaries.items()}
    save(args.output / 'run.json', dict(baseline=str(args.baseline), ids=[r['id'] for r in selected], binaries=fingerprints,
                                      fresh_unpack=args.fresh_unpack, decoder='Win32'))

    def check(old, arch):
        root = args.output / f"{old['id']:04}" / arch
        root.mkdir(parents=True)
        workspace = Path(old['directory']) / 'workspace'
        source = args.baseline / 'inputs' / old['source']
        before = hashes(source)
        original = originals / old['source']
        original_before = hashes(original)
        row = dict(id=old['id'], arch=arch, source=old['source'], stages={})
        try:
            modified_pages = old.get('modified_pages', [])
            if args.fresh_unpack:
                workspace = root / 'workspace'
                row['stages']['fresh_unpack'] = invoke([binaries['Win32'], 'unpack', source, workspace], root, 'fresh-unpack', args.timeout)
                if row['stages']['fresh_unpack']['status'] != 'ok':
                    raise RuntimeError('fresh_unpack_failed')
                unchanged = root / ('unchanged' + source.suffix)
                row['stages']['unchanged_pack'] = invoke([binaries[arch], 'pack', workspace, unchanged], root, 'unchanged-pack', args.timeout)
                row['unchanged_identical'] = row['stages']['unchanged_pack']['status'] == 'ok' and hashes(unchanged) == before
                if not row['unchanged_identical']:
                    raise RuntimeError('unchanged_roundtrip_differs')
                modified_pages = append_comments(workspace, old['id'])
                row['modified_pages'] = modified_pages
            expected = inventory(workspace)
            row['baseline_unresolved_tokens'] = unresolved_tokens(workspace)
            expected_identities = declaration_identities(workspace)
            packed = root / 'edited.e'
            row['stages']['pack'] = invoke([binaries[arch], 'pack', workspace, packed], root, 'pack', args.timeout)
            if row['stages']['pack']['status'] == 'ok':
                decoded = root / 'decoded'
                row['stages']['unpack'] = decode_in_source_directory(binaries['Win32'], packed, source, decoded, root, 'unpack', args.timeout)
                if row['stages']['unpack']['status'] == 'ok':
                    actual = inventory(decoded)
                    row['differences'] = compare(expected, actual, root)
                    row['missing_markers'] = [p['path'] for p in modified_pages if p['marker'] not in actual.get(p['path'], {}).get('value', '')]
                    row['unresolved_tokens'] = unresolved_tokens(decoded)
                    token_set = lambda items: {(item['path'], token) for item in items for token in item['tokens']}
                    row['new_unresolved_tokens'] = sorted(token_set(row['unresolved_tokens']) - token_set(row['baseline_unresolved_tokens']))
                    actual_identities = declaration_identities(decoded)
                    row['identity_changes'] = [key for key in sorted(expected_identities.keys() | actual_identities.keys())
                                               if expected_identities.get(key) != actual_identities.get(key)]
                    row['stages']['repack'] = invoke([binaries[arch], 'pack', decoded, root / 'second.e'], root, 'repack', args.timeout)
            else:
                match = re.search(r'pack failed: ([^\r\n]+)', row['stages']['pack']['diagnostic'])
                row['error'] = match.group(1) if match else row['stages']['pack']['diagnostic']
        except Exception as error:
            row['error'] = repr(error)
        row['source_unchanged'] = hashes(source) == before
        row['original_unchanged'] = hashes(original) == original_before
        save(root / 'result.json', row)
        return row

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(check, r, a) for r in selected for a in args.architectures]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            save(args.output / 'results.json', sorted(rows, key=lambda r: (r['id'], r['arch'])))
            print(row['id'], row['arch'], row['stages'].get('pack', {}).get('status'), row.get('error', '')[:180], flush=True)
    assert fingerprints == {a: hashes(p) for a, p in binaries.items()}, 'binary changed during test'
    roundtrip_ok = lambda r: all(r['stages'].get(s, {}).get('status') == 'ok' for s in ['pack', 'unpack', 'repack']) and not any(r.get(k) for k in ['missing_markers', 'new_unresolved_tokens', 'identity_changes']) and 'error' not in r
    summary = dict(total=len(rows), roundtrip_success=sum(roundtrip_ok(r) for r in rows),
                   strict_success=sum(roundtrip_ok(r) and not r.get('differences') and not r.get('unresolved_tokens') for r in rows),
                   stages={s: dict(Counter(r['stages'].get(s, {}).get('status', 'not_run') for r in rows)) for s in ['pack', 'unpack', 'repack']}, pack=dict(Counter(r['stages'].get('pack', {}).get('status', 'exception') for r in rows)),
                   missing_comments=[r['id'] for r in rows if r.get('missing_markers')],
                   identity_changes=[dict(id=r['id'], arch=r['arch'], pages=r['identity_changes']) for r in rows if r.get('identity_changes')],
                   new_unresolved_tokens=[dict(id=r['id'], arch=r['arch'], tokens=r['new_unresolved_tokens']) for r in rows if r.get('new_unresolved_tokens')],
                   source_unchanged=all(r['source_unchanged'] for r in rows), originals_unchanged=all(r['original_unchanged'] for r in rows))
    save(args.output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary['roundtrip_success'] == len(rows) and summary['source_unchanged'] and summary['originals_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
