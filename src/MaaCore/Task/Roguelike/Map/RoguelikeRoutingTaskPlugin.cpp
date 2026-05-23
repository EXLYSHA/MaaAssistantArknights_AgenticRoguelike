#include "RoguelikeRoutingTaskPlugin.h"

#include <limits>
#include <numeric>
#include <unordered_set>

#include "Config/TaskData.h"
#include "Controller/Controller.h"
#include "MaaUtils/ImageIo.h"
#include "MaaUtils/NoWarningCV.hpp"
#include "Task/ProcessTask.h"
#include "Task/Roguelike/VLMAgent/RoguelikeVLMAgentPlugin.h"
#include "Utils/DebugImageHelper.hpp"
#include "Utils/Logger.hpp"
#include "Vision/Matcher.h"
#include "Vision/Miscellaneous/PixelAnalyzer.h"
#include "Vision/MultiMatcher.h"

namespace
{
[[maybe_unused]] std::string vlm_node_type(asst::RoguelikeNodeType type)
{
    switch (type) {
    case asst::RoguelikeNodeType::CombatOps:
        return "battle";
    case asst::RoguelikeNodeType::EmergencyOps:
        return "elite";
    case asst::RoguelikeNodeType::DreadfulFoe:
        return "boss";
    case asst::RoguelikeNodeType::Encounter:
    case asst::RoguelikeNodeType::Recreation:
    case asst::RoguelikeNodeType::Scout:
    case asst::RoguelikeNodeType::Prophecy:
    case asst::RoguelikeNodeType::FaceOff:
        return "encounter";
    case asst::RoguelikeNodeType::Boons:
        return "boon";
    case asst::RoguelikeNodeType::SafeHouse:
        return "safehouse";
    case asst::RoguelikeNodeType::RogueTrader:
        return "shop";
    case asst::RoguelikeNodeType::IdeaFilter:
        return "filter";
    case asst::RoguelikeNodeType::BoskyPassage:
        return "passage";
    default:
        return "unknown";
    }
}

std::string sarkaz_routing_action_for_node(asst::RoguelikeNodeType type)
{
    switch (type) {
    case asst::RoguelikeNodeType::CombatOps:
        return "Sarkaz@RoguelikeRoutingAction-StageCombatOpsEnter";
    case asst::RoguelikeNodeType::EmergencyOps:
        return "Sarkaz@RoguelikeRoutingAction-StageEmergencyOpsEnter";
    case asst::RoguelikeNodeType::DreadfulFoe:
        return "Sarkaz@RoguelikeRoutingAction-StageDreadfulFoeEnter";
    case asst::RoguelikeNodeType::Encounter:
    case asst::RoguelikeNodeType::Recreation:
    case asst::RoguelikeNodeType::Scout:
    case asst::RoguelikeNodeType::Prophecy:
    case asst::RoguelikeNodeType::FaceOff:
        return "Sarkaz@RoguelikeRoutingAction-StageEncounterEnter";
    case asst::RoguelikeNodeType::Boons:
        return "Sarkaz@RoguelikeRoutingAction-StageBoonsEnter";
    case asst::RoguelikeNodeType::SafeHouse:
        return "Sarkaz@RoguelikeRoutingAction-StageSafeHouseEnter";
    case asst::RoguelikeNodeType::RogueTrader:
        return "Sarkaz@RoguelikeRoutingAction-StageTraderEnter";
    case asst::RoguelikeNodeType::IdeaFilter:
        return "Sarkaz@RoguelikeRoutingAction-StageFilterTruthEnter";
    case asst::RoguelikeNodeType::BoskyPassage:
        return "Sarkaz@RoguelikeRoutingAction-StageBoskyPassageEnter";
    default:
        return "";
    }
}
} // namespace

bool asst::RoguelikeRoutingTaskPlugin::load_params([[maybe_unused]] const json::value& params)
{
    const std::string& theme = m_config->get_theme();

    // 本插件暂处于实验阶段，仅用于萨卡兹和界园肉鸽的第一层
    if (theme != RoguelikeTheme::Sarkaz && theme != RoguelikeTheme::JieGarden) {
        return false;
    }

    const TaskPtr config_task = Task.get("RoguelikeRoutingConfig");

    m_origin_x = config_task->special_params.at(0);
    m_middle_x = config_task->special_params.at(1);
    m_last_x = config_task->special_params.at(2);
    m_node_width = config_task->special_params.at(3);
    m_node_height = config_task->special_params.at(4);
    m_column_offset = config_task->special_params.at(5);
    m_nameplate_offset = config_task->special_params.at(6);
    m_roi_margin = config_task->special_params.at(7);
    m_direction_threshold = config_task->special_params.at(8);

    const RoguelikeMode& mode = m_config->get_mode();
    const std::string squad = params.get("squad", "");

    if (theme == RoguelikeTheme::Sarkaz && mode == RoguelikeMode::FastPass && squad == "蓝图测绘分队") {
        m_routing_strategy = RoutingStrategy::Sarkaz_FastPass;
        return true;
    }

    if (theme == RoguelikeTheme::Sarkaz && mode == RoguelikeMode::VLMAgent) {
        m_routing_strategy = RoutingStrategy::Sarkaz_FastPass;
        return true;
    }

    if (theme == RoguelikeTheme::Sarkaz && mode == RoguelikeMode::Investment && squad == "点刺成锭分队") {
        m_routing_strategy = RoutingStrategy::Sarkaz_FastInvestment;
        return true;
    }

    if (theme == RoguelikeTheme::JieGarden) {
        if (((mode == RoguelikeMode::Investment && squad == "指挥分队") ||
             (mode == RoguelikeMode::Collectible && params.get("collectible_mode_squad", squad) == "指挥分队")) &&
            m_config->get_difficulty() >= 3) {
            m_routing_strategy = RoutingStrategy::JieGarden_FastPassWithBattle;
            return true;
        }
    }

    return false;
}

void asst::RoguelikeRoutingTaskPlugin::reset_in_run_variables()
{
    m_map.reset();
    m_need_generate_map = true;
    m_selected_column = 0;
    m_selected_x = 0;
}

bool asst::RoguelikeRoutingTaskPlugin::verify(const AsstMsg msg, const json::value& details) const
{
    if (msg != AsstMsg::SubTaskStart || details.get("subtask", std::string()) != "ProcessTask") {
        return false;
    }

    std::string task_name = details.get("details", "task", "");

    // trigger 任务的名字可以为 "...@Roguelike@Routing-..." 的形式
    if (const size_t pos = task_name.find('-'); pos != std::string::npos) {
        task_name = task_name.substr(0, pos);
    }

    if (task_name == m_config->get_theme() + "@Roguelike@Routing") {
        return true;
    }

    return false;
}

bool asst::RoguelikeRoutingTaskPlugin::_run()
{
    LogTraceFunction;

    switch (m_routing_strategy) {
    case RoutingStrategy::Sarkaz_FastInvestment:
        if (m_need_generate_map) {
            // 随机点击一个第一列的节点，先随便写写，垃圾代码迟早要重构
            ProcessTask(*this, { "Sarkaz@RoguelikeRouting-CombatOps" }).run();
            // 刷新节点
            ProcessTask(*this, { "Sarkaz@RoguelikeRouting-RefreshNode" }).run();
            // 不识别了，进商店，Go!
            Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-StageTraderEnter");
            // 偷懒，直接用 m_need_generate_map 判断是否已进过商店
            m_need_generate_map = false;
        }
        else {
            Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        }
        break;
    case RoutingStrategy::JieGarden_FastPassWithBattle:
        if (m_need_generate_map) {
            // 向左滑动以检视前三列节点
            ProcessTask(*this, { "RoguelikeRouting-MoveRightToPeek" }).run();
            cv::Mat image = ctrler()->get_image();
            cv::Mat image_draw = image.clone();
            update_map(image, RoguelikeMap::INIT_INDEX + 1, image_draw);
#ifdef ASST_DEBUG
            utils::save_debug_image(
                image_draw,
                utils::path("debug") / "roguelikeMap",
                /*auto_clean=*/true,
                /*description=*/"bosky map draw",
                /*suffix=*/"draw");
#endif
            m_need_generate_map = false;

            // 根据第三列节点类型更新导航策略
            const size_t sample_node_of_last_column = m_map.size() - 1;
            const RoguelikeNodeType sample_node_type = m_map.get_node_type(sample_node_of_last_column);
            Log.info("RoguelikeRouting | Type of last node:", type2name(sample_node_type));
            if (sample_node_type == RoguelikeNodeType::RogueTrader) {
                m_routing_strategy = RoutingStrategy::JieGarden_FastPassWithoutBattle;
                m_config->set_skip_recruit_in_fast_pass(true);
                return _run();
            }
        }
        if (m_map.get_curr_pos() == RoguelikeMap::INIT_INDEX) {
            // 规划路线
            m_map.set_cost_fun([&](const RoguelikeNodePtr& node) {
                if (node->type == RoguelikeNodeType::CombatOps) {
                    return 10;
                }
                if (node->type == RoguelikeNodeType::EmergencyOps || node->type == RoguelikeNodeType::DreadfulFoe) {
                    return 11;
                }
                return 0;
            });
            m_map.update_node_costs();
            const size_t next_node = m_map.get_next_node();

            // 若无法避免超过三场战斗则重开
            if (m_map.get_node_cost(next_node) >= 30) {
                callback(
                    AsstMsg::TaskChainExtraInfo,
                    json::object {
                        { "what", "RoutingRestart" },
                        { "why", "TooManyBattlesAhead" },
                        { "node_cost", m_map.get_node_cost(next_node) },
                    });

                Task.set_task_base("RoguelikeRoutingAction", "JieGarden@RoguelikeRoutingAction-ExitThenAbandon");
            }
            else {
                const int next_node_x = m_left_most_column_x_in_view;
                const int next_node_y = m_map.get_node_y(next_node);
                Point next_node_center = Point(next_node_x + m_node_width / 2, next_node_y + m_node_height / 2);
                ctrler()->click(next_node_center);
                sleep(200);

                Task.set_task_base(
                    "RoguelikeRoutingAction",
                    "JieGarden@RoguelikeRoutingAction-StageCombatOpsEnterThenLeave");
                m_map.set_curr_pos(next_node);
            }
        }
        else {
            // 执行默认的避战策略
            Task.set_task_base("RoguelikeRoutingAction", "JieGarden@Roguelike@Stages_default");
        }
        break;

    case RoutingStrategy::JieGarden_FastPassWithoutBattle:
        if (m_need_generate_map) {
            cv::Mat image = ctrler()->get_image();
            cv::Mat image_draw = image.clone();
            update_map(image, RoguelikeMap::INIT_INDEX + 1, image_draw);
#ifdef ASST_DEBUG
            utils::save_debug_image(
                image_draw,
                utils::path("debug") / "roguelikeMap",
                /*auto_clean=*/true,
                /*description=*/"bosky map draw",
                /*suffix=*/"draw");
#endif
            m_need_generate_map = false;
        }
        if (m_map.get_curr_pos() == RoguelikeMap::INIT_INDEX) {
            m_map.set_cost_fun([&](const RoguelikeNodePtr& node) {
                if (node->type == RoguelikeNodeType::CombatOps || node->type == RoguelikeNodeType::EmergencyOps ||
                    node->type == RoguelikeNodeType::DreadfulFoe) {
                    return 1;
                }
                return 0;
            });
            m_map.update_node_costs();
            const size_t next_node = m_map.get_next_node();

            // 若无法避免超过两场战斗则重开
            if (m_map.get_node_cost(next_node) >= 2) {
                callback(
                    AsstMsg::TaskChainExtraInfo,
                    json::object {
                        { "what", "RoutingRestart" },
                        { "why", "TooManyBattlesAhead" },
                        { "node_cost", m_map.get_node_cost(next_node) },
                    });

                Task.set_task_base("RoguelikeRoutingAction", "JieGarden@RoguelikeRoutingAction-ExitThenAbandon");
            }
            else {
                const int next_node_x = m_left_most_column_x_in_view;
                const int next_node_y = m_map.get_node_y(next_node);
                Point next_node_center = Point(next_node_x + m_node_width / 2, next_node_y + m_node_height / 2);
                ctrler()->click(next_node_center);
                sleep(200);

                Task.set_task_base(
                    "RoguelikeRoutingAction",
                    "JieGarden@RoguelikeRoutingAction-StageCombatOpsEnterThenLeave");
                m_map.set_curr_pos(next_node);
            }
        }
        else {
            // 执行默认的避战策略
            Task.set_task_base("RoguelikeRoutingAction", "JieGarden@Roguelike@Stages_default");
        }
        break;
    case RoutingStrategy::Sarkaz_FastPass:
        // VLM 模式下完全跳过 m_map 缓存逻辑，每次直接用当前画面识别可见节点交给 VLM。
        if (m_config->get_mode() == RoguelikeMode::VLMAgent) {
            return navigate_route_vlm_only();
        }
        if (m_need_generate_map) {
            generate_map();
            m_need_generate_map = false;
        }

        m_selected_column = m_map.get_node_column(m_map.get_curr_pos());
        update_selected_x();

        refresh_following_combat_nodes();
        navigate_route();
        break;

    default:
        break;
    }

    return true;
}

bool asst::RoguelikeRoutingTaskPlugin::update_map(
    const cv::Mat& image,
    const size_t leftmost_column,
    std::optional<std::reference_wrapper<cv::Mat>> image_draw_opt)
{
    LogTraceFunction;

    if (leftmost_column == 0) {
        Log.error(__FUNCTION__, "| leftmost_column must be greater than zero");
        return false;
    }

    const std::string& theme = m_config->get_theme();

    size_t curr_col = leftmost_column - 1;
    int curr_x = -m_node_width - 1; // 第一列节点将触发 rect.x >= curr_x + m_node_width 并更新 curr_col 与 curr_x

    MultiMatcher node_analyzer(image);
    node_analyzer.set_task_info(theme + "@RoguelikeRoutingNodeAnalyze");
    if (!node_analyzer.analyze()) {
        Log.error(__FUNCTION__, "| no nodes are recognised");
        return false;
    }
    MultiMatcher::ResultsVec match_results = node_analyzer.get_result();
    sort_by_vertical_(match_results); // 按照水平方向从左到右排序各列节点，同一列节点按照垂直方向从上到下排序
    m_left_most_column_x_in_view = match_results.front().rect.x;

    const size_t old_num_columns = m_map.get_num_columns();
    for (const auto& [rect, score, templ_name] : match_results) {
        const RoguelikeNodeType type = RoguelikeMapInfo.templ2type(theme, templ_name);
#ifdef ASST_DEBUG
        if (image_draw_opt.has_value()) {
            cv::rectangle(image_draw_opt.value().get(), make_rect<cv::Rect>(rect), cv::Scalar(255, 255, 255), 2);
            cv::putText(
                image_draw_opt.value().get(),
                templ_name,
                cv::Point(rect.x, rect.y - m_roi_margin),
                cv::FONT_HERSHEY_DUPLEX,
                0.5,
                cv::Scalar(255, 255, 255));
        }
#endif
        if (rect.x >= curr_x + m_node_width) { // 识别到下一列的节点
            ++curr_col;
            curr_x = rect.x;
        }
        if (curr_col >= old_num_columns) // 仅更新新列节点
        {
            const size_t node = m_map.create_and_insert_node(type, curr_col, rect.y).value();
            generate_edges(node, image, rect.x, image_draw_opt);
        }
    }

    return true;
}

void asst::RoguelikeRoutingTaskPlugin::generate_map()
{
    LogTraceFunction;

    const std::string& theme = m_config->get_theme();

    m_map.reset();
    size_t curr_col = RoguelikeMap::INIT_INDEX + 1;
    Rect roi = Task.get<MatchTaskInfo>(theme + "@RoguelikeRoutingNodeAnalyze")->roi;

    // 第一列节点
    cv::Mat image = ctrler()->get_image();
    MultiMatcher node_analyzer(image);
    node_analyzer.set_task_info(theme + "@RoguelikeRoutingNodeAnalyze");
    if (!node_analyzer.analyze()) {
        Log.error(__FUNCTION__, "| no nodes found in the first column");
        return;
    }
    MultiMatcher::ResultsVec match_results = node_analyzer.get_result();
    sort_by_horizontal_(match_results); // 按照垂直方向排序（从上到下）
    for (const auto& [rect, score, templ_name] : match_results) {
        const RoguelikeNodeType type = RoguelikeMapInfo.templ2type(theme, templ_name);
        const size_t node = m_map.create_and_insert_node(type, curr_col, rect.y).value();
        generate_edges(node, image, rect.x);
    }

    // 第二列及以后的节点
    roi.x += m_column_offset;
    node_analyzer.set_roi(roi);
    while (!need_exit() && node_analyzer.analyze()) {
        ++curr_col;
        match_results = node_analyzer.get_result();
        sort_by_horizontal_(match_results);
        for (const auto& [rect, score, templ_name] : match_results) {
            const RoguelikeNodeType type = RoguelikeMapInfo.templ2type(theme, templ_name);
            const size_t node = m_map.create_and_insert_node(type, curr_col, rect.y).value();
            generate_edges(node, image, rect.x);
        }
        ProcessTask(*this, { "RoguelikeRouting-MoveRight" }).run();
        sleep(200);
        image = ctrler()->get_image();
        node_analyzer.set_image(image);
    }

    ProcessTask(*this, { theme + "@RoguelikeRouting-ExitThenContinue" }).run(); // 通过退出重进回到初始位置
}

void asst::RoguelikeRoutingTaskPlugin::generate_edges(
    const size_t& node,
    const cv::Mat& image,
    const int& node_x,
    [[maybe_unused]] std::optional<std::reference_wrapper<cv::Mat>> image_draw_opt)
{
    LogTraceFunction;

    const size_t node_column = m_map.get_node_column(node);

    if (node_column == RoguelikeMap::INIT_INDEX) {
        Log.error(__FUNCTION__, "| cannot generate edges for init node");
        return;
    }

    if (node_column == RoguelikeMap::INIT_INDEX + 1) {
        m_map.add_edge(RoguelikeMap::INIT_INDEX, node); // 第一列节点直接与 init 连接
        return;
    }

    // 将 image转换为二值图像后计算亮点
    PixelAnalyzer analyzer(image);

    const int center_x = node_x - (m_column_offset - m_node_width) / 2; // node 与 前一列节点的中点横坐标
    const int node_y = m_map.get_node_y(node);
    Rect roi(0, 0, m_roi_margin * 2, m_roi_margin * 2);

    // 遍历前一列节点
    const size_t pre_col_begin = m_map.get_column_begin(node_column - 1);
    const size_t pre_col_end = m_map.get_column_end(node_column - 1);
    for (size_t prev = pre_col_begin; prev < pre_col_end; ++prev) {
        const int prev_y = m_map.get_node_y(prev);
        const int center_y = (prev_y + node_y + m_node_height) / 2;
        roi.x = center_x - m_roi_margin;
        roi.y = center_y - m_roi_margin;
#ifdef ASST_DEBUG
        if (image_draw_opt.has_value()) {
            cv::rectangle(image_draw_opt.value().get(), make_rect<cv::Rect>(roi), cv::Scalar(255, 255, 255), 1);
        }
#endif
        analyzer.set_roi(roi);

        if (!analyzer.analyze()) { // 节点间没有连线
            continue;
        }

        // 按照水平方向排序（从左到右）
        std::vector<Point> brightPixels = analyzer.get_result();

        auto [x_min_p, x_max_p] = std::ranges::minmax(brightPixels, /*comp=*/ {}, [](const Point& p) { return p.x; });
        const int leftmost_x = x_min_p.x;
        const int rightmost_x = x_max_p.x;

        auto leftmostBrightPixels =
            brightPixels | std::views::filter([&](const Point& p) { return p.x == leftmost_x; });
        auto rightmostBrightPixels =
            brightPixels | std::views::filter([&](const Point& p) { return p.x == rightmost_x; });

        auto [leftmost_y_min_p, leftmost_y_max_p] =
            std::ranges::minmax(leftmostBrightPixels, /*comp=*/ {}, [](const Point& p) { return p.y; });
        const int leftmost_y = (leftmost_y_min_p.y + leftmost_y_max_p.y) / 2;

        auto [rightmost_y_min_p, rightmost_y_max_p] =
            std::ranges::minmax(rightmostBrightPixels, /*comp=*/ {}, [](const Point& p) { return p.y; });
        const int rightmost_y = (rightmost_y_min_p.y + rightmost_y_max_p.y) / 2;

        if ((std::abs(prev_y - node_y) < m_direction_threshold &&
             std::abs(leftmost_y - rightmost_y) < m_direction_threshold) ||
            (prev_y < node_y && leftmost_y < rightmost_y - m_direction_threshold) ||
            (prev_y > node_y && leftmost_y > rightmost_y + m_direction_threshold)) {
            m_map.add_edge(prev, node);
#ifdef ASST_DEBUG
            if (image_draw_opt.has_value()) {
                cv::line(
                    image_draw_opt.value().get(),
                    cv::Point(node_x - m_column_offset + m_node_width / 2, prev_y + m_node_height / 2),
                    cv::Point(node_x + m_node_width / 2, node_y + m_node_height / 2),
                    cv::Scalar(255, 255, 255),
                    2);
            }
#endif
        }
    }

    // 同列前一个节点
    if (node > m_map.get_column_begin(node_column)) {
        size_t prev = node - 1;
        roi.x = node_x + m_node_width / 2 - m_roi_margin;
        roi.y = (m_map.get_node_y(prev) + m_node_height + m_nameplate_offset + node_y) / 2 - m_roi_margin;
#ifdef ASST_DEBUG
        if (image_draw_opt.has_value()) {
            cv::rectangle(image_draw_opt.value().get(), make_rect<cv::Rect>(roi), cv::Scalar(255, 255, 255), 1);
        }
#endif
        analyzer.set_roi(roi);
        if (analyzer.analyze()) {
            m_map.add_edge(prev, node);
            m_map.add_edge(node, prev);
#ifdef ASST_DEBUG
            if (image_draw_opt.has_value()) {
                cv::line(
                    image_draw_opt.value().get(),
                    cv::Point(node_x + m_node_width / 2, m_map.get_node_y(prev) + m_node_height / 2),
                    cv::Point(node_x + m_node_width / 2, node_y + m_node_height / 2),
                    cv::Scalar(255, 255, 255),
                    2);
            }
#endif
        }
    }
}

void asst::RoguelikeRoutingTaskPlugin::refresh_following_combat_nodes()
{
    LogTraceFunction;

    const std::string& theme = m_config->get_theme();

    const size_t curr_node = m_map.get_curr_pos();
    const size_t curr_node_column = m_map.get_node_column(curr_node);

    for (size_t next_node : m_map.get_node_succs(curr_node)) {
        // 不刷新同一列的节点
        const size_t next_node_column = m_map.get_node_column(next_node);
        if (next_node_column <= curr_node_column) {
            continue;
        }
        // 每个节点仅刷新一次
        if (m_map.get_node_refresh_times(next_node)) {
            continue;
        }
        // 不刷新非战斗节点
        RoguelikeNodeType next_node_type = m_map.get_node_type(next_node);
        if (next_node_type != RoguelikeNodeType::CombatOps && next_node_type != RoguelikeNodeType::EmergencyOps &&
            next_node_type != RoguelikeNodeType::DreadfulFoe) {
            continue;
        }

        int next_node_x = m_selected_x + (next_node_column == m_selected_column ? 0 : m_column_offset);
        int next_node_y = m_map.get_node_y(next_node);
        Rect next_node_rect = Rect(next_node_x, next_node_y, m_node_width, m_node_height);

        // 点击节点
        ctrler()->click(next_node_rect);
        m_selected_column = m_map.get_node_column(next_node);
        update_selected_x();
        next_node_rect.x = m_selected_x;
        sleep(200);

        // 刷新节点
        ProcessTask(*this, { m_config->get_theme() + "@RoguelikeRouting-RefreshNode" }).run();
        m_map.set_node_refresh_times(next_node, m_map.get_node_refresh_times(next_node) + 1);

        // 识别并更新节点类型
        Matcher node_analyzer(ctrler()->get_image());
        node_analyzer.set_task_info(theme + "@RoguelikeRoutingNodeAnalyze");
        node_analyzer.set_roi(next_node_rect);
        if (node_analyzer.analyze()) {
            const Matcher::Result& match_results = node_analyzer.get_result();
            m_map.set_node_type(next_node, RoguelikeMapInfo.templ2type(theme, match_results.templ_name));
        }
    }
}

void asst::RoguelikeRoutingTaskPlugin::navigate_route()
{
    LogTraceFunction;

    const size_t curr_col = m_map.get_node_column(m_map.get_curr_pos());

    m_map.set_cost_fun([&](const RoguelikeNodePtr& node) {
        if (node->visited) {
            return 1000;
        }

        if (node->column == curr_col) {
            return 1000;
        }

        if (node->type == RoguelikeNodeType::CombatOps || node->type == RoguelikeNodeType::EmergencyOps ||
            node->type == RoguelikeNodeType::DreadfulFoe) {
            return 1 + (node->refresh_times ? 999 : 0);
        }

        return 0;
    });

    m_map.update_node_costs();

    size_t next_node = m_map.get_next_node();
    bool vlm_chosen = false;

    if (m_config->get_mode() == RoguelikeMode::VLMAgent) {
        if (auto vlm = m_config->get_vlm_agent(); vlm && vlm->enabled() && !vlm->session_id().empty()) {
            // 拍照前先点一下地图左上空白区，关掉可能残留的节点详情面板，避免遮挡 VLM 视野
            ctrler()->click(Point(40, 360));
            sleep(200);

            // 用当前画面重新模板匹配，得到每个可见节点的真实屏幕坐标。
            // m_map 里缓存的 y 与 m_selected_x 在每次进入节点后都可能失效。
            // 注意 RoguelikeRoutingNodeAnalyze 任务的 ROI 只覆盖单列，必须扩到整图才能识别全部可见节点。
            cv::Mat live_image = ctrler()->get_image();
            std::unordered_map<size_t, Rect> live_rects;
            {
                MultiMatcher live_analyzer(live_image);
                live_analyzer.set_task_info(m_config->get_theme() + "@RoguelikeRoutingNodeAnalyze");
                live_analyzer.set_roi(Rect(0, 0, live_image.cols, live_image.rows));
                if (live_analyzer.analyze()) {
                    auto matches = live_analyzer.get_result();
                    sort_by_vertical_(matches);
                    Log.info(
                        __FUNCTION__,
                        "| VLM live match found",
                        matches.size(),
                        "node templates in screen");

                    // 按列拆分（与 update_map 同样的逻辑：x 跨过 node_width 视为下一列）
                    std::vector<std::vector<MultiMatcher::Result>> per_col;
                    int curr_x = -m_node_width - 1;
                    for (const auto& m : matches) {
                        if (m.rect.x >= curr_x + m_node_width) {
                            per_col.emplace_back();
                            curr_x = m.rect.x;
                        }
                        per_col.back().push_back(m);
                    }
                    for (auto& col : per_col) {
                        std::sort(col.begin(), col.end(),
                                  [](const auto& a, const auto& b) { return a.rect.y < b.rect.y; });
                    }

                    // 把屏幕上每个 (列, 行) 对到 m_map 的 node index。
                    // 找出 m_map 里"哪一列在屏幕最左"的方式：从当前节点列附近往左尝试。
                    const size_t curr_col = m_map.get_node_column(m_map.get_curr_pos());
                    Log.info(
                        __FUNCTION__,
                        "| live screen columns:",
                        per_col.size(),
                        "m_map columns:",
                        m_map.get_num_columns(),
                        "curr_col:",
                        curr_col);
                    for (size_t i = 0; i < per_col.size(); ++i) {
                        Log.info(__FUNCTION__, "| screen col", i, "size", per_col[i].size(),
                                 "x≈", per_col[i].empty() ? 0 : per_col[i][0].rect.x);
                    }
                    for (size_t col_off = 0; col_off + per_col.size() <= m_map.get_num_columns(); ++col_off) {
                        // 尝试 m_map 列 [start, start + per_col.size()) 对齐屏幕列 [0, per_col.size())
                        size_t start = col_off;
                        bool ok = true;
                        std::unordered_map<size_t, Rect> trial;
                        for (size_t screen_col = 0; screen_col < per_col.size(); ++screen_col) {
                            size_t mc = start + screen_col;
                            size_t cb = m_map.get_column_begin(mc);
                            size_t ce = m_map.get_column_end(mc);
                            if (ce - cb != per_col[screen_col].size()) {
                                ok = false;
                                break;
                            }
                            for (size_t row = 0; row < per_col[screen_col].size(); ++row) {
                                trial[cb + row] = per_col[screen_col][row].rect;
                            }
                        }
                        if (ok && trial.count(m_map.get_curr_pos()) + (curr_col < start || curr_col >= start + per_col.size() ? 1 : 0) >= 1) {
                            // 优先选择能覆盖当前节点附近的对齐方案
                            live_rects = std::move(trial);
                            break;
                        }
                        if (ok && live_rects.empty()) {
                            live_rects = std::move(trial);
                        }
                    }
                }
            }

            const size_t curr_node = m_map.get_curr_pos();
            const auto reachable_nodes = m_map.get_node_succs(curr_node);
            std::unordered_set<size_t> reachable_set(reachable_nodes.begin(), reachable_nodes.end());

            json::value ctx;
            ctx["current_roster_summary"] = vlm->current_roster_summary();
            ctx["note"] =
                "请直接看截图判断地图状态：左下角的图标读取 floor/hope/hp/思绪 等数值，"
                "看节点图标确定关卡名/类型，看连线推断后继关系。"
                "context 里给出的 click_point 是每个节点中心的屏幕坐标，仅用于把 nXX 与画面位置一一对应。"
                "只允许从 reachable_node_ids 里选下一步，并自行考虑思绪/HP/费用等门槛节点是否能进。";

            json::array path_so_far;
            if (curr_node != RoguelikeMap::INIT_INDEX) {
                path_so_far.emplace_back("n" + std::to_string(curr_node));
            }
            ctx["planned_path_so_far"] = std::move(path_so_far);

            json::array nodes;
            json::array reachable_options;
            for (size_t node = RoguelikeMap::INIT_INDEX + 1; node < m_map.size(); ++node) {
                const size_t column = m_map.get_node_column(node);
                const RoguelikeNodeType node_type = m_map.get_node_type(node);
                const bool reachable = reachable_set.contains(node);

                int node_x = 0, node_y = 0;
                bool visible = false;
                if (auto it = live_rects.find(node); it != live_rects.end()) {
                    node_x = it->second.x;
                    node_y = it->second.y;
                    visible = true;
                }
                else {
                    // 不在当前屏幕上的兜底（理论上 reachable 节点必然可见）
                    const int column_delta = static_cast<int>(column) - static_cast<int>(m_selected_column);
                    node_x = m_selected_x + column_delta * m_column_offset;
                    node_y = m_map.get_node_y(node);
                }

                json::value item;
                item["id"] = "n" + std::to_string(node);
                item["raw_type"] = type2name(node_type);
                item["depth_from_start"] = static_cast<int>(column);
                item["reachable_now"] = reachable;
                item["visible_on_screen"] = visible;
                json::array click_point;
                click_point.emplace_back(node_x + m_node_width / 2);
                click_point.emplace_back(node_y + m_node_height / 2);
                item["click_point"] = std::move(click_point);
                nodes.emplace_back(std::move(item));
                if (reachable) {
                    reachable_options.emplace_back("n" + std::to_string(node));
                }
            }
            ctx["all_nodes_in_floor"] = std::move(nodes);
            ctx["reachable_node_ids"] = std::move(reachable_options);

            // 当前所在节点 id
            if (curr_node == RoguelikeMap::INIT_INDEX) {
                ctx["current_node_id"] = "start";
            }
            else {
                ctx["current_node_id"] = "n" + std::to_string(curr_node);
            }

            auto resp = vlm->request_decision("/decide/map_node", live_image, ctx);
            if (resp && resp->is_object()) {
                const auto& obj = resp->as_object();
                auto action = obj.find("action");
                auto node_id = obj.find("node_id");
                if (action && action->is_string() && action->as_string() == "goto" && node_id &&
                    node_id->is_string()) {
                    for (size_t node : reachable_nodes) {
                        if (node_id->as_string() == "n" + std::to_string(node)) {
                            next_node = node;
                            vlm_chosen = true;
                            // 把真实屏幕坐标存到成员变量，后面 click 时用真实坐标而不是 m_map 缓存
                            if (auto it = live_rects.find(node); it != live_rects.end()) {
                                m_vlm_next_click_override = Point(
                                    it->second.x + m_node_width / 2,
                                    it->second.y + m_node_height / 2);
                            }
                            else {
                                m_vlm_next_click_override = std::nullopt;
                            }
                            Log.info(
                                __FUNCTION__,
                                "| VLM map node pick:",
                                node_id->as_string(),
                                type2name(m_map.get_node_type(node)),
                                "click=",
                                m_vlm_next_click_override
                                    ? m_vlm_next_click_override->to_string()
                                    : std::string("(cached)"));
                            break;
                        }
                    }
                }
            }
        }
    }

    if (!vlm_chosen && m_map.get_node_cost(next_node) >= 1000) {
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        reset_in_run_variables();
        return;
    }

    Point next_node_center;
    if (vlm_chosen && m_vlm_next_click_override) {
        next_node_center = *m_vlm_next_click_override;
        m_vlm_next_click_override.reset();
    }
    else {
        const size_t next_node_column = m_map.get_node_column(next_node);
        const int next_node_x = m_selected_x + (next_node_column == m_selected_column ? 0 : m_column_offset);
        const int next_node_y = m_map.get_node_y(next_node);
        next_node_center = Point(next_node_x + m_node_width / 2, next_node_y + m_node_height / 2);
    }
    ctrler()->click(next_node_center);
    sleep(200);

    const RoguelikeNodeType next_node_type = m_map.get_node_type(next_node);
    if (m_config->get_mode() == RoguelikeMode::VLMAgent) {
        const std::string action = sarkaz_routing_action_for_node(next_node_type);
        if (!action.empty()) {
            Task.set_task_base("RoguelikeRoutingAction", action);
        }
        else {
            Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        }
        // VLM 模式下每次进完一个节点都让 m_map 重新生成，
        // 因为玩家进入战斗/事件/商店后回来时一般会换新一层地图，
        // 旧的 m_map 结构和坐标全部失效。
        reset_in_run_variables();
        return;
    }

    if (next_node_type == RoguelikeNodeType::Encounter) {
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-StageEncounterEnter");
        m_map.set_curr_pos(next_node);
    }
    else if (next_node_type == RoguelikeNodeType::RogueTrader) {
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-StageTraderEnter");
        reset_in_run_variables();
    }
    else {
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        reset_in_run_variables();
    }
}

void asst::RoguelikeRoutingTaskPlugin::update_selected_x()
{
    if (m_selected_column == RoguelikeMap::INIT_INDEX) {
        m_selected_x = m_origin_x - m_column_offset;
    }
    else if (m_selected_column == RoguelikeMap::INIT_INDEX + 1) {
        m_selected_x = m_origin_x;
    }
    else if (m_selected_column == m_map.get_num_columns() - 1) [[unlikely]] {
        m_selected_x = m_last_x;
    }
    else {
        m_selected_x = m_middle_x;
    }
}

bool asst::RoguelikeRoutingTaskPlugin::navigate_route_vlm_only()
{
    LogTraceFunction;

    auto vlm = m_config->get_vlm_agent();
    if (!vlm || !vlm->enabled() || vlm->session_id().empty()) {
        Log.warn(__FUNCTION__, "| VLM agent not available, fallback abandon");
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        return true;
    }

    // 关掉残留的节点详情面板
    ctrler()->click(Point(40, 360));
    sleep(200);

    cv::Mat live_image = ctrler()->get_image();

    MultiMatcher analyzer(live_image);
    analyzer.set_task_info(m_config->get_theme() + "@RoguelikeRoutingNodeAnalyze");
    analyzer.set_roi(Rect(0, 0, live_image.cols, live_image.rows));
    if (!analyzer.analyze()) {
        Log.error(__FUNCTION__, "| no nodes detected on screen");
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        return true;
    }

    auto matches = analyzer.get_result();
    sort_by_vertical_(matches);

    // 节点是否"已访问/失效"的判定：模板名包含 "Grey"。
    // 但有些节点类型（例如 RogueTrader）在资源里**只有** Grey 模板，
    // 没有彩色版本——这种节点永远会被误判成 visited。所以先扫一遍所有匹配，
    // 找出"两种版本都存在"的类型族，只有这些类型族 Grey == visited 才有效。
    auto base_name = [](const std::string& templ) -> std::string {
        // 去掉路径和扩展名，再去掉 "Grey" 后缀
        std::string s = templ;
        if (auto pos = s.find_last_of("/\\"); pos != std::string::npos) s = s.substr(pos + 1);
        if (auto pos = s.rfind(".png"); pos != std::string::npos) s = s.substr(0, pos);
        if (auto pos = s.rfind("Grey"); pos != std::string::npos && pos == s.size() - 4) {
            s = s.substr(0, pos);
        }
        return s;
    };
    std::unordered_set<std::string> seen_grey;
    std::unordered_set<std::string> seen_colored;
    for (const auto& m : matches) {
        const std::string base = base_name(m.templ_name);
        if (m.templ_name.find("Grey") != std::string::npos) {
            seen_grey.insert(base);
        }
        else {
            seen_colored.insert(base);
        }
    }
    // 同时跟全主题模板表对照：如果某 base 在配置里**只有** Grey 模板，
    // 说明它的"灰色"实际上就是彩色（典型：RogueTrader），不能当 visited。
    auto is_grey_template_meaningful = [&](const std::string& templ) -> bool {
        if (templ.find("Grey") == std::string::npos) return false;
        const std::string base = base_name(templ);
        // 当前帧或全图任一处看到过该 base 的非 Grey 版本，就认为 Grey 有意义
        if (seen_colored.contains(base)) return true;
        // 模板配置里查：该 base 是否有非 Grey 模板
        auto task_info = Task.get<MatchTaskInfo>(m_config->get_theme() + "@RoguelikeRoutingNodeAnalyze");
        if (task_info) {
            for (const auto& t : task_info->templ_names) {
                std::string tb = base_name(t);
                if (tb == base && t.find("Grey") == std::string::npos) {
                    return true;
                }
            }
        }
        return false;
    };

    // 按 x 把节点划成屏幕上的列
    struct ScreenNode
    {
        std::string id;
        Rect rect;
        std::string templ;
        RoguelikeNodeType type;
        bool visited = false;
        size_t col_in_screen = 0;
    };
    std::vector<std::vector<ScreenNode>> per_col;
    int curr_x = -m_node_width - 1;
    for (const auto& m : matches) {
        if (m.rect.x >= curr_x + m_node_width) {
            per_col.emplace_back();
            curr_x = m.rect.x;
        }
        ScreenNode sn;
        sn.rect = m.rect;
        sn.templ = m.templ_name;
        sn.type = RoguelikeMapInfo.templ2type(m_config->get_theme(), m.templ_name);
        sn.visited = is_grey_template_meaningful(m.templ_name);
        sn.col_in_screen = per_col.size() - 1;
        per_col.back().push_back(sn);
    }
    for (auto& col : per_col) {
        std::sort(col.begin(), col.end(),
                  [](const ScreenNode& a, const ScreenNode& b) { return a.rect.y < b.rect.y; });
    }

    // 给每个屏幕节点分配 nXX_Y id（X 是屏幕列号，Y 是从上到下行号）
    size_t total = 0;
    for (size_t c = 0; c < per_col.size(); ++c) {
        for (size_t r = 0; r < per_col[c].size(); ++r) {
            per_col[c][r].id = "n" + std::to_string(c) + "_" + std::to_string(r);
            ++total;
        }
    }
    Log.info(__FUNCTION__, "| screen has", per_col.size(), "columns total", total, "nodes");
    for (size_t c = 0; c < per_col.size(); ++c) {
        size_t visited_n = 0;
        for (const auto& sn : per_col[c]) if (sn.visited) ++visited_n;
        Log.info(__FUNCTION__, "| col", c, "size", per_col[c].size(),
                 "x≈", per_col[c].empty() ? 0 : per_col[c][0].rect.x,
                 "visited_count", visited_n);
    }

    if (per_col.empty()) {
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        return true;
    }

    // 找到第一个**含至少一个 unvisited 节点**的列作为当前可走候选；
    // 该列里只有 unvisited 节点才作为可点击候选。
    size_t reachable_col_idx = per_col.size();
    for (size_t c = 0; c < per_col.size(); ++c) {
        bool has_unvisited = false;
        for (const auto& sn : per_col[c]) {
            if (!sn.visited) {
                has_unvisited = true;
                break;
            }
        }
        if (has_unvisited) {
            reachable_col_idx = c;
            break;
        }
    }
    if (reachable_col_idx == per_col.size()) {
        Log.warn(__FUNCTION__, "| no column with unvisited nodes, abandon");
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        return true;
    }
    Log.info(__FUNCTION__, "| reachable column index =", reachable_col_idx);
    const auto& reachable_col = per_col[reachable_col_idx];

    json::array nodes_json;
    json::array reachable_ids_json;
    for (const auto& col : per_col) {
        for (const auto& sn : col) {
            json::value item;
            item["id"] = sn.id;
            item["raw_type"] = type2name(sn.type);
            item["depth_from_start"] = static_cast<int>(sn.col_in_screen);
            item["reachable_now"] = (sn.col_in_screen == reachable_col_idx) && !sn.visited;
            item["visited"] = sn.visited;
            json::array click_point;
            click_point.emplace_back(sn.rect.x + sn.rect.width / 2);
            click_point.emplace_back(sn.rect.y + sn.rect.height / 2);
            item["click_point"] = std::move(click_point);
            nodes_json.emplace_back(std::move(item));
        }
    }
    for (const auto& sn : reachable_col) {
        if (!sn.visited) {
            reachable_ids_json.emplace_back(sn.id);
        }
    }

    json::value ctx;
    ctx["current_roster_summary"] = vlm->current_roster_summary();
    ctx["all_nodes_in_floor"] = std::move(nodes_json);
    ctx["reachable_node_ids"] = std::move(reachable_ids_json);
    ctx["current_node_id"] = "start_or_previous";
    ctx["planned_path_so_far"] = json::array {};
    ctx["note"] =
        "请直接看截图判断地图状态：左下角的图标读取 floor/hope/hp/思绪 等数值。"
        "all_nodes_in_floor 是当前屏幕上识别到的所有节点（屏幕最左列已是当前可走的下一步候选）。"
        "节点 id 的格式是 nCOL_ROW（屏幕列号_行号），仅用于和 click_point 一一对应。"
        "只允许从 reachable_node_ids 里选下一步。";

    auto resp = vlm->request_decision("/decide/map_node", live_image, ctx);
    if (!resp || !resp->is_object()) {
        Log.error(__FUNCTION__, "| VLM did not return a valid decision, abandon");
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        return true;
    }

    const auto& obj = resp->as_object();
    auto action = obj.find("action");
    auto node_id = obj.find("node_id");
    if (!action || !action->is_string() || action->as_string() != "goto" || !node_id || !node_id->is_string()) {
        Log.error(__FUNCTION__, "| VLM response missing goto/node_id, abandon");
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        return true;
    }

    const std::string picked_id = node_id->as_string();
    const ScreenNode* picked = nullptr;
    for (const auto& sn : reachable_col) {
        if (!sn.visited && sn.id == picked_id) {
            picked = &sn;
            break;
        }
    }
    if (!picked) {
        Log.warn(__FUNCTION__, "| VLM picked unreachable id", picked_id, ", fallback to first unvisited");
        for (const auto& sn : reachable_col) {
            if (!sn.visited) {
                picked = &sn;
                break;
            }
        }
    }
    if (!picked) {
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
        return true;
    }

    Point click_point(picked->rect.x + picked->rect.width / 2,
                      picked->rect.y + picked->rect.height / 2);
    Log.info(__FUNCTION__, "| VLM map node pick:", picked->id, type2name(picked->type),
             "click=", click_point.to_string());
    ctrler()->click(click_point);
    sleep(300);

    const std::string action_task = sarkaz_routing_action_for_node(picked->type);
    if (!action_task.empty()) {
        Task.set_task_base("RoguelikeRoutingAction", action_task);
    }
    else {
        Task.set_task_base("RoguelikeRoutingAction", "Sarkaz@RoguelikeRoutingAction-ExitThenAbandon");
    }
    return true;
}
