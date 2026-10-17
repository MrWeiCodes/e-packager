#include "WorkerMessagePipe.h"

#include <algorithm>
#include <stdexcept>

namespace e2txt {
namespace {
// 大于单项属性的 64 MiB 限制，允许 CBOR 数组膨胀及属性集合；拒绝损坏的帧长度。
constexpr std::uint64_t kMaxMessageSize = 256ull * 1024 * 1024;
constexpr DWORD kChunkSize = 64 * 1024;

[[noreturn]] void PipeError(const DWORD error)
{
    throw std::runtime_error("property_worker_failed: pipe Win32 error=" + std::to_string(error));
}
}

WorkerMessagePipe::~WorkerMessagePipe() { Close(); }

void WorkerMessagePipe::Close() noexcept
{
    if (m_pipe != INVALID_HANDLE_VALUE) CloseHandle(m_pipe);
    if (m_event) CloseHandle(m_event);
    m_pipe = INVALID_HANDLE_VALUE;
    m_event = nullptr;
    m_peer = nullptr;
}

void WorkerMessagePipe::CreateServer(const std::wstring& name)
{
    Close();
    m_pipe = CreateNamedPipeW(name.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED |
        FILE_FLAG_FIRST_PIPE_INSTANCE, PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT |
        PIPE_REJECT_REMOTE_CLIENTS, 1, kChunkSize, kChunkSize, 0, nullptr);
    if (m_pipe == INVALID_HANDLE_VALUE) PipeError(GetLastError());
    m_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!m_event) PipeError(GetLastError());
}

DWORD WorkerMessagePipe::Complete(OVERLAPPED& operation, const BOOL completed, const DWORD error)
{
    if (!completed && error != ERROR_IO_PENDING) PipeError(error);
    if (!completed) {
        const auto now = GetTickCount64();
        const DWORD remaining = now >= m_deadline ? 0 : static_cast<DWORD>((std::min)(m_deadline - now, ULONGLONG{30000}));
        const HANDLE handles[] = {m_event, m_peer};
        const DWORD wait = WaitForMultipleObjects(2, handles, FALSE, remaining);
        if (wait != WAIT_OBJECT_0) {
            const DWORD waitError = GetLastError();
            // 等待取消完成后才允许栈上的 OVERLAPPED 和缓冲区释放。
            CancelIoEx(m_pipe, &operation);
            DWORD ignored = 0;
            GetOverlappedResult(m_pipe, &operation, &ignored, TRUE);
            if (wait == WAIT_TIMEOUT) throw std::runtime_error("property_worker_timeout: pipe I/O");
            if (wait == WAIT_OBJECT_0 + 1) {
                DWORD code = 0;
                GetExitCodeProcess(m_peer, &code);
                throw std::runtime_error("property_worker_failed: " + std::to_string(code));
            }
            PipeError(waitError);
        }
    }
    DWORD transferred = 0;
    if (!GetOverlappedResult(m_pipe, &operation, &transferred, FALSE)) PipeError(GetLastError());
    return transferred;
}

void WorkerMessagePipe::Connect(HANDLE peer, const ULONGLONG deadline)
{
    m_peer = peer;
    m_deadline = deadline;
    OVERLAPPED operation{};
    operation.hEvent = m_event;
    ResetEvent(m_event);
    const BOOL completed = ConnectNamedPipe(m_pipe, &operation);
    const DWORD error = completed ? ERROR_SUCCESS : GetLastError();
    if (error != ERROR_PIPE_CONNECTED) (void)Complete(operation, completed, error);
}

void WorkerMessagePipe::OpenClient(const std::wstring& name)
{
    Close();
    m_pipe = CreateFileW(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (m_pipe == INVALID_HANDLE_VALUE) PipeError(GetLastError());
}

void WorkerMessagePipe::Transfer(void* data, std::size_t size, const bool writing)
{
    auto* cursor = static_cast<std::uint8_t*>(data);
    while (size != 0) {
        const auto count = static_cast<DWORD>((std::min)(size, static_cast<std::size_t>(kChunkSize)));
        DWORD transferred = 0;
        OVERLAPPED operation{};
        operation.hEvent = m_event;
        if (m_event) {
            if (GetTickCount64() >= m_deadline) throw std::runtime_error("property_worker_timeout: pipe I/O");
            ResetEvent(m_event);
        }
        const BOOL completed = writing
            ? WriteFile(m_pipe, cursor, count, &transferred, m_event ? &operation : nullptr)
            : ReadFile(m_pipe, cursor, count, &transferred, m_event ? &operation : nullptr);
        const DWORD error = completed ? ERROR_SUCCESS : GetLastError();
        if (m_event) transferred = Complete(operation, completed, error);
        else if (!completed) PipeError(error);
        if (transferred == 0) PipeError(ERROR_BROKEN_PIPE);
        cursor += transferred;
        size -= transferred;
    }
}

void WorkerMessagePipe::Write(const std::vector<std::uint8_t>& bytes)
{
    std::uint64_t size = bytes.size();
    if (size == 0 || size > kMaxMessageSize) throw std::runtime_error("property_worker_message_size_invalid");
    Transfer(&size, sizeof(size), true);
    Transfer(const_cast<std::uint8_t*>(bytes.data()), bytes.size(), true);
}

std::vector<std::uint8_t> WorkerMessagePipe::Read()
{
    std::uint64_t size = 0;
    Transfer(&size, sizeof(size), false);
    if (size == 0 || size > kMaxMessageSize) throw std::runtime_error("property_worker_message_size_invalid");
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(size));
    Transfer(bytes.data(), bytes.size(), false);
    return bytes;
}

} // namespace e2txt
