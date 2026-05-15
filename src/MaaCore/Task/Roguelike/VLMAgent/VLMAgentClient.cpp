#include "VLMAgentClient.h"

#include <array>
#include <sstream>

#include <boost/asio.hpp>

#include "Utils/Logger.hpp"

namespace asst
{
using tcp = boost::asio::ip::tcp;

static constexpr std::array<char, 64> kBase64Table = {
    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P',
    'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'a', 'b', 'c', 'd', 'e', 'f',
    'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v',
    'w', 'x', 'y', 'z', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '+', '/',
};

std::string VLMAgentClient::base64_encode(const std::vector<byte_t>& data)
{
    std::string out;
    out.reserve(((data.size() + 2) / 3) * 4);
    size_t i = 0;
    for (; i + 2 < data.size(); i += 3) {
        uint32_t v = (uint32_t(data[i]) << 16) | (uint32_t(data[i + 1]) << 8) | uint32_t(data[i + 2]);
        out.push_back(kBase64Table[(v >> 18) & 0x3F]);
        out.push_back(kBase64Table[(v >> 12) & 0x3F]);
        out.push_back(kBase64Table[(v >> 6) & 0x3F]);
        out.push_back(kBase64Table[v & 0x3F]);
    }
    if (i < data.size()) {
        uint32_t v = uint32_t(data[i]) << 16;
        bool has_two = (i + 1 < data.size());
        if (has_two) v |= uint32_t(data[i + 1]) << 8;
        out.push_back(kBase64Table[(v >> 18) & 0x3F]);
        out.push_back(kBase64Table[(v >> 12) & 0x3F]);
        out.push_back(has_two ? kBase64Table[(v >> 6) & 0x3F] : '=');
        out.push_back('=');
    }
    return out;
}

std::pair<int, std::string> VLMAgentClient::post_json(std::string_view path, const std::string& body)
{
    try {
        boost::asio::io_context io;
        tcp::resolver resolver(io);
        auto endpoints = resolver.resolve(m_cfg.host, std::to_string(m_cfg.port));
        tcp::socket socket(io);
        boost::asio::connect(socket, endpoints);

        std::ostringstream req;
        req << "POST " << path << " HTTP/1.1\r\n"
            << "Host: " << m_cfg.host << ":" << m_cfg.port << "\r\n"
            << "Content-Type: application/json\r\n"
            << "Content-Length: " << body.size() << "\r\n"
            << "Connection: close\r\n\r\n"
            << body;
        std::string request = req.str();
        boost::asio::write(socket, boost::asio::buffer(request));

        boost::asio::streambuf response_buf;
        boost::system::error_code ec;
        boost::asio::read(socket, response_buf, boost::asio::transfer_all(), ec);
        if (ec && ec != boost::asio::error::eof) {
            Log.error("VLMAgentClient: asio read error: " + ec.message());
            return { 0, {} };
        }

        std::string raw((std::istreambuf_iterator<char>(&response_buf)), {});

        // 拆 HTTP/1.1 status line
        int status = 0;
        size_t first_space = raw.find(' ');
        if (first_space != std::string::npos) {
            size_t second_space = raw.find(' ', first_space + 1);
            if (second_space != std::string::npos) {
                try {
                    status = std::stoi(raw.substr(first_space + 1, second_space - first_space - 1));
                }
                catch (...) {
                    status = 0;
                }
            }
        }

        // body 在 \r\n\r\n 之后
        size_t header_end = raw.find("\r\n\r\n");
        std::string body_str = header_end == std::string::npos ? std::string {} : raw.substr(header_end + 4);

        // Transfer-Encoding: chunked 解析
        if (raw.find("Transfer-Encoding: chunked") != std::string::npos) {
            std::string decoded;
            size_t pos = 0;
            while (pos < body_str.size()) {
                size_t line_end = body_str.find("\r\n", pos);
                if (line_end == std::string::npos) break;
                size_t chunk_len = 0;
                try {
                    chunk_len = std::stoul(body_str.substr(pos, line_end - pos), nullptr, 16);
                }
                catch (...) {
                    break;
                }
                if (chunk_len == 0) break;
                size_t data_start = line_end + 2;
                if (data_start + chunk_len > body_str.size()) break;
                decoded.append(body_str, data_start, chunk_len);
                pos = data_start + chunk_len + 2;
            }
            body_str = std::move(decoded);
        }

        return { status, body_str };
    }
    catch (const std::exception& e) {
        Log.error(std::string("VLMAgentClient: post_json exception: ") + e.what());
        return { 0, {} };
    }
}

std::optional<std::string> VLMAgentClient::start_session(
    std::string_view theme,
    int mode,
    int difficulty,
    std::string_view goal_hint)
{
    json::value body;
    body["theme"] = std::string(theme);
    body["mode"] = mode;
    body["difficulty"] = difficulty;
    body["goal_hint"] = std::string(goal_hint);

    auto [status, resp_body] = post_json("/session/start", body.to_string());
    if (status != 200) {
        Log.error("VLMAgentClient: start_session failed, status=" + std::to_string(status));
        return std::nullopt;
    }

    auto parsed = json::parse(resp_body);
    if (!parsed || !parsed->is_object()) {
        Log.error("VLMAgentClient: start_session response not JSON object: " + resp_body);
        return std::nullopt;
    }
    const auto& obj = parsed->as_object();
    if (auto session_id = obj.find("session_id"); session_id && session_id->is_string()) {
        return session_id->as_string();
    }
    return std::nullopt;
}

void VLMAgentClient::end_session(std::string_view session_id, std::string_view outcome, int floor_reached)
{
    json::value body;
    body["session_id"] = std::string(session_id);
    body["outcome"] = std::string(outcome);
    body["floor_reached"] = floor_reached;
    (void)post_json("/session/end", body.to_string());
}

std::optional<json::value> VLMAgentClient::request_decision(
    std::string_view path,
    std::string_view session_id,
    const std::vector<std::string>& images_b64,
    const json::value& context)
{
    json::value body;
    body["session_id"] = std::string(session_id);
    json::array imgs;
    for (const auto& b : images_b64) imgs.emplace_back(b);
    body["screenshots"] = std::move(imgs);
    body["context"] = context;

    auto [status, resp_body] = post_json(path, body.to_string());
    if (status != 200) {
        Log.error("VLMAgentClient: " + std::string(path) + " failed, status=" + std::to_string(status));
        return std::nullopt;
    }

    auto parsed = json::parse(resp_body);
    if (!parsed) {
        Log.error("VLMAgentClient: response not JSON: " + resp_body);
        return std::nullopt;
    }
    return *parsed;
}
} // namespace asst
