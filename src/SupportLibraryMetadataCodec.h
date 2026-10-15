#pragma once

#include "SupportLibraryPublicInfo.h"
#include "../thirdparty/json.hpp"

// 工作进程仅传输复制后的元数据值；路径由调用方恢复，不跨进程传指针。
// CBOR 保留当前 ANSI 代码页字符串的原始字节，避免重复转码。
namespace support_library_public_info {
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(ArgumentMetadata, name, englishName, dataType, state, defaultValue)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(CommandMetadata, index, name, englishName, executeSymbol, category, state, returnType, arguments)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(DataTypeElementMetadata, name, englishName, dataType, state, defaultValue, isArray)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(DataTypeMetadata, index, name, englishName, state, commandIndexes, elements, propertyNames, propertyTypes, eventNames)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(ConstantMetadata, index, name, englishName, type, numberValue, textValue)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(LibraryMetadata, fileName, name, guid, state, majorVersion, minorVersion, buildNumber, notifySymbol, dependentLibraries, commands, dataTypes, constants)
}
