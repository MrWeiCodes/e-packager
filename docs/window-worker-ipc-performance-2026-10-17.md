# 用户管理器工程解包性能优化

用户提供 `1 - 管理器 - 95-1.e`（15,886,711 字节），包含 80 个窗口 XML、95 个源码 TXT、2204 个窗口/控件对象。
此前逐请求启动进程的版本单轮为 220.96 秒，第一阶段复用进程后单轮为 89.25 秒，仍明显慢于用户反馈的早期版本约 16 秒。
本轮以 `f6fbe0f` 的常驻进程版本为基线，继续优化。测试均使用副本，不修改下载目录中的原文件。

## 瓶颈与修改

分段计时显示，旧版 2229 次请求仅响应文件读取就累计约 21.77 秒；辅助进程处理累计约 30.54 秒。
控件属性读取通常只有几十微秒，创建临时顶层窗口则抽样约 5～14 毫秒。改成批量读取文件后，文件打开/读取开销仍然存在。

- 新增独立的 `WorkerMessagePipe`，通过命名管道传输带长度的 CBOR 消息，不再逐控件读写临时文件。独立管道不受支持库 stdout 输出影响。
- 主端使用异步 I/O，写请求和读响应共用 30 秒截止时间；同时等待辅助进程退出。超时先取消并等待 I/O 完成，再释放缓冲区，避免悬空访问。单帧限制 256 MiB，拒绝损坏长度。
- 继续保留请求编号校验、崩溃/超时后重启、Job Object 随主进程退出回收。新内部入口为 `--form-control-pipe-server`；原有一次性文件工作进程入口保留。x64 与其 x86 辅助 EXE 必须来自同次构建。
- 每个 codec 复用一个隐藏顶层宿主，单次请求使用独立子容器，结束时销毁容器和临时控件。不会把上个控件实例作为下个请求的实例复用。
- 日志句柄在进程内复用，每条记录仍即时写入并加跨进程文件锁；每次主命令仍清空历史日志。写入前在锁内移动到文件末尾，防止覆盖其他进程追加的内容。
- 日志保留 `elapsed_ms`，新增高精度的 `elapsed_us` 和 `worker_us`，分别表示请求总耗时与辅助进程实际处理耗时（含临时控件销毁）。

## 验证方式

使用普通 `unpack`，不加 `--main-only`；同一台机器交替运行基线与新版各三轮，计时包含启动、解包及退出。
每轮比较 `src/` 下所有文件的相对路径与字节，不能仅通过耗时判定优化成功。

```powershell
python tools/BenchmarkWindowUnpack.py --before-root temp/property-ipc-perf/comparison --architecture Win32 --rounds 3 --input 'temp/user-manager-test-6a3a46fe/1 - 管理器 - 95-1.e'
```

`--before-root` 下保存 `before-Win32/e-packager.exe`。基准工具默认与普通解包一致，仍可显式加 `--main-only` 测试仅主工程。

## 实测结果

| x86 Release | 第 1 轮 | 第 2 轮 | 第 3 轮 | 平均 |
| --- | ---: | ---: | ---: | ---: |
| 本轮优化前 | 83.888 秒 | 77.230 秒 | 77.165 秒 | 79.428 秒 |
| 本轮优化后 | 14.830 秒 | 14.888 秒 | 14.896 秒 | 14.871 秒 |

同批次平均耗时降低 **81.3%**，约 **5.34 倍**速度；对照最早单轮 220.96 秒约降低 93.3%，但后者不是本批交替计时。
六轮输出的 175 个源码/XML 文件全部逐字节相同；每轮 1 个工作进程、2229 次请求，无失败或超时。
新版请求总耗时约 6.53 秒，其中辅助进程处理约 5.58 秒。余下时间包括工程解析、源码/资源导出和依赖处理，不能全部归到属性桥接上。

三轮报告及各轮日志：`temp/window-benchmark-2fc4ed60c1/report.json`。
分段分析和功能测试记录：`temp/property-ipc-perf/`。

用户工程另做一轮 x64 Release 解包，耗时 **14.410 秒**，175 个文件与 x86 输出逐字节相同。
x86/x64 的未修改回包分别为 **0.611 秒 / 0.301 秒**，均与原文件逐字节一致，MD5 均为 `de4fb9fb4ee2e3e665dd5d4066c0ffae`。
原始下载文件 SHA-256 再次验证未改变：`ae6fced302ad4e5396a1366e14c81a45a71d90fe8058ea82d1f9b3a689c8deb1`。
对应记录为 `temp/property-ipc-perf/final-x64/report.json`、`temp/property-ipc-perf/roundtrip-report.json`。

## 功能与故障回归

- Release Win32 和 x64 均可编译，无警告、无错误。
- 两个架构各通过 118 项属性修改回读检查，覆盖 22 类窗口/控件，保留事件绑定；未修改的样例回包逐字节一致。
- 工作进程复用、普通失败缓存、崩溃恢复、30 秒超时恢复、正常回收及父进程直接退出后的回收。
- 管道测试覆盖 1 字节、64 KiB 边界及 3 MiB 双向连续消息，以及零长度、超大长度、截断消息、读写超时取消。
- 两个架构通过日志位置提示、全部备用路径、写入失败、仅查询版本不改日志、每次主命令重置、辅助进程追加及 trace 重置测试。

管道边界测试在 x86/x64 的 VS 开发者命令提示符分别编译运行：

```bat
cl /nologo /O2 /std:c++20 /EHsc /MT /Isrc tools\fixtures\WorkerMessagePipeTest.cpp src\WorkerMessagePipe.cpp /Fotemp\property-ipc-perf\ /Fetemp\property-ipc-perf\pipe-test.exe
temp\property-ipc-perf\pipe-test.exe
```

进程故障驱动使用 x64 编译 `tools/fixtures/FormControlWorkerSessionTest.cpp`，链接 `src/FormControlPropertyBridge.cpp`、`src/RuntimeLogger.cpp`、`src/WorkerMessagePipe.cpp`，再运行 `tools/TestFormControlWorker.py`。

本机 eGrid 2.11 与工程要求的 3.0 不一致，`_Lib5Cmd80`、`_Lib5Cmd81` 仍产生 6 条命令编号越界警告，另有 8 个用户 E: 盘上的外部模块缺失。
优化前后依赖条件一致。本次验证性能、输出一致性及属性编辑回读，未声称补齐了用户依赖或验证了其工程编辑后的编译。未做全量样本测试。
