"""审计缺陷回归：原样字节、声明注释、表达式类型与方法词法作用域。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def write(path, text):
    path.write_bytes(b'\xef\xbb\xbf' + text.replace('\r\n', '\n').replace('\n', '\r\n').encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parent.parent
    decoder = repo / 'bin/Win32/Release/e-packager.exe'
    evidence = []

    def run(exe, *arguments, error=None):
        result = subprocess.run([str(exe), *map(str, arguments)], capture_output=True, timeout=120)
        output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        evidence.append(dict(command=[str(exe), *map(str, arguments)], exit=result.returncode, output=output))
        (args.output / 'results.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        if error is None:
            assert result.returncode == 0, output
        else:
            assert result.returncode != 0 and error in output, output

    template = args.output / 'template.e'
    shutil.copy2(repo / 'eproj/e-console-exe-new-proj.e', template)
    workspace = args.output / 'workspace'
    run(decoder, 'unpack', template, workspace, '--main-only')
    run(decoder, 'pack', workspace, args.output / 'baseline.e')
    assert hashlib.sha256(template.read_bytes()).digest() == hashlib.sha256((args.output / 'baseline.e').read_bytes()).digest()
    # 导出当前核心库的声明，x64 可据此解析 x86 支持库的命令签名。
    run(decoder, 'update', workspace, '--add-elib', 'krnln')
    source = '''.版本 2
.程序集 程序集1
.子程序 _启动子程序, 整数型
.局部变量 判断值, 逻辑型
.局部变量 文本, 文本型
判断值 ＝ 到数值 ("1") ＝ 到数值 ("2")
判断值 ＝ 到数值 ("1") ＜ 到数值 ("2")
判断值 ＝ 到数值 ("1") ≤ 到数值 ("2")
判断值 ＝ 到数值 ("1") ＞ 到数值 ("2")
判断值 ＝ 到数值 ("1") ≥ 到数值 ("2")
判断值 ＝ 到数值 ("1") ≠ 到数值 ("2")
文本 ＝ "左" ＋ 到文本 (123)
返回 (0)
.子程序 另一方法
.局部变量 判断值, 文本型
判断值 ＝ "不同方法中的同名变量"
'''
    pages = {
        '空程序集': '.程序集 空程序集',
        '空类': '.程序集 空类, <对象>, 公开',
        '有备注': '.程序集 有备注, , , 已有备注',
        '有变量': '.程序集 有变量\n.程序集变量 数据, 整数型',
        '变量备注': '.程序集 变量备注\n.程序集变量 数据, 整数型, , , 原备注',
    }
    write(workspace / 'src/程序集1.txt', source)
    for name, header in pages.items():
        write(workspace / f'src/{name}.txt', '.版本 2\n' + header + "\n\n' 第一行审计注释\n' 第二行审计注释\n")
    for arch in ('Win32', 'x64'):
        exe = repo / f'bin/{arch}/Release/e-packager.exe'
        run(exe, 'validate', workspace)
        packed = args.output / f'{arch}.e'
        run(exe, 'pack', workspace, packed)
        decoded = args.output / f'{arch}-decoded'
        run(decoder, 'unpack', packed, decoded, '--main-only')
        for name in pages:
            actual = (decoded / f'src/{name}.txt').read_text(encoding='utf-8-sig')
            assert actual.count("' 第一行审计注释") == 1 and actual.count("' 第二行审计注释") == 1, actual
            assert '.子程序' not in actual, actual
            for declaration in pages[name].splitlines():
                assert declaration in actual.splitlines(), actual
        run(decoder, 'update', decoded, '--add-elib', 'krnln')
        # 原生备注重新拆包后必须能再次语义回包，不能仅保存一次。
        write(decoded / 'src/程序集1.txt', source + "\n' 再次触发语义重建\n")
        run(exe, 'pack', decoded, args.output / f'{arch}-second.e')
        again = args.output / f'{arch}-second-decoded'
        run(decoder, 'unpack', args.output / f'{arch}-second.e', again, '--main-only')
        for name in pages:
            assert (decoded / f'src/{name}.txt').read_bytes() == (again / f'src/{name}.txt').read_bytes(), name
        for invalid, code in (
            (source.replace('文本 ＝ "左" ＋ 到文本 (123)', '文本 ＝ 123'), 'assignment_type_mismatch'),
            (source.replace('判断值 ＝ "不同方法中的同名变量"', '文本 ＝ "前一方法的局部变量不可见"'), 'symbol_not_found'),
        ):
            write(workspace / 'src/程序集1.txt', invalid)
            run(exe, 'validate', workspace, error=code)
            run(exe, 'pack', workspace, args.output / f'{arch}-invalid.e', error=code)
        write(workspace / 'src/程序集1.txt', source)
        print(f'PASS {arch}', flush=True)

    window = args.output / 'window'
    run(decoder, 'unpack', repo / 'eproj/e-window-exe-new-proj.e', window, '--main-only')
    run(decoder, 'update', window, '--add-elib', 'krnln')
    for page in (window / 'src').glob('*.txt'):
        if not page.name.startswith('.'):
            page.unlink()
    window_code = '''.版本 2
.程序集 独立程序集
.子程序 测试
_启动窗口.销毁 ()
_启动窗口.krnln::销毁 ()
'''
    write(window / 'src/独立程序集.txt', window_code)
    for arch in ('Win32', 'x64'):
        exe = repo / f'bin/{arch}/Release/e-packager.exe'
        packed = args.output / f'window-{arch}.e'
        run(exe, 'pack', window, packed)
        decoded = args.output / f'window-{arch}-decoded'
        run(decoder, 'unpack', packed, decoded, '--main-only')
        actual = (decoded / 'src/独立程序集.txt').read_text(encoding='utf-8-sig')
        assert actual.count('_启动窗口.销毁 ()') == 2, actual
        # 库限定名必须验证所属库，不可直接剥掉前缀后接受任意库。
        write(window / 'src/独立程序集.txt', window_code.replace('krnln::', 'missing_library::'))
        run(exe, 'pack', window, args.output / f'window-invalid-{arch}.e', error='not_found')
        write(window / 'src/独立程序集.txt', window_code)
        print(f'PASS {arch} window methods', flush=True)


if __name__ == '__main__':
    main()
