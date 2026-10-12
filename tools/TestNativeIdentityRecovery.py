"""验证原生方法归属恢复，以及未知类型和事件处理器的拒绝边界。"""
import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, text):
    path.write_bytes(text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8-sig'))


class Reader:
    """独立读取程序段中的页面索引和方法归属，用于交叉核对导出结果。"""
    def __init__(self, data):
        self.data, self.position = data, 0

    def take(self, size):
        assert 0 <= size <= len(self.data) - self.position
        result = self.data[self.position:self.position + size]
        self.position += size
        return result

    def integer(self):
        return struct.unpack('<i', self.take(4))[0]

    def blob(self):
        return self.take(self.integer())

    def headers(self):
        size = self.integer()
        assert size >= 0 and size % 8 == 0
        ids = [self.integer() for _ in range(size // 8)]
        self.take(size // 2)
        return ids


def native_sections(path):
    data = path.read_bytes()
    assert data[:8] == b'CNWTEPRG'
    offset, sections = 8, {}
    while offset + 100 <= len(data):
        key, size = struct.unpack_from('<I', data, offset + 8)[0], struct.unpack_from('<i', data, offset + 56)[0]
        assert 0 <= size <= len(data) - offset - 100
        sections[key] = data[offset + 100:offset + 100 + size]
        offset += 100 + size
    return sections


def native_methods(path):
    r = Reader(native_sections(path)[0x03007319])
    r.take(8)
    for _ in range(3):
        r.blob()
    for _ in range(struct.unpack('<h', r.take(2))[0]):
        r.blob()
    flags = r.integer()
    startup = r.integer()
    if flags & 1:
        r.take(16)
    r.blob()
    r.blob()
    pages = {}
    for page_id in r.headers():
        r.take(8)
        r.blob()
        r.blob()
        ids = r.blob()
        pages[page_id] = list(struct.unpack('<' + 'i' * (len(ids) // 4), ids))
        r.integer()
        r.blob()
    methods = {}
    for method_id in r.headers():
        owner = r.integer()
        r.take(8)
        r.blob()
        r.blob()
        for _ in range(2):
            r.integer()
            r.blob()
        for _ in range(5):
            r.blob()
        methods[method_id] = dict(owner=owner, body_bytes=len(r.blob()))
    return pages, methods, startup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roundtrip', type=Path, required=True, help='TestRemainingRepackFailures 的 fresh-unpack 输出目录')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    rows = [row for row in read_json(args.roundtrip / 'results.json') if row['arch'] == 'Win32']
    evidence = dict(ownership=[], system_info=[], negative_cases=[])
    type_fixtures, event_fixture = {}, None
    for row in rows:
        workspace = args.roundtrip / f"{row['id']:04}/Win32/workspace"
        meta = read_json(workspace / 'project/_meta.json')
        expected_system = bytearray(native_sections(workspace / 'project/.native_source.bin')[0x02007319])
        original_file_type = struct.unpack_from('<i', expected_system, 16)[0]
        struct.pack_into('<i', expected_system, 16, 1)
        for arch in ('Win32', 'x64'):
            actual_system = native_sections(args.roundtrip / f"{row['id']:04}/{arch}/edited.e")[0x02007319]
            assert actual_system == expected_system, (row['id'], arch, 'editable system information differs')
            evidence['system_info'].append(dict(id=row['id'], arch=arch, original_file_type=original_file_type,
                                                 editable_file_type=1, compile_type=struct.unpack_from('<i', actual_system, 24)[0]))
        if meta['sourceFileKind'] == 'ec':
            pages, methods, startup = native_methods(workspace / 'project/.native_source.bin')
            snapshots = read_json(workspace / 'project/.native_source_map.json')
            exported = {method['id']: page['classId'] for page in snapshots for method in page['methods']}
            listed = {method: page for page, ids in pages.items() for method in ids}
            # 已有索引优先；仅无索引的方法按函数自身的 owner 恢复。
            expected = {method: listed.get(method, info['owner']) for method, info in methods.items()}
            assert exported == expected, (row['id'], 'native method ownership differs')
            startup_names = []
            for source, snapshot in zip(meta['sourceFiles'], snapshots):
                names = re.findall(r'(?m)^\.子程序\s+([^,\n]+)', (workspace / source['relativePath']).read_text(encoding='utf-8-sig'))
                assert len(names) == len(snapshot['methods'])
                startup_names.extend(name for name, method in zip(names, snapshot['methods']) if method['id'] == startup)
            assert startup_names == ['_启动子程序'], (row['id'], startup, startup_names)
            recovered = [method for method in methods if method not in listed]
            evidence['ownership'].append(dict(id=row['id'], methods=len(methods), recovered=len(recovered),
                                               startup_id=startup, startup_name=startup_names[0],
                                               recovered_body_bytes=sum(methods[m]['body_bytes'] for m in recovered)))
            if event_fixture is None:
                for form in meta['formFiles']:
                    path = workspace / form['relativePath']
                    if '处理器="' in path.read_text(encoding='utf-8-sig'):
                        event_fixture = workspace, form['relativePath']
                        break
        else:
            for source in meta['sourceFiles']:
                content = (workspace / source['relativePath']).read_text(encoding='utf-8-sig')
                for match in re.finditer(r'(?m)^\.(程序集变量|局部变量|参数|子程序)\s+[^,\n]+,\s*(0x[0-9A-Fa-f]+)\b', content):
                    type_fixtures.setdefault(match[1], (workspace, source['relativePath'], match.span(2)))
    assert type_fixtures and event_fixture and evidence['ownership'], 'required fixtures not found'

    def rejected(exe, workspace, name, expected_error):
        destination = args.output / (name + '.e')
        result = subprocess.run([str(exe), 'pack', str(workspace), str(destination)], capture_output=True, timeout=180)
        output = (result.stdout + result.stderr).decode('utf-8-sig', errors='replace')
        evidence['negative_cases'].append(dict(name=name, exit=result.returncode, diagnostic=output,
                                                output_exists=destination.exists()))
        write(args.output / 'evidence.json', json.dumps(evidence, ensure_ascii=False, indent=2))
        assert result.returncode != 0 and expected_error in output and not destination.exists(), output

    for arch in ('Win32', 'x64'):
        exe = repo / f'bin/{arch}/Release/e-packager.exe'
        for kind, (source_workspace, relative, span) in type_fixtures.items():
            workspace = args.output / f'{arch}-{kind}'
            shutil.copytree(source_workspace, workspace)
            page = workspace / relative
            original = page.read_text(encoding='utf-8-sig')
            for name, invalid in [('unknown-name', '明确不存在的类型'), ('unbound-id', '0x7FFF0001')]:
                write(page, original[:span[0]] + invalid + original[span[1]:])
                rejected(exe, workspace, f'{arch}-{kind}-{name}', 'type_id_resolution_failed')
            write(page, original)
            # 原生类型只可用于相应的原声明；不能成为接受任意十六进制类型的通道。
            position = original.index('\n', original.index('.程序集 '))
            new_declaration = '\n.程序集变量 新增未绑定类型变量, ' + original[span[0]:span[1]]
            write(page, original[:position] + new_declaration + original[position:])
            rejected(exe, workspace, f'{arch}-{kind}-new-declaration', 'type_id_resolution_failed')
        source_workspace, relative = event_fixture
        workspace = args.output / f'{arch}-missing-handler'
        shutil.copytree(source_workspace, workspace)
        page = workspace / relative
        write(page, re.sub(r'处理器="[^"]+"', '处理器="明确不存在的处理器"', page.read_text(encoding='utf-8-sig'), count=1))
        rejected(exe, workspace, f'{arch}-missing-handler', 'handler_not_found_or_ambiguous')
        print(arch, 'PASS', flush=True)
    evidence['passed'] = True
    write(args.output / 'evidence.json', json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
