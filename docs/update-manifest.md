# 更新清单

标签发布 Action 在打包 Win32 ZIP 后生成 `update.json`，与 ZIP 一起上传到同一个 Release。
客户端读取 `https://github.com/aiqinxuancai/e-packager/releases/latest/download/update.json`，无需调用 GitHub API 或配置 Token。预发布版本不会成为 latest。

```json
{
  "schema_version": 1,
  "tag": "v1.2.3",
  "asset": {
    "name": "e-packager-v1.2.3-windows-win32.zip",
    "size": 123456,
    "sha256": "实际 ZIP 文件的 64 位十六进制 SHA-256"
  }
}
```

`tag` 保留原始标签（包括可选的 v/V 前缀），附件名必须为 `e-packager-{tag}-windows-win32.zip`。脚本根据实际 ZIP 计算大小和校验值，禁止空包或附件名不匹配。下载地址由客户端使用固定仓库、标签和附件名构造，不在清单中指定。

本地生成示例：

```powershell
./scripts/generate_update_manifest.ps1 -Tag v1.2.3 -AssetPath ./e-packager-v1.2.3-windows-win32.zip -OutputPath update.json
```

AutoLinker 仅在清单返回 HTTP 404 时兼容旧 Release：通过 `/releases/latest` 的最终重定向地址获取标签并构造 ZIP 地址。该兼容路径没有大小和 SHA-256 元数据，仍校验 ZIP 文件标识。其他 HTTP 错误或无效清单直接报错，不回退到 GitHub API。
