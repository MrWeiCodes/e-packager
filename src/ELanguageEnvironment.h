#pragma once

#include <filesystem>
#include <string>
#include <vector>

// 统一管理易语言安装目录及支持库搜索；命令开始后配置保持不变。
namespace e_language_environment {

// 校验安装目录必须同时包含 lib、static_lib、ecom 三个子目录。
bool ValidateDirectory(const std::filesystem::path& directory, std::string& error);
// 显式目录校验失败时返回错误，不切换到其他安装。
bool SetExplicitDirectory(const std::filesystem::path& directory, std::string& error);
std::filesystem::path GetExplicitDirectory();
// 按环境变量、注册表、程序目录、程序上级目录的顺序探测有效安装。
std::filesystem::path GetInstallationDirectory();
// 在选定安装中定位主程序，支持注册表记录、e.exe 与 e版本号.exe。
std::filesystem::path GetInstallationExecutablePath();
// 提取通用 --e-dir 参数，保留其他参数及其值供原命令解析。
bool ConfigureCommandLine(int argc, char* argv[], std::vector<char*>& arguments, std::string& error);
// 架构限定搜索优先使用指定搜索目录；普通搜索中的 --e-dir 强制限定支持库来源。
// FNR 候选统一排在其他候选之后，避免运行库遮蔽包含命令表的开发库。
std::vector<std::filesystem::path> BuildSupportLibraryCandidates(
    const std::filesystem::path& sourcePath,
    const std::filesystem::path& libraryFile,
    const std::vector<std::filesystem::path>& searchDirectories = {},
    bool restrictSearch = false,
    const std::filesystem::path& resolvedPath = {});

}  // namespace e_language_environment
