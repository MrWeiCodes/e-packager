"""验证安装目录选择、强制目录及未解码命令诊断；所有工程在 temp 副本中处理。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--e-dir', required=True)
    parser.add_argument('--fixture', required=True, help='Win32 SupportCommandDiagnosticsTest.cpp 生成的 FNE')
    parser.add_argument('--directory-probe', required=True, help='ELanguageDirectoryTest.cpp 生成的目录探测程序')
    parser.add_argument('--architecture', choices=('Win32', 'x64', 'both'), default='both')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    root = repo / 'temp' / ('environment-test-' + uuid.uuid4().hex[:10])
    root.mkdir(parents=True)
    real_installation = Path(args.e_dir).resolve()
    fixture = Path(args.fixture).resolve()
    probe = Path(args.directory_probe).resolve()
    environment = dict(os.environ)
    environment.pop('E_PACKAGER_EIDE', None)
    environment.pop('E_PACKAGER_TEST_COMMAND_TABLE', None)

    def install(path):
        for child in ('lib', 'static_lib', 'ecom'):
            (path / child).mkdir(parents=True)
        return path

    def run(tool, cwd, label, arguments, ok=True, env=None):
        result = subprocess.run([str(tool), *map(str, arguments)], cwd=cwd,
                                env=environment if env is None else env,
                                capture_output=True, timeout=60)
        (cwd / (label + '.stdout.log')).write_bytes(result.stdout)
        (cwd / (label + '.stderr.log')).write_bytes(result.stderr)
        if (cwd / 'e-packager.log').is_file():
            shutil.copy2(cwd / 'e-packager.log', cwd / (label + '.runtime.log'))
        assert (result.returncode == 0) == ok, (label, result.returncode, result.stderr.decode('utf-8', 'replace'))
        return result

    # 原生目录探测器注入注册表候选，仅替换读取接口，不改系统注册表。
    parent_install = install(root / 'parent-install')
    parent_tool = parent_install / 'tools' / 'probe.exe'
    parent_tool.parent.mkdir()
    shutil.copy2(probe, parent_tool)
    bad_registry = root / 'bad-registry'
    (bad_registry / 'lib').mkdir(parents=True)
    good_registry = install(root / 'registered-install')
    for name, registry, expected in (
        ('no-registry', '-', parent_install),
        ('invalid-registry', bad_registry, parent_install),
        ('valid-registry', good_registry, good_registry),
    ):
        cwd = root / name
        cwd.mkdir()
        run(parent_tool, cwd, name, [registry, expected])
        log = (cwd / 'e-packager.log').read_text(encoding='utf-8-sig')
        assert 'e_language_directory_selected:' in log
        if name != 'valid-registry':
            assert 'source=executable_parent' in log
        if name == 'invalid-registry':
            assert 'source=registry' in log and 'static_lib,ecom' in log
    own_tool = parent_install / 'probe.exe'
    shutil.copy2(probe, own_tool)
    run(own_tool, root, 'own-directory', ['-', parent_install])
    isolated = root / 'isolated'
    isolated.mkdir()
    isolated_tool = isolated / 'probe.exe'
    shutil.copy2(probe, isolated_tool)
    run(isolated_tool, isolated, 'no-installation', ['-', '-'])
    assert 'e_language_directory_not_found:' in (isolated / 'e-packager.log').read_text(encoding='utf-8-sig')
    bad_env = dict(environment, E_PACKAGER_EIDE=str(bad_registry / 'e.exe'))
    run(parent_tool, root, 'invalid-environment', ['-', parent_install], env=bad_env)
    dotted_installation = install(root / 'e5.6')
    versioned_exe = dotted_installation / 'e5.95.exe'
    versioned_exe.write_bytes(b'executable lookup fixture')
    run(parent_tool, root, 'dotted-environment-directory', ['-', dotted_installation, versioned_exe],
        env=dict(environment, E_PACKAGER_EIDE=str(dotted_installation)))
    custom_exe = dotted_installation / 'custom-ide.EXE'
    custom_exe.write_bytes(b'executable lookup fixture')
    run(parent_tool, root, 'environment-executable', ['-', dotted_installation, custom_exe],
        env=dict(environment, E_PACKAGER_EIDE=str(custom_exe)))
    print('PASS automatic discovery: registry, invalid/missing registry, executable directory, parent, missing installation', flush=True)

    forced = install(root / '指定安装')
    shutil.copy2(real_installation / 'lib' / 'krnln.fne', forced / 'lib' / 'krnln.fne')
    absent = install(root / 'missing-library-install')
    broken = install(root / 'broken-library-install')
    (broken / 'lib' / 'krnln.fne').write_bytes(b'not a PE file\r\n')
    metadata = install(root / 'metadata-install')
    shutil.copy2(fixture, metadata / 'lib' / 'krnln.fne')
    report = {}
    architectures = ('Win32', 'x64') if args.architecture == 'both' else (args.architecture,)
    for architecture in architectures:
        tool = repo / 'bin' / architecture / 'Release' / 'e-packager.exe'
        cwd = root / architecture
        cwd.mkdir()
        shutil.copy2(repo / 'eproj' / 'e-console-exe-new-proj.e', cwd / 'input.e')
        run(tool, cwd, 'prepare', ['unpack', cwd / 'input.e', cwd / 'workspace', '--main-only', '--e-dir', forced])
        page = next(path for path in (cwd / 'workspace' / 'src').rglob('*.txt')
                    if '_启动子程序' in path.read_text(encoding='utf-8-sig'))
        source = '.版本 2\n.程序集 程序集1\n.子程序 _启动子程序, 整数型\n.局部变量 文本, 文本型\n文本 ＝ 到文本 (123)\n返回 (取文本长度 (文本))\n'
        page.write_bytes(b'\xef\xbb\xbf' + source.replace('\n', '\r\n').encode('utf-8'))
        run(tool, cwd, 'create-source', ['pack', cwd / 'workspace', cwd / 'commands.e', '--e-dir=' + str(forced)])
        run(tool, cwd, 'forced-unpack', ['--e-dir', forced, 'unpack', cwd / 'commands.e', cwd / 'good', '--main-only'])
        run(tool, cwd, 'forced-pack', ['pack', cwd / 'good', cwd / 'roundtrip.e', '--e-dir', forced])
        assert (cwd / 'roundtrip.e').read_bytes() == (cwd / 'commands.e').read_bytes()
        result = run(tool, cwd, 'json', ['validate', cwd / 'good', '--diagnostics', 'json', '--e-dir', forced])
        assert json.loads(result.stdout)['ok']
        for label, values in (
            ('invalid-directory', ['--e-dir', bad_registry]),
            ('missing-value', ['--e-dir']),
            ('empty-value', ['--e-dir=']),
            ('duplicate-option', ['--e-dir', forced, '--e-dir', forced]),
        ):
            run(tool, cwd, label, ['unpack', cwd / 'commands.e', cwd / label, *values], ok=False)
            assert not (cwd / label).exists(), label
        log = (cwd / 'forced-unpack.runtime.log').read_text(encoding='utf-8-sig')
        assert str(forced / 'lib' / 'krnln.fne') in log
        assert 'support_command_unresolved:' not in log
        if architecture == 'x64':
            assert 'support_library_x86_worker_loaded:' in log
            assert ' x86]' in log and 'source=--e-dir' in log

        # 工程旁运行库无命令表时，仍须先使用安装目录中的开发库。
        for suffix in ('fne', 'fne.dll'):
            scenario = cwd / ('runtime-shadow-' + suffix)
            scenario.mkdir()
            installation = install(scenario / 'installation')
            development = installation / 'lib' / ('krnln.' + suffix)
            shutil.copy2(real_installation / 'lib' / 'krnln.fne', development)
            shutil.copy2(fixture, scenario / 'krnln.FNR')
            shutil.copy2(cwd / 'commands.e', scenario / 'commands.e')
            env = dict(environment, E_PACKAGER_EIDE=str(installation), E_PACKAGER_TEST_COMMAND_TABLE='empty')
            run(tool, scenario, 'unpack', ['unpack', scenario / 'commands.e', scenario / 'workspace'], env=env)
            run(tool, scenario, 'pack', ['pack', scenario / 'workspace', scenario / 'roundtrip.e'], env=env)
            assert (scenario / 'commands.e').read_bytes() == (scenario / 'roundtrip.e').read_bytes()
            log = (scenario / 'unpack.runtime.log').read_text(encoding='utf-8-sig')
            log += (scenario / 'pack.runtime.log').read_text(encoding='utf-8-sig')
            assert 'support_command_unresolved:' not in log, (architecture, suffix, 'local FNR shadowed development library')
            assert 'support_library_loaded: path=' + str(development) in log
            assert 'support_library_found: context=public_info, path=' + str(development) in log
            loads = [line for line in log.splitlines() if 'support_library_load_begin:' in line]
            assert loads and all('.fnr' not in line.lower() for line in loads), loads
            assert not any('_Lib0Cmd' in p.read_text(encoding='utf-8-sig')
                           for p in (scenario / 'workspace' / 'src').rglob('*.txt'))

        cases = [('missing', absent, None, 'library_not_found'),
                 ('broken', broken, None, 'metadata_load_failed'),
                 ('invalid-info', metadata, 'invalid-info', 'metadata_load_failed'),
                 ('unreadable', metadata, 'unreadable', 'command_table_unreadable'),
                 ('short', metadata, 'short', 'command_id_out_of_range'),
                 ('empty', metadata, 'empty', 'command_table_empty'),
                 ('nameless', metadata, 'nameless', 'command_name_empty_or_unreadable')]
        for label, installation, mode, reason in cases:
            scenario = cwd / label
            scenario.mkdir()
            env = dict(environment)
            if mode:
                env['E_PACKAGER_TEST_COMMAND_TABLE'] = mode
            run(tool, scenario, label, ['unpack', cwd / 'commands.e', scenario / 'workspace',
                                       '--main-only', '--e-dir', installation], env=env)
            log = (scenario / 'e-packager.log').read_text(encoding='utf-8-sig')
            records = [line for line in log.splitlines() if 'support_command_unresolved:' in line]
            assert records, (architecture, label)
            assert all('reason=' + reason in line for line in records), records
            assert all('placeholder=_Lib0Cmd' in line and 'function=' in line and 'expected_guid=' in line for line in records)
            assert any('_Lib0Cmd' in p.read_text(encoding='utf-8-sig') for p in (scenario / 'workspace' / 'src').rglob('*.txt'))
            assert str(real_installation / 'lib' / 'krnln.fne') not in log, 'forced search escaped to registry'
            if mode in ('unreadable', 'short', 'empty', 'nameless'):
                assert 'loaded_version=5.7.0' in log and 'declared_commands=' in log
            data = (scenario / 'e-packager.log').read_bytes()
            assert data.count(b'\xef\xbb\xbf') == 1 and b'\n' not in data.replace(b'\r\n', b'')
        report[architecture] = 'explicit override, validation, worker propagation, FNE/FNE.DLL over local FNR, exact roundtrip and seven unresolved-command reasons passed'
        print('PASS ' + architecture + ': ' + report[architecture], flush=True)
    (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(root)


if __name__ == '__main__':
    main()
