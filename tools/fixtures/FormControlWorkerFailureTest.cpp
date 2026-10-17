// 用真实 x86 DLL 验证常驻工作进程的崩溃、超时隔离和请求恢复。
#include <Windows.h>
#include <lib2.h>

extern "C" __declspec(dllexport) PLIB_INFO WINAPI GetNewInf()
{
    wchar_t mode[32]{};
    GetEnvironmentVariableW(L"E_PACKAGER_TEST_WORKER_FAILURE", mode, 32);
    if (lstrcmpW(mode, L"crash") == 0) TerminateProcess(GetCurrentProcess(), 73);
    if (lstrcmpW(mode, L"timeout") == 0) Sleep(60000);
    static LIB_INFO info{};
    info.m_dwLibFormatVer = LIB_FORMAT_VER;
    info.m_szGuid = "6C9EE8C6E56343E6978F70B7EF9C8A91";
    info.m_szName = "WorkerFailureTest";
    info.m_nMajorVersion = 1;
    return &info;
}
