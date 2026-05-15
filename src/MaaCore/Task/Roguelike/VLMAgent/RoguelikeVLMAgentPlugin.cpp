#include "RoguelikeVLMAgentPlugin.h"

#include <sstream>

#include "MaaUtils/NoWarningCV.hpp"
#include "Utils/Logger.hpp"

namespace asst
{
bool RoguelikeVLMAgentPlugin::load_params(const json::value& params)
{
    if (m_config->get_mode() != RoguelikeMode::VLMAgent) {
        m_enabled = false;
        return false;
    }
    m_enabled = true;

    VLMAgentClient::Config cfg;
    if (auto host = params.find<std::string>("vlm_agent_host")) {
        cfg.host = *host;
    }
    if (auto port = params.find<int>("vlm_agent_port")) {
        cfg.port = static_cast<uint16_t>(*port);
    }
    if (auto timeout_ms = params.find<int>("vlm_agent_timeout_ms")) {
        cfg.timeout = std::chrono::milliseconds(*timeout_ms);
    }
    m_client.set_config(std::move(cfg));

    Log.info(
        "RoguelikeVLMAgentPlugin: enabled, agent at " + m_client.config().host + ":" +
        std::to_string(m_client.config().port));
    return true;
}

void RoguelikeVLMAgentPlugin::reset_in_run_variables()
{
    if (!m_enabled) return;
    if (!m_session_id.empty()) {
        // 上一局未正常结束，best-effort 清理
        m_client.end_session(m_session_id, "abandon", m_config->status().floor);
        m_session_id.clear();
    }
    ensure_session_started();
}

void RoguelikeVLMAgentPlugin::ensure_session_started()
{
    if (!m_enabled || !m_session_id.empty()) return;

    auto sid = m_client.start_session(
        m_config->get_theme(),
        static_cast<int>(m_config->get_mode()),
        0, // difficulty: TODO 从 m_config 取
        "通关");
    if (!sid) {
        Log.error("RoguelikeVLMAgentPlugin: start_session failed; agent unreachable");
        return;
    }
    m_session_id = *sid;
    Log.info("RoguelikeVLMAgentPlugin: session started: " + m_session_id);
}

std::optional<json::value> RoguelikeVLMAgentPlugin::request_decision(
    std::string_view path,
    const cv::Mat& image,
    const json::value& context)
{
    if (image.empty()) {
        return std::nullopt;
    }
    return request_decision(path, std::vector<cv::Mat> { image }, context);
}

std::optional<json::value> RoguelikeVLMAgentPlugin::request_decision(
    std::string_view path,
    const std::vector<cv::Mat>& images,
    const json::value& context)
{
    if (!m_enabled || m_session_id.empty()) {
        return std::nullopt;
    }

    std::vector<std::string> images_b64;
    images_b64.reserve(images.size());
    for (const cv::Mat& image : images) {
        if (image.empty()) {
            continue;
        }
        std::vector<uchar> png_bytes;
        if (!cv::imencode(".png", image, png_bytes)) {
            Log.error("RoguelikeVLMAgentPlugin: failed to encode screenshot for VLM request");
            continue;
        }
        std::vector<VLMAgentClient::byte_t> bytes(png_bytes.begin(), png_bytes.end());
        images_b64.emplace_back(VLMAgentClient::base64_encode(bytes));
    }

    if (images_b64.empty()) {
        return std::nullopt;
    }
    return m_client.request_decision(path, m_session_id, images_b64, context);
}

json::array RoguelikeVLMAgentPlugin::current_roster_context()
{
    json::array roster;
    for (const auto& [name, oper] : m_config->status().opers) {
        json::value item;
        item["name"] = name;
        item["elite"] = oper.elite;
        item["level"] = oper.level;
        roster.emplace_back(std::move(item));
    }
    return roster;
}

json::array RoguelikeVLMAgentPlugin::current_relics_context()
{
    json::array relics;
    for (const auto& relic : m_config->status().collections) {
        relics.emplace_back(relic);
    }
    return relics;
}

std::string RoguelikeVLMAgentPlugin::current_roster_summary()
{
    std::ostringstream oss;
    bool first = true;
    for (const auto& [name, oper] : m_config->status().opers) {
        if (!first) {
            oss << ", ";
        }
        first = false;
        oss << name << "(E" << oper.elite << " L" << oper.level << ")";
    }
    return oss.str();
}

void RoguelikeVLMAgentPlugin::finish_session(std::string_view outcome)
{
    if (!m_enabled || m_session_id.empty()) return;
    m_client.end_session(m_session_id, outcome, m_config->status().floor);
    m_session_id.clear();
}
} // namespace asst
