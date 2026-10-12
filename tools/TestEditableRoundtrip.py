"""Regression for editable packing, validation levels and native source preservation."""
import argparse
import base64
import struct
import json
import os
from pathlib import Path
import subprocess


def write(path, text):
    path.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--eide", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    args.output = args.output.resolve()
    repo = Path(__file__).resolve().parent.parent
    evidence = []
    env = dict(os.environ, TEMP=str(args.output), TMP=str(args.output))

    def run(exe, *parts, expected=0):
        command = [str(exe), *map(str, parts)]
        result = subprocess.run(command, capture_output=True, timeout=180, env=env)
        stdout = result.stdout.decode("utf-8-sig", "replace")
        stderr = result.stderr.decode("utf-8-sig", "replace")
        evidence.append(dict(command=command, exit=result.returncode, stdout=stdout, stderr=stderr))
        (args.output / "results.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        assert result.returncode == expected, (command, stdout, stderr)
        return json.loads(stdout) if "--diagnostics" in parts else stdout

    valid = ".版本 2\n.程序集 程序集1\n.子程序 _启动子程序, 整数型\n返回 (0)\n"
    invalid = ".版本 2\n.程序集 程序集1\n.子程序 _启动子程序, 整数型\n.局部变量 文本, 文本型\n文本 ＝ 123\n不存在的方法 (\n.如果真 (不存在的变量)\n    啊哇\n.如果真结束\n返回 (0)\n"
    comments = ".版本 2\n.程序集 程序集1\n.子程序 _启动子程序, 整数型\n' .如果真 (真)\n' 返回 (12)\n' .如果真结束\n返回 (0)\n"
    masked = ".版本 2\n.程序集 程序集1\n.子程序 _启动子程序, 整数型\n' .如果真 (真)\n    返回 (12)\n' .如果真结束\n返回 (0)\n"
    qualified = valid + ".子程序 未调用的成员命令\nkrnln::销毁 ()\n"
    for arch in ("Win32", "x64"):
        exe = repo / f"bin/{arch}/Release/e-packager.exe"
        workspace = args.output / arch
        run(exe, "unpack", repo / "eproj/e-console-exe-new-proj.e", workspace, "--main-only")
        run(repo / "bin/Win32/Release/e-packager.exe", "update", workspace, "--add-elib", "krnln")
        page = workspace / "src/程序集1.txt"
        for name, source in (("valid", valid), ("invalid", invalid), ("comments", comments), ("masked", masked), ("qualified", qualified)):
            write(page, source)
            report = run(exe, "validate", workspace, "--level", "editable", "--diagnostics", "json")
            assert report["ok"] and report["rebuildVerified"] and not report["ideOpenVerified"], report
            run(exe, "validate", workspace, "--diagnostics", "json", expected=1 if name == "invalid" else 0)
            packed = args.output / f"{arch}-{name}.e"
            run(exe, "pack", workspace, packed)
            decoded = args.output / f"{arch}-{name}-decoded"
            run(repo / "bin/Win32/Release/e-packager.exe", "unpack", packed, decoded, "--main-only")
            actual = (decoded / "src/程序集1.txt").read_text(encoding="utf-8-sig")
            # The decoder omits a redundant library qualifier when no user symbol collides.
            expected_source = source.replace("krnln::", "") if name == "qualified" else source
            assert [line.rstrip() for line in expected_source.splitlines() if line.strip()] == [line.rstrip() for line in actual.splitlines() if line.strip()], actual
            if name == "qualified":
                mapping = json.loads((decoded / "project/.native_source_map.json").read_text(encoding="utf-8-sig"))
                method = next(m for c in mapping for m in c["methods"] if m["name"] == "未调用的成员命令")
                data = base64.b64decode(method["expressionData"])
                assert data[0] == 0x6a and struct.unpack_from("<ihh", data, 1) == (216, 0, 0), data.hex()
            write(decoded / "src/程序集1.txt", actual + "\n' second semantic rebuild\n")
            run(exe, "pack", decoded, args.output / f"{arch}-{name}-second.e")
            if args.eide and name in ("valid", "invalid", "qualified"):
                report = run(exe, "validate", workspace, "--level", "compile", "--diagnostics", "json", "--eide", args.eide, "--compile-static", expected=1 if name == "invalid" else 0)
                assert report["status"] == ("failed" if name == "invalid" else "passed"), report
                checked = args.output / f"{arch}-{name}-compile-checked.e"
                run(exe, "pack", workspace, checked, "--compile-check", "--eide", args.eide,
                    "--compile-static", expected=1 if name == "invalid" else 0)
                assert checked.exists() == (name != "invalid"), checked
                if name == "valid":
                    run(exe, "compile-check", checked, "--eide", args.eide, "--compile-static")
        write(page, valid.replace("返回 (0)", ".如果真 (真)\n    返回 (0)"))
        run(exe, "pack", workspace, args.output / f"{arch}-broken-structure.e", expected=1)
        run(exe, "validate", workspace, "--level", "editable", "--diagnostics", "json", expected=1)
        write(page, valid)
        report = run(exe, "validate", workspace, "--level", "compile", "--diagnostics", "json", "--eide", args.output / "missing-eide.exe", expected=2)
        assert report["status"] == "unavailable", report
        print(f"PASS {arch}", flush=True)

if __name__ == "__main__":
    main()
