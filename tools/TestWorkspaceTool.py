"""验证解包工具覆盖、自复制和省略工作区目录的增删命令。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from TestEComUpdateRoundTrip import read_json, write


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    root = (args.output or repo / 'temp' / f'workspace-tool-{uuid.uuid4().hex}').resolve()
    root.mkdir(parents=True, exist_ok=False)
    original = root / 'original.e'
    module = root / 'fixture.ec'
    shutil.copy2(repo / 'eproj/e-console-exe-new-proj.e', original)
    shutil.copy2(args.module, module)
    binary = root / 'resource.bin'
    binary.write_bytes(bytes(range(256)))
    decoder = repo / 'bin/Win32/Release/e-packager.exe'
    sequence = 0

    def run(tool, *arguments, cwd=root, error=None):
        nonlocal sequence
        sequence += 1
        process = subprocess.run([str(tool), *map(str, arguments)], cwd=cwd,
                                 capture_output=True, timeout=120)
        raw = process.stdout + process.stderr
        log = root / f'{sequence:03d}.log'
        log.write_bytes(raw)
        text = raw.decode('utf-8', errors='replace')
        if error is None:
            assert process.returncode == 0, f'{log}: {text}'
        else:
            assert process.returncode != 0 and error in text, f'{log}: {text}'

    def names(workspace, kind):
        return [r['logicalName'] for r in read_json(workspace / kind / 'list.json')['items']]

    results = []
    for arch in ('Win32', 'x64'):
        tool = repo / f'bin/{arch}/Release/e-packager.exe'
        workspace = root / arch
        run(tool, 'unpack', original, workspace, '--main-only')
        copied = workspace / 'tool/e-packager.exe'
        expected_hash = digest(tool)
        assert digest(copied) == expected_hash
        copied.write_bytes(b'obsolete executable')
        run(tool, 'unpack', original, workspace, '--main-only')
        assert digest(copied) == expected_hash, 'Existing executable was not replaced'
        # 同一个可执行文件已经在运行时，再次解包到自身工作区仍应成功。
        run(copied, 'unpack', original, workspace, '--main-only')
        assert digest(copied) == expected_hash
        # 改名的调用程序仍需输出文档约定的 tool/e-packager.exe。
        renamed = root / f'renamed-{arch}.exe'
        shutil.copy2(tool, renamed)
        run(renamed, 'unpack', original, workspace, '--main-only')
        assert digest(copied) == expected_hash
        assert not (workspace / 'tool' / renamed.name).exists()

        write(workspace / 'src/程序集1.txt', '.版本 2\n.程序集 程序集1\n.子程序 _启动子程序, 整数型\n返回 (0)\n')
        # 外部工具从工作区根目录调用；资源相对路径仍基于当前工作目录。
        run(tool, '--add-image', '图片=../resource.bin', cwd=workspace)
        run(tool, 'update', '--add-audio', '音频=../resource.bin', cwd=workspace)
        assert names(workspace, 'image') == ['图片']
        assert names(workspace, 'audio') == ['音频']
        # 当前目录为 tool/ 或外部目录时，均能定位副本所属工作区。
        run(copied, 'update', '--remove-image', '图片', cwd=copied.parent)
        run(copied, '--remove-audio', '音频')
        run(copied, '--add-ecom', module)
        run(copied, 'update', '--remove-ecom', 'fixture.ec')
        assert not any(d['kind'] == 'ecom' for d in read_json(workspace / 'project/.module.json')['dependencies'])
        # 支持库新增仍由 Win32 加载，省略目录入口与显式入口一致。
        run(decoder, '--add-elib', 'spec', cwd=workspace)
        run(copied, '--remove-elib', 'spec')
        assert not any(d.get('fileName') == 'spec' for d in read_json(workspace / 'project/.module.json')['dependencies'])
        run(copied, 'update')
        assert not (workspace / 'pack').exists(), 'Update unexpectedly created default pack directory'
        run(copied, '--add-image', f'保留={binary}', '--add-audio', f'删除={binary}')
        run(copied, '--remove-audio', '删除')
        packed = root / f'{arch}.e'
        run(copied, 'pack', workspace, packed)
        decoded = root / f'{arch}-decoded'
        run(decoder, 'unpack', packed, decoded, '--main-only')
        assert names(decoded, 'image') == ['保留'] and names(decoded, 'audio') == []
        item = read_json(decoded / 'image/list.json')['items'][0]
        assert (decoded / item['relativePath']).read_bytes() == binary.read_bytes()
        # 当前工作区优先于工具所属工作区；显式路径则优先于两者。
        run(copied, '--add-image', f'当前={binary}', cwd=decoded)
        assert names(workspace, 'image') == ['保留']
        assert '当前' in names(decoded, 'image')
        run(copied, 'update', decoded, '--remove-image', '当前', cwd=workspace)
        assert names(decoded, 'image') == ['保留']
        run(copied, '--add-image', cwd=workspace, error='e-packager update')
        run(copied, '--remove-unknown', 'missing', error='e-packager update')
        run(tool, 'update', error='workspace_project_root_not_found')
        run(tool, '--add-image', binary, error='workspace_project_root_not_found')
        # 公共定位逻辑仍支持原有无参回包，并保持无修改工程字节一致。
        clean = root / f'{arch}-clean'
        run(tool, 'unpack', original, clean, '--main-only')
        run(clean / 'tool/e-packager.exe', cwd=clean / 'tool')
        assert (clean / 'pack/original.e').read_bytes() == original.read_bytes()
        results.append(dict(architecture=arch, passed=True, copy_sha256=expected_hash))
        write(root / 'results.json', json.dumps(results, indent=2))
        print(f'PASS {arch}: overwrite, self-copy, implicit workspace, direct options and roundtrip', flush=True)
    print(f'Results: {root}', flush=True)


if __name__ == '__main__':
    main()
