# EC 完整语义回包回归

先依次构建 Release Win32、Release x64。x64 需要配套的 Win32 工作进程读取经典 FNE 接口。

## 单个 EC

```powershell
python tools/TestEcSemanticRoundTrip.py --input eproj/异常模块-rt.ec --output temp/exception-new `
  --ide C:/Users/aiqin/OneDrive/e5.6/e5.95.exe `
  --launcher D:/git/AutoLinker/bin/fne_release/AutoLinkerTest.exe
```

脚本分别用 Win32 和 x64 拆包，将全部程序集／类页加唯一注释，验证未修改字节一致、修改后源码及资源一致、注释保留、再次回包和真实 IDE 编译。省略两个 IDE 参数时只检查语义回包，不启动 IDE。测试副本和报告保存在指定的新目录，不修改输入 EC。

## 目录全量检查

```powershell
python tools/TestModuleRoundtripAudit.py --source C:/Users/aiqin/OneDrive/code/模块 `
  --output temp/ec-all-new --extensions .ec --workers 4 --timeout 180
```

缺失支持库时通过重复的 `--support-library` 参数补充真实 FNE 文件。它们仅复制到测试输入副本的 lib 目录，来源与哈希记录在 run.json；不要将缺库导致的占位符或未检查语句当成成功。全量脚本不调用 IDE，不运行生成的程序。

本次样本使用的额外支持库：

- eAPI.fne：本地白月 3.2 的 lib 目录。
- aiqinStructure.fne：模块目录中“易支持库/爱琴常用数据结构/release”。
- AQGlobalNotificationFne.fne：从本地 D:/git/AQGlobalNotificationFne 源码副本构建；仅修正旧 SDK 函数指针 typedef 中现代编译器不接受的默认参数。原仓库未修改。

EC 拆包后修改生成的是可编辑 .e；需要重新发布 .ec 时通过易语言 IDE 编译。原样 .ec 回包仍保持原始字节。

## 2026-10-15 验证结果

- Release Win32 与 x64 构建通过。
- 异常模块-rt.ec：两个架构均对全部 41 个程序集／类页追加注释，完成语义回包、再次拆包及易语言 IDE 编译；另验证实际字符串代码修改后的 IDE 编译。证据位于 temp/exception-rt-final。
- 模块目录全部 188 个 EC：Win32、x64 共 376 个用例全部通过；每个架构共修改 4233 页。原样回包逐字节、MD5、SHA256 一致，修改后源码／窗口／资源／注释比较及二次回包通过，原文件保持不变。报告位于 temp/ec-all-audit-final/report.md。
- 全量 EC 审计仅验证语义回包，未逐个执行 IDE 编译。
- 额外 TestEComHeadlessRoundTrip 导入模块回归在首个小模块的 IDE 编译阶段发生 headless_process_timeout，直接重试仍超时，未计为通过；记录位于 temp/ec-import-regression-final/module-retry.json。