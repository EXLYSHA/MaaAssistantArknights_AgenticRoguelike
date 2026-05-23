#include "RoguelikeCustomStartTaskPlugin.h"

#include <array>
#include <unordered_set>

#include "Config/GeneralConfig.h"
#include "Config/Miscellaneous/BattleDataConfig.h"
#include "Config/TaskData.h"
#include "Controller/Controller.h"
#include "Task/ProcessTask.h"
#include "Task/Roguelike/VLMAgent/RoguelikeVLMAgentPlugin.h"
#include "Utils/Logger.hpp"
#include "Vision/Miscellaneous/PipelineAnalyzer.h"
#include "Vision/OCRer.h"

namespace
{
std::string normalize_squad_ocr_text(const std::string& text)
{
    std::string normalized;
    normalized.reserve(text.size());
    for (char ch : text) {
        if (ch != ' ' && ch != '\t' && ch != '\n' && ch != '\r') {
            normalized.push_back(ch);
        }
    }
    return normalized;
}

bool is_squad_title(const std::string& text)
{
    static const std::string SquadSuffix = "分队";
    if (text.size() < SquadSuffix.size() || text.size() > 30) {
        return false;
    }
    return text.compare(text.size() - SquadSuffix.size(), SquadSuffix.size(), SquadSuffix) == 0;
}

bool is_unlock_marker(const std::string& text)
{
    return text.find("解锁") != std::string::npos || text.find("解鎖") != std::string::npos ||
           text.find("锁条件") != std::string::npos || text.find("鎖條件") != std::string::npos;
}

int center_x(const asst::Rect& rect)
{
    return rect.x + rect.width / 2;
}

bool same_squad_card(const asst::TextRect& title, const asst::TextRect& unlock_marker)
{
    int dx = center_x(title.rect) - center_x(unlock_marker.rect);
    if (dx < 0) {
        dx = -dx;
    }
    const int dy = unlock_marker.rect.y - title.rect.y;
    return dx < 170 && dy > 0 && dy < 90;
}

asst::Point visual_squad_slot_point(int slot_index)
{
    static constexpr std::array<int, 4> SlotCenterX = { 170, 455, 740, 1025 };
    return { SlotCenterX.at(static_cast<size_t>(slot_index)), 445 };
}

json::array make_visual_squad_slots(size_t screenshot_count)
{
    json::array slots;
    for (size_t screenshot_index = 0; screenshot_index != screenshot_count; ++screenshot_index) {
        for (int slot_index = 0; slot_index != 4; ++slot_index) {
            const asst::Point p = visual_squad_slot_point(slot_index);
            json::value item;
            item["id"] = "shot_" + std::to_string(screenshot_index) + "_slot_" + std::to_string(slot_index);
            item["screenshot_index"] = static_cast<int>(screenshot_index);
            item["slot_index"] = slot_index;
            item["position"] = "该截图从左到右第 " + std::to_string(slot_index + 1) + " 张完整卡片";
            item["click_point"] = json::array { p.x, p.y };
            slots.emplace_back(std::move(item));
        }
    }
    return slots;
}
} // namespace

bool asst::RoguelikeCustomStartTaskPlugin::verify(AsstMsg msg, const json::value& details) const
{
    if (details.get("subtask", std::string()) != "ProcessTask") {
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
    static const std::array<std::tuple<AsstMsg, std::string_view, RoguelikeCustomType>, 4> TaskMap = {
        std::make_tuple(AsstMsg::SubTaskCompleted, "Roguelike@Squad-EnterPoint", RoguelikeCustomType::Squad),
        std::make_tuple(AsstMsg::SubTaskStart, "Roguelike@LastReward-EnterPoint", RoguelikeCustomType::Reward),
        std::make_tuple(AsstMsg::SubTaskCompleted, "Roguelike@RolesDefault", RoguelikeCustomType::Roles),
        std::make_tuple(AsstMsg::SubTaskStart, "Roguelike@RecruitMain", RoguelikeCustomType::CoreChar),
    };

    m_waiting_to_run = RoguelikeCustomType::None;
    for (const auto& [t_msg, t_task, t] : TaskMap) {
        if (t_msg == msg && task_view.ends_with(t_task)) {
            m_waiting_to_run = t;
            break;
        }
    }

    if (m_waiting_to_run == RoguelikeCustomType::None) {
        return false;
    }
    if (m_waiting_to_run == RoguelikeCustomType::Reward) {
        return true;
    }
    if (m_waiting_to_run == RoguelikeCustomType::Squad) {
        if (m_config->get_run_for_collectible()) { // 烧水分队
        }
        else {                                     // 开局分队
        }
        return true;
    }
    if (m_waiting_to_run == RoguelikeCustomType::CoreChar) {
        return !m_config->get_core_char().empty();
    }

    // Roles CoreChar
    if (m_waiting_to_run == RoguelikeCustomType::Roles && m_config->get_mode() == RoguelikeMode::VLMAgent) {
        // VLM 模式下不需要预先配置 roles，进入 hijack_roles 由 VLM 决策招募组合
        return true;
    }
    if (auto it = m_customs.find(m_waiting_to_run); it == m_customs.cend()) {
        return false;
    }
    else if (it->second.empty()) {
        return false;
    }

    return true;
}

bool asst::RoguelikeCustomStartTaskPlugin::load_params(const json::value& params)
{
    m_squad = params.get("squad", "");
    if (m_config->get_mode() == RoguelikeMode::Collectible) {
        m_collectible_mode_squad = params.get("collectible_mode_squad", m_squad);
    }

    m_config->set_core_char(params.get("core_char", ""));                            // 开局干员名
    set_custom(RoguelikeCustomType::Roles, params.get("roles", ""));                 // 开局职业组
    m_config->set_use_support(params.get("use_support", false));                     // 开局干员是否为助战干员
    m_config->set_use_nonfriend_support(params.get("use_nonfriend_support", false)); // 是否可以是非好友助战干员

    if (auto select_list = params.find<json::object>("collectible_mode_start_list"); select_list) {
        RoguelikeStartSelect list;
        list.hot_water = select_list->get("hot_water", false);
        list.shield = select_list->get("shield", false);
        list.ingot = select_list->get("ingot", false);
        list.hope = select_list->get("hope", false);
        list.random = select_list->get("random", false);
        if (m_config->get_theme() == RoguelikeTheme::Mizuki) {
            list.key = select_list->get("key", false);
            list.dice = select_list->get("dice", false);
        }
        else if (m_config->get_theme() == RoguelikeTheme::Sarkaz) {
            list.ideas = select_list->get("ideas", false);
        }
        else if (m_config->get_theme() == RoguelikeTheme::JieGarden) {
            list.ticket = select_list->get("ticket", false);
        }
        m_start_select = list;
    }

    return true;
}

void asst::RoguelikeCustomStartTaskPlugin::set_custom(RoguelikeCustomType type, std::string custom)
{
    m_customs.insert_or_assign(type, std::move(custom));
}

bool asst::RoguelikeCustomStartTaskPlugin::_run()
{
    const std::unordered_map<RoguelikeCustomType, std::function<bool(void)>> TypeActuator = {
        { RoguelikeCustomType::Squad, std::bind(&RoguelikeCustomStartTaskPlugin::hijack_squad, this) },
        { RoguelikeCustomType::Reward, std::bind(&RoguelikeCustomStartTaskPlugin::hijack_reward, this) },
        { RoguelikeCustomType::Roles, std::bind(&RoguelikeCustomStartTaskPlugin::hijack_roles, this) },
        { RoguelikeCustomType::CoreChar, std::bind(&RoguelikeCustomStartTaskPlugin::hijack_core_char, this) },
    };

    auto it = TypeActuator.find(m_waiting_to_run);
    if (it == TypeActuator.cend()) {
        return false;
    }

    return it->second();
}

bool asst::RoguelikeCustomStartTaskPlugin::hijack_squad()
{
    std::string squad = !m_config->get_run_for_collectible() ? m_squad : m_collectible_mode_squad;
    if (m_config->get_mode() == RoguelikeMode::VLMAgent) {
        if (auto vlm = m_config->get_vlm_agent(); vlm && vlm->enabled() && !vlm->session_id().empty()) {
            std::vector<cv::Mat> screenshots;
            std::vector<std::string> available_squads;
            std::vector<std::string> locked_squads;
            std::unordered_set<std::string> seen_squads;
            std::unordered_set<std::string> seen_locked_squads;

            constexpr size_t SwipeTimes = 7;
            for (size_t i = 0; i != SwipeTimes; ++i) {
                if (need_exit()) {
                    return false;
                }
                auto image = ctrler()->get_image();
                screenshots.emplace_back(image.clone());
                OCRer analyzer(image);
                analyzer.set_task_info("RoguelikeCustom-HijackSquad");
                if (analyzer.analyze()) {
                    const auto& results = analyzer.get_result();
                    std::vector<TextRect> unlock_markers;
                    for (const auto& result : results) {
                        const std::string text = normalize_squad_ocr_text(result.text);
                        if (is_unlock_marker(text)) {
                            unlock_markers.emplace_back(result);
                        }
                    }

                    for (const auto& result : analyzer.get_result()) {
                        std::string text = normalize_squad_ocr_text(result.text);
                        if (!is_squad_title(text)) {
                            continue;
                        }

                        bool locked = false;
                        for (const auto& marker : unlock_markers) {
                            if (same_squad_card(result, marker)) {
                                locked = true;
                                break;
                            }
                        }

                        if (locked) {
                            if (!seen_locked_squads.contains(text)) {
                                seen_locked_squads.emplace(text);
                                locked_squads.emplace_back(text);
                            }
                            continue;
                        }

                        if (!seen_squads.contains(text)) {
                            seen_squads.emplace(text);
                            available_squads.emplace_back(text);
                        }
                    }
                }
                ProcessTask(*this, { "Roguelike@SquadSlowlySwipeToTheRight" }).run();
                sleep(Task.get("RoguelikeCustom-HijackSquad")->post_delay);
            }
            ProcessTask(*this, { "SwipeToTheLeft" }).run();

            if (!screenshots.empty()) {
                json::value ctx;
                ctx["selection_mode"] = "visual_slots";
                ctx["screenshot_count"] = static_cast<int>(screenshots.size());
                ctx["slots_per_screenshot"] = 4;
                ctx["visual_slots"] = make_visual_squad_slots(screenshots.size());

                json::array squads;
                for (const auto& name : available_squads) {
                    squads.emplace_back(name);
                }
                ctx["available_squads"] = std::move(squads);
                if (!locked_squads.empty()) {
                    json::array locked;
                    for (const auto& name : locked_squads) {
                        locked.emplace_back(name);
                    }
                    ctx["locked_squads"] = std::move(locked);
                }
                ctx["user_hint"] = squad;
                ctx["instruction"] =
                    "OCR 只作为辅助。请看截图序列，选择一个没有锁图标、没有解锁条件的完整分队卡片，"
                    "返回对应 screenshot_index 和 slot_index。";

                auto resp = vlm->request_decision("/decide/squad", screenshots, ctx);
                if (resp && resp->is_object()) {
                    const auto& obj = resp->as_object();
                    auto action = obj.find("action");
                    auto squad_name = obj.find("squad_name");
                    auto screenshot_index = obj.find("screenshot_index");
                    auto slot_index = obj.find("slot_index");

                    if (action && action->is_string() && action->as_string() == "pick" && screenshot_index &&
                        screenshot_index->is_number() && slot_index && slot_index->is_number()) {
                        const int screenshot_index_value = screenshot_index->as_integer();
                        const int slot_index_value = slot_index->as_integer();
                        if (screenshot_index_value >= 0 &&
                            static_cast<size_t>(screenshot_index_value) < screenshots.size() && slot_index_value >= 0 &&
                            slot_index_value < 4) {
                            for (size_t i = 0; i != SwipeTimes; ++i) {
                                ProcessTask(*this, { "SwipeToTheLeft" }).run();
                            }
                            for (int i = 0; i != screenshot_index_value; ++i) {
                                ProcessTask(*this, { "Roguelike@SquadSlowlySwipeToTheRight" }).run();
                                sleep(Task.get("RoguelikeCustom-HijackSquad")->post_delay);
                            }
                            const Point click_point = visual_squad_slot_point(slot_index_value);
                            Log.info(
                                __FUNCTION__,
                                "| VLM squad visual pick:",
                                "screenshot",
                                screenshot_index_value,
                                "slot",
                                slot_index_value,
                                "point",
                                click_point.to_string(),
                                "name",
                                squad_name && squad_name->is_string() ? squad_name->as_string() : "");
                            ctrler()->click(click_point);
                            if (squad_name && squad_name->is_string()) {
                                m_config->set_squad(squad_name->as_string());
                            }
                            return true;
                        }
                    }

                    if (action && action->is_string() && action->as_string() == "pick" && squad_name &&
                        squad_name->is_string() && seen_squads.contains(squad_name->as_string())) {
                        squad = squad_name->as_string();
                        Log.info(__FUNCTION__, "| VLM squad pick:", squad);
                    }
                }
            }
        }
    }

    if (squad.empty()) { // 简单处理，认为指挥分队无需滑屏，没有就随机
        return ProcessTask(
                   *this,
                   { m_config->get_theme() + "@Roguelike@SquadDefault",
                     m_config->get_theme() + "@Roguelike@Squad-Random" })
            .run();
    }

    constexpr size_t SwipeTimes = 7;
    for (size_t i = 0; i != SwipeTimes; ++i) {
        if (need_exit()) {
            return false;
        }
        auto image = ctrler()->get_image();
        OCRer analyzer(image);
        analyzer.set_task_info("RoguelikeCustom-HijackSquad");
        analyzer.set_required({ squad });

        if (!analyzer.analyze()) {
            ProcessTask(*this, { "Roguelike@SquadSlowlySwipeToTheRight" }).run();
            sleep(Task.get("RoguelikeCustom-HijackSquad")->post_delay);
            continue;
        }
        const auto& rect = analyzer.get_result().front().rect;
        ctrler()->click(rect);

        m_config->set_squad(std::move(squad));
        return true;
    }
    ProcessTask(*this, { "SwipeToTheLeft" }).run();
    return false;
}

bool asst::RoguelikeCustomStartTaskPlugin::hijack_reward()
{
    const auto& list = get_select_list();
    if (list.empty()) {
        // 执行默认选择顺序
        ProcessTask(*this, { m_config->get_theme() + "@Roguelike@LastReward-Strategy" }).run();
        return true;
    }

    // 处理选择顺序
    PipelineAnalyzer analyzer(ctrler()->get_image());
    analyzer.set_tasks(list);
    if (auto ret = analyzer.analyze(); !ret) {
        // 未获取到期望物品，设置烧水flag，重开
        m_config->set_run_for_collectible(true);
        m_control_ptr->exit_then_stop(true);
    }
    else if (m_config->get_start_with_elite_two() || m_config->get_first_floor_foldartal()) {
        // 之后还要凹开局精二或第一层密文板，不停止任务，继续探索
        ctrler()->click(ret->rect);
        sleep(Config.get_options().task_delay);
    }
    else {
        m_control_ptr->exit_then_stop(false);
        m_task_ptr->set_enable(false);
    }

    return true;
}

bool asst::RoguelikeCustomStartTaskPlugin::hijack_roles()
{
    constexpr size_t SwipeTimes = 7;

    if (m_config->get_mode() == RoguelikeMode::VLMAgent) {
        if (auto vlm = m_config->get_vlm_agent(); vlm && vlm->enabled() && !vlm->session_id().empty()) {
            // Roles 屏（招募组合：先手制胜/稳扎稳打/取长补短/随心所欲）所有卡片都在同一个画面，
            // 单张截图即可，避免无意义的滑屏 + 重复传图。
            cv::Mat image = ctrler()->get_image();

            std::vector<std::string> ocr_roles;
            std::unordered_set<std::string> seen;
            OCRer ocr(image);
            ocr.set_task_info("RoguelikeCustom-HijackRoles");
            if (ocr.analyze()) {
                for (const auto& r : ocr.get_result()) {
                    const std::string text = normalize_squad_ocr_text(r.text);
                    if (text.empty() || text.size() > 30) {
                        continue;
                    }
                    if (!seen.contains(text)) {
                        seen.emplace(text);
                        ocr_roles.emplace_back(text);
                    }
                }
            }

            json::value ctx;
            ctx["selection_mode"] = "visual_slots";
            ctx["screenshot_count"] = 1;
            ctx["slots_per_screenshot"] = 4;
            ctx["visual_slots"] = make_visual_squad_slots(1);

            json::array roles;
            for (const auto& name : ocr_roles) {
                roles.emplace_back(name);
            }
            ctx["ocr_candidates"] = std::move(roles);
            ctx["squad"] = m_config->get_squad();
            ctx["instruction"] =
                "这是肉鸽开局的招募组合（也称为职业组/Roles）选择，整个界面一张截图就能看到全部 4 张卡片，"
                "请结合视觉判断每个招募组合给出的偏向（如近战/远程/法术/治疗/盾兵/速攻等），"
                "结合当前分队和你计划的过关路线，选择一个最合适的招募组合，"
                "返回 screenshot_index=0 和对应 slot_index。";

            auto resp = vlm->request_decision("/decide/recruit_combo", image, ctx);
            if (resp && resp->is_object()) {
                const auto& obj = resp->as_object();
                auto action = obj.find("action");
                auto slot_index = obj.find("slot_index");
                auto combo_name = obj.find("combo_name");

                if (action && action->is_string() && action->as_string() == "pick" && slot_index &&
                    slot_index->is_number()) {
                    const int slot = slot_index->as_integer();
                    if (slot >= 0 && slot < 4) {
                        const Point click_point = visual_squad_slot_point(slot);
                        Log.info(
                            __FUNCTION__,
                            "| VLM recruit_combo visual pick: slot",
                            slot,
                            "point",
                            click_point.to_string(),
                            "name",
                            combo_name && combo_name->is_string() ? combo_name->as_string() : "");
                        ctrler()->click(click_point);
                        return true;
                    }
                }
            }
            // VLM 失败，回退默认
            return ProcessTask(*this, { "Roguelike@RolesDefault" }).run();
        }
    }

    const std::string& required_role = m_customs[RoguelikeCustomType::Roles];

    for (size_t i = 0; i != SwipeTimes; ++i) {
        if (need_exit()) {
            return false;
        }

        auto image = ctrler()->get_image();
        OCRer analyzer(image);
        analyzer.set_task_info("RoguelikeCustom-HijackRoles");
        analyzer.set_required({ required_role });

        if (analyzer.analyze()) {
            const auto& rect = analyzer.get_result().front().rect;
            ctrler()->click(rect);
            return true;
        }

        ProcessTask(*this, { "Roguelike@SquadSlowlySwipeToTheRight" }).run();
        sleep(Task.get("RoguelikeCustom-HijackRoles")->post_delay);
    }

    ProcessTask(*this, { "SwipeToTheLeft" }).run();
    return false;
}

bool asst::RoguelikeCustomStartTaskPlugin::hijack_core_char()
{
    static const std::unordered_map<battle::Role, std::string> RoleOcrNameMap = {
        { battle::Role::Caster, "术师" }, { battle::Role::Medic, "医疗" },   { battle::Role::Pioneer, "先锋" },
        { battle::Role::Sniper, "狙击" }, { battle::Role::Special, "特种" }, { battle::Role::Support, "辅助" },
        { battle::Role::Tank, "重装" },   { battle::Role::Warrior, "近卫" }
    };
    const std::string& char_name = m_config->get_core_char();
    const auto& role = BattleData.get_role(char_name);
    auto role_iter = RoleOcrNameMap.find(role);
    if (role_iter == RoleOcrNameMap.cend()) {
        Log.error("Unknown role", char_name, static_cast<int>(role));
        return false;
    }
    // select role
    const std::string& role_ocr_name = role_iter->second;
    Log.info("role", role_ocr_name);
    auto image = ctrler()->get_image();
    OCRer analyzer(image);
    analyzer.set_task_info("RoguelikeCustom-HijackCoChar");
    analyzer.set_required({ role_ocr_name });
    if (!analyzer.analyze()) {
        return false;
    }
    for (int retry = 0; retry < 3; ++retry) {
        const auto& role_rect = analyzer.get_result().front().rect;
        ctrler()->click(role_rect);
        sleep(Task.get("RoguelikeCustom-HijackCoChar")->pre_delay);

        ProcessTask check(
            *this,
            { m_config->get_theme() + "@Roguelike@ChooseOperFlag",
              m_config->get_theme() + "@Roguelike@RecruitCloseGuide" });
        check.set_times_limit("Roguelike@ChooseOperFlag", 0);
        check.set_retry_times(0);
        if (check.run()) {
            return true; // 进入选择干员界面
        }
    }
    return false; // 进入选择干员界面失败
}

std::vector<std::string> asst::RoguelikeCustomStartTaskPlugin::get_select_list() const
{
    if (m_config->get_mode() != RoguelikeMode::Collectible ||
        m_config->get_run_for_collectible() /* 正在烧水，使用默认策略 */ ||
        m_config->get_only_start_with_elite_two() /* 只凹精二没有奖励，但第一次开时可能有之前的奖励 */) {
        return {};
    }

    std::vector<std::string> list;
    if (m_start_select.hot_water) {
        list.emplace_back(m_config->get_theme() + "@Roguelike@LastReward"); // 热水壶
    }
    if (m_start_select.shield) {
        list.emplace_back(m_config->get_theme() + "@Roguelike@LastReward2"); // 盾；傀影没盾，是生命
    }
    if (m_start_select.ingot) {
        list.emplace_back(m_config->get_theme() + "@Roguelike@LastReward3"); // 源石锭
    }
    if (m_start_select.hope) {
        list.emplace_back(m_config->get_theme() + "@Roguelike@LastReward4"); // 希望
    }

    if (m_start_select.random) {
        list.emplace_back(m_config->get_theme() + "@Roguelike@LastRewardRand"); // 随机奖励
    }
    if (m_config->get_theme() == RoguelikeTheme::Mizuki) {
        if (m_start_select.key) {
            list.emplace_back("Mizuki@Roguelike@LastReward5"); // 钥匙
        }
        if (m_start_select.dice) {
            list.emplace_back("Mizuki@Roguelike@LastReward6"); // 骰子
        }
    }
    else if (m_config->get_theme() == RoguelikeTheme::Sarkaz && m_start_select.ideas) {
        list.emplace_back("Sarkaz@Roguelike@LastReward5"); // 构想
    }
    else if (m_config->get_theme() == RoguelikeTheme::JieGarden && m_start_select.ticket) {
        list.emplace_back("JieGarden@Roguelike@LastReward5"); // 票券
    }

    return list;
}
