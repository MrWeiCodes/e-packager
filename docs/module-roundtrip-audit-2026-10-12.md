# 模块目录 .e 拆包与注释语义回包审计（2026-10-12）

## 结论

递归测试 `C:\Users\aiqin\OneDrive\Code\模块` 中全部 **482 个 `.e` 文件**，Win32、x64 各运行一次，共 964 个测试项。`draw_menu.e` 为零字节文件，两架构均跳过；其余 481 个文件全部尝试。原文件内容复核全部一致。此次仅新增测试脚本和问题记录，未修改产品实现。

| 项目 | Release Win32 | Release x64 |
| --- | ---: | ---: |
| 非空输入 | 481 | 481 |
| 拆包退出成功 | 478 | 481 |
| 无修改回包逐字节、MD5、SHA256 一致 | 478 | 481 |
| 追加注释后回包成功（90 秒主轮） | 306 | 0 |
| 回包后再次拆包成功 | 306 | 0 |
| 严格内容检查通过 | 293 | 0 |
| 回包成功但内容有差异 | 13 | 0 |
| 回包明确报错 | 171 | 481 |
| 回包超过 90 秒 | 1 | 0 |
| 拆包进程崩溃 | 3 | 0 |

Win32 的 13 个内容差异中，**10 个文件的 20 个无方法程序集／类页丢失新增注释**，另外 **3 个仅观察到格式规范化**。未发现本轮成功回包产物的窗口 XML、资源索引或二进制资源变化。未执行 IDE 编译，不能将这些结果解释为 IDE 可编译或程序行为正确。

唯一超时样本 `LWPS测试支持库.e` 串行放宽至 180 秒后，**147.047 秒完成回包**，再次拆包无内容差异，因此是慢样本，未证实死锁。将这次补测单独计入时，Win32 回包成功 307 个、严格检查通过 294 个；上表保留主轮口径。

## 环境与证据

- Git：`4f7dabad4b018536fd796d82448ffb6d1d05c5bf`。
- 构建器：`C:\Program Files\Microsoft Visual Studio\18\Professional\MSBuild\Current\Bin\MSBuild.exe`。
- Release Win32、Release x64 均构建成功。x64 目录包含配套 `e-packager-x86.exe`，并非遗漏辅助程序。
- Win32 EXE SHA256：`a990889cdfea8c399fe26803f11bdfc1ae99bb4fb80ad37e5f5c6dfe04c60bab`。
- x64 EXE SHA256：`3109434b96789b464fd2f3fe04945afa3595d1bd6b4bf9b4f5a41a091bd3a0d7`。
- 主轮：2026-10-12 12:08:11—12:18:15（本地 UTC+8），4 个脚本工作线程，每命令 90 秒上限。
- 再拆包上下文补验完成：12:20:28，使用同一组 EXE，对全部 306 个成功回包样本补验。
- 主证据：`D:\test\module-roundtrip-20261012-full`。
- 串行崩溃／慢样本复测：`D:\test\module-roundtrip-20261012-crash-repro`。
- Win32 拆包 → x64 回包交叉抽查：`D:\test\module-roundtrip-20261012-cross`。
- 构建日志：`D:\test\module-audit-build-Win32.log`、`D:\test\module-audit-build-x64.log`。

仓库内保留 [全部 964 项结果 CSV](module-roundtrip-audit-2026-10-12-results.csv) 和 [机器可读汇总及复测证据](module-roundtrip-audit-2026-10-12-evidence.json)。CSV 含原文件哈希、各阶段状态／退出码／耗时、修改页数量、问题分类及本地证据路径。完整源码副本、产物、日志、命令、差异位于临时目录，不提交第三方工程源码。

`cases/<四位 ID>/<架构>/result.json` 是逐例结果；`unpack.log`、`baseline_pack.log`、`semantic_pack.log`、`reunpack-context.log` 是对应日志。内容差异见 `decoded-context/content.diff.txt`。初次再拆包结果保留在 `initial_decode` 和 `initial-results.json`；最终统计读 `results.json`、`summary.json`，不要使用未重写的原始 `progress.jsonl` 计算补验后的结果。

## 测试方法与边界

脚本：[TestModuleRoundtripAudit.py](../tools/TestModuleRoundtripAudit.py)，使用说明：[TestModuleRoundtripAudit.md](../tools/TestModuleRoundtripAudit.md)。

1. 整棵目录复制到 `D:\test` 下，保留相对 `.ec` 和工程旁支持库。只将副本路径交给被测工具；不执行样本程序。
2. 每架构独立拆包，再无修改回包，比较原文件字节、MD5 和 SHA256。
3. 遍历主工程 `src/`，每个含程序集／类声明的文本页底部追加一行 `' module-roundtrip-audit-<ID>-<页号>`，使用 UTF-8 BOM、CRLF；不修改依赖源码或删除快照。
4. 回包后检查非空、字节发生变化，再将产物放到输入副本旁的唯一临时文件，以 `unpack --main-only` 再拆包。
5. 检查所有新增注释、源码、窗口、资源索引与二进制。文本仅忽略空行和行首尾空白，资源索引按 JSON 结构比较，二进制按 SHA256 比较。
6. 单条命令超时终止本次进程树；记录 Windows 异常退出码。末尾再次校验全部受测原文件。

页尾修改会使工程摘要失效，但未修改方法仍可能复用方法快照，**不是所有方法强制语义重编译**。本轮覆盖用户指定的“每个类／程序集底部加注释”编辑路径。空页注释是否保存也直接检查，不用增加空白行代替。

首轮有 6 个样本因将回包产物移出原工程目录，重新拆包时加载了另一个同名支持库或找不到本地支持库，产生类型／命令名称假差异。ID 为 **254、255、338、340、342、352**。在输入副本旁重拆后全部消失；脚本已修正，306 个成功回包样本全部补验，以上 6 个不计为产品内容损坏。

## 问题 1：组件工程拆包稳定崩溃

优先级：高。以下 3 个 Win32 样本默认拆包均以 **`0xC000041D`** 退出，日志只有启动信息，未形成可用工作区。

| ID | 相对路径 |
| --- | --- |
| 0339 | 易支持库/易写易库孤岛版/测试/调用测试/组件调用测试.e |
| 0341 | 易支持库/易写易库孤岛版/调用测试/组件调用测试.e |
| 0353 | 易支持库/易写易库模块封装版ekmk_孤岛源码/测试/调用测试/组件调用测试.e |

串行复测每个样本的默认拆包、`--main-only` 拆包，**6 次均以同一码崩溃**，排除了仅因多个测试并行或依赖导出引起的解释。Windows Application 事件 1000 同时记录 **`0xC0000005`** 和 `0xC000041D`，故障模块为 `unknown`。没有调用栈，不能据此断言是哪个支持库或控件函数造成的。

证据：`D:\test\module-roundtrip-20261012-crash-repro\results.json`、`windows-application-errors.json` 以及各 ID 的 `default.command.json`、`main-only.command.json`。崩溃前 trace 已走到 `BuildProgramPages end count=1`，后续可从页面生成之后及控件属性处理链路定位，但这只是调查入口。

复现（输出目录请使用新名字）：

```powershell
& 'D:\git\e-packager\bin\Win32\Release\e-packager.exe' unpack `
  'D:\test\module-roundtrip-20261012-full\inputs\易支持库\易写易库孤岛版\测试\调用测试\组件调用测试.e' `
  'D:\test\component-crash-repro-new' --main-only
```

## 问题 2：x64 独立拆包丢失支持库名称，语义回包全数失败

优先级：高，属于本机 x86 支持库环境下的架构能力限制。本轮 481 个非空文件的 x64 拆包和原样回包退出成功、字节一致；但源码普遍含 `_Lib0Cmd...` 等占位符，修改后 **481 个全部回包报错**。

例：ID 0001 `0.YHan.Helper.e`，`semantic_pack.log` 报 `function_not_found: _Lib0Cmd197`。拆包提示已找到 `krnln.fnr` 但加载失败，Windows 错误 193，且 x64 跳过 `elib` 公开信息导出。目录里存在 x86 辅助 EXE 并没有使这条命令解码链路自动跨架构工作。

交叉抽查使用 Win32 工作区交给 x64 回包，再用 Win32 重拆：

| ID | x64 回包 Win32 工作区结果 |
| --- | --- |
| 0001、0002 | 成功；新增注释及所有比较内容一致 |
| 0003 | 与 Win32 相同的预检赋值类型错误 |
| 0036 | 与 Win32 相同的 `krnln::销毁` 方法解析失败 |
| 0042 | 成功，但同样丢失 5 个空程序集注释 |

因此至少上述成功对照不能解释为“x64 写包器完全不能用”，应重点调查原生 `.e` 解码时的支持库名称解析及 x86 代理覆盖范围。本轮没有对全部 481 个 Win32 工作区执行 x64 交叉回包。

## 问题 3：空程序集／类页尾注释被静默丢弃

优先级：中。10 个样本的 20 个源码页均出现：`pack`、再次 `unpack` 退出 0，但新增的页尾注释消失。所有受影响页的子程序数为 0。

| ID | 文件 | 丢注释页数 |
| --- | --- | ---: |
| 0042 | Ex_DirectUI4.1/0.YHan.Eternal.ExFC.e | 5 |
| 0090 | Ex_DirectUI4.1/Ex_DirectUI 4.1 [Demo]/0.YHan.Eternal.ExFC.e | 5 |
| 0099 | ExDui2.0有能力的完善吧.e | 1 |
| 0168 | NotifyIcon.e | 2 |
| 0174 | opencvimage2.e | 1 |
| 0193 | rar.e | 1 |
| 0356 | 易支持库/爱琴常用数据结构/爱琴的基础数据结构.e | 2 |
| 0416 | 爱琴炫彩的API应用模块.e | 1 |
| 0417 | 爱琴炫彩的API应用模块13.e | 1 |
| 0460 | 进程监控.e | 1 |

ID 0042 的典型差异：

```diff
 .版本 2
 .程序集 程序集3
-' module-roundtrip-audit-0042-0014
```

`ParseProgramPage`（`src/e2txt_restore.cpp`）的程序集级循环处理程序集变量和子程序；普通行仅向后推进，方法体以外的独立注释没有被保存。这与实测一致。后续修复需要明确这类注释的原生表示或给出可操作诊断，不能在成功状态下静默吞掉；本轮未改实现。

## 问题 4：仅注释修改触发多类语义回包失败

Win32 171 个明确报错按首个错误分类，以下数量互斥：

| 首个错误 | 文件数 | 代表样本／细节 |
| --- | ---: | --- |
| `source_preflight_failed` | 65 | 0003 `adb.e`，赋值类型不匹配；0026 `count_未完成.e`，符号未声明 |
| `dependency_module_not_found` | 65 | 0044 缺 `$0.YHan.Helper.ec`；0382 缺历史绝对路径 `AsmEngine.ec` |
| `semantic_method_rebuild_failed` | 31 | 0036 `krnln::销毁`；0188 `winMain.销毁`；0468 `object_target_type_not_found: 线程池` |
| `type_id_resolution_failed` | 6 | 0092 `匿名类_5`；0216 `矩形L` |
| 窗口／控件／事件错误（`window_form`） | 3 | 0238 控件类型元数据不可用；0366 事件参数类型不匹配 |
| `source_syntax_error` | 1 | 0233 `ui_text.e`，`Class_UI_ToolBtn.txt:53`，`if_true_end_invalid` |

这些是**失败类别，不是 171 个均已确认的工具缺陷**。缺库、旧路径、支持库版本不一致和原工程未完成代码均可能导致失败，应先核对输入及依赖再归因。

例如 `adb.e` 的 `ADBSocket.txt:261/271/281` 将 `哈希表类zy.取值` 赋给字节集，而当前导出的 `HashTable/header/header.txt` 将返回类型声明为整数型；需进一步核对原工程使用的模块版本，不能直接认定预检误判。ID 0225 的 `DateTime._销毁` 原本就含独立文本 `啊哇`，被预检拒绝不构成已证实回归。

预检错误覆盖 `symbol_not_found`、`assignment_type_mismatch`、`addition_type_mismatch`、`return_type_mismatch`、`member_not_found`、`statement_not_callable`、`declaration_name_missing`、`arithmetic_type_mismatch`、`comparison_type_mismatch`。另有 16 个 Win32 样本拆包文本含未解析支持库占位符，均未跳过测试；需要结合逐例依赖记录判断缺库原因。

部分原始诊断有编码混用，例如 ID 0233 的 `page_type` 字段无法作为纯 UTF-8 解码。保留原始日志字节供后续修正，不将终端乱码当作源码内容变化。

## 问题 5：大型 WPS 样本慢，90 秒超时但长时复测通过

ID 0321：`易支持库/wps支持库exek/LWPS测试支持库.e`。

主轮拆包和原样回包成功；追加注释后 90.188 秒被测试脚本终止。相同工作区串行复测允许 180 秒，147.047 秒回包成功；8.234 秒再次拆包成功，源码、注释、窗口和资源无差异。trace 显示两个 WPS 页各有 4353 个方法，属于大型样本，需后续性能剖析，不能据超时断言死循环。

证据：`D:\test\module-roundtrip-20261012-crash-repro\0321\verification.json`。主轮的 timeout 记录保留，不改写为 90 秒内通过。

## 观察项：3 个文件仅格式规范化

| ID | 文件 | 差异 |
| --- | --- | --- |
| 0180 | Path_modernize_win7_test.e | ASCII `=`、`==`、`!=`、`+` 规范化为 `＝`、`≠`、`＋` |
| 0386 | 易语言EP助手开发/模块源码/SyserKernel Engine.e | `置入代码 ({ ... })` 大括号内边缘空格被移除 |
| 0388 | 易语言EP助手开发/模块源码/取寄存器值.e | 同类字节集字面量空格规范化 |

严格文本比较将它们保留为 `content_changed`，人工检查未观察到语句或字节集数值变化，不计作已证实语义损坏。

## 再次运行

```powershell
py -3 -X utf8 tools/TestModuleRoundtripAudit.py `
  --source 'C:\Users\aiqin\OneDrive\Code\模块' `
  --output 'D:\test\module-roundtrip-next' `
  --workers 4 --timeout 180
```

只复测崩溃样本：加 `--ids 339,341,353 --architectures Win32 --workers 1`。编号以本次完整排序清单为准，输入目录增删文件后应先核对 `manifest.json`。所有测试使用新临时目录，避免旧产物干扰判定。
