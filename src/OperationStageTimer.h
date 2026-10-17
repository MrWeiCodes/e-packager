#pragma once

#include "RuntimeLogger.h"
#include <chrono>
#include <string>
#include <string_view>
#include <utility>

namespace runtime_logger {

// 记录一次操作各阶段的独立耗时，方便从日志区分解析、生成、写盘和依赖处理。
class OperationStageTimer {
public:
    OperationStageTimer(std::string operation, std::string source)
        : m_operation(std::move(operation)), m_source(std::move(source)), m_start(Clock::now()) {}

    void Record(std::string_view stage)
    {
        const auto now = Clock::now();
        const auto microseconds = std::chrono::duration_cast<std::chrono::microseconds>(now - m_start).count();
        Write(Level::Info, "operation_stage: operation=" + m_operation + ", stage=" + std::string(stage) +
            ", elapsed_us=" + std::to_string(microseconds) + ", source=" + m_source);
        m_start = Clock::now();
    }

private:
    using Clock = std::chrono::steady_clock;
    std::string m_operation;
    std::string m_source;
    Clock::time_point m_start;
};

} // namespace runtime_logger
