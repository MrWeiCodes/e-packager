#pragma once

#include <Windows.h>
#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

// 统一记录 UTF-8 运行日志，供安装目录与支持库问题排查。
namespace runtime_logger {

enum class Level { Info, Warning, Error };

// 主命令开始新日志：首次写入前清空旧内容并启用 stderr 提示；辅助进程不调用。
void BeginSession() noexcept;

// 优先追加到启动工作目录，失败时尝试程序目录、用户日志目录和临时目录。
// 写入失败不抛异常，不改变 Win32 最后错误。
void Write(Level level, std::string_view message) noexcept;

// 返回 Win32 错误码和 UTF-8 系统说明。
std::string DescribeWin32Error(DWORD errorCode);

// 记录本次支持库查找的上下文及按顺序排列的候选文件路径。
void LogLibrarySearch(std::string_view context, std::string_view libraryName,
    const std::filesystem::path& sourcePath,
    const std::vector<std::filesystem::path>& candidates);

}  // namespace runtime_logger
