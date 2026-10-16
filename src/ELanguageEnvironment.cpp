#include "ELanguageEnvironment.h"
#include "PathHelper.h"
#include "RuntimeLogger.h"

#include <algorithm>
#include <cwctype>
#include <unordered_set>

namespace e_language_environment {
namespace {

std::filesystem::path explicitDirectory;

std::filesystem::path Absolute(const std::filesystem::path& path)
{
    std::error_code error;
    const auto absolute = std::filesystem::absolute(path, error);
    return (error ? path : absolute).lexically_normal();
}

void AppendUnique(std::vector<std::filesystem::path>& paths, const std::filesystem::path& path)
{
    if (path.empty()) return;
    const auto normalized = path.lexically_normal();
    if (std::find(paths.begin(), paths.end(), normalized) == paths.end()) paths.push_back(normalized);
}

std::filesystem::path ExecutableDirectory()
{
    std::wstring buffer(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (length == 0 || length >= buffer.size()) return {};
    buffer.resize(length);
    return std::filesystem::path(buffer).parent_path();
}

std::filesystem::path EnvironmentPath()
{
    const DWORD required = GetEnvironmentVariableW(L"E_PACKAGER_EIDE", nullptr, 0);
    if (required <= 1) return {};
    std::wstring value(required, L'\0');
    const DWORD written = GetEnvironmentVariableW(L"E_PACKAGER_EIDE", value.data(), required);
    if (written == 0 || written >= required) return {};
    value.resize(written);
    return std::filesystem::path(value);
}

std::filesystem::path DiscoverDirectory()
{
    std::vector<std::pair<std::filesystem::path, std::string>> candidates;
    auto environment = EnvironmentPath();
    if (!environment.empty()) {
        auto extension = environment.extension().wstring();
        std::transform(extension.begin(), extension.end(), extension.begin(), towlower);
        if (extension == L".exe") environment = environment.parent_path();
        candidates.emplace_back(environment, "E_PACKAGER_EIDE");
    }
    for (const auto& path : GetRegisteredEplOpenCommandBaseDirs()) candidates.emplace_back(path, "registry");
    const auto executableDirectory = ExecutableDirectory();
    if (!executableDirectory.empty()) {
        candidates.emplace_back(executableDirectory, "executable_directory");
        candidates.emplace_back(executableDirectory.parent_path(), "executable_parent");
    }
    for (const auto& [path, source] : candidates) {
        std::string error;
        const auto directory = Absolute(path);
        if (!ValidateDirectory(directory, error)) {
            runtime_logger::Write(runtime_logger::Level::Warning,
                "e_language_directory_rejected: source=" + source + ", " + error);
            continue;
        }
        runtime_logger::Write(runtime_logger::Level::Info,
            "e_language_directory_selected: source=" + source + ", directory=" + PathToUtf8(directory));
        return directory;
    }
    runtime_logger::Write(runtime_logger::Level::Warning,
        "e_language_directory_not_found: no valid installation; use --e-dir <directory containing lib, static_lib, ecom>");
    return {};
}

}  // namespace

bool ValidateDirectory(const std::filesystem::path& directory, std::string& error)
{
    error.clear();
    std::string missing;
    for (const auto* name : {L"lib", L"static_lib", L"ecom"}) {
        std::error_code ec;
        if (directory.empty() || !std::filesystem::is_directory(directory / name, ec)) {
            if (!missing.empty()) missing += ",";
            missing += WideToUtf8Text(name);
            if (ec && ec != std::errc::no_such_file_or_directory) {
                missing += " (" + runtime_logger::DescribeWin32Error(static_cast<DWORD>(ec.value())) + ")";
            }
        }
    }
    if (missing.empty()) return true;
    error = "e_language_directory_invalid: directory=" + PathToUtf8(directory) + ", missing_directories=[" + missing + "]";
    return false;
}

bool SetExplicitDirectory(const std::filesystem::path& directory, std::string& error)
{
    if (directory.empty()) {
        error = "e_language_directory_required: --e-dir <directory>";
        return false;
    }
    const auto absolute = Absolute(directory);
    if (!ValidateDirectory(absolute, error)) {
        runtime_logger::Write(runtime_logger::Level::Error, error);
        return false;
    }
    explicitDirectory = absolute;
    runtime_logger::Write(runtime_logger::Level::Info,
        "e_language_directory_selected: source=--e-dir, directory=" + PathToUtf8(absolute));
    return true;
}

std::filesystem::path GetExplicitDirectory() { return explicitDirectory; }

std::filesystem::path GetInstallationDirectory()
{
    if (!explicitDirectory.empty()) return explicitDirectory;
    static const auto discovered = DiscoverDirectory();
    return discovered;
}

std::filesystem::path GetInstallationExecutablePath()
{
    const auto directory = GetInstallationDirectory();
    if (directory.empty()) return {};
    std::error_code error;
    const auto environment = EnvironmentPath();
    if (!environment.empty() && std::filesystem::equivalent(environment.parent_path(), directory, error) &&
        std::filesystem::is_regular_file(environment, error)) return Absolute(environment);
    for (const auto& executable : GetRegisteredEplOpenCommandExecutablePaths()) {
        if (std::filesystem::equivalent(executable.parent_path(), directory, error) &&
            std::filesystem::is_regular_file(executable, error)) return executable;
    }
    if (std::filesystem::is_regular_file(directory / L"e.exe", error)) return directory / L"e.exe";
    std::vector<std::filesystem::path> matches;
    for (const auto& entry : std::filesystem::directory_iterator(directory, error)) {
        auto name = entry.path().filename().wstring();
        std::transform(name.begin(), name.end(), name.begin(), towlower);
        if (name.size() > 5 && name.front() == L'e' && name.ends_with(L".exe") &&
            name[1] >= L'0' && name[1] <= L'9' &&
            std::all_of(name.begin() + 1, name.end() - 4, [](wchar_t ch) { return (ch >= L'0' && ch <= L'9') || ch == L'.'; }) &&
            entry.is_regular_file(error)) matches.push_back(entry.path());
    }
    std::sort(matches.begin(), matches.end());
    if (!matches.empty()) return matches.back();
    runtime_logger::Write(runtime_logger::Level::Warning,
        "e_language_executable_not_found: directory=" + PathToUtf8(directory));
    return {};
}

bool ConfigureCommandLine(const int argc, char* argv[], std::vector<char*>& arguments, std::string& error)
{
    arguments.clear();
    arguments.push_back(argv[0]);
    std::filesystem::path requested;
    bool seen = false;
    // 其余带值选项原样成对保留，避免把密码或资源名中的 --e-dir 当成选项。
    const std::unordered_set<std::string> flags = {
        "--main-only", "--compiler-input", "--compile-check", "--compile-static", "--force",
        "--no-pdb", "--dll", "--blackmoon", "--legacy-blackmoon", "--help", "--version", "--update"
    };
    for (int index = 1; index < argc; ++index) {
        const std::string option = argv[index];
        if (option == "--e-dir" || option.starts_with("--e-dir=")) {
            if (seen) { error = "duplicate_e_language_directory_option"; return false; }
            seen = true;
            std::string value;
            if (option == "--e-dir") {
                if (index + 1 >= argc || std::string_view(argv[index + 1]).starts_with("--")) {
                    error = "e_language_directory_required: --e-dir <directory>";
                    return false;
                }
                value = argv[++index];
            } else value = option.substr(8);
            requested = std::filesystem::path(value);
            continue;
        }
        arguments.push_back(argv[index]);
        if ((option.starts_with("--") || option == "-D") && option.find('=') == std::string::npos &&
            !flags.contains(option) && index + 1 < argc) {
            arguments.push_back(argv[++index]);
        }
    }
    if (seen && !SetExplicitDirectory(requested, error)) return false;
    arguments.push_back(nullptr);
    return true;
}

std::vector<std::filesystem::path> BuildSupportLibraryCandidates(
    const std::filesystem::path& sourcePath, const std::filesystem::path& libraryFile,
    const std::vector<std::filesystem::path>& searchDirectories, const bool restrictSearch,
    const std::filesystem::path& resolvedPath)
{
    std::vector<std::filesystem::path> candidates;
    if (libraryFile.empty()) return candidates;
    std::vector<std::filesystem::path> variants;
    if (libraryFile.has_extension()) {
        variants.push_back(libraryFile);
        auto extension = libraryFile.extension().wstring();
        std::transform(extension.begin(), extension.end(), extension.begin(), towlower);
        if (extension == L".fne") variants.emplace_back(libraryFile.wstring() + L".dll");
    } else {
        for (const auto* extension : {L".fne", L".fne.dll", L".fnr", L".dll", L""}) {
            variants.emplace_back(libraryFile.wstring() + extension);
        }
    }
    const auto appendRoot = [&](const std::filesystem::path& root, const bool ancestors) {
        if (root.empty()) return;
        for (const auto& variant : variants) {
            const auto relative = variant.is_absolute() ? variant.filename() : variant;
            AppendUnique(candidates, root / relative);
            AppendUnique(candidates, root / L"lib" / relative.filename());
            if (ancestors) {
                auto parent = root.parent_path();
                while (!parent.empty()) {
                    AppendUnique(candidates, parent / L"lib" / relative);
                    if (parent == parent.root_path()) break;
                    parent = parent.parent_path();
                }
            }
        }
    };
    if (restrictSearch) {
        for (const auto& directory : searchDirectories) appendRoot(directory, false);
    } else if (!explicitDirectory.empty()) {
        for (const auto& variant : variants) AppendUnique(candidates, explicitDirectory / L"lib" / variant.filename());
    } else {
        AppendUnique(candidates, resolvedPath);
        for (const auto& directory : searchDirectories) appendRoot(directory, false);
        if (libraryFile.is_absolute()) {
            for (const auto& variant : variants) AppendUnique(candidates, variant);
        } else {
            // 先探测并记录安装，工程自带开发支持库仍保留原有搜索优先级。
            const auto installation = GetInstallationDirectory();
            if (!sourcePath.empty()) appendRoot(sourcePath.parent_path(), true);
            std::error_code error;
            appendRoot(std::filesystem::current_path(error), true);
            appendRoot(ExecutableDirectory(), true);
            if (!installation.empty()) appendRoot(installation, false);
        }
    }
    // FNR 运行库可能没有命令表；跨所有允许的目录优先查找开发库，
    // 避免工程旁或旧 resolvedPath 中的 FNR 遮蔽安装目录中的 FNE。
    // 同类候选保留原顺序，且不会扩大 --e-dir 或目标架构限定的搜索范围。
    std::stable_partition(candidates.begin(), candidates.end(), [](const auto& path) {
        auto extension = path.extension().wstring();
        std::transform(extension.begin(), extension.end(), extension.begin(), towlower);
        return extension != L".fnr";
    });
    return candidates;
}

}  // namespace e_language_environment
