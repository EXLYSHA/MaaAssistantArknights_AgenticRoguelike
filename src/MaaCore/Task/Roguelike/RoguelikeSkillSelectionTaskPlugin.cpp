#include "RoguelikeSkillSelectionTaskPlugin.h"

#include "Config/Roguelike/RoguelikeRecruitConfig.h"
#include "Config/TaskData.h"
#include "Controller/Controller.h"
#include "Task/Roguelike/VLMAgent/RoguelikeVLMAgentPlugin.h"
#include "Utils/Logger.hpp"
#include "Vision/Roguelike/RoguelikeSkillSelectionImageAnalyzer.h"

bool asst::RoguelikeSkillSelectionTaskPlugin::verify(AsstMsg msg, const json::value& details) const
{
    if (msg != AsstMsg::SubTaskStart || details.get("subtask", std::string()) != "ProcessTask") {
        return false;
    }

    if (!RoguelikeConfig::is_valid_theme(m_config->get_theme())) {
        Log.error("Roguelike name doesn't exist!");
        return false;
    }
    const std::string roguelike_name = m_config->get_theme() + "@";
    const std::string& task = details.get("details", "task", "");
    std::string_view task_view = task;
    if (task_view.starts_with(roguelike_name)) {
        task_view.remove_prefix(roguelike_name.length());
    }
    if (task_view == "Roguelike@StartAction") {
        return true;
    }
    else {
        return false;
    }
}

bool asst::RoguelikeSkillSelectionTaskPlugin::_run()
{
    LogTraceFunction;

    auto image = ctrler()->get_image();
    RoguelikeSkillSelectionImageAnalyzer analyzer(image);

    if (!analyzer.analyze()) {
        return false;
    }

    int delay = Task.get("RoguelikeSkillSelectionMove1")->post_delay;
    bool has_rookie = false;
    for (const auto& [name, skill_vec] : analyzer.get_result()) {
        const auto& oper_info = RoguelikeRecruit.get_oper_info(m_config->get_theme(), name);
        if (oper_info.name.empty()) {
            Log.warn("Unknown oper", name);
            continue;
        }

        bool vlm_handled = false;
        if (m_config->get_mode() == RoguelikeMode::VLMAgent) {
            if (auto vlm = m_config->get_vlm_agent(); vlm && vlm->enabled() && !vlm->session_id().empty()) {
                json::value ctx;
                ctx["operator"] = name;
                ctx["occasion"] = "pre_battle";
                ctx["current_roster_summary"] = vlm->current_roster_summary();

                json::array skills;
                for (size_t index = 0; index < skill_vec.size(); ++index) {
                    json::value skill;
                    skill["index"] = static_cast<int>(index) + 1;
                    skill["name_ocr"] = "";
                    skill["desc_ocr"] = "";
                    skills.emplace_back(std::move(skill));
                }
                ctx["skills"] = std::move(skills);

                auto resp = vlm->request_decision("/decide/skill_selection", image, ctx);
                if (resp && resp->is_object()) {
                    const auto& obj = resp->as_object();
                    auto action = obj.find("action");
                    auto skill_index = obj.find("skill_index");
                    if (action && action->is_string() && action->as_string() == "pick" && skill_index &&
                        skill_index->is_number()) {
                        const int index = skill_index->as_integer();
                        if (index >= 1 && static_cast<size_t>(index) <= skill_vec.size()) {
                            Log.info(__FUNCTION__, name, " VLM select skill:", index);
                            ctrler()->click(skill_vec.at(index - 1));
                            sleep(delay);
                            vlm_handled = true;
                        }
                    }
                }
            }
        }

        if (!vlm_handled && oper_info.alternate_skill > 0) {
            Log.info(__FUNCTION__, name, " select alternate skill:", oper_info.alternate_skill);
            ctrler()->click(skill_vec.at(oper_info.alternate_skill - 1));
            sleep(delay);
        }
        if (!vlm_handled && oper_info.skill > 0) {
            Log.info(__FUNCTION__, name, " select main skill:", oper_info.skill);
            ctrler()->click(skill_vec.at(oper_info.skill - 1));
            sleep(delay);
        }
        constexpr int RookieStd = 200;
        if (oper_info.promote_priority < RookieStd) {
            has_rookie = true;
        }
    }

    if (m_config->status().opers.empty()) {
        std::unordered_map<std::string, RoguelikeOper> opers;
        for (const auto& [name, skill_vec] : analyzer.get_result()) {
            opers[name] = { .elite = 1, .level = 80 };
            // 不知道是啥等级随便填一个
        }
        m_config->status().opers = std::move(opers);
    }

    if (analyzer.get_team_full() && !has_rookie) {
        Log.info("Team full and no rookie");
        m_config->status().team_full_without_rookie = true;
    }
    else {
        Log.info("Team not full or has rookie");
        m_config->status().team_full_without_rookie = false;
    }
    return true;
}
