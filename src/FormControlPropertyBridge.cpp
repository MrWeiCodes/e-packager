#include "FormControlPropertyBridge.h"
#include "PathHelper.h"
#include "ELanguageEnvironment.h"
#include "SupportLibraryMetadataCodec.h"
#include "RuntimeLogger.h"

#include <Windows.h>
#include <atomic>
#include <memory>
#include <fstream>
#include <mutex>
#include <unordered_map>

namespace e2txt {
namespace {
using json = nlohmann::json;

json ReadMessage(const std::filesystem::path& path)
{
    std::ifstream input(path, std::ios::binary);
    return json::from_cbor(input);
}

void WriteMessage(const std::filesystem::path& path, const json& value)
{
    const auto bytes = json::to_cbor(value);
    std::ofstream output(path, std::ios::binary);
    output.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    output.flush();
    if (!output) throw std::runtime_error("property_worker_write_failed");
}
}

namespace {
#ifndef _WIN64
struct WorkerContext {
    std::unique_ptr<FormControlPropertyCodec> codec;
    std::string key;
    std::string explicitDirectory;
};

json ProcessRequest(const json& request, WorkerContext& context)
{
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    json response;
    try {
        const auto directory = request.value("e_directory", std::string());
        if (!directory.empty() && directory != context.explicitDirectory) {
            std::string error;
            if (!e_language_environment::SetExplicitDirectory(Utf8PathToPath(directory), error)) {
                throw std::runtime_error(error);
            }
            context.explicitDirectory = directory;
        }
        if (request.at("operation") == "library_metadata") {
            support_library_public_info::LibraryMetadata metadata;
            std::string error;
            response["ok"] = support_library_public_info::LoadSupportLibraryMetadata(
                Utf8PathToPath(request.at("path").get<std::string>()), metadata, error);
            response["metadata"] = metadata;
            response["error"] = error;
            return response;
        }
        const auto encodedContext = json::to_cbor(json{
            {"source", request.at("source")}, {"libraries", request.at("libraries")},
            {"directories", request.at("directories")}, {"restrict", request.at("restrict")},
            {"e_directory", directory}});
        const std::string key(encodedContext.begin(), encodedContext.end());
        if (!context.codec || context.key != key) {
            context.codec.reset();
            std::vector<std::filesystem::path> directories;
            for (const auto& directory : request.at("directories"))
                directories.push_back(Utf8PathToPath(directory.get<std::string>()));
            context.codec = std::make_unique<FormControlPropertyCodec>(request.at("source"),
                request.at("libraries").get<std::vector<FormControlSupportLibrary>>(),
                directories, request.at("restrict"), FormControlExecutionMode::InProcess);
            context.key = key;
        }
        auto& codec = *context.codec;
        struct ReleaseWindows {
            FormControlPropertyCodec& codec;
            ~ReleaseWindows() { codec.ReleaseProbeWindow(); }
        } release{codec};
        std::string error;
        const auto type = request.at("type").get<std::int32_t>();
        const std::string operation = request.at("operation");
        if (operation == "events") {
            std::vector<FormControlEventDefinition> events;
            response["ok"] = codec.ReadEvents(type, events, &error);
            response["events"] = events;
        } else if (operation == "decode") {
            std::vector<FormControlPropertyValue> values;
            FormControlPropertySemanticData semantic;
            response["ok"] = codec.Decode(type, request.at("data"), request.at("form"),
                request.at("unit"), values, &error, &semantic);
            response["values"] = values;
            response["semantic"] = semantic;
        } else if (operation == "apply") {
            std::vector<std::uint8_t> data;
            response["ok"] = codec.Apply(type, request.at("data"), request.at("form"),
                request.at("unit"), request.at("attributes"), data, &error,
                request.at("children").get<std::vector<FormControlPropertyXmlNode>>());
            response["data"] = data;
        } else {
            throw std::runtime_error("property_worker_operation_invalid");
        }
        response["error"] = error;
    } catch (const std::exception& exception) {
        response = {{"ok", false}, {"error", exception.what()}};
    }
    return response;
}
#endif
} // namespace

int RunFormControlWorker(const std::filesystem::path& requestPath, const std::filesystem::path& responsePath)
{
#ifdef _WIN64
    return 2;
#else
    WorkerContext context;
    WriteMessage(responsePath, ProcessRequest(ReadMessage(requestPath), context));
    return 0;
#endif
}


namespace {
// 同一工程复用属性 codec 和 DLL，每条请求结束后销毁临时探测窗口。
// 请求/响应通过文件传递 CBOR，事件负责同步，避免轮询或管道被支持库 stdout 干扰。
struct Handle {
    HANDLE value = nullptr;
    ~Handle() { Reset(); }
    void Reset(HANDLE next = nullptr) { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); value = next; }
};

std::wstring EventName(const std::filesystem::path& directory, const wchar_t* suffix)
{
    return L"Local\\" + directory.filename().wstring() + suffix;
}

std::filesystem::path FindWorker()
{
    std::wstring executable(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, executable.data(), static_cast<DWORD>(executable.size()));
    if (!length || length >= executable.size()) throw std::runtime_error("property_worker_executable_path_failed");
    executable.resize(length);
#ifndef _WIN64
    return executable;
#else
    const auto base = std::filesystem::path(executable).parent_path();
    for (const auto& candidate : {base / L"e-packager-x86.exe",
         base.parent_path().parent_path() / L"Win32" / base.filename() / L"e-packager.exe"}) {
        if (std::filesystem::is_regular_file(candidate)) return candidate;
    }
    throw std::runtime_error("property_worker_missing: place Win32 e-packager-x86.exe beside the x64 executable");
#endif
}

class WorkerSession {
public:
    ~WorkerSession() { Stop(); }

    bool Invoke(const json& request, json& response, std::string& error)
    {
        try {
            if (process.value && WaitForSingleObject(process.value, 0) != WAIT_TIMEOUT) Stop();
            if (!process.value) Start();
            // 每次响应包含递增编号，杜绝超时/崩溃后复用旧响应。
            const auto sequence = ++requestNumber;
            WriteMessage(directory / L"request.cbor", {{"sequence", sequence}, {"request", request}});
            if (!SetEvent(ready.value)) throw std::runtime_error("property_worker_signal_failed");
            const HANDLE handles[] = {done.value, process.value};
            const DWORD wait = WaitForMultipleObjects(2, handles, FALSE, 30000);
            if (wait != WAIT_OBJECT_0) {
                DWORD code = 0;
                GetExitCodeProcess(process.value, &code);
                error = (wait == WAIT_TIMEOUT ? "property_worker_timeout: " : "property_worker_failed: ") + std::to_string(code);
                Stop();
                return false;
            }
            const auto result = ReadMessage(directory / L"response.cbor");
            if (result.at("sequence").get<unsigned long long>() != sequence)
                throw std::runtime_error("property_worker_response_mismatch");
            response = result.at("response");
            return true;
        } catch (const std::exception& exception) {
            error = exception.what();
            Stop();
            return false;
        }
    }

    void Stop() noexcept
    {
        if (process.value) {
            if (stop.value) SetEvent(stop.value);
            if (WaitForSingleObject(process.value, 1000) != WAIT_OBJECT_0) {
                TerminateProcess(process.value, 1);
                WaitForSingleObject(process.value, 1000);
            }
        }
        process.Reset(); job.Reset(); ready.Reset(); done.Reset(); stop.Reset();
        if (!directory.empty()) {
            std::error_code ignored;
            std::filesystem::remove_all(directory, ignored);
            directory.clear();
        }
    }

    DWORD Pid() const { return pid; }
private:
    void Start()
    {
        const auto worker = FindWorker();
        static std::atomic<unsigned> serial = 0;
        const auto nextDirectory = std::filesystem::temp_directory_path() /
            (L"e-packager-property-" + std::to_wstring(GetCurrentProcessId()) + L"-" +
             std::to_wstring(GetTickCount64()) + L"-" + std::to_wstring(++serial));
        if (!std::filesystem::create_directory(nextDirectory)) throw std::runtime_error("property_worker_directory_exists");
        directory = nextDirectory;
        ready.Reset(CreateEventW(nullptr, FALSE, FALSE, EventName(directory, L"-request").c_str()));
        done.Reset(CreateEventW(nullptr, FALSE, FALSE, EventName(directory, L"-response").c_str()));
        stop.Reset(CreateEventW(nullptr, TRUE, FALSE, EventName(directory, L"-stop").c_str()));
        if (!ready.value || !done.value || !stop.value) throw std::runtime_error("property_worker_event_failed");
        // 父进程异常退出时也终止工作进程，避免第三方回调挂死后残留。
        job.Reset(CreateJobObjectW(nullptr, nullptr));
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!job.value || !SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
            throw std::runtime_error("property_worker_job_failed");
        auto command = L"\"" + worker.wstring() + L"\" --form-control-server \"" + directory.wstring() +
            L"\" " + std::to_wstring(GetCurrentProcessId());
        STARTUPINFOW startup{sizeof(startup)};
        PROCESS_INFORMATION created{};
        if (!CreateProcessW(worker.c_str(), command.data(), nullptr, nullptr, FALSE,
            CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr, nullptr, &startup, &created))
            throw std::runtime_error("property_worker_start_failed: " + std::to_string(GetLastError()));
        process.Reset(created.hProcess);
        Handle thread; thread.Reset(created.hThread);
        pid = created.dwProcessId;
        if (!AssignProcessToJobObject(job.value, process.value) || ResumeThread(thread.value) == static_cast<DWORD>(-1))
            throw std::runtime_error("property_worker_resume_failed: " + std::to_string(GetLastError()));
        runtime_logger::Write(runtime_logger::Level::Info,
            "property_worker_started: worker_pid=" + std::to_string(pid) + ", executable=" + PathToUtf8(worker));
    }
    Handle process, job, ready, done, stop;
    std::filesystem::path directory;
    unsigned long long requestNumber = 0;
    DWORD pid = 0;
};

struct BridgeState {
    std::mutex mutex;
    WorkerSession worker;
    std::unordered_map<std::string, json> cache;
};
BridgeState& State() { static BridgeState state; return state; }
} // namespace

int RunFormControlServer(const std::filesystem::path& directory, const std::uint32_t parentPid)
{
#ifdef _WIN64
    return 2;
#else
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    Handle parent, ready, done, stop;
    parent.Reset(OpenProcess(SYNCHRONIZE, FALSE, parentPid));
    ready.Reset(OpenEventW(SYNCHRONIZE, FALSE, EventName(directory, L"-request").c_str()));
    done.Reset(OpenEventW(EVENT_MODIFY_STATE, FALSE, EventName(directory, L"-response").c_str()));
    stop.Reset(OpenEventW(SYNCHRONIZE, FALSE, EventName(directory, L"-stop").c_str()));
    if (!parent.value || !ready.value || !done.value || !stop.value) return 2;
    const HANDLE handles[] = {parent.value, stop.value, ready.value};
    WorkerContext context;
    for (;;) {
        const DWORD wait = WaitForMultipleObjects(3, handles, FALSE, INFINITE);
        if (wait == WAIT_OBJECT_0 || wait == WAIT_OBJECT_0 + 1) return 0;
        if (wait != WAIT_OBJECT_0 + 2) return 2;
        try {
            const auto message = ReadMessage(directory / L"request.cbor");
            const auto response = ProcessRequest(message.at("request"), context);
            WriteMessage(directory / L"response.cbor", {{"sequence", message.at("sequence")}, {"response", response}});
            if (!SetEvent(done.value)) return 2;
        } catch (...) { return 2; }
    }
#endif
}

void ShutdownFormControlWorker() noexcept
{
    try {
        auto& state = State();
        std::lock_guard lock(state.mutex);
        state.worker.Stop();
        state.cache.clear();
    } catch (...) {}
}

bool InvokeFormControlWorker(const json& request, json& response, std::string* error)
{
    auto& state = State();
    auto effectiveRequest = request;
    effectiveRequest["e_directory"] = PathToUtf8(e_language_environment::GetExplicitDirectory());
    const auto encoded = json::to_cbor(effectiveRequest);
    const std::string key(encoded.begin(), encoded.end());
    std::lock_guard lock(state.mutex);
    if (const auto found = state.cache.find(key); found != state.cache.end()) {
        response = found->second;
    } else {
        const ULONGLONG start = GetTickCount64();
        std::string detail;
        const bool transported = state.worker.Invoke(effectiveRequest, response, detail);
        const auto elapsed = GetTickCount64() - start;
        const bool ok = transported && response.value("ok", false);
        runtime_logger::Write(ok ? runtime_logger::Level::Info : runtime_logger::Level::Warning,
            "property_worker_request: operation=" + request.value("operation", std::string()) +
            ", type=" + std::to_string(request.value("type", 0)) +
            ", unit=" + std::to_string(request.value("unit", 0u)) +
            ", source=" + request.value("source", std::string()) +
            ", worker_pid=" + std::to_string(state.worker.Pid()) +
            ", elapsed_ms=" + std::to_string(elapsed) + ", ok=" + (ok ? "true" : "false") +
            ", error=" + (transported ? response.value("error", std::string()) : detail));
        if (!transported) { if (error) *error = detail; return false; }
        // 确定的属性失败也可复用；进程崩溃/超时不缓存，后续请求启动新工作进程。
        state.cache.emplace(key, response);
    }
    const bool ok = response.value("ok", false);
    if (error) *error = ok ? std::string() : response.value("error", "property_worker_failed");
    return ok;
}
} // namespace e2txt
