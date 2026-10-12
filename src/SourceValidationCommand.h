#pragma once
#include <filesystem>
#include "AutoLinkerCompileCheck.h"

namespace source_validation {
// 命令行验证级别；可编辑检查不宣称已经通过 IDE 打开测试。
enum class Level { Editable, Semantic, Compile };
// 执行验证，返回 0 通过、1 验证失败、2 环境导致无法完成验证。
int Run(const std::filesystem::path& input, Level level, bool jsonOutput,
	const autolinker_compile_check::Options& compileOptions);
}
