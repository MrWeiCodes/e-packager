# 源码与支持库解析性能优化

本轮基线已经包含窗口属性命名管道和宿主复用优化，继续检查源码还原、声明、支持库元数据、资源写盘及依赖导出。未提交 Git。

## 实现

- `SymbolResolver` 按子程序 ID 建索引，程序集收集子程序、内联类型归属分析、公开头生成及原生快照组装复用此索引，替代反复扫描整个子程序表。
- 按类型 ID/地址别名建立名称索引；内置类型与用户类型的重名检查使用名称集合，替代每次遍历完整符号表。这也减少 XML 中类型名称生成的开销。
- 在进入子程序时建立参数和局部变量名称集合；全局/成员名称、控件所属窗口及成员所属窗口各建索引，保留同名变量与控件的限定规则。
- 索引在匿名名称和同名类型消歧完成后建立，局限于当前解析器。重复 ID 保留原遍历的首个匹配，类型仍保持原优先级；未增加跨工程或跨运行的支持库缓存。
- 支持库仅供符号解析时，读取结构化元数据，跳过随后被丢弃的完整命令、类型和常量说明文本。公开接口文件导出仍生成完整说明。加载校验、候选优先级和错误日志继续执行。
- 新增独立的 `OperationStageTimer.h`，日志记录 `operation_stage`、`operation`、`stage`、`elapsed_us` 和 `source`。按来源区分主工程与依赖模块，不同计时范围存在包含关系，不能跨层累加。

## 用户工程：三轮交替实测

原文件 `C:\Users\aiqin\Downloads\1 - 管理器 - 95-1.e` 仅用于核对哈希，测试使用 `temp/user-manager-test-6a3a46fe/` 中的副本。
采用普通 `unpack`，包含依赖处理、启动和退出，不加 `--main-only`。同一架构内依次交替运行基线和新版。

| Release | 优化前第 1 / 2 / 3 轮 | 优化后第 1 / 2 / 3 轮 | 平均变化 |
| --- | --- | --- | --- |
| Win32 | 15.409 / 14.755 / 14.384 秒 | 8.737 / 8.565 / 9.402 秒 | 14.849 → 8.901 秒，减少 40.1% |
| x64 | 14.835 / 13.656 / 12.683 秒 | 10.087 / 7.557 / 7.300 秒 | 13.725 → 8.314 秒，减少 39.4% |

优化前加入阶段计时的一次剖析中，主工程源码还原为 3.277 秒；新版 Win32 三轮分别为 0.445 / 0.423 / 0.505 秒，平均 0.458 秒。声明生成从该次剖析的 0.126 秒降至新版平均 0.055 秒。前者为一次剖析、后者为三轮平均，不把阶段比值视作所有工程的固定提升比例。

三轮各自比较主工程及依赖的相对文件路径和 SHA-256：Win32 每轮 298 个产物、x64 每轮 287 个产物完全一致，均包含 175 个主工程源码/XML 文件。只排除随版本更新的 `tool/e-packager.exe` 和 `tool/e-packager-x86.exe`。x64 原本不能原生导出部分 x86 支持库的说明文件，因此两个架构的总数不同；同架构优化前后数量与内容一致。

每轮只启动一个属性辅助进程，请求无失败。不同架构耗时来自不同批次，不作为 x86 与 x64 的速度排名。

报告及逐轮日志：

- `temp/window-benchmark-96b48b92be/report.json`：Win32。
- `temp/window-benchmark-8154a02486/report.json`：x64。
- `temp/property-ipc-perf/core-profile/e-packager.log`：修改索引前的阶段剖析。

## 无窗口模块及写盘波动

使用安装目录中精易模块的副本 `temp/core-perf-20261017/jingyi.ec`，2,289,409 字节；通过 `--main-only` 单测无窗口工程。两个架构各三轮，每轮 92 个产物全部一致。

| Release | 优化前平均 / 中位数 | 优化后平均 / 中位数 |
| --- | --- | --- |
| Win32 | 1.093 / 1.066 秒 | 1.524 / 0.973 秒 |
| x64 | 1.066 / 0.972 秒 | 0.835 / 0.815 秒 |

Win32 新版第三轮总耗时为 2.653 秒，阶段日志显示 `write_bundle` 为 2.067 秒，前两轮为 0.329 / 0.342 秒；该轮源码还原仅 0.244 秒。保留全部样本，没有从平均数中删除此轮，也不声称这个样例的 Win32 平均总耗时改善。写盘波动的具体系统原因未经验证。

新版无窗口模块源码还原的三轮平均为 Win32 0.275 秒、x64 0.280 秒。最初依赖导出剖析中该模块为 0.423 秒，来源路径及执行上下文不同，只作为定位参考。

原始报告：`temp/window-benchmark-3ddbf0190a/report.json`。

## 功能验证与限制

- Release Win32、x64 编译成功，日志无编译警告或错误，见 `temp/core-perf-20261017/build-final-{Win32,x64}.log`。
- 两个架构各 9 项源码修改、回包、真实易语言编译、运行和再次解包检查通过：全局变量/菜单重名、局部变量与全局变量重名、局部变量与控件/菜单重名、中文名称边界、隐式窗口方法/属性、跨程序集控件/菜单访问。x64 解包也实际使用 x64 EXE。报告为 `symbols-Win32-final/results.json` 和 `symbols-x64-serial/results.json`。
- 两个架构均保留 `assignment_type_mismatch` 诊断。既有测试原先要求回包失败，但优化前二进制已经把此项作为 `source_preflight_warning` 输出并成功回包；测试已对齐现有行为，没有修改生产校验器。
- 最小控制台工程两个架构的修改后语义回包、再次解包及源码/资源比较通过，见 `edited-console-minimal/results.json`。
- 用户工程和精易模块分别在 Win32、x64 未修改回包，共 4 次逐字节比较通过。用户工程 MD5 为 `de4fb9fb4ee2e3e665dd5d4066c0ffae`；见 `roundtrip-report.json`。
- 原始下载工程 SHA-256 复核未改变：`ae6fced302ad4e5396a1366e14c81a45a71d90fe8058ea82d1f9b3a689c8deb1`。

以上功能报告若未写完整路径，均位于 `temp/core-perf-20261017/`。

额外大样例的修改回包没有计为通过：安装目录精易模块存在裁剪后的空声明名，预检查出现 3230 个错误，优化前版本复现相同结果；`e-console-exe-full-test.e` 存在模块代码回读差异，同样编辑使用优化前版本回包，与新版产生的 `.e` 完全一致。证据为 `edited-jingyi/`、`baseline-jingyi-edit.log`、`edited-console/` 和 `baseline-console-edit.log`。

额外的 EC 目标无头编译测试在生成初始模块时，AutoLinker 启动器返回 `headless_process_timeout`；串行重试仍超时，尚未进入解包/回包检查，不计为通过。记录为 `ecom-headless-serial/module.ec.json`。上述两架构各 9 项真实编译和运行测试已通过。

用户工程仍要求本机没有的外部模块，以及高于本机 eGrid 2.11 的版本；原有 6 条 `_Lib5Cmd80/81` 命令越界警告和 8 个外部模块缺失没有因本轮优化而消失。本轮不宣称用户工程编辑后可完整编译。未执行全量样本测试。

## 复现

```powershell
python tools/BenchmarkWindowUnpack.py --before-root temp/core-perf-20261017 --architecture both --rounds 3 --input 'temp/user-manager-test-6a3a46fe/1 - 管理器 - 95-1.e'
python tools/BenchmarkWindowUnpack.py --before-root temp/core-perf-20261017 --architecture both --rounds 3 --input temp/core-perf-20261017/jingyi.ec --main-only
```

基线二进制保存在 `before-Win32/` 和 `before-x64/`。基准脚本保留各轮日志、标准输出、阶段耗时及产物数量，并断言工程和依赖产物一致。
