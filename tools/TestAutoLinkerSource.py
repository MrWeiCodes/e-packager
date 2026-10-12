"""Read real IDE pages and optional compiler diagnostics through AutoLinker MCP.
Only launches/closes owned IDE processes; never saves or edits project source.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid


def owned_dialogs(process_id):
    """只读本脚本启动的 IDE 弹窗，区分文件拒绝载入和 MCP 注册超时。"""
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    dialogs = []

    def window_text(window):
        text = ctypes.create_unicode_buffer(4096)
        user32.GetWindowTextW(ctypes.c_void_p(window), text, len(text))
        return text.value

    @callback_type
    def visit(window, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(window), ctypes.byref(owner))
        if owner.value != process_id:
            return True
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ctypes.c_void_p(window), name, len(name))
        if name.value != '#32770':
            return True
        children = []

        @callback_type
        def child_visit(child, _):
            value = window_text(child)
            if value:
                children.append(value)
            return True

        user32.EnumChildWindows(ctypes.c_void_p(window), child_visit, 0)
        dialogs.append(dict(title=window_text(window), text=children))
        return True

    user32.EnumWindows(visit, 0)
    return dialogs


class Client:
    def __init__(self, endpoint="http://127.0.0.1:19207/mcp"):
        self.endpoint, self.session, self.sequence = endpoint, None, 0
        self.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                     "clientInfo": {"name": "e-packager-ide-audit", "version": "1"}})

    def request(self, method, params, timeout=60):
        self.sequence += 1
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        payload = json.dumps(dict(jsonrpc="2.0", id=self.sequence, method=method, params=params)).encode("utf-8")
        with urllib.request.urlopen(urllib.request.Request(self.endpoint, payload, headers), timeout=timeout) as response:
            self.session = response.headers.get("Mcp-Session-Id", self.session)
            result = json.load(response)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]

    def call(self, name, arguments=None, timeout=60):
        result = self.request("tools/call", dict(name=name, arguments=arguments or {}), timeout)
        data = result.get("structuredContent")
        if data is None:
            data = json.loads(next(c["text"] for c in result["content"] if c["type"] == "text"))
        if result.get("isError") or data.get("ok") is False:
            if name != "compile_with_output_path":
                raise RuntimeError(data)
        return data


def inspect_source(eide, source, output, pages, compile_code=False, compile_target='auto'):
    output.mkdir(parents=True, exist_ok=False)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    env = dict(os.environ, TEMP=str(output), TMP=str(output))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen([str(eide), str(source)], env=env, startupinfo=startup)
    record = dict(source=str(source), sha256=before, process_id=process.pid, pages={})
    try:
        deadline, client, selected = time.monotonic() + 45, None, None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"IDE exited: {process.returncode}")
            try:
                if client is None:
                    client = Client()
                instances = client.call("list_instances")["instances"]
                selected = next((i for i in instances if i["process_id"] == process.pid and i.get("source_open")), None)
                if selected:
                    break
            except (OSError, RuntimeError):
                client = None
            time.sleep(0.25)
        if selected is None:
            raise TimeoutError("IDE did not open source and register with MCP")
        client.call("select_instance", {"instance_id": selected["instance_id"]})
        record["ide"] = client.call("get_current_eide_info")
        record["mirror"] = client.call("refresh_workspace_mirror", {"mode": "main_only"})
        for page in pages:
            chunks, offset = [], 0
            while True:
                part = client.call("read_real_file", {"file_path": page, "offset": offset, "limit": 20000})
                chunks.append(part)
                if not part.get("has_more"):
                    break
                offset = part["next_offset"]
            record["pages"][page] = chunks
        record["opened"] = True
        if compile_code:
            suffix = '.ec' if compile_target == 'ecom' else ('.dll' if compile_target == 'win_dll' else '.exe')
            artifact = output / ('e-packager-audit-' + uuid.uuid4().hex + suffix)
            # IDE 编译易模块可能自动复制到自身 ecom 目录。使用唯一名称，
            # 仅清理本次新增且与产物字节相同的副本，不能覆盖或删除既有模块。
            published = eide.parent / 'ecom' / artifact.name
            published_existed = published.exists()
            record["compile"] = client.call("compile_with_output_path", {
                "output_path": str(artifact), "target": compile_target,
                "static_compile": compile_target != 'ecom'}, timeout=650)
            if suffix == '.ec' and not published_existed and published.is_file() and artifact.is_file():
                if hashlib.sha256(published.read_bytes()).digest() == hashlib.sha256(artifact.read_bytes()).digest():
                    published.unlink()
                    record['removed_published_copy'] = str(published)
    except Exception as error:
        record["error"] = str(error)
        record["dialogs"] = owned_dialogs(process.pid)
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        record["original_unchanged"] = hashlib.sha256(source.read_bytes()).hexdigest() == before
        (output / "evidence.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eide", type=Path, default=Path("C:/Users/aiqin/OneDrive/e5.6/e5.95.exe"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page", action="append", default=[])
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--compile-target", choices=['auto', 'win_exe', 'win_console_exe', 'win_dll', 'ecom'], default='auto')
    args = parser.parse_args()
    result = inspect_source(args.eide.resolve(), args.source.resolve(), args.output.resolve(), args.page, args.compile, args.compile_target)
    print(json.dumps({k: result[k] for k in ("source", "opened", "error", "original_unchanged") if k in result}, ensure_ascii=False))
    return 0 if result.get("opened") and result["original_unchanged"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
