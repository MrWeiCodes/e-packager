#include "WorkspaceUpdate.h"
#include "PathHelper.h"
#include "SupportLibraryPublicInfo.h"
#include <algorithm>
#include <cctype>
#include <fstream>
#include <unordered_set>

namespace workspace_update {
namespace {
std::string TrimAsciiCopy(std::string text)
{
	const auto isSpace = [](unsigned char ch) {
		return std::isspace(ch) != 0;
	};
	text.erase(
		text.begin(),
		std::find_if(text.begin(), text.end(), [&](const unsigned char ch) {
			return !isSpace(ch);
		}));
	text.erase(
		std::find_if(text.rbegin(), text.rend(), [&](const unsigned char ch) {
			return !isSpace(ch);
		}).base(),
		text.end());
	return text;
}

std::string ToLowerAsciiCopy(std::string text)
{
	std::transform(text.begin(), text.end(), text.begin(), [](unsigned char ch) {
		return static_cast<char>(std::tolower(ch));
	});
	return text;
}

bool ReadFileBytes(const std::filesystem::path& path, std::vector<std::uint8_t>& outBytes, std::string& outError)
{
	outBytes.clear();

	std::ifstream in(path, std::ios::binary);
	if (!in.is_open()) {
		outError = "open_failed: " + PathToUtf8(path);
		return false;
	}

	in.seekg(0, std::ios::end);
	const std::streamoff size = in.tellg();
	if (size < 0) {
		outError = "tellg_failed: " + PathToUtf8(path);
		return false;
	}
	in.seekg(0, std::ios::beg);

	outBytes.resize(static_cast<size_t>(size));
	if (size > 0) {
		in.read(reinterpret_cast<char*>(outBytes.data()), size);
		if (!in.good() && static_cast<size_t>(in.gcount()) != outBytes.size()) {
			outError = "read_failed: " + PathToUtf8(path);
			return false;
		}
	}

	return true;
}


bool ResolveModulePath(const std::filesystem::path& source, const std::string& input,
	std::filesystem::path& result)
{
	for (const auto& candidate : BuildModuleFileLookupCandidates(source, input)) {
		std::error_code ec;
		if (std::filesystem::exists(candidate, ec)) {
			result = candidate;
			return true;
		}
	}
	return false;
}

bool IsEquivalentDependency(const e2txt::Dependency& left, const e2txt::Dependency& right)
{
	if (left.kind != right.kind) {
		return false;
	}

	if (left.kind == e2txt::DependencyKind::ECom) {
		return ToLowerAsciiCopy(TrimAsciiCopy(left.path)) == ToLowerAsciiCopy(TrimAsciiCopy(right.path));
	}

	const std::string leftFile = ToLowerAsciiCopy(TrimAsciiCopy(left.fileName));
	const std::string rightFile = ToLowerAsciiCopy(TrimAsciiCopy(right.fileName));
	const std::string leftGuid = ToLowerAsciiCopy(TrimAsciiCopy(left.guid));
	const std::string rightGuid = ToLowerAsciiCopy(TrimAsciiCopy(right.guid));
	if (!leftGuid.empty() || !rightGuid.empty()) {
		return leftFile == rightFile && leftGuid == rightGuid;
	}
	return leftFile == rightFile;
}

bool HasEquivalentDependency(
	const std::vector<e2txt::Dependency>& dependencies,
	const e2txt::Dependency& candidate)
{
	return std::any_of(dependencies.begin(), dependencies.end(), [&](const e2txt::Dependency& item) {
		return IsEquivalentDependency(item, candidate);
	});
}

bool BuildEComDependencyFromInput(
	const std::filesystem::path& sourcePath,
	const std::string& inputText,
	e2txt::Dependency& outDependency,
	std::string& outResolvedPath,
	std::string& outError)
{
	outDependency = {};
	outResolvedPath.clear();
	outError.clear();

	const std::string trimmedInput = TrimAsciiCopy(inputText);
	if (trimmedInput.empty()) {
		outError = "empty_ecom_input";
		return false;
	}

	std::filesystem::path resolvedPath;
	const std::filesystem::path directPath(trimmedInput);
	std::error_code ec;
	if ((directPath.is_absolute() || trimmedInput.find('\\') != std::string::npos || trimmedInput.find('/') != std::string::npos) &&
		std::filesystem::exists(directPath, ec)) {
		resolvedPath = std::filesystem::absolute(directPath, ec);
		if (ec) {
			resolvedPath = directPath;
		}
	}
	else if (!ResolveModulePath(sourcePath, trimmedInput, resolvedPath)) {
		outError = "ecom_not_found: " + trimmedInput;
		return false;
	}

	e2txt::Generator generator;
	e2txt::ProjectBundle moduleBundle;
	if (!generator.GenerateBundle(PathToUtf8(resolvedPath), moduleBundle, &outError)) {
		outError = "ecom_parse_failed: " + PathToUtf8(resolvedPath) + " => " + outError;
		return false;
	}

	outDependency.kind = e2txt::DependencyKind::ECom;
	outDependency.name = TrimAsciiCopy(moduleBundle.projectName);
	if (outDependency.name.empty()) {
		outDependency.name = resolvedPath.stem().string();
	}
	outDependency.path = "$" + resolvedPath.filename().string();
	outDependency.reExport = false;
	outResolvedPath = PathToUtf8(resolvedPath);
	return true;
}

std::string StripWrappingQuotes(std::string text)
{
	text = TrimAsciiCopy(std::move(text));
	if (text.size() >= 2 &&
		((text.front() == '"' && text.back() == '"') ||
			(text.front() == '\'' && text.back() == '\''))) {
		return text.substr(1, text.size() - 2);
	}
	return text;
}

std::string NormalizeResourceLogicalName(std::string name)
{
	name = StripWrappingQuotes(std::move(name));
	if (!name.empty() && name.front() == '#') {
		name.erase(name.begin());
	}
	return TrimAsciiCopy(std::move(name));
}

bool IsValidResourceLogicalName(const std::string& name)
{
	if (name.empty()) {
		return false;
	}
	return name.find_first_of("\\/:*?\"<>|") == std::string::npos;
}

std::string ResourceKindKeyPrefix(const e2txt::BundleResourceKind kind)
{
	return kind == e2txt::BundleResourceKind::Image ? "image" : "sound";
}

std::string ResourceKindDirectoryName(const e2txt::BundleResourceKind kind)
{
	return kind == e2txt::BundleResourceKind::Image ? "image" : "audio";
}

bool HasResourceLogicalNameConflict(
	const std::vector<e2txt::BundleBinaryResource>& resources,
	const e2txt::BundleResourceKind kind,
	const std::string& logicalName,
	bool& outSameKindExists)
{
	outSameKindExists = false;
	const std::string normalizedName = ToLowerAsciiCopy(TrimAsciiCopy(logicalName));
	for (const auto& resource : resources) {
		if (ToLowerAsciiCopy(TrimAsciiCopy(resource.logicalName)) != normalizedName) {
			continue;
		}
		if (resource.kind == kind) {
			outSameKindExists = true;
		}
		return true;
	}
	return false;
}

std::string MakeUniqueResourceKey(
	const std::vector<e2txt::BundleBinaryResource>& resources,
	const e2txt::BundleResourceKind kind,
	const std::string& logicalName)
{
	const std::string baseKey = ResourceKindKeyPrefix(kind) + ":" + logicalName;
	std::string candidate = baseKey;
	for (int counter = 2;; ++counter) {
		const bool exists = std::any_of(resources.begin(), resources.end(), [&](const e2txt::BundleBinaryResource& resource) {
			return resource.key == candidate;
		});
		if (!exists) {
			return candidate;
		}
		candidate = baseKey + "#" + std::to_string(counter);
	}
}

bool AppendUniqueRootChildKey(std::vector<std::string>& rootChildKeys, const std::string& key)
{
	if (key.empty() ||
		std::find(rootChildKeys.begin(), rootChildKeys.end(), key) != rootChildKeys.end()) {
		return false;
	}
	rootChildKeys.push_back(key);
	return true;
}

bool BuildBinaryResourceFromInput(
	const std::vector<e2txt::BundleBinaryResource>& existingResources,
	const e2txt::BundleResourceKind kind,
	const std::string& inputText,
	e2txt::BundleBinaryResource& outResource,
	bool& outAlreadyExists,
	std::string& outError)
{
	outResource = {};
	outAlreadyExists = false;
	outError.clear();

	std::string input = StripWrappingQuotes(inputText);
	if (input.empty()) {
		outError = kind == e2txt::BundleResourceKind::Image ? "empty_image_input" : "empty_audio_input";
		return false;
	}

	std::string logicalName;
	std::string fileNameText = input;
	const size_t assignPos = input.find('=');
	if (assignPos != std::string::npos) {
		const std::string namePart = TrimAsciiCopy(input.substr(0, assignPos));
		const std::string pathPart = TrimAsciiCopy(input.substr(assignPos + 1));
		if (!namePart.empty() &&
			!pathPart.empty() &&
			namePart.find_first_of("\\/:") == std::string::npos) {
			logicalName = NormalizeResourceLogicalName(namePart);
			fileNameText = StripWrappingQuotes(pathPart);
		}
	}

	std::filesystem::path sourcePath(fileNameText);
	if (logicalName.empty()) {
		logicalName = NormalizeResourceLogicalName(sourcePath.stem().string());
	}
	if (!IsValidResourceLogicalName(logicalName)) {
		outError = "invalid_resource_name: " + logicalName;
		return false;
	}

	std::error_code ec;
	if (!std::filesystem::exists(sourcePath, ec) || !std::filesystem::is_regular_file(sourcePath, ec)) {
		outError = "resource_file_not_found: " + fileNameText;
		return false;
	}
	sourcePath = std::filesystem::absolute(sourcePath, ec);
	if (ec) {
		sourcePath = std::filesystem::path(fileNameText);
	}

	bool sameKindExists = false;
	if (HasResourceLogicalNameConflict(existingResources, kind, logicalName, sameKindExists)) {
		if (sameKindExists) {
			outAlreadyExists = true;
			return true;
		}
		outError = "resource_name_conflict: #" + logicalName;
		return false;
	}

	std::vector<std::uint8_t> data;
	if (!ReadFileBytes(sourcePath, data, outError)) {
		return false;
	}

	outResource.kind = kind;
	outResource.key = MakeUniqueResourceKey(existingResources, kind, logicalName);
	outResource.logicalName = logicalName;
	outResource.relativePath = ResourceKindDirectoryName(kind) + "/" + logicalName + ".bin";
	outResource.comment.clear();
	outResource.isPublic = false;
	outResource.data = std::move(data);
	return true;
}


std::string NormalizeSelector(std::string text)
{
	text = StripWrappingQuotes(std::move(text));
	if (!text.empty() && text.front() == '$') text.erase(text.begin());
	std::replace(text.begin(), text.end(), '\\', '/');
	return ToLowerAsciiCopy(std::filesystem::path(text).lexically_normal().generic_string());
}

bool RemoveDependencies(e2txt::ProjectBundle& bundle, e2txt::DependencyKind kind,
	const std::vector<std::string>& inputs, size_t& count, std::string& error)
{
	std::unordered_set<size_t> removed;
	for (const auto& input : inputs) {
		const auto selector = NormalizeSelector(input);
		std::vector<size_t> matches;
		for (size_t i = 0; i < bundle.dependencies.size(); ++i) {
			const auto& item = bundle.dependencies[i];
			if (item.kind != kind || selector.empty()) continue;
			const auto matchesField = [&](const std::string& field) {
				return !field.empty() && NormalizeSelector(field) == selector;
			};
			const auto file = std::filesystem::path(NormalizeSelector(
				kind == e2txt::DependencyKind::ECom ? item.path : item.fileName));
			if (matchesField(item.name) || matchesField(item.guid) || matchesField(item.path) ||
				matchesField(item.fileName) || matchesField(Utf8PathToPath(item.resolvedPath).string()) ||
				selector == file.filename().string() || selector == file.stem().string()) {
				matches.push_back(i);
			}
		}
		if (matches.size() != 1) {
			error = (matches.empty() ? "dependency_not_found: " : "ambiguous_dependency: ") + input;
			return false;
		}
		removed.insert(matches.front());
	}
	size_t index = 0;
	std::erase_if(bundle.dependencies, [&](const auto&) { return removed.contains(index++); });
	count = removed.size();
	return true;
}

bool RemoveResources(e2txt::ProjectBundle& bundle, e2txt::BundleResourceKind kind,
	const std::vector<std::string>& inputs, size_t& count,
	std::vector<std::string>& removedPaths, std::string& error)
{
	std::unordered_set<size_t> removed;
	std::unordered_set<std::string> removedKeys;
	for (const auto& input : inputs) {
		const auto name = ToLowerAsciiCopy(NormalizeResourceLogicalName(input));
		const auto selector = NormalizeSelector(input);
		std::vector<size_t> matches;
		for (size_t i = 0; i < bundle.resources.size(); ++i) {
			const auto& item = bundle.resources[i];
			if (item.kind == kind && !name.empty() &&
				(ToLowerAsciiCopy(item.logicalName) == name ||
				ToLowerAsciiCopy(item.key) == ToLowerAsciiCopy(StripWrappingQuotes(input)) ||
				(!item.relativePath.empty() && NormalizeSelector(item.relativePath) == selector))) {
				matches.push_back(i);
			}
		}
		if (matches.size() != 1) {
			error = (matches.empty() ? "resource_not_found: " : "ambiguous_resource: ") + input;
			return false;
		}
		const auto& item = bundle.resources[matches.front()];
		if (removed.insert(matches.front()).second) {
			removedKeys.insert(item.key);
			removedPaths.push_back(item.relativePath);
		}
	}
	size_t index = 0;
	std::erase_if(bundle.resources, [&](const auto&) { return removed.contains(index++); });
	const auto isRemoved = [&](const std::string& key) { return removedKeys.contains(key); };
	std::erase_if(bundle.rootChildKeys, isRemoved);
	for (auto& folder : bundle.folders) std::erase_if(folder.childKeys, isRemoved);
	count = removed.size();
	return true;
}

bool IsWithin(const std::filesystem::path& path, const std::filesystem::path& directory)
{
	auto p = path.begin();
	for (auto d = directory.begin(); d != directory.end(); ++d, ++p) {
		if (p == path.end() || _wcsicmp(p->c_str(), d->c_str()) != 0) return false;
	}
	return p != path.end();
}

bool PlanResourceCleanup(const e2txt::ProjectBundle& bundle, const std::filesystem::path& workspace,
	const std::vector<std::string>& removedPaths, Result& result, std::string& error)
{
	for (const auto& relative : removedPaths) {
		const auto path = std::filesystem::weakly_canonical(workspace / relative);
		// 同一文件仍被任意资源引用时保留；禁止通过 .. 或链接删除工作区外的文件。
		const bool shared = std::any_of(bundle.resources.begin(), bundle.resources.end(), [&](const auto& item) {
			return _wcsicmp(path.c_str(), std::filesystem::weakly_canonical(workspace / item.relativePath).c_str()) == 0;
		});
		if (shared) continue;
		const auto root = std::filesystem::weakly_canonical(workspace);
		const auto image = std::filesystem::weakly_canonical(workspace / "image");
		const auto audio = std::filesystem::weakly_canonical(workspace / "audio");
		if (!IsWithin(path, root) || (!IsWithin(path, image) && !IsWithin(path, audio)) ||
			_wcsicmp(path.filename().c_str(), L"list.json") == 0 ||
			std::filesystem::is_directory(path)) {
			error = "unsafe_resource_remove_path: " + relative;
			return false;
		}
		result.removedResourceFiles.push_back(path);
	}
	return true;
}
} // namespace

bool Apply(e2txt::ProjectBundle& bundle, const std::filesystem::path& workspace,
	const std::filesystem::path& workspaceSourcePath, const Options& options,
	Result& result, std::string& error)
{
	result = {};
	error.clear();
	std::vector<std::string> removedPaths;
	if (!RemoveDependencies(bundle, e2txt::DependencyKind::ECom, options.removeEcom, result.removedEcom, error) ||
		!RemoveDependencies(bundle, e2txt::DependencyKind::ELib, options.removeElib, result.removedElib, error) ||
		!RemoveResources(bundle, e2txt::BundleResourceKind::Image, options.removeImage, result.removedImage, removedPaths, error) ||
		!RemoveResources(bundle, e2txt::BundleResourceKind::Sound, options.removeAudio, result.removedAudio, removedPaths, error)) return false;
	for (const auto& input : options.addEcom) {
		e2txt::Dependency dependency;
		std::string resolvedPath;
		if (!BuildEComDependencyFromInput(workspaceSourcePath, input, dependency, resolvedPath, error)) {
			return false;
		}
		if (!HasEquivalentDependency(bundle.dependencies, dependency)) {
			bundle.dependencies.push_back(std::move(dependency));
			++result.addedEcom;
		}
	}

	for (const auto& input : options.addElib) {
		support_library_public_info::BuildDependencyResult buildResult;
		if (!support_library_public_info::TryBuildDependencyFromInput(workspaceSourcePath, input, buildResult, error)) {
			return false;
		}
		if (!HasEquivalentDependency(bundle.dependencies, buildResult.dependency)) {
			bundle.dependencies.push_back(std::move(buildResult.dependency));
			++result.addedElib;
		}
	}

	for (const auto& input : options.addImage) {
		e2txt::BundleBinaryResource resource;
		bool alreadyExists = false;
		if (!BuildBinaryResourceFromInput(
				bundle.resources,
				e2txt::BundleResourceKind::Image,
				input,
				resource,
				alreadyExists,
				error)) {
			return false;
		}
		if (!alreadyExists) {
			AppendUniqueRootChildKey(bundle.rootChildKeys, resource.key);
			bundle.resources.push_back(std::move(resource));
			++result.addedImage;
		}
	}

	for (const auto& input : options.addAudio) {
		e2txt::BundleBinaryResource resource;
		bool alreadyExists = false;
		if (!BuildBinaryResourceFromInput(
				bundle.resources,
				e2txt::BundleResourceKind::Sound,
				input,
				resource,
				alreadyExists,
				error)) {
			return false;
		}
		if (!alreadyExists) {
			AppendUniqueRootChildKey(bundle.rootChildKeys, resource.key);
			bundle.resources.push_back(std::move(resource));
			++result.addedAudio;
		}
	}

	if (!PlanResourceCleanup(bundle, workspace, removedPaths, result, error)) return false;
	if (result.addedEcom + result.addedElib + result.addedImage + result.addedAudio +
		result.removedEcom + result.removedElib + result.removedImage + result.removedAudio > 0) {
		bundle.nativeBundleDigest.clear();
		bundle.nativeSourceBytes.clear();
		bundle.nativeSourceSnapshots.clear();
	}
	return true;
}

bool RemoveResourceFiles(const Result& result, std::string& error)
{
	for (const auto& path : result.removedResourceFiles) {
		std::error_code ec;
		std::filesystem::remove(path, ec);
		if (ec) {
			error = "remove_resource_file_failed: " + PathToUtf8(path) + " => " + ec.message();
			return false;
		}
	}
	return true;
}
} // namespace workspace_update
