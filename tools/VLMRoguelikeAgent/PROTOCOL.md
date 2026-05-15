# MaaCore ↔ VLM Agent 通信协议 (v0.2)

本地 HTTP，JSON over POST。所有截图用 base64 PNG。

## 通用约定

### 会话管理

每局开始时由 MaaCore 调用 `POST /session/start` 拿到 `session_id`，整局所有决策请求都带上这个 ID。Agent 端在 session 中维持上下文（已招干员、已得藏品、决策历史、地图规划等），实现累积式记忆。

局结束（通关/失败/主动退出）调用 `POST /session/end` 清理。

### 通用请求字段

所有 `/decide/*` 端点都接受：

```
{
    "session_id": "...",
    "screenshots": ["<base64 PNG>", "..."],   // 至少 1 张；多图用于翻页/拼接整层
    "context": { ... 端点专属 ... }
}
```

`screenshots` 总是数组（即便只有一张）。地图全景、招募翻页、分队滑动等场景由 C++ 端先收集多张图后整体提交。

### 通用响应字段

所有响应都形如：

```
{
    "action": "<具体动作类型 | inspect>",
    "reasoning": "<VLM 给出的理由，用于日志>",
    "confidence": 0.0-1.0,
    ...                                       // 端点专属字段
}
```

### 侦察动作 `action: "inspect"`

任何决策端点都可返回 `inspect`，请求 C++ 端展开某项详情后再决策：

```
{
    "action": "inspect",
    "target": {
        "kind": "operator_skill | relic_tooltip | enemy_info | option_detail",
        "ref": "棘刺 | <候选下标> | <option_index>"
    },
    "reasoning": "需要看技能 3 的描述决定是否招"
}
```

C++ 端收到后执行对应的"hover/点击展开"动作，截新图，**用同一 session_id 重新发起原决策请求**，新增的图追加到 `screenshots` 末尾。单次决策最多允许 **2 轮 inspect**，超出后 agent 端强制返回最佳猜测，避免死循环。

### 错误处理

- HTTP 5xx / 超时（>30s）/ schema 不合法：MaaCore 回退到原有 JSON 规则
- 单局期间累计回退 ≥3 次：完全切回非 VLM 模式跑完该局
- 单次决策最多 2 轮 inspect

---

## 端点定义

### 1. `POST /session/start`

```
请求:
{
    "theme": "Sarkaz",
    "mode": 30001,
    "difficulty": 15,
    "goal_hint": "通关",
    "client_version": "..."
}

响应:
{ "session_id": "sess-...", "vlm_model": "claude-sonnet-4-6 | mock" }
```

### 2. `POST /session/end`

```
请求:
{ "session_id": "...", "outcome": "pass|fail|abandon", "floor_reached": 6 }

响应: { "ok": true }
```

### 3. `POST /decide/squad`  *（开局选分队）*

```
context:
{
    "available_squads": ["蓝图测绘分队", "心胜于物分队", "...（C++ 端滑动 OCR 收集全部）"],
    "user_hint": "（可选，用户指定偏好）"
}

响应:
{ "action": "pick", "squad_name": "蓝图测绘分队", "reasoning": "...", "confidence": 0.9 }
```

### 4. `POST /decide/recruit`

```
context:
{
    "floor": 2,
    "hope": 5,
    "is_start_recruit": false,
    "current_roster": [
        {"name": "棘刺", "elite": 2, "level": 60, "groups": ["地面阻挡", "棘刺"]}
    ],
    "candidates": [
        {"name": "维什戴尔", "elite": 2, "level": 60, "groups": ["益达"]},
        ...
    ],
    "remaining_group_needs": { "高台输出": 1, "奶": 1 }
}

响应:
{ "action": "pick|skip|refresh", "pick_index": 0, "reasoning": "...", "confidence": 0.85 }
```

注：`screenshots` 含翻页扫描到的所有候选图。

### 5. `POST /decide/skill_selection`  *（精英化或战前技能选择）*

```
context:
{
    "operator": "棘刺",
    "occasion": "promote|pre_battle",
    "skills": [
        {"index": 1, "name_ocr": "...", "desc_ocr": "（OCR 可能为空，让 VLM 自己看图）"},
        {"index": 2, "name_ocr": "..."},
        {"index": 3, "name_ocr": "..."}
    ],
    "current_roster_summary": "..."
}

响应:
{ "action": "pick", "skill_index": 3, "reasoning": "...", "confidence": 0.9 }
```

### 6. `POST /decide/pre_battle_team`  *（战前选上场干员）*

替换 `RoguelikeFormationTaskPlugin` 的自动逻辑。

```
context:
{
    "stage_name": "丛林密布",
    "formation_limit": 6,
    "full_roster": [
        {"name": "棘刺", "elite": 2, "level": 60, "groups": [...]},
        ...
    ],
    "stage_required_groups": ["地面阻挡", "高台输出"]
}

响应:
{
    "action": "form",
    "selected": ["棘刺", "维什戴尔", "...", "...", "...", "..."],
    "reasoning": "...",
    "confidence": 0.85
}
```

### 7. `POST /decide/encounter`

```
context:
{
    "floor": 3,
    "hope": 7, "hp": 4, "vision": 5,
    "event_name_ocr": "随到随取",
    "options_ocr": ["开锁查看", "使用热像仪"],
    "current_relics": ["安玛的爱", "暮临"]
}

响应:
{ "action": "choose", "option_index": 1, "reasoning": "...", "confidence": 0.9 }
```

### 8. `POST /decide/shopping`

```
context:
{
    "floor": 2, "hope": 12,
    "shop_items": [
        {"name": "源石锭", "price": 3, "type": "currency"},
        {"name": "夜莺的歌声", "price": 8, "type": "relic"},
        {"name": "棘刺·晋升", "price": 5, "type": "promote", "operator": "棘刺"}
    ],
    "current_roster_summary": "...",
    "current_relics": ["..."]
}

响应:
{ "action": "buy_list", "purchases": [2, 1], "reasoning": "...", "confidence": 0.8 }
```

### 9. `POST /decide/map_node`  *（看单层全景）*

C++ 端先做"整层采集"：滑动 + 拼接，识别所有节点。

```
context:
{
    "floor": 4,
    "hope": 3, "hp": 3,
    "all_nodes_in_floor": [
        {"id": "n_a", "type": "battle",     "name": "丛林密布",       "depth_from_start": 1, "reachable_now": true,  "click_point": [340, 280]},
        {"id": "n_b", "type": "encounter",  "name": null,             "depth_from_start": 1, "reachable_now": true,  "click_point": [620, 290]},
        {"id": "n_c", "type": "shop",       "name": null,             "depth_from_start": 2, "reachable_now": false, "click_point": [880, 270]},
        {"id": "n_d", "type": "safehouse",  "name": null,             "depth_from_start": 3, "reachable_now": false, "click_point": [1080, 260]},
        {"id": "n_e", "type": "boss",       "name": "...",            "depth_from_start": 4, "reachable_now": false, "click_point": [1180, 260]}
    ],
    "planned_path_so_far": ["n_a"],
    "current_roster_summary": "..."
}

响应:
{
    "action": "goto",
    "node_id": "n_b",
    "planned_path_next": ["n_b", "n_c", "n_d", "n_e"],   // 可选，agent 内部规划
    "reasoning": "HP 仅剩 3，避战优先补希望，事件可能给藏品",
    "confidence": 0.75
}
```

`screenshots` 含整层拼接图（C++ 端水平滑动采集后传 2-3 张即可，VLM 视觉拼接）。Agent 端把 `planned_path_next` 写入 session，下一次决策时复用以保持连贯。

### 10. `POST /decide/level_reward`  *（每层结算奖励选择）*

```
context:
{
    "floor": 3,
    "reward_type": "battle_drop|level_clear|elite_drop",
    "options": [
        {"index": 0, "kind": "relic", "name": "夜莺的歌声"},
        {"index": 1, "kind": "operator_recruit", "name": "酒神"},
        {"index": 2, "kind": "hope", "value": 3},
        {"index": 3, "kind": "skip"}
    ],
    "current_roster_summary": "...",
    "current_relics": ["..."]
}

响应:
{ "action": "pick", "option_index": 1, "reasoning": "...", "confidence": 0.85 }
```

### 11. `POST /decide/battle_plan`  *(v1.5，可选)*

战前生成定制 deploy_plan，仅当现有 autopilot 在当前队伍下被预判执行不了时触发。返回字段中 `operator` 用具体名（不是 groups），绕开分组匹配。

```
响应 plan 结构:
{
    "stage_name": "丛林密布",
    "replacement_home": [{"location": [9,4], "direction": "left"}],
    "deploy_plan": [
        {"operator": "棘刺", "location": [9,3], "direction": "down", "skill": 3},
        ...
    ]
}
```

---

## C++ 端集成点

| 现有插件 | VLM 模式下行为 |
|---|---|
| `RoguelikeCustomStartTaskPlugin` (squad 部分) | `/decide/squad` |
| `RoguelikeRecruitTaskPlugin` | 翻页扫描后调 `/decide/recruit` |
| `RoguelikeSkillSelectionTaskPlugin` | `/decide/skill_selection` |
| `RoguelikeFormationTaskPlugin` | `/decide/pre_battle_team` |
| `RoguelikeStageEncounterTaskPlugin` | `/decide/encounter` |
| `RoguelikeShoppingTaskPlugin` | `/decide/shopping` |
| `RoguelikeRoutingTaskPlugin` / 地图选点 | 整层采集后调 `/decide/map_node` |
| `RoguelikeLastRewardTaskPlugin` / 关卡奖励 | `/decide/level_reward` |
| `RoguelikeBattleTaskPlugin` | v1 不动；v1.5 调 `/decide/battle_plan` |

新增 `RoguelikeVLMAgentPlugin` 不接管界面，仅承载 HTTP 客户端 + session_id + inspect 重试逻辑，各决策插件按 `RoguelikeConfig.mode == VLMAgent` 切换分支。

---

## 知识库 (`knowledge/`)

Agent 启动时加载，作为静态上下文注入 system prompt：

- `sarkaz_overview.md` — 主题机制（构想、思维负荷、碎片、坍缩等）
- `sarkaz_relics_full.json` — 全部藏品名 → 效果描述
- `sarkaz_skills.json` — 关键干员 → 各技能描述
- `sarkaz_group_manifest.json` — 由 `tools/build_group_manifest.py` 从 autopilot/*.json 预处理生成的"全主题分组需求"

静态知识库优先 + 视觉兜底 + `inspect` 主动侦察，三层保证 VLM 拿到决策所需信息。
