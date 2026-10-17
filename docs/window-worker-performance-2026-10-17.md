# 窗口解包辅助进程性能回归

用户反馈 x86 v1.2.19 解包约 16 秒，v1.2.20 起约 200 秒，无窗口工程仍约 1～2 秒。
对照 v1.2.19..v1.2.20，Win32 控件属性从进程内调用改成了隔离调用，而桥接器每次请求都重新启动 EXE。
事件读取、每个控件属性读取都可能触发一次启动，进程启动和支持库初始化开销随请求数量增长。
本地样例验证了这一开销；本阶段尚未获得用户原工程。取得用户工程后的进一步优化见 [管道与宿主窗口优化](window-worker-ipc-performance-2026-10-17.md)。

## 修改

- 同一次主命令复用一个隔离的 Win32 进程，通过事件同步 CBOR 请求和响应。
- 相同工程上下文复用 codec、OLE 和支持库初始化；每条请求结束时销毁临时探测窗口。
- 请求有递增编号，防止读取旧响应。保留 30 秒超时；崩溃/超时后后续请求重新启动进程。
- 主命令退出时关闭工作进程并清理临时消息文件；Job Object 保证父进程异常退出时工作进程也退出。
- `property_worker_started` 记录启动次数；`property_worker_request` 记录操作、源文件、类型、控件编号、耗时和错误。
- 普通属性失败的响应可缓存；进程崩溃/超时不缓存。

## 本地对比

修改前基于 `85f8ff9`，修改后为本次工作区构建，均为 Release。
输入 `eproj/e-window-exe-full+otherFne.e`，带 `--main-only`，每个架构交替运行旧版/新版三轮。
计时包含命令启动、解包及退出，不编译易语言工程。

| 架构 | 修改前三轮（秒） | 修改后三轮（秒） | 平均耗时（秒） | 辅助进程数 |
| --- | --- | --- | --- | --- |
| x86 | 7.909、5.132、4.829 | 1.261、1.022、0.984 | 5.957 → 1.089 | 53 → 1 |
| x64 | 5.634、7.306、6.277 | 1.567、1.262、1.164 | 6.406 → 1.331 | 58 → 1 |

所有轮次的 `src/` 文件（包括窗口 XML）逐字节相同。
本地结果不代表用户机器或其工程的确切改善幅度。

复测命令：

```powershell
python tools/BenchmarkWindowUnpack.py --before-root temp/property-perf-14739fc5 --rounds 3 --main-only
```

`--before-root` 需包含保存的 `before-Win32/e-packager.exe`、`before-x64/e-packager.exe` 和 x64 所需的 x86 辅助程序。
本次报告：`temp/window-benchmark-692b29156d/report.json`。

## 验证

- Release Win32 / x64：0 警告、0 错误。
- 两个架构均通过 118 项属性修改/回读检查，覆盖 22 类窗口和控件；不修改时回包字节一致，事件绑定保留。
- 隔离工作进程：多请求复用、普通失败及缓存、崩溃后恢复、30 秒超时后恢复、正常回收、父进程直接退出后的回收均通过。
- 易语言目录强制指定、x64 元数据跨进程读取、FNE 优先于 FNR、七类未解码命令诊断回归通过。

进程故障测试驱动为 x64 `tools/fixtures/FormControlWorkerSessionTest.cpp`，链接实际的 `src/FormControlPropertyBridge.cpp` 和 `src/RuntimeLogger.cpp`（当前管道版还需链接 `src/WorkerMessagePipe.cpp`）。
故障 DLL 为 Win32 `tools/fixtures/FormControlWorkerFailureTest.cpp`，使用 `elib/lib2.h` 并导出 `GetNewInf=_GetNewInf@0`。
驱动仅替换路径转换/显式安装路径获取接口，实际运行新构建的 Win32 e-packager 辅助进程。

```powershell
python tools/TestFormControlWorker.py --driver temp/property-perf-14739fc5/worker-driver.exe --fixture temp/property-perf-14739fc5/worker-failure.fne
```

测试在新的 temp 子目录中进行，不修改原始工程，不进行全量样本测试。
