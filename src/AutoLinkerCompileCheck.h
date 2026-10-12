#pragma once

#include <filesystem>
#include <string>

namespace autolinker_compile_check {

// AutoLinker 无头编译检查选项。
struct Options {
	std::filesystem::path eIdePath;
	std::string target = "auto";
	bool staticCompile = false;
	unsigned int timeoutSeconds = 120;
};

// 已完成路径发现和参数校验的编译检查选项。
struct PreparedOptions : Options {
};

// 无头编译检查结果。
struct Result {
	bool ok = false;
	// IDE 已给出编译结论，与启动失败、超时等无法验证状态区分。
	bool validationCompleted = false;
	// 保留 IDE 原始结构化诊断，不猜测源码行号。
	std::string diagnosticsJson;
	std::string summary;
	std::string error;
};

// 解析显式参数、环境变量和注册表中的 IDE 路径。
bool Prepare(const Options& options, PreparedOptions& outOptions, std::string& outError);

// 直接启动用户指定版本化 IDE 的 AutoLinker 无头编译入口。
Result CompileToOutputWithEide(
	const std::filesystem::path& sourcePath,
	const std::filesystem::path& outputPath,
	const std::filesystem::path& eIdePath,
	const std::string& target,
	bool staticCompile,
	unsigned int timeoutSeconds,
	const std::filesystem::path& projectSourcePath = {});

// 直接启动 IDE 对指定易语言工程执行真实编译。
Result Run(const std::filesystem::path& sourcePath, const PreparedOptions& options);

// 直接启动 IDE 并保留指定输出文件，供后续编译方式消费原生 PE。
Result CompileToOutput(
	const std::filesystem::path& sourcePath,
	const std::filesystem::path& outputPath,
	const PreparedOptions& options);

}  // namespace autolinker_compile_check
