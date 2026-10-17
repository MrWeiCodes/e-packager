#pragma once

#include "e2txt.h"
#include <filesystem>
#include <string>
#include <vector>

// 工作区增删操作：先验证并修改内存模型，再由命令入口持久化。
namespace workspace_update {
struct Options {
	std::vector<std::string> addEcom, addElib, addImage, addAudio;
	std::vector<std::string> removeEcom, removeElib, removeImage, removeAudio;
};

struct Result {
	size_t addedEcom = 0, addedElib = 0, addedImage = 0, addedAudio = 0;
	size_t removedEcom = 0, removedElib = 0, removedImage = 0, removedAudio = 0;
	std::vector<std::filesystem::path> removedResourceFiles;
};

// 删除先于新增；失败时调用方不得持久化 bundle。
bool Apply(e2txt::ProjectBundle& bundle, const std::filesystem::path& workspace,
	const std::filesystem::path& workspaceSourcePath, const Options& options,
	Result& result, std::string& error);

// 索引保存成功后，仅清理已验证位于资源目录内且不再引用的文件。
bool RemoveResourceFiles(const Result& result, std::string& error);
} // namespace workspace_update
