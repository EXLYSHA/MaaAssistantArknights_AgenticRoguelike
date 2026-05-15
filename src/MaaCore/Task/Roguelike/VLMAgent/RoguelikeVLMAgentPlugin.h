#pragma once

#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "MaaUtils/NoWarningCVMat.hpp"
#include "Task/Roguelike/AbstractRoguelikeTaskPlugin.h"
#include "Task/Roguelike/VLMAgent/VLMAgentClient.h"

namespace asst
{
// 不直接接管任何界面，只承载 HTTP client + session_id，供 Roguelike 各决策插件
// 在 VLMAgent 模式下共享。开局调 /session/start 取 session_id，结束调 /session/end。
class RoguelikeVLMAgentPlugin final : public AbstractRoguelikeTaskPlugin
{
public:
    using AbstractRoguelikeTaskPlugin::AbstractRoguelikeTaskPlugin;
    virtual ~RoguelikeVLMAgentPlugin() override = default;

    virtual bool load_params(const json::value& params) override;
    virtual void reset_in_run_variables() override;

    bool enabled() const { return m_enabled; }
    const std::string& session_id() const { return m_session_id; }
    VLMAgentClient& client() { return m_client; }

    // 截图编码 + session_id 包装。失败返回 nullopt，调用方继续走原规则。
    std::optional<json::value> request_decision(
        std::string_view path,
        const cv::Mat& image,
        const json::value& context);
    std::optional<json::value> request_decision(
        std::string_view path,
        const std::vector<cv::Mat>& images,
        const json::value& context);

    json::array current_roster_context();
    json::array current_relics_context();
    std::string current_roster_summary();

    // 结束当前局的 session（失败无所谓）。
    void finish_session(std::string_view outcome);

private:
    virtual bool _run() override { return true; } // 本插件不参与正常的任务链触发
    virtual bool verify(AsstMsg msg, const json::value& details) const override
    {
        (void)msg;
        (void)details;
        return false;
    }

    void ensure_session_started();

    bool m_enabled = false;
    VLMAgentClient m_client;
    std::string m_session_id; // 非空表示已启动
};
} // namespace asst
