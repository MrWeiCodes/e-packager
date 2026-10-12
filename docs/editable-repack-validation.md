# 可编辑回包与分级验证

`pack` 默认以生成可继续在 IDE 中编辑的工程为目标。源码语义错误不等于工程文件损坏。有效表达式仍优先语义编码；不能解析的表达式或调用以易语言原生未检查语句保存，并输出 `source_preserved_unexamined` 诊断，不自动注释、改正或删除源码，不回退到旧执行快照。

## 对外命令

```powershell
e-packager pack D:\test\workspace D:\test\edited.e
e-packager validate D:\test\workspace --level editable --diagnostics json
e-packager validate D:\test\workspace --level semantic --diagnostics json
e-packager validate D:\test\workspace --level compile --diagnostics json --eide C:\Users\aiqin\OneDrive\e5.6\e5.95.exe --compile-static
```

| 级别 | 检查内容 | 是否调用 IDE |
| --- | --- | --- |
| `editable` | 目录、声明和流程结构检查，并实际构造回包字节；表达式错误作为警告 | 否 |
| `semantic`（默认） | 原有语法、符号和可确定类型检查 | 否 |
| `compile` | 可编辑回包后交由 AutoLinker / IDE 实际编译，不由静态检查器代替 IDE 裁决 | 是 |

`editable` 返回的 `ideOpenVerified=false` 是有意的：生成字节成功不能单独证明 IDE 已实际打开。真实 IDE 打开和页面读取由下面的 MCP 测试完成。

`validate` 退出码：`0` 表示所选级别通过，`1` 表示验证失败，`2` 表示 IDE 缺失、编译超时、结果缺失等导致无法完成编译验证。JSON 包含 `level`、`status`（`passed/failed/unavailable`）、`ok`、`diagnostics`、`runtimeWarnings`；实际编译额外保留 `ideResult`。IDE 未核实的文件或行号保持 `null`，不从光标行号猜测。

编译级别还支持现有 `--compile-target`、`--compile-static`、`--compile-timeout` 选项；这些选项只能用于 `--level compile`。现有 `compile-check <file.e|file.ec>`、`pack --compile-check` 保留，继续共用 AutoLinker 编译实现。不会执行编译生成的程序。测试时可将 `TEMP`、`TMP` 指向 `D:\test` 的独立子目录。

## 放宽与保留的边界

- 括号未闭合、未知调用、未知变量、类型不匹配、无法编码的流程条件可以保留给 IDE 编辑。回包成功不能证明这些代码正确，也不能证明编码器已完整支持该语法。
- 流程块仍必须可以安全构造；缺失结束标记、交叉闭合、错误声明、缺失资源、无法解析的类型身份与窗口结构仍报错，不猜测或制造对象。
- 同缩进的连续注释不会仅因包含 `.如果真` 等文字而被解释为流程块。真正带缩进子体的屏蔽流程仍保持其结构，防止其中语句意外激活。
- 显式库限定的唯一成员命令通过真实支持库命令表解析，包含无显式对象接收者的原生调用；同名歧义不猜测，错误库前缀仍无法解析。
- 普通程序集是函数作用域，不作为可实例化类型遮蔽核心支持库类型；用户类和窗口类仍注册自己的类型。
- 零改动回包保留原生字节一致性。类与程序集底部加注释的测试用于强制语义重建，不能用未修改回包替代。

## 脚本

```powershell
py -3 -X utf8 tools/TestEditableRoundtrip.py --output D:\test\editable-regression-new --eide C:\Users\aiqin\OneDrive\e5.6\e5.95.exe
py -3 -X utf8 tools/TestAutoLinkerSource.py --source D:\test\sample-copy.e --output D:\test\sample-ide-new --page src/程序集1.txt --compile
py -3 -X utf8 tools/TestModuleRoundtripAudit.py --output D:\test\editable-full-new --architectures Win32 x64 --workers 4 --timeout 180
```

所有输出目录须是新的目录。MCP 脚本通过固定网关 `http://127.0.0.1:19207/mcp` 初始化会话，按自己启动的 PID 选择实例，刷新镜像后使用 `read_real_file` 读取 IDE 真实页面。普通 `read_file` 是拆包镜像，不作为独立的 IDE 源码证据。可以重复传 `--page`，脚本自动读完所有分页；`--compile` 保存原始编译诊断及产物验证结果，未指定时只读页面。

脚本不保存或修改工程，结束时仅关闭自己启动的 IDE，并核对受测文件 SHA256。不要同时让另一个 IDE 打开同一路径，以免 IDE 将启动请求转发给已有进程。工程应预先复制到 `D:\test`，并保留相对依赖和工程旁支持库。编译失败本身不会使“打开和读取”脚本失败：以 `evidence.json` 的 `compile.ok` / `artifact_verified` 判断可编译结果，不能把脚本退出 0 当作编译成功。

完整审计保留严格源码差异，不通过粗暴删除空白或替换运算符掩盖变化。格式规范化、原始错误、工具误判、依赖缺失和新增错误须在审计报告中分别记录。
