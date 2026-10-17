// 管道边界回归：大帧/连续帧、损坏长度、截断响应以及读写超时取消。
#include "WorkerMessagePipe.h"
#include <exception>
#include <iostream>
#include <stdexcept>
#include <thread>

using e2txt::WorkerMessagePipe;

static void Require(bool ok, const char* message)
{
    if (!ok) throw std::runtime_error(message);
}

static std::wstring PipeName()
{
    static unsigned sequence = 0;
    return L"\\\\.\\pipe\\e-packager-pipe-test-" + std::to_wstring(GetCurrentProcessId()) + L"-" + std::to_wstring(++sequence);
}

static HANDLE PeerProcess()
{
    struct Process {
        HANDLE value = OpenProcess(SYNCHRONIZE, FALSE, GetCurrentProcessId());
        ~Process() { CloseHandle(value); }
    };
    static Process process;
    return process.value;
}

static void RoundTrip()
{
    const auto name = PipeName();
    WorkerMessagePipe server;
    server.CreateServer(name);
    std::exception_ptr failure;
    std::jthread client([&] {
        try {
            WorkerMessagePipe pipe;
            pipe.OpenClient(name);
            for (unsigned i = 0; i < 5; ++i) pipe.Write(pipe.Read());
            (void)pipe.Read(); // 等待父端确认已读取最后一帧，避免关闭时丢弃管道中的字节。
        } catch (...) { failure = std::current_exception(); }
    });
    try {
        server.Connect(PeerProcess(), GetTickCount64() + 5000);
        for (const std::size_t size : {1u, 65535u, 65536u, 65537u, 3u * 1024 * 1024}) {
            std::vector<std::uint8_t> bytes(size);
            for (std::size_t i = 0; i < size; ++i) bytes[i] = static_cast<std::uint8_t>(i * 37 + size);
            server.SetDeadline(GetTickCount64() + 5000);
            server.Write(bytes);
            Require(server.Read() == bytes, "roundtrip bytes changed");
        }
        server.Write({1});
    } catch (...) {
        server.Close();
        client.join();
        throw;
    }
    client.join();
    if (failure) std::rethrow_exception(failure);
}

static void MalformedFrame(const std::uint64_t size)
{
    const auto name = PipeName();
    WorkerMessagePipe server;
    server.CreateServer(name);
    std::jthread client([&] {
        const HANDLE pipe = CreateFileW(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
        DWORD written = 0;
        WriteFile(pipe, &size, sizeof(size), &written, nullptr);
        FlushFileBuffers(pipe); // 等待头部被消费后再关闭，截断测试才真正覆盖半帧读取。
        CloseHandle(pipe);
    });
    server.Connect(PeerProcess(), GetTickCount64() + 5000);
    bool rejected = false;
    try { (void)server.Read(); } catch (const std::exception&) { rejected = true; }
    server.Close();
    client.join();
    Require(rejected, "malformed frame accepted");
}

static void Timeout(const bool writing)
{
    const auto name = PipeName();
    WorkerMessagePipe server;
    server.CreateServer(name);
    std::jthread client([&] {
        WorkerMessagePipe pipe;
        pipe.OpenClient(name);
        Sleep(250);
    });
    server.Connect(PeerProcess(), GetTickCount64() + 5000);
    server.SetDeadline(GetTickCount64() + 50);
    bool timedOut = false;
    try {
        if (writing) server.Write(std::vector<std::uint8_t>(3 * 1024 * 1024, 42));
        else (void)server.Read();
    } catch (const std::exception& error) {
        timedOut = std::string(error.what()).find("property_worker_timeout") != std::string::npos;
    }
    server.Close();
    client.join();
    Require(timedOut, "I/O timeout not enforced");
}

int main()
{
    try {
        std::cout << "roundtrip\n" << std::flush;
        RoundTrip();
        std::cout << "zero length\n" << std::flush;
        MalformedFrame(0);
        std::cout << "oversized length\n" << std::flush;
        MalformedFrame(256ull * 1024 * 1024 + 1);
        std::cout << "truncated payload\n" << std::flush;
        MalformedFrame(20);
        std::cout << "read timeout\n" << std::flush;
        Timeout(false);
        std::cout << "write timeout\n" << std::flush;
        Timeout(true);
        std::cout << "PASS pipe large/continuous frames, invalid lengths, truncated payload, read/write cancellation\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
