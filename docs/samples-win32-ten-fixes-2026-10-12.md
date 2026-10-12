# samples 剩余 10 例 Win32 语义回包修复

> 本文引用的 JSON / CSV 为本地生成的测试证据，已归档到 `D:\test\e-packager-cleanup-20261012-203743\docs`，不随仓库提交；测试结论、问题分析和复现方法保留在本文。

## 范围和最终结论

本轮只复测上一轮 `samples` 审计中明确失败的 10 个输入，不重跑整个 339 文件语料。
编号沿用 `D:\test\samples-audit-20261012\manifest.json`。
原始目录 `C:\Users\aiqin\Downloads\samples\samples` 没有修改；操作对象均为 `D:\test` 内的副本。

| 验证项 | Win32 回包 | x64 回包 |
| --- | ---: | ---: |
| 重新拆包后原样回包，字节/MD5/SHA256 一致 | 10/10 | 10/10 |
| 每个类/程序集底部加注释后的语义回包 | 10/10 | 10/10 |
| 再拆包，源码/XML/资源内容一致 | 10/10 | 10/10 |
| 追加注释保留 | 10/10 | 10/10 |
| 页面、方法、变量、类型的原生身份保留 | 10/10 | 10/10 |
| 第二次回包 | 10/10 | 10/10 |
| 新增 `_Lib*` | 0 | 0 |
| 超时/崩溃 | 0 | 0 |
| 原本就没有 `_Lib*` 的严格通过项 | 2/10 | 2/10 |

**边界：两列均由 Win32 拆包、解码，再分别由 Win32/x64 写入。不能据此声称 x64 原生加载 x86 支持库的问题已解决。**
另外 8 例仍保留原有缺失支持库的占位符；没有把它们改成伪造的名称、类型或空实现。
本轮结果不能改写历史全量审计的失败记录，也不能视为整个语料已完成新的全量验证。

## 根因与通用修正

### 1. 窗口程序集的原始声明分类不一致

0025、0291、0293、0300、0301、0303、0306、0310 原来报 `type_id_resolution_failed`。
缺少支持库元数据时，拆包器会输出 `0xA000A`、`0x200A0` 等原生类型编号。
真正的失败原因不是必须接受任意十六进制类型，而是显式窗口绑定只应用到了当前声明，
没有应用到原始声明：两边的 `isFormClass` 不同，稳定页面 key 匹配被拒绝，随之丢失了原生类型身份。

现在用原始工程自己的窗口名及窗口绑定解析原始声明。类型名称没有改动的对应声明，继续使用原生类型 ID。
不放宽 `TypeResolver`，不引入缺省类型、类型归零或按样本名称判断。
新声明不能借用另一个声明的原生类型；修改成未知名字或无绑定的十六进制编号，仍会失败。

### 2. EC 页面方法索引不完整

0087 `易容大师.ec`、0274 `连接编译器.ec` 的函数记录仍有方法体和 `ownerClass`，
但部分页面的 `functionIds` 为空。之前只遍历页面列表，XML 却能看到全局函数表中的事件处理器，于是回包报缺失处理器。

解析程序段时统一补齐归属：先保留所有已列出的页面方法索引，再将尚未列出的函数加入其唯一存在的 `ownerClass` 页面。
已明确列在别的页面的方法不会被搬回旧 owner；重复页面 ID 不能用于推断归属。
这样命名缓存、源码、原生快照及窗口绑定都使用同一份页面索引。

独立 Python 二进制读取验证：

| 输入 | 原生方法总数 | 恢复到页面的遗漏方法 | 这些方法原有方法体字节数 |
| --- | ---: | ---: | ---: |
| 0087 | 95 | 59 | 30,532 |
| 0274 | 10 | 8 | 5,454 |

没有删除事件、制造处理器空壳或复用整个旧方法体来代替语义重建。

### 3. 匿名窗口及空声明行的身份

匿名窗口 XML 的 `名称` 原来直接取空的原始名字，而文件名和绑定使用匿名符号名。
现在统一经过同一个符号解析器，避免第一次回读时 XML 名称发生变化。

0025、0303 的空声明行也有原生 ID。它们虽没有可引用的名称，仍不能在仅追加注释时重新编号。
现在按相同空声明的出现顺序复用身份；类型、属性、数组或备注改变后，不借用旧空行的类型。

### 4. 可编辑源码与编译后模块的文件种类混用

只看回包返回码会漏掉这个问题：两例 EC 恢复的 `.e` 虽含编辑信息段，系统信息里的 `fileType` 仍为编译后模块的值 `3`。
真实 IDE 提示“本程序内不包含编辑信息，不能载入。”

通过 IDA MCP 检查本机 `e5.95.exe` 副本：

- `0x45C4A0` 的载入函数读取系统信息段的 60 字节结构。
- `0x45C920` 取结构偏移 `+16` 的整数；普通源码载入在 `0x45C94E` 要求其等于 `1`。
- 否则在 `0x45C965` 使用 `0x6619BC` 的上述错误文本。
- 同一函数另有模块导入分支，不能混淆文件种类与 `projectType` 编译目标。

语义序列化现在明确输出 `kEditableSourceFileType`，仍保留模块编译目标 `1000`、版本、保留字段和扩展数据。
原样回包走原生字节复用，不改变 `.ec` 的原始文件种类。
这是序列化的格式语义，不是修改 IDE 或按偏移给特定样本打补丁。

### 5. 原生启动入口被匿名命名遮盖

修正文件种类后，两例能打开，但编译提示找不到 `_启动子程序`。
程序头的 `flag2` 实际保存了启动方法 ID；旧命名流程先生成 EC 匿名名，使既有的入口恢复分支永远无法命中。
现在对没有原始名或调试名、且 ID 与程序头明确指定入口相同的方法恢复入口名。
没有按第一个方法、固定数字 ID 或签名猜测，也没有创建新的启动函数。

## 真实 IDE 与编译验证

使用 AutoLinker MCP，按测试进程 PID 选择实例，通过 `read_real_file` 读取真实 IDE 页面，不能用拆包镜像代替证据。
读取了启动程序集及被恢复的窗口事件程序集；IDE 会将事件方法显示为 `_匿名窗口_1_创建完毕` 等正常事件名，方法体和追加注释均存在。

0087、0274 的 Win32 和 x64 回包产物共 **4 份**，均成功打开并以明确的 `ecom` 目标重新编译。
检查了 `ok=true`、`artifact_verified=true` 和生成的 `.ec` 产物，不运行编译结果。
最初的 `auto` 目标探查及入口修正前的编译失败另留在 `D:\test`，不计入成功结果。

IDE 编译模块会自动发布副本到 IDE 的 `ecom` 目录。测试工具已改用唯一产物名，并仅删除本次新建且哈希与产物一致的发布副本。
本轮初始两次验证产生的通用 `artifact.ec` 副本也依据创建时间和 SHA256 确认为本次产物后清理；证据包含清理记录。

其余 8 例没有据此宣称可编译：0025 原有 `eAPI` 缺失，7 个 Grid++Report 工程缺失相关 `gregn45.npk`/`grdes45.npk` 元数据。
它们原有 `_Lib*` 及十六进制类型身份保留，没有新增 `_Lib0*`。

## 脚本与负例

- `TestRemainingRepackFailures.py`：新增原样回包指纹、声明 ID/类型身份和新增占位符检查。原始占位符与新增占位符分别记录。
- `TestNativeIdentityRecovery.py`：独立读取 EC 页面索引、函数归属和启动 ID；验证可编辑文件种类及其它系统信息字节；检查错误类型、新增无绑定声明和不存在的事件处理器。
- 两个架构共 20 个拒绝性用例通过（局部变量、程序集变量、参数及事件处理器），均未产生伪成功的 `.e` 文件。
- `TestDeclarationIdentity.py`、`TestUnexaminedLiteralRoundtrip.py`、`TestEditableRoundtrip.py` 继续验证既有声明编辑、连续语义回包及 editable/semantic/compile 级别边界。
- Release Win32、Release x64 均完成编译；源码保持 UTF-8 BOM / CRLF。

已有的两份 EC 解包目录漏掉了方法正文，需从原始副本重新拆包；不能为了修旧目录而自动补回用户可能主动删除的方法。

```powershell
py -3 -X utf8 tools/TestRemainingRepackFailures.py `
  --baseline D:\test\samples-audit-20261012 `
  --output D:\test\samples-ten-new `
  --ids 25 87 274 291 293 300 301 303 306 310 `
  --architectures Win32 x64 --workers 4 --timeout 600 --fresh-unpack

py -3 -X utf8 tools/TestNativeIdentityRecovery.py `
  --roundtrip D:\test\samples-ten-new --output D:\test\samples-ten-boundaries-new

py -3 -X utf8 tools/TestAutoLinkerSource.py `
  --source D:\test\samples-ten-new\0274\Win32\edited.e `
  --output D:\test\samples-ten-ide-new `
  --page src/匿名程序集_1.txt --page src/匿名程序集_3.txt `
  --compile --compile-target ecom
```

保留给外部调用的实际编译验证命令：

```powershell
.\bin\Win32\Release\e-packager.exe compile-check D:\test\edited.e `
  --eide C:\Users\aiqin\OneDrive\e5.6\e5.95.exe `
  --compile-target ecom --compile-timeout 120

.\bin\Win32\Release\e-packager.exe validate D:\test\workspace `
  --level compile --diagnostics json `
  --eide C:\Users\aiqin\OneDrive\e5.6\e5.95.exe --compile-target ecom
```

普通回包继续使用 editable 标准；上述命令用于单独判断能否编译。EXE 工程应选择对应编译目标。

## 证据

- 最终 20 例：`D:\test\samples-ten-complete-20261012`。
- 独立原生验证和 20 个负例：`D:\test\samples-ten-native-boundaries-20261012`。
- IDE 最终证据：`D:\test\samples-ten-ide-final-{87,274}` 及对应 `-x64` 目录。
- 本地归档汇总：`samples-win32-ten-fixes-2026-10-12-evidence.json`、`samples-win32-ten-fixes-2026-10-12-results.csv`。
- 原始全量记录仍为 `samples-audit-2026-10-12.md`，没有覆盖其结果。
