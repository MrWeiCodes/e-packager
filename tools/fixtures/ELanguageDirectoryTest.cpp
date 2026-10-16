// 用可控的注册表读取结果验证实际目录探测器，不修改本机注册表。
#include "ELanguageEnvironment.h"
#include "PathHelper.h"
#include <iostream>

namespace {
std::filesystem::path registeredDirectory;
}

std::string WideToUtf8Text(const std::wstring& value)
{
    if (value.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    std::string result(size, '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size, nullptr, nullptr);
    return result;
}
std::string PathToUtf8(const std::filesystem::path& path) { return WideToUtf8Text(path.wstring()); }
std::vector<std::filesystem::path> GetRegisteredEplOpenCommandBaseDirs()
{
    return registeredDirectory.empty() ? std::vector<std::filesystem::path>{} : std::vector{registeredDirectory};
}
std::vector<std::filesystem::path> GetRegisteredEplOpenCommandExecutablePaths() { return {}; }

int wmain(int argc, wchar_t* argv[])
{
    if (argc != 3 && argc != 4) return 2;
    if (std::wstring_view(argv[1]) != L"-") registeredDirectory = argv[1];
    const auto actual = e_language_environment::GetInstallationDirectory();
    const std::filesystem::path expected = std::wstring_view(argv[2]) == L"-" ? std::filesystem::path{} : argv[2];
    if (actual.empty() && expected.empty()) return 0;
    std::error_code error;
    if (!std::filesystem::equivalent(actual, expected, error)) {
        std::cerr << "expected=" << PathToUtf8(expected) << ", actual=" << PathToUtf8(actual) << '\n';
        return 1;
    }
    std::cout << PathToUtf8(actual) << '\n';
    if (argc == 4) {
        const auto executable = e_language_environment::GetInstallationExecutablePath();
        if (!std::filesystem::equivalent(executable, std::filesystem::path(argv[3]), error)) {
            std::cerr << "expected executable=" << PathToUtf8(argv[3])
                << ", actual=" << PathToUtf8(executable) << '\n';
            return 1;
        }
    }
    return 0;
}
