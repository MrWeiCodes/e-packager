#include "RuntimeLogger.h"
#include "PathHelper.h"

#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <sstream>

namespace runtime_logger {
namespace {

struct PreserveLastError {
    DWORD value = GetLastError();
    ~PreserveLastError() { SetLastError(value); }
};

struct FileHandle {
    HANDLE value = INVALID_HANDLE_VALUE;
    ~FileHandle() { if (value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    void Reset() { if (value != INVALID_HANDLE_VALUE) CloseHandle(value); value = INVALID_HANDLE_VALUE; }
};

struct FileLock {
    HANDLE file;
    OVERLAPPED position{};
    bool locked = false;
    explicit FileLock(HANDLE handle) : file(handle) {
        locked = LockFileEx(file, LOCKFILE_EXCLUSIVE_LOCK, 0, MAXDWORD, MAXDWORD, &position) != FALSE;
    }
    ~FileLock() { if (locked) UnlockFileEx(file, 0, MAXDWORD, MAXDWORD, &position); }
};

DWORD ResetTraceLog()
{
    // 仅清空已有跟踪日志，帮助/参数错误等不产生跟踪的命令不创建空文件。
    const FileHandle file{CreateFileW(L"e2txt_trace.log", GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr)};
    if (file.value == INVALID_HANDLE_VALUE) {
        const DWORD error = GetLastError();
        return error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND ? ERROR_SUCCESS : error;
    }
    const FileLock lock(file.value);
    if (!lock.locked) return GetLastError();
    return SetEndOfFile(file.value) ? ERROR_SUCCESS : GetLastError();
}

struct LoggerState {
    std::mutex mutex;
    FileHandle file;
    std::vector<std::filesystem::path> candidates;
    std::size_t candidateIndex = 0;
    std::string failures;
    bool initialized = false;
    bool announce = false;
    bool locationReported = false;
    bool resetPending = false;
    bool traceResetPending = false;
};

LoggerState& State()
{
    static LoggerState state;
    return state;
}

std::filesystem::path EnvironmentDirectory(const wchar_t* name)
{
    const DWORD required = GetEnvironmentVariableW(name, nullptr, 0);
    if (required <= 1) return {};
    std::wstring value(required, L'\0');
    const DWORD length = GetEnvironmentVariableW(name, value.data(), required);
    if (length == 0 || length >= required) return {};
    value.resize(length);
    return value;
}

void InitializeCandidates(LoggerState& state)
{
    const auto append = [&](const std::filesystem::path& directory) {
        if (directory.empty()) return;
        std::error_code error;
        auto path = std::filesystem::absolute(directory / L"e-packager.log", error).lexically_normal();
        if (error) return;
        for (const auto& existing : state.candidates) if (existing == path) return;
        state.candidates.push_back(std::move(path));
    };
    std::error_code error;
    append(std::filesystem::current_path(error));
    std::wstring executable(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, executable.data(), static_cast<DWORD>(executable.size()));
    if (length != 0 && length < executable.size()) {
        executable.resize(length);
        append(std::filesystem::path(executable).parent_path());
    }
    const auto local = EnvironmentDirectory(L"LOCALAPPDATA");
    if (!local.empty()) append(local / L"e-packager" / L"logs");
    const auto temporary = std::filesystem::temp_directory_path(error);
    if (!error) append(temporary / L"e-packager" / L"logs");
    state.initialized = true;
}

DWORD AppendRecord(FileHandle& file, const std::filesystem::path& path, std::string bytes, const bool reset = false)
{
    // 单次进程复用日志句柄；每条记录仍即时写入并加跨进程锁，故障时不丢失缓冲日志。
    if (file.value == INVALID_HANDLE_VALUE) {
        std::error_code directoryError;
        std::filesystem::create_directories(path.parent_path(), directoryError);
        if (directoryError) return static_cast<DWORD>(directoryError.value());
        file.value = CreateFileW(path.c_str(), GENERIC_READ | FILE_APPEND_DATA | (reset ? GENERIC_WRITE : 0),
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
            OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file.value == INVALID_HANDLE_VALUE) return GetLastError();
    }

    // 主进程与 x86 辅助进程共享日志，锁定追加过程以保持 BOM 和每条记录完整。
    const FileLock lock(file.value);
    if (!lock.locked) return GetLastError();
    // 清空和首条写入共用文件锁，辅助进程始终只追加。
    if (reset) {
        LARGE_INTEGER beginning{};
        if (!SetFilePointerEx(file.value, beginning, nullptr, FILE_BEGIN) || !SetEndOfFile(file.value)) return GetLastError();
    }
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file.value, &size)) return GetLastError();
    if (size.QuadPart == 0) bytes.insert(0, "\xEF\xBB\xBF");
    if (bytes.size() > (std::numeric_limits<DWORD>::max)()) return ERROR_FILE_TOO_LARGE;
    // 首次清空时句柄带 GENERIC_WRITE；持久复用时必须在锁内移到共享日志末尾，
    // 否则辅助进程追加后，主进程仍会从自己的旧偏移覆盖新记录。
    LARGE_INTEGER end{};
    if (!SetFilePointerEx(file.value, end, nullptr, FILE_END)) return GetLastError();
    DWORD written = 0;
    if (!WriteFile(file.value, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr)) return GetLastError();
    return written == bytes.size() ? ERROR_SUCCESS : ERROR_WRITE_FAULT;
}

const char* LevelName(const Level level)
{
    switch (level) {
    case Level::Warning: return "WARN";
    case Level::Error: return "ERROR";
    default: return "INFO";
    }
}

}  // namespace

void BeginSession() noexcept
{
    const PreserveLastError preserve;
    try {
        auto& state = State();
        const std::lock_guard lock(state.mutex);
        state.announce = true;
        state.file.Reset();
        state.resetPending = true;
        state.traceResetPending = true;
    } catch (...) {}
}

void Write(const Level level, const std::string_view message) noexcept
{
    const PreserveLastError preserve;
    try {
        auto& state = State();
        const std::lock_guard lock(state.mutex);
        if (!state.initialized) InitializeCandidates(state);
        std::string traceResetError;
        if (state.traceResetPending) {
            state.traceResetPending = false;
            const DWORD error = ResetTraceLog();
            if (error != ERROR_SUCCESS) {
                traceResetError = "trace_log_reset_failed: path=e2txt_trace.log, " + DescribeWin32Error(error);
                if (state.announce) std::cerr << traceResetError << std::endl;
            }
        }
        SYSTEMTIME now{};
        GetLocalTime(&now);
        std::ostringstream line;
        line << std::setfill('0') << std::setw(4) << now.wYear << '-'
            << std::setw(2) << now.wMonth << '-' << std::setw(2) << now.wDay << ' '
            << std::setw(2) << now.wHour << ':' << std::setw(2) << now.wMinute << ':'
            << std::setw(2) << now.wSecond << '.' << std::setw(3) << now.wMilliseconds
            << " [" << LevelName(level) << "] [pid=" << GetCurrentProcessId()
            << (sizeof(void*) == 8 ? " x64] " : " x86] ");
        const auto prefix = line.str();
        for (const char ch : message) {
            if (ch == '\r') line << "\\r";
            else if (ch == '\n') line << "\\n";
            else line << ch;
        }
        line << "\r\n";
        if (!traceResetError.empty()) line << prefix << traceResetError << "\r\n";
        for (; state.candidateIndex < state.candidates.size(); ++state.candidateIndex) {
            const auto& path = state.candidates[state.candidateIndex];
            const DWORD error = AppendRecord(state.file, path, line.str(), state.resetPending);
            if (error == ERROR_SUCCESS) {
                state.resetPending = false;
                if (!state.locationReported) {
                    if (!state.failures.empty()) {
                        const auto detail = "log_fallback: destination=" + PathToUtf8(path) + ", failures=" + state.failures;
                        AppendRecord(state.file, path, prefix + detail + "\r\n");
                        if (state.announce) std::cerr << detail << std::endl;
                    }
                    if (state.announce) std::cerr << WideToUtf8Text(L"日志文件: ") << PathToUtf8(path) << std::endl;
                    state.locationReported = true;
                }
                return;
            }
            state.file.Reset();
            if (!state.failures.empty()) state.failures += "; ";
            state.failures += PathToUtf8(path) + " (" + DescribeWin32Error(error) + ")";
            state.locationReported = false;
        }
        if (state.announce && !state.locationReported) {
            std::cerr << WideToUtf8Text(L"日志写入失败: ") << state.failures << std::endl;
            state.locationReported = true;
        }
    }
    catch (...) {
        // 诊断日志不能影响解包、回包和工作进程协议。
    }
}

std::string DescribeWin32Error(const DWORD errorCode)
{
    const PreserveLastError preserve;
    std::string result = "Win32 error=" + std::to_string(errorCode);
    wchar_t buffer[2048]{};
    const DWORD length = FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr, errorCode, 0, buffer, static_cast<DWORD>(sizeof(buffer) / sizeof(buffer[0])), nullptr);
    if (length != 0) {
        std::wstring detail(buffer, length);
        while (!detail.empty() && (detail.back() == L'\r' || detail.back() == L'\n' || detail.back() == L' ')) {
            detail.pop_back();
        }
        result += ": " + WideToUtf8Text(detail);
    }
    return result;
}

void LogLibrarySearch(const std::string_view context, const std::string_view libraryName,
    const std::filesystem::path& sourcePath,
    const std::vector<std::filesystem::path>& candidates)
{
    const PreserveLastError preserve;
    std::ostringstream message;
    message << "support_library_search: context=" << context << ", name=" << libraryName
        << ", source=" << PathToUtf8(sourcePath) << ", candidates=[";
    for (std::size_t index = 0; index < candidates.size(); ++index) {
        if (index != 0) message << ", ";
        std::error_code error;
        const auto absolute = std::filesystem::absolute(candidates[index], error);
        message << '"' << PathToUtf8(error ? candidates[index] : absolute.lexically_normal()) << '"';
    }
    message << ']';
    Write(Level::Info, message.str());
}

}  // namespace runtime_logger
