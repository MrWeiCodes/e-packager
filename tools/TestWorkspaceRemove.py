"""实际验证四类增删、资源清理、错误无落盘，以及双架构回包和 IDE 编译。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from TestEComUpdateRoundTrip import read_json, write
from TestEComHeadlessRoundTrip import compile_project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ide', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--arch', nargs='+', choices=('Win32', 'x64'), default=('Win32', 'x64'))
    parser.add_argument('--module', type=Path, help='可选：使用已有真实 EC，避免依赖 IDE 的模块编译能力')
    parser.add_argument('--module-expression', default='删除测试取值 ()', help='模块公开的无参整数型调用，用于残留引用测试')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    output = (args.output or repo / 'temp' / f'workspace-remove-{uuid.uuid4().hex}').resolve()
    output.mkdir(parents=True, exist_ok=False)
    decoder = repo / 'bin/Win32/Release/e-packager.exe'
    sequence = 0

    def run(tool, *arguments, error=None):
        nonlocal sequence
        sequence += 1
        completed = subprocess.run([str(tool), *map(str, arguments)], capture_output=True, timeout=120)
        raw = completed.stdout + completed.stderr
        log = output / f'{sequence:03d}-{arguments[0]}.log'
        log.write_bytes(raw)
        text = raw.decode('utf-8', errors='replace')
        if error is None:
            assert completed.returncode == 0, f'{log}: {text}'
        else:
            assert completed.returncode != 0 and error in text, f'{log}: {text}'
        return text

    def unpack(source, target):
        run(decoder, 'unpack', source, target)

    def tree(workspace):
        return {str(p.relative_to(workspace)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in workspace.rglob('*') if p.is_file()}

    def resources(workspace, kind):
        return read_json(workspace / kind / 'list.json')['items']

    def metadata(workspace):
        return read_json(workspace / 'project/.module.json')

    original = output / 'original.e'
    shutil.copy2(repo / 'eproj/e-console-exe-new-proj.e', original)
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    module = output / 'fixture.ec'
    if args.module:
        shutil.copy2(args.module, module)
    else:
        module_workspace = output / 'module-workspace'
        unpack(original, module_workspace)
        write(module_workspace / 'src/程序集1.txt', '''.版本 2
.程序集 删除测试模块
.子程序 _启动子程序, 整数型
返回 (0)
.子程序 删除测试取值, 整数型, 公开
返回 (9)
''')
        module_source = output / 'fixture.e'
        run(decoder, 'pack', module_workspace, module_source)
        compile_project(args.launcher, args.ide, module_source, module, 'ecom')
    seed = output / 'seed'
    unpack(original, seed)
    source = '.版本 2\n.程序集 程序集1\n.子程序 _启动子程序, 整数型\n返回 (0)\n'
    write(seed / 'src/程序集1.txt', source)
    # 支持库元数据通过 Win32 加载；两个版本分别执行删除和语义回包。
    run(decoder, 'update', seed, '--add-elib', 'spec')
    binary = output / 'resource.bin'
    binary.write_bytes(bytes(range(256)))
    replacement = output / 'replacement.bin'
    replacement.write_bytes(b'replaced resource')
    results = []
    for arch in args.arch:
        tool = repo / f'bin/{arch}/Release/e-packager.exe'
        root = output / arch
        root.mkdir()
        workspace = root / 'workspace'
        shutil.copytree(seed, workspace)
        run(tool, 'update', workspace, '--add-ecom', module,
            '--add-image', f'删除图片={binary}', '--add-image', f'保留图片={binary}',
            '--add-audio', f'删除音频={binary}', '--add-audio', f'保留音频={binary}')
        baseline = root / 'baseline.e'
        run(tool, 'pack', workspace, baseline)
        decoded = root / 'decoded'
        unpack(baseline, decoded)
        assert len(resources(decoded, 'image')) == len(resources(decoded, 'audio')) == 2
        assert any(d['kind'] == 'ecom' for d in metadata(decoded)['dependencies'])
        assert any(Path(d.get('fileName', '')).stem.lower() == 'spec' for d in metadata(decoded)['dependencies'])
        images = {r['logicalName']: r for r in resources(decoded, 'image')}
        sounds = {r['logicalName']: r for r in resources(decoded, 'audio')}

        # 一次请求中后续参数出错不能让前面的删除/新增部分落盘。
        before = tree(decoded)
        for option in ('--remove-image', '--remove-audio', '--remove-ecom', '--remove-elib'):
            run(tool, 'update', decoded, '--remove-image', '删除图片', option, 'missing', error='_not_found:')
            assert tree(decoded) == before, f'Partial write: {option}'
        run(tool, 'update', decoded, '--remove-image', '删除图片', '--add-audio', root / 'missing.bin', error='resource_file_not_found')
        assert tree(decoded) == before
        run(tool, 'update', decoded, '--remove-image', error='e-packager update')
        run(tool, 'update', decoded, '--remove-image', '--remove-audio', '删除音频', error='e-packager update')
        assert tree(decoded) == before

        # 精确路径消除同名模块歧义；不存在的源依赖文件也应可以删除。
        ambiguous = root / 'ambiguous'
        shutil.copytree(decoded, ambiguous)
        meta = metadata(ambiguous)
        dependency = next(d for d in meta['dependencies'] if d['kind'] == 'ecom')
        other = dict(dependency, path='$different.ec', resolvedPath=str(root / 'missing.ec'))
        meta['dependencies'].append(other)
        write(ambiguous / 'project/.module.json', json.dumps(meta, ensure_ascii=False, indent=2))
        ambiguous_before = tree(ambiguous)
        run(tool, 'update', ambiguous, '--remove-ecom', dependency['name'], error='ambiguous_dependency:')
        assert tree(ambiguous) == ambiguous_before
        run(tool, 'update', ambiguous, '--remove-ecom', root / 'missing.ec')
        assert len([d for d in metadata(ambiguous)['dependencies'] if d['kind'] == 'ecom']) == 1

        # 同名替换明确先删后增，新增的文件不能被后续清理误删。
        replace = root / 'replace'
        shutil.copytree(decoded, replace)
        run(tool, 'update', replace, '--add-image', f'删除图片={replacement}', '--remove-image', '#删除图片')
        item = next(r for r in resources(replace, 'image') if r['logicalName'] == '删除图片')
        assert (replace / item['relativePath']).read_bytes() == replacement.read_bytes()
        run(tool, 'pack', replace, root / 'replaced.e')
        unpack(root / 'replaced.e', root / 'replaced-decoded')
        item = next(r for r in resources(root / 'replaced-decoded', 'image') if r['logicalName'] == '删除图片')
        assert (root / 'replaced-decoded' / item['relativePath']).read_bytes() == replacement.read_bytes()

        # 共享文件仍被另一个索引条目使用时不能删除。
        shared = root / 'shared'
        shutil.copytree(decoded, shared)
        index = read_json(shared / 'image/list.json')
        index['items'][1]['relativePath'] = index['items'][0]['relativePath']
        shared_file = shared / index['items'][0]['relativePath']
        write(shared / 'image/list.json', json.dumps(index, ensure_ascii=False, indent=2))
        run(tool, 'update', shared, '--remove-image', index['items'][0]['logicalName'])
        assert shared_file.read_bytes() == binary.read_bytes()
        run(tool, 'pack', shared, root / 'shared.e')

        # 资源索引不能借助 ../ 指向工作区外并删除外部文件。
        unsafe = root / 'unsafe'
        shutil.copytree(decoded, unsafe)
        external = root / 'external.bin'
        external.write_bytes(binary.read_bytes())
        index = read_json(unsafe / 'image/list.json')
        index['items'][0]['relativePath'] = '../external.bin'
        write(unsafe / 'image/list.json', json.dumps(index, ensure_ascii=False, indent=2))
        unsafe_before = tree(unsafe)
        run(tool, 'update', unsafe, '--remove-image', index['items'][0]['logicalName'], error='unsafe_resource_remove_path:')
        assert tree(unsafe) == unsafe_before and external.read_bytes() == binary.read_bytes()

        # 保留旧快照且源码仍引用被删项，语义检查必须报错，可编辑回包须保留待修文本且不能恢复被删项。
        for kind, expression, option, target in (
                ('image', '#删除图片', '--remove-image', '删除图片'),
                ('ecom', args.module_expression, '--remove-ecom', 'fixture.ec')):
            referenced = root / f'referenced-{kind}'
            shutil.copytree(decoded, referenced)
            return_type = '字节集' if kind == 'image' else '整数型'
            write(referenced / 'src/引用页.txt', f'.版本 2\n.程序集 引用页\n.子程序 引用取值, {return_type}\n返回 ({expression})\n')
            run(tool, 'pack', referenced, root / f'referenced-{kind}.e')
            native = root / f'referenced-{kind}-native'
            unpack(root / f'referenced-{kind}.e', native)
            run(tool, 'update', native, option, target)
            # x64 无法导出原生支持库命令表，先由 Win32 刷新派生元数据再做严格语义诊断。
            run(decoder, 'update', native)
            run(decoder, 'validate', native, '--level', 'semantic', error='_not_found')
            run(tool, 'pack', native, root / f'invalid-{kind}.e')
            invalid = root / f'invalid-{kind}'
            unpack(root / f'invalid-{kind}.e', invalid)
            if kind == 'image':
                assert all(r['logicalName'] != '删除图片' for r in resources(invalid, 'image'))
            else:
                assert not any(d['kind'] == 'ecom' for d in metadata(invalid)['dependencies'])

        # 删除工程树中的同一 key，包括根节点和分组节点。
        meta = read_json(decoded / 'project/_meta.json')
        meta.setdefault('rootChildKeys', []).append(images['删除图片']['key'])
        meta.setdefault('folders', []).append(dict(key=900, parentKey=0, expand=True, name='删除测试',
                                                  childKeys=[images['删除图片']['key'], sounds['删除音频']['key']]))
        write(decoded / 'project/_meta.json', json.dumps(meta, ensure_ascii=False, indent=2))
        meta = metadata(decoded)
        elib = next(d for d in meta['dependencies'] if Path(d.get('fileName', '')).stem.lower() == 'spec')
        ecom = next(d for d in meta['dependencies'] if d['kind'] == 'ecom')
        elib_selector = elib['name'] if arch == 'Win32' else elib['guid']
        ecom_selector = ecom['name'] if arch == 'Win32' else ecom['resolvedPath']
        text = run(tool, 'update', decoded, '--remove-image', '#删除图片', '--remove-image', images['删除图片']['key'],
                   '--remove-audio', sounds['删除音频']['relativePath'], '--remove-ecom', ecom_selector,
                   '--remove-elib', elib_selector)
        assert 'resources_removed=2' in text and 'dependencies_removed=2' in text
        for kind, item in (('image', images['删除图片']), ('audio', sounds['删除音频'])):
            assert not (decoded / item['relativePath']).exists()
            assert len(resources(decoded, kind)) == 1
            assert item['key'] not in json.dumps(read_json(decoded / 'project/_meta.json'), ensure_ascii=False)
        assert not (decoded / 'project/.native_source.bin').exists()
        assert not (decoded / 'ecom').exists() or not list((decoded / 'ecom').iterdir())
        assert not any(p.stem.lower() == 'spec' for p in (decoded / 'elib').glob('*.txt'))
        # 连续刷新不会使旧快照重新有效或恢复已删项。
        run(tool, 'update', decoded)
        run(tool, 'update', decoded)
        packed = root / 'removed.e'
        run(tool, 'pack', decoded, packed)
        final = root / 'final'
        unpack(packed, final)
        assert [r['logicalName'] for r in resources(final, 'image')] == ['保留图片']
        assert [r['logicalName'] for r in resources(final, 'audio')] == ['保留音频']
        for kind in ('image', 'audio'):
            assert (final / resources(final, kind)[0]['relativePath']).read_bytes() == binary.read_bytes()
        dependencies = metadata(final)['dependencies']
        assert not any(d['kind'] == 'ecom' or Path(d.get('fileName', '')).stem.lower() == 'spec' for d in dependencies)
        compile_project(args.launcher, args.ide, packed, root / 'removed.exe', 'win_console_exe')
        # 最后一个资源也应可以删除，空索引可正常回包。
        run(tool, 'update', final, '--remove-image', '保留图片', '--remove-audio', '保留音频')
        run(tool, 'pack', final, root / 'empty.e')
        unpack(root / 'empty.e', root / 'empty')
        assert resources(root / 'empty', 'image') == resources(root / 'empty', 'audio') == []
        results.append(dict(architecture=arch, passed=True, headless_compiled=True))
        write(output / 'results.json', json.dumps(results, ensure_ascii=False, indent=2))
        print(f'PASS {arch}: all removal scenarios and native compile', flush=True)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    write(output / 'results.json', json.dumps(results, ensure_ascii=False, indent=2))
    print(f'Results: {output}', flush=True)


if __name__ == '__main__':
    main()
