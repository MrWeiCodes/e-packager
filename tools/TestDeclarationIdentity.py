"""验证语义回包的声明身份、页面重排、类型修改及真正的方法体重建。"""
import argparse
import json
from pathlib import Path
import subprocess


def write(path, text):
    path.write_bytes(text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    decoder = repo / 'bin/Win32/Release/e-packager.exe'
    results = []

    def run(exe, *arguments, expected=0):
        result = subprocess.run([str(exe), *map(str, arguments)], capture_output=True, timeout=120)
        output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        results.append(dict(command=[str(exe), *map(str, arguments)], exit=result.returncode, output=output))
        write(args.output / 'results.json', json.dumps(results, ensure_ascii=False, indent=2))
        assert result.returncode == expected, output

    for arch in ['Win32', 'x64']:
        exe = repo / f'bin/{arch}/Release/e-packager.exe'
        root = args.output / arch
        root.mkdir()
        workspace = root / 'seed'
        run(decoder, 'unpack', repo / 'eproj/e-console-exe-new-proj.e', workspace, '--main-only')
        run(decoder, 'update', workspace, '--add-elib', 'krnln')
        write(workspace / 'src/程序集1.txt', '.版本 2\n.程序集 程序集1\n.子程序 _启动子程序, 整数型\n返回 (7)\n')
        write(workspace / 'src/甲.txt', '.版本 2\n.程序集 甲, , , 第一页\n.程序集变量 数值, 整数型\n.子程序 获取, 整数型, 公开\n.参数 参数, 整数型\n.局部变量 临时, 整数型\n临时 ＝ 参数\n返回 (临时)\n')
        write(workspace / 'src/乙.txt', '.版本 2\n.程序集 乙\n.子程序 乙方法, 整数型\n返回 (19)\n')
        initial = root / 'initial.e'
        run(exe, 'pack', workspace, initial)
        edited = root / 'edited'
        run(decoder, 'unpack', initial, edited, '--main-only')
        source_map = json.loads((edited / 'project/.native_source_map.json').read_text(encoding='utf-8-sig'))
        meta_path = edited / 'project/_meta.json'
        meta = json.loads(meta_path.read_text(encoding='utf-8-sig'))
        identities = {entry['logicalName']: item['classId'] for entry, item in zip(meta['sourceFiles'], source_map)}
        meta['sourceFiles'].reverse()
        write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
        page = edited / 'src/程序集1.txt'
        write(page, page.read_text(encoding='utf-8-sig').replace('返回 (7)', '返回 (29)') + "\n' declaration-identity-marker\n")
        run(exe, 'pack', edited, root / 'changed.e')
        decoded = root / 'decoded'
        run(decoder, 'unpack', root / 'changed.e', decoded, '--main-only')
        actual = (decoded / 'src/程序集1.txt').read_text(encoding='utf-8-sig')
        assert '返回 (29)' in actual and '返回 (7)' not in actual and 'declaration-identity-marker' in actual
        new_meta = json.loads((decoded / 'project/_meta.json').read_text(encoding='utf-8-sig'))
        new_map = json.loads((decoded / 'project/.native_source_map.json').read_text(encoding='utf-8-sig'))
        assert identities == {entry['logicalName']: item['classId'] for entry, item in zip(new_meta['sourceFiles'], new_map)}
        target = decoded / 'src/甲.txt'
        original = target.read_text(encoding='utf-8-sig')
        for anchor in ['.程序集变量 数值, 整数型', '.子程序 获取, 整数型', '.参数 参数, 整数型', '.局部变量 临时, 整数型']:
            assert anchor in original
            write(target, original.replace(anchor, anchor.replace('整数型', '不存在的新类型')))
            run(exe, 'pack', decoded, root / 'must-not-exist.e', expected=1)
            assert not (root / 'must-not-exist.e').exists()
        write(target, original)
        run(exe, 'pack', decoded, root / 'second.e')
        dll_page = decoded / 'src/.DLL声明.txt'
        write(dll_page, '.版本 2\n.DLL命令 , 整数型, "kernel32.dll", "GetTickCount"\n')
        run(exe, 'validate', decoded, '--level', 'semantic', expected=1)
        run(exe, 'validate', decoded, '--level', 'editable')
        run(exe, 'pack', decoded, root / 'unnamed-dll.e')
        unnamed = root / 'unnamed'
        run(decoder, 'unpack', root / 'unnamed-dll.e', unnamed, '--main-only')
        assert '.DLL命令 , 整数型' in (unnamed / 'src/.DLL声明.txt').read_text(encoding='utf-8-sig')
        module_path = decoded / 'project/.module.json'
        module = json.loads(module_path.read_text(encoding='utf-8-sig'))
        module['dependencies'].append(dict(kind='ecom', name='identity-test-missing-new-module', path=str(root / 'missing-new-module.ec')))
        write(module_path, json.dumps(module, ensure_ascii=False, indent=2))
        run(exe, 'pack', decoded, root / 'missing-new-module.e', expected=1)
        assert not (root / 'missing-new-module.e').exists()
        print(arch, 'PASS', flush=True)


if __name__ == '__main__':
    main()
