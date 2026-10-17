#pragma once

#include <Windows.h>
#include <cstdint>
#include <string>
#include <vector>

namespace e2txt {

// 本机工作进程的双向消息管道；主进程使用异步 I/O，以统一截止时间防止卡死。
class WorkerMessagePipe {
public:
    WorkerMessagePipe() = default;
    ~WorkerMessagePipe();
    WorkerMessagePipe(const WorkerMessagePipe&) = delete;
    WorkerMessagePipe& operator=(const WorkerMessagePipe&) = delete;

    void CreateServer(const std::wstring& name);
    void Connect(HANDLE peer, ULONGLONG deadline);
    void OpenClient(const std::wstring& name);
    void Close() noexcept;
    // 同一条请求的写入和响应读取共用截止时间；客户端由父进程 Job 管理生存期。
    void SetDeadline(ULONGLONG deadline) { m_deadline = deadline; }
    void Write(const std::vector<std::uint8_t>& bytes);
    std::vector<std::uint8_t> Read();

private:
    DWORD Complete(OVERLAPPED& operation, BOOL completed, DWORD error);
    void Transfer(void* data, std::size_t size, bool writing);
    HANDLE m_pipe = INVALID_HANDLE_VALUE;
    HANDLE m_event = nullptr;
    HANDLE m_peer = nullptr; // 借用主进程持有的工作进程句柄。
    ULONGLONG m_deadline = 0;
};

} // namespace e2txt
