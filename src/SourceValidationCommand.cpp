#include "SourceValidationCommand.h"
#include <Windows.h>
#include <fstream>
#include "SourcePreflightValidator.h"
#include "EFolderCodec.h"
#include "WorkspaceProjectSupport.h"
#include "PathHelper.h"
#include "e2txt.h"
#include "../thirdparty/json.hpp"
#include <iostream>

namespace source_validation {
namespace {
using json = nlohmann::json;
struct TemporaryDirectory {
	std::filesystem::path path;
	~TemporaryDirectory() { std::error_code ec; if (!path.empty()) std::filesystem::remove_all(path, ec); }
};
}
int Run(const std::filesystem::path& input, const Level level, const bool jsonOutput,
	const autolinker_compile_check::Options& compileOptions)
{
	const char* levelName = level == Level::Editable ? "editable" : level == Level::Compile ? "compile" : "semantic";
	json output = {{"command", "validate"}, {"level", levelName}, {"diagnostics", json::array()},
		{"ideOpenVerified", false}};
	const auto finish = [&](const int status, const std::string& message) {
		output["ok"] = status == 0;
		output["status"] = status == 0 ? "passed" : status == 1 ? "failed" : "unavailable";
		output["message"] = message;
		output["runtimeWarnings"] = e2txt::ConsumeRuntimeWarnings();
		std::size_t errors = 0, warnings = 0;
		for (const auto& item : output["diagnostics"]) {
			if (item.value("severity", "") == "error") ++errors;
			if (item.value("severity", "") == "warning") ++warnings;
		}
		if (status != 0 && errors == 0) {
			output["diagnostics"].push_back({{"severity", "error"}, {"phase", levelName},
				{"code", status == 2 ? "validation_unavailable" : "validation_failed"},
				{"message", message}, {"file", nullptr}, {"line", nullptr}});
			++errors;
		}
		output["errors"] = errors;
		output["warnings"] = warnings;
		if (jsonOutput) std::cout << output.dump() << std::endl;
		else std::cout << "validate: level=" << levelName << ", status=" << output["status"].get<std::string>()
			<< "\n" << message << std::endl;
		if (!jsonOutput) for (const auto& warning : output["runtimeWarnings"]) std::cout << warning.get<std::string>() << std::endl;
		return status;
	};
	e2txt::ClearRuntimeWarnings();
	std::string error;
	const auto directory = std::filesystem::absolute(input);
	if (!workspace_support::ValidateInfoJsonVersion(directory, error)) return finish(1, error);
	e2txt::ProjectBundle bundle;
	e2txt::BundleDirectoryCodec codec;
	if (!codec.ReadBundle(PathToUtf8(directory), bundle, &error)) return finish(1, error);
	const auto report = e2txt::ValidateProjectBundleSource(bundle,
		level == Level::Semantic ? e2txt::SourceValidationLevel::Semantic : e2txt::SourceValidationLevel::Editable);
	const auto preflight = json::parse(e2txt::FormatSourcePreflightReportJson(report, &bundle));
	output.update(preflight);
	if (!report.IsValid() || level == Level::Semantic)
		return finish(report.IsValid() ? 0 : 1, e2txt::FormatSourcePreflightReport(report));
	std::vector<std::uint8_t> bytes;
	e2txt::Restorer restorer;
	if (!restorer.RestoreBundleToBytes(bundle, bytes, &error)) return finish(1, error);
	output["rebuildVerified"] = true;
	if (level == Level::Editable) return finish(0, e2txt::FormatSourcePreflightReport(report));
	autolinker_compile_check::PreparedOptions prepared;
	if (!autolinker_compile_check::Prepare(compileOptions, prepared, error)) return finish(2, error);
	TemporaryDirectory temporary;
	std::error_code ec;
	const auto root = std::filesystem::temp_directory_path(ec);
	if (ec) return finish(2, "validation_temp_directory_failed: " + ec.message());
	for (unsigned attempt = 0; attempt < 100; ++attempt) {
		const auto candidate = root / ("e-packager-validate-" + std::to_string(GetCurrentProcessId()) + "-" +
			std::to_string(GetTickCount64()) + "-" + std::to_string(attempt));
		if (std::filesystem::create_directory(candidate, ec)) { temporary.path = candidate; break; }
		if (ec) return finish(2, "validation_temp_directory_failed: " + ec.message());
	}
	if (temporary.path.empty()) return finish(2, "validation_temp_directory_failed");
	const auto source = temporary.path / "source.e";
	std::ofstream stream(source, std::ios::binary);
	stream.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
	stream.close();
	if (!stream) return finish(2, "validation_source_write_failed");
	const auto result = autolinker_compile_check::CompileToOutputWithEide(source, temporary.path / "artifact.exe",
		prepared.eIdePath, prepared.target, prepared.staticCompile, prepared.timeoutSeconds,
		Utf8PathToPath(bundle.sourcePath));
	if (!result.diagnosticsJson.empty()) {
		output["ideResult"] = json::parse(result.diagnosticsJson);
		if (output["ideResult"].contains("diagnostics")) {
			for (const auto& diagnostic : output["ideResult"]["diagnostics"]) output["diagnostics"].push_back(diagnostic);
		}
	}
	return finish(result.ok ? 0 : result.validationCompleted ? 1 : 2, result.ok ? result.summary : result.error);
}
}
