#pragma once

#include <chrono>
#include <optional>
#include <string>
#include <vector>

#include <meojson/json.hpp>

namespace asst
{
// 简易 HTTP/1.1 client，仅支持 POST application/json，用于和本地 VLM agent 通信。
// 基于 boost::asio（仓库已链接），零新增依赖。
class VLMAgentClient
{
public:
    using byte_t = unsigned char;

    struct Config
    {
        std::string host = "127.0.0.1";
        uint16_t port = 8765;
        std::chrono::milliseconds timeout = std::chrono::seconds(30);
    };

    VLMAgentClient() = default;
    explicit VLMAgentClient(Config cfg) : m_cfg(std::move(cfg)) {}

    void set_config(Config cfg) { m_cfg = std::move(cfg); }
    const Config& config() const { return m_cfg; }

    // 在一局开始时调用 /session/start 取 session_id；失败返回 nullopt。
    std::optional<std::string> start_session(
        std::string_view theme,
        int mode,
        int difficulty,
        std::string_view goal_hint);

    // /session/end，best-effort。
    void end_session(std::string_view session_id, std::string_view outcome, int floor_reached);

    // 发起一次决策请求。path 形如 "/decide/encounter"。
    // images 是若干 base64-encoded PNG。失败返回 nullopt（调用方应回退到原有 JSON 规则）。
    std::optional<json::value> request_decision(
        std::string_view path,
        std::string_view session_id,
        const std::vector<std::string>& images_b64,
        const json::value& context);

    // 把内存中的图像字节流编码成 base64。供截图后直接喂入 request_decision。
    static std::string base64_encode(const std::vector<byte_t>& data);

private:
    // 真正的 HTTP POST 实现。返回 (status_code, response_body)。错误时 status=0。
    std::pair<int, std::string> post_json(std::string_view path, const std::string& body);

    Config m_cfg;
};
} // namespace asst
