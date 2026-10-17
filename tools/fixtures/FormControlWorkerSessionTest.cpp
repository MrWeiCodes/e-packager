// x64 驱动链接实际桥接器，验证复用、失败恢复、进程回收；不调用易语言编译器。
#include "FormControlPropertyBridge.h"
#include "ELanguageEnvironment.h"
#include "PathHelper.h"
#include "RuntimeLogger.h"
#include <iostream>
#include <stdexcept>

std::string WideToUtf8Text(const std::wstring& value)
{
    if (value.empty()) return {};
    const int count = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    std::string result(count, '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), count, nullptr, nullptr);
    return result;
}
std::string PathToUtf8(const std::filesystem::path& path) { return WideToUtf8Text(path.wstring()); }
namespace e_language_environment {
std::filesystem::path GetExplicitDirectory() { return {}; }
}
static void Require(bool ok, const std::string& message) { if (!ok) throw std::runtime_error(message); }

int wmain(int argc, wchar_t* argv[])
{
    try {
        Require(argc == 3, "usage: driver fixture.fne crash|timeout|normal|parent-exit");
        runtime_logger::BeginSession();
        runtime_logger::Write(runtime_logger::Level::Info, "worker_test_begin");
        using nlohmann::json;
        const json metadata{{"operation", "library_metadata"}, {"path", PathToUtf8(std::filesystem::absolute(argv[1]))}};
        json response;
        std::string error;
        const std::wstring mode = argv[2];
        if (mode == L"crash" || mode == L"timeout") {
            SetEnvironmentVariableW(L"E_PACKAGER_TEST_WORKER_FAILURE", mode.c_str());
            Require(!e2txt::InvokeFormControlWorker(metadata, response, &error), "bad worker unexpectedly succeeded");
            Require(error.find(mode == L"timeout" ? "property_worker_timeout" : "property_worker_failed") != std::string::npos, error);
        }
        SetEnvironmentVariableW(L"E_PACKAGER_TEST_WORKER_FAILURE", nullptr);
        Require(e2txt::InvokeFormControlWorker(metadata, response, &error), error);
        Require(response.at("metadata").at("name") == "WorkerFailureTest", "metadata mismatch");
        if (mode == L"parent-exit") ExitProcess(0); // 跳过析构，验证 Job 清理。
        // 多个不同请求复用同一进程，普通失败后继续服务。
        auto invalid = metadata;
        invalid["operation"] = "invalid";
        Require(!e2txt::InvokeFormControlWorker(invalid, response, &error), "invalid request accepted");
        const auto expectedError = error;
        error.clear();
        Require(!e2txt::InvokeFormControlWorker(invalid, response, &error) && error == expectedError, "cached failure changed result");
        for (int index = 0; index < 5; ++index) {
            auto distinct = metadata;
            distinct["probe"] = index;
            Require(e2txt::InvokeFormControlWorker(distinct, response, &error), error);
        }
        e2txt::ShutdownFormControlWorker();
        std::cout << "PASS persistent requests and cleanup\n";
        return 0;
    } catch (const std::exception& error) {
        e2txt::ShutdownFormControlWorker();
        std::cerr << error.what() << '\n';
        return 1;
    }
}
