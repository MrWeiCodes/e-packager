// 构造可控的原生命令表，验证占位命令诊断能够区别元数据问题。
#include <Windows.h>
#include <lib2.h>
#include <cstring>

extern "C" __declspec(dllexport) PLIB_INFO WINAPI GetNewInf()
{
    static LIB_INFO info{};
    static CMD_INFO commands[700]{};
    char mode[32]{};
    GetEnvironmentVariableA("E_PACKAGER_TEST_COMMAND_TABLE", mode, sizeof(mode));
    info.m_dwLibFormatVer = LIB_FORMAT_VER;
    info.m_szGuid = "d09f2340818511d396f6aaf844c7e325";
    info.m_szName = "DiagnosticFixture";
    info.m_nMajorVersion = 5;
    info.m_nMinorVersion = 7;
    info.m_nCmdCount = 700;
    info.m_pBeginCmdInfo = commands;
    if (std::strcmp(mode, "unreadable") == 0) info.m_pBeginCmdInfo = reinterpret_cast<PCMD_INFO>(1);
    else if (std::strcmp(mode, "short") == 0) info.m_nCmdCount = 1;
    else if (std::strcmp(mode, "empty") == 0) info.m_nCmdCount = 0;
    else if (std::strcmp(mode, "invalid-info") == 0) return nullptr;
    for (auto& command : commands) {
        command.m_szName = std::strcmp(mode, "nameless") == 0 ? nullptr : "ProbeCommand";
        command.m_dtRetValType = SDT_INT;
    }
    return &info;
}
