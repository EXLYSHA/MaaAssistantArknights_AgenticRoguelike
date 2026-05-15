# 集成战略（Roguelike）功能实现详解

本文档面向希望了解或参与开发集成战略自动化功能的开发者，系统讲解该功能在 MAA 代码库中的架构设计、核心模块和数据驱动规则体系。如需查阅具体 JSON 字段格式，可参考 [集成战略协议文档](../protocol/integrated-strategy-schema.md)。

---

## 目录

1. [一句话结论](#一句话结论)
2. [代码与资源目录结构](#代码与资源目录结构)
3. [启动链路](#启动链路)
4. [架构设计：插件系统](#架构设计插件系统)
5. [任务流程：状态机与 JSON 驱动](#任务流程状态机与-json-驱动)
6. [核心数据结构](#核心数据结构)
7. [各功能插件详解](#各功能插件详解)
8. [数据驱动配置体系](#数据驱动配置体系)
9. [图像识别层](#图像识别层)
10. [多主题支持](#多主题支持)
11. [状态保存在哪里](#状态保存在哪里)
12. [修改策略应该看哪里](#修改策略应该看哪里)
13. [读代码建议](#读代码建议)

---

## 一句话结论

集成战略功能不是端到端 AI，也不是实时规划整局游戏。它是一个**任务链 + 插件 + 资源规则**的数据驱动系统：

- `resource/tasks/Roguelike/*.json` 定义页面识别、点击、跳转和不同模式下的选点策略。
- `resource/roguelike/<主题>/` 定义主题相关规则，包括招募优先级、关卡作战作业、不期而遇选择、商店购买、特殊机制等。
- `src/MaaCore/Task/Roguelike/` 中的 C++ 插件在固定任务链中接管复杂决策，例如招募、编队、战斗部署、商店购买、事件选项、地图导航。
- UI 侧只负责把用户设置序列化成 `Roguelike` 任务参数，核心逻辑在 MaaCore 中执行。

整套系统把"经验打法"拆成可维护的固定规则：任务链负责找到正确页面，插件负责把截图解析成结构化状态，资源 JSON 给出当前状态下的优先级和动作。

---

## 代码与资源目录结构

```
src/MaaCore/
├── Task/
│   ├── Interface/
│   │   └── RoguelikeTask.h/.cpp          # 任务入口，组装所有插件
│   └── Roguelike/
│       ├── AbstractRoguelikeTaskPlugin.h/.cpp  # 所有插件的基类
│       ├── RoguelikeConfig.h/.cpp              # 共享状态与配置
│       ├── RoguelikeControlTaskPlugin.h/.cpp   # 流程控制（停止/重开判断）
│       ├── RoguelikeBattleTaskPlugin.h/.cpp    # 战斗自动部署
│       ├── RoguelikeRecruitTaskPlugin.h/.cpp   # 干员招募
│       ├── RoguelikeFormationTaskPlugin.h/.cpp # 快捷编队
│       ├── RoguelikeSkillSelectionTaskPlugin.h/.cpp  # 技能选择
│       ├── RoguelikeShoppingTaskPlugin.h/.cpp  # 商店购物
│       ├── RoguelikeStageEncounterTaskPlugin.h/.cpp  # 不期而遇事件
│       ├── RoguelikeInvestTaskPlugin.h/.cpp    # 源石锭投资
│       ├── RoguelikeSettlementTaskPlugin.h/.cpp # 结算处理
│       ├── RoguelikeDifficultySelectionTaskPlugin.h/.cpp  # 难度选择
│       ├── RoguelikeStrategyChangeTaskPlugin.h/.cpp       # 策略切换
│       ├── RoguelikeResetTaskPlugin.h/.cpp     # 重置/重开
│       ├── RoguelikeLevelTaskPlugin.h/.cpp     # 关卡层级管理
│       ├── RoguelikeCustomStartTaskPlugin.h/.cpp # 自定义开局
│       ├── RoguelikeLastRewardTaskPlugin.h/.cpp  # 最终奖励
│       ├── RoguelikeIterateMonthlySquadPlugin.h/.cpp      # 月度小队迭代
│       ├── RoguelikeIterateDeepExplorationPlugin.h/.cpp   # 深入调查迭代
│       ├── RoguelikeInputSeedTaskPlugin.h/.cpp  # 萨卡兹种子输入
│       ├── Map/
│       │   ├── RoguelikeMap.h/.cpp
│       │   ├── RoguelikeRoutingTaskPlugin.h/.cpp           # 路径导航
│       │   ├── RoguelikeBoskyPassageMap.h/.cpp
│       │   └── RoguelikeBoskyPassageRoutingTaskPlugin.h/.cpp
│       ├── Sami/
│       │   ├── RoguelikeFoldartalStartTaskPlugin.h/.cpp    # 密文板启动
│       │   ├── RoguelikeFoldartalUseTaskPlugin.h/.cpp      # 密文板使用
│       │   ├── RoguelikeFoldartalGainTaskPlugin.h/.cpp     # 密文板获取
│       │   └── RoguelikeCollapsalParadigmTaskPlugin.h/.cpp # 坍缩范式
│       └── JieGarden/
│           └── RoguelikeCoppersTaskPlugin.h/.cpp            # 常乐节点
│
├── Config/
│   └── Roguelike/
│       ├── RoguelikeRecruitConfig.h/.cpp       # 招募规则配置解析
│       ├── RoguelikeShoppingConfig.h/.cpp      # 购物规则配置解析
│       ├── RoguelikeStageEncounterConfig.h/.cpp # 事件选择配置解析
│       ├── RoguelikeMapConfig.h/.cpp           # 地图数据配置解析
│       ├── RoguelikeCopilotConfig.h/.cpp       # 战斗代理配置解析
│       ├── Sami/
│       │   ├── RoguelikeFoldartalConfig.h/.cpp
│       │   └── RoguelikeCollapsalParadigmConfig.h/.cpp
│       └── JieGarden/
│           └── RoguelikeCoppersConfig.h/.cpp
│
└── Vision/
    └── Roguelike/
        ├── RoguelikeRecruitImageAnalyzer.h/.cpp      # 招募界面 OCR
        ├── RoguelikeRecruitSupportAnalyzer.h/.cpp    # 助战干员识别
        ├── RoguelikeFormationImageAnalyzer.h/.cpp    # 快捷编队识别
        ├── RoguelikeSkillSelectionImageAnalyzer.h/.cpp
        ├── RoguelikeEncounterOptionAnalyzer.h/.cpp   # 事件选项 OCR
        ├── RoguelikeParameterAnalyzer.h/.cpp         # 参数识别
        └── JieGarden/
            └── RoguelikeCoppersAnalyzer.h/.cpp

resource/
├── tasks/Roguelike/
│   ├── base.json          # 通用任务流程定义（主状态机）
│   ├── routing.json       # 导航相关任务
│   ├── Phantom.json       # 傀影主题专用任务
│   ├── Mizuki.json        # 水月主题专用任务
│   ├── Sami.json          # 萨米主题专用任务
│   ├── Sarkaz.json        # 萨卡兹主题专用任务
│   └── JieGarden.json     # 界园主题专用任务
│
└── roguelike/
    ├── Phantom/
    │   ├── recruitment.json
    │   ├── shopping.json
    │   ├── encounter/default.json
    │   └── autopilot/*.json
    ├── Mizuki/    （同上结构）
    ├── Sami/      （同上 + collapsal_paradigms.json, foldartal.json）
    ├── Sarkaz/    （同上 + fragments.json, map.json）
    └── JieGarden/ （同上 + coppers.json, map.json）
```

---

## 启动链路

1. **GUI 提交参数**

   `AsstRoguelikeTask.Serialize()` 把用户在界面上填写的所有选项序列化，包括 `mode`、`theme`、`difficulty`、`starts_count`、`squad`、`roles`、`core_char`、`use_support` 等。

2. **创建 `RoguelikeTask`**

   `RoguelikeTask` 内部创建 `ProcessTask` 并注册全部插件（详见下节）。

3. **`set_params()` 校验并加载参数**

   `RoguelikeConfig::verify_and_load_params()` 校验主题和模式，记录当前主题、模式、难度、分队等，并根据模式绑定策略切换任务（`Roguelike@StrategyChange_modeX`）。

4. **主任务从 `{theme}@Roguelike@Begin` 开始**

   基础定义在 `resource/tasks/Roguelike/base.json`，主题文件（如 `Sami.json`、`Sarkaz.json`）会覆盖或补充主题差异。

5. **`ProcessTask` 驱动主循环**

   持续截图，依次尝试 `next[]` 中的任务候选，命中后执行对应的点击或调用已注册插件进行复杂决策。

---

## 架构设计：插件系统

集成战略的核心架构是**插件系统**。`RoguelikeTask` 创建一个 `ProcessTask`，向它注册约 20 个功能插件，每个插件独立负责一块功能：

```
RoguelikeTask
  └── ProcessTask（主循环，逐帧截图识别当前界面）
        ├── RoguelikeControlTaskPlugin      ← 控制流（重开/停止决策）
        ├── RoguelikeFormationTaskPlugin    ← 快捷编队
        ├── RoguelikeRecruitTaskPlugin      ← 干员招募
        ├── RoguelikeBattleTaskPlugin       ← 战斗部署
        ├── RoguelikeSkillSelectionTaskPlugin ← 技能选择
        ├── RoguelikeShoppingTaskPlugin     ← 商店购物
        ├── RoguelikeStageEncounterTaskPlugin ← 不期而遇
        ├── RoguelikeInvestTaskPlugin       ← 投资源石锭
        ├── RoguelikeSettlementTaskPlugin   ← 结算
        ├── RoguelikeDifficultySelectionTaskPlugin
        ├── RoguelikeStrategyChangeTaskPlugin
        ├── RoguelikeCustomStartTaskPlugin
        ├── RoguelikeResetTaskPlugin
        ├── RoguelikeLevelTaskPlugin
        ├── RoguelikeLastRewardTaskPlugin
        ├── RoguelikeIterateMonthlySquadPlugin
        ├── RoguelikeIterateDeepExplorationPlugin
        ├── （萨米）RoguelikeFoldartal*TaskPlugin
        ├── （萨米）RoguelikeCollapsalParadigmTaskPlugin
        ├── （萨卡兹）RoguelikeInputSeedTaskPlugin
        ├── （界园）RoguelikeCoppersTaskPlugin
        └── Map/RoguelikeRoutingTaskPlugin 等
```

所有插件继承自 `AbstractRoguelikeTaskPlugin`，共享同一个 `RoguelikeConfig` 实例（持有全局状态）和 `RoguelikeControlTaskPlugin`（负责发出重开/停止指令）。

`ProcessTask` 主循环在每次截图后，依次询问已注册的插件："当前画面你能处理吗？"若插件识别到属于自己管辖的界面，则执行相应逻辑。

---

## 任务流程：状态机与 JSON 驱动

### ProcessTask 与 tasks.json

MAA 使用基于任务链的状态机。`ProcessTask` 维护"当前任务"，每步执行后根据 JSON 中的 `next[]` 列表跳转到下一个任务。集成战略的主流程定义在 `resource/tasks/Roguelike/base.json`。

### 主流程简图

```
{theme}@Roguelike@Begin（入口）
  │
  ├─ Roguelike@ChooseDifficulty     选择难度
  │
  └─ Roguelike@StartExplore         开始/继续探索（可循环 N 次）
       │
       ├─ 快捷编队（Formation）
       ├─ 干员招募（Recruit → ChooseOper）
       │
       └─ Roguelike@Stages          进入关卡循环
            │
            ├─ Roguelike@InBattle / Roguelike@StartAction   战斗
            ├─ Roguelike@DropsFlag      战后奖励选择
            ├─ Roguelike@ChooseOperFlag 新干员选择
            ├─ 不期而遇（StageEncounterJudgeOption）
            ├─ 商店（TraderRandomShopping）
            │
            ├─ Roguelike@NextLevel      进入下一层 → 循环回 Stages
            ├─ Roguelike@GamePass       通关结算
            └─ Roguelike@ExitThenAbandon  主动退出 → 回到 Begin 重开
```

### 任务节点示例（base.json）

```json
"Roguelike@Begin": {
    "action": "DoNothing",
    "next": [
        "Roguelike@StartExplore",
        "Roguelike@Stages#next",
        "Roguelike@NextLevel",
        "Roguelike@ExitThenAbandon"
    ]
}
```

`next[]` 每一项是 ProcessTask 依次截图尝试匹配的候选任务，命中第一个匹配任务后跳转执行。

---

## 核心数据结构

### 运行模式 `RoguelikeMode`（`RoguelikeConfig.h`）

| 值 | 名称 | 目的 |
|---|---|---|
| `0` | `Exp` | 刷等级/经验，激进策略，尽量多打层数 |
| `1` | `Investment` | 刷源石锭，第一层投资后退出 |
| `3` | `Ending` | 尝试通关，激进策略 |
| `4` | `Collectible` | 刷开局奖励/凹开局精二 |
| `5` | `CLP_PDS` | 萨米专用，刷隐藏坍缩范式 |
| `6` | `Squad` | 月度小队 |
| `7` | `Exploration` | 深入调查 |
| `10001` | `FastPass` | 萨卡兹专用，快速通过第一层 |
| `20001` | `FindPlaytime` | 界园专用，刷常乐节点 |

### 局内动态状态 `RoguelikeStatus`

```cpp
struct RoguelikeStatus {
    int hope = 0;                     // 当前希望值（货币）
    int hp = 0;                       // 当前生命值
    int floor = 0;                    // 已到达层数
    int formation_upper_limit = 6;    // 编队上限
    // 已招募干员、已拥有藏品、萨米/萨卡兹/界园特殊状态等...
};
```

各插件读写此结构共享局内状态：招募插件写入干员，商店插件据此判断是否购买职业藏品，战斗插件据此获取干员技能策略，编队插件据此补阵容。

### 干员信息 `RoguelikeOper`

```cpp
struct RoguelikeOper {
    int elite = 0;   // 精英化等级
    int level = 0;   // 干员等级
};
```

---

## 各功能插件详解

### 1. RoguelikeRecruitTaskPlugin —— 干员招募

**核心流程：**

1. 判断是否是开局招募，若有 `core_char` 则优先招募指定开局干员
2. 用 `RoguelikeRecruitImageAnalyzer` 扫描招募列表，识别干员名、精英化、等级（支持翻页）
3. 查询 `recruitment.json`，为每位候选干员计算最终 `recruit_priority`
4. 应用 `recruit_priority_offsets`（条件性优先级偏移）
5. 按最终优先级排序，点击选择最高优先级干员
6. 将招募结果写入 `RoguelikeStatus.opers`

### 2. RoguelikeBattleTaskPlugin —— 战斗自动部署

战斗时调用通用 `BattleHelper` 模块，策略来自 `autopilot/*.json`：

1. OCR 识别当前关卡名
2. 通过 `TilePack` 查找地图瓦片数据（蓝门、可部署格、方向按钮等）
3. 从 `RoguelikeCopilotConfig` 读取对应关卡的 `deploy_plan`
4. 若有 `deploy_plan`，按干员分组、部署顺序、击杀数条件、位置、方向匹配当前可用干员依次部署
5. 若无可用作业则进入通用部署逻辑（按职业顺序、蓝门压力等计算）
6. 循环识别费用、击杀数、干员冷却，自动开技能、按条件撤退

### 3. RoguelikeStageEncounterTaskPlugin —— 不期而遇

**核心流程：**

1. OCR 识别事件标题，在 `RoguelikeStageEncounterConfig` 中查找规则
2. 默认按 `choose` 字段选择固定选项
3. 若配置了 `choices.requirements`，根据当前视野值/藏品条件选择对应选项
4. 若点击后界面未响应，尝试 `fallback_choices`

### 4. RoguelikeShoppingTaskPlugin —— 商店购物

1. OCR 识别商店商品名
2. 根据当前队伍统计职业、练度、待晋升干员
3. 按 `shopping.json` 优先级从上到下匹配商品，检查是否满足购买条件
4. 萨米刷坍缩范式模式会跳过降低坍缩值的商品

### 5. RoguelikeInvestTaskPlugin —— 源石锭投资

Investment 模式下，第一层战斗结束后进入商店投资源石锭，然后主动触发 `ExitThenAbandon` 快速重开。

### 6. RoguelikeFormationTaskPlugin —— 快捷编队

1. 扫描所有编队页，优先选取 `team_complete_condition` 中核心分组的干员
2. 再补其他非预备干员，直到编队上限
3. 依赖 `recruitment.json` 的分组定义，不维护独立评价体系

### 7. RoguelikeControlTaskPlugin —— 流程控制

负责全局的"继续/重开/停止"决策：检查运行次数上限、结算通关/失败状态，在需要重开时触发 `ExitThenAbandon` 并重置局内状态。

### 8. 萨米主题专用插件

- **RoguelikeFoldartalGainTaskPlugin**：获得密文板时记录
- **RoguelikeFoldartalUseTaskPlugin**：在合适时机按规则使用密文板
- **RoguelikeFoldartalStartTaskPlugin**：处理开局密文板选择
- **RoguelikeCollapsalParadigmTaskPlugin**：识别和处理坍缩范式，`CLP_PDS` 模式下以最大化坍缩值为目标

### 9. 地图导航插件

- **RoguelikeRoutingTaskPlugin**：用于萨卡兹 `FastPass`/`FastInvestment`、界园指挥分队高难快速通过
- **RoguelikeBoskyPassageRoutingTaskPlugin**：界园树洞地图和常乐节点路线

地图识别通过模板匹配识别节点类型，构造 `RoguelikeMap` 后为不同节点设置成本值，若预计战斗数过多则退出重开。

---

## 数据驱动配置体系

### recruitment.json

```json
{
    "theme": "Phantom",
    "priority": [
        {
            "name": "分组名",
            "opers": [
                {
                    "name": "棘刺",
                    "skill": 3,
                    "alternate_skill": 1,
                    "skill_usage": 1,
                    "is_key": true,
                    "is_start": true,
                    "recruit_priority": 810,
                    "promote_priority": 1000,
                    "promote_priority_when_team_full": 1200,
                    "recruit_priority_offsets": [
                        {
                            "groups": ["地面阻挡", "地面单切", "棘刺"],
                            "is_less": true,
                            "threshold": 1,
                            "offset": 200
                        }
                    ]
                }
            ]
        }
    ]
}
```

**关键字段：**

| 字段 | 含义 |
|---|---|
| `recruit_priority` | 招募优先级（0-1000，越高越优先） |
| `promote_priority` | 晋升优先级 |
| `is_key` | 核心干员（用于判断队伍是否完整） |
| `is_start` | 适合作为开局干员 |
| `skill` / `alternate_skill` | 战斗中使用的技能编号（1-3） |
| `skill_usage` | 0=不用，1=自动，2=手动 |
| `recruit_priority_offsets` | 根据队伍组成动态调整优先级 |

`recruit_priority_offsets` 示例：`is_less: true, threshold: 1, offset: 200` 表示"当已有该组干员 < 1 人时，此干员优先级 +200"，用于表达"缺什么补什么"的逻辑。

### encounter/default.json

```json
{
    "stage": [
        {
            "name": "随到随取",
            "option_num": 2,
            "choose": 2,
            "choices": [
                {
                    "name": "使用热像仪",
                    "requirements": [
                        { "name": "Vision", "type": ">", "value": "3" }
                    ]
                }
            ]
        }
    ]
}
```

支持的条件：
- `Vision`：视野值数值比较（`>`/`<`/`=`）
- `Relic`：是否拥有指定藏品（`have`）

### autopilot/{stage}.json（战斗部署策略）

```json
{
    "stage_name": "事不过四",
    "replacement_home": [
        { "location": [5, 1], "direction": "left" }
    ],
    "blacklist_location": [[2, 2]],
    "deploy_plan": [
        {
            "groups": ["锏", "核心干员"],
            "location": [5, 1],
            "direction": "left"
        },
        {
            "groups": ["地面阻挡"],
            "location": [4, 1],
            "direction": "left"
        },
        {
            "groups": ["高台输出"],
            "location": [6, 2],
            "direction": "down"
        }
    ]
}
```

`groups` 引用 `recruitment.json` 中的分组名，系统从队伍中找到属于该分组的干员按顺序部署。

### shopping.json

```json
{
    "theme": "Phantom",
    "priority": [
        { "name": "藏品名称", "priority": 800 }
    ]
}
```

---

## 图像识别层

所有"判断当前在哪个界面"都依赖图像识别：

1. **模板匹配**：`ProcessTask` 对每个候选任务做截图模板匹配（tasks.json 的 `template` 字段），确认当前界面
2. **OCR 识别**：确认界面后用 OCR 读取干员名、事件选项文字、数值等
3. **插件响应**：识别成功后调用对应插件的钩子

专用分析器位于 `src/MaaCore/Vision/Roguelike/`，包括招募界面 OCR、编队识别、事件选项 OCR、参数识别（希望/血量值）等。

---

## 多主题支持

五个主题（傀影、水月、萨米、萨卡兹、界园）通过以下机制区分：

1. **任务名前缀**：通用任务用 `Roguelike@` 前缀，主题专用任务用主题名前缀（如 `Phantom@Roguelike@GamePassSkip1Confirm`）
2. **配置文件隔离**：每个主题在 `resource/roguelike/{theme}/` 下有独立数据
3. **插件条件启用**：主题专用插件在 `load_params()` 时根据主题参数决定是否激活
4. **多服务器适配**：`resource/global/{server}/resource/tasks/Roguelike/` 存放各服务器界面差异的任务覆盖

---

## 状态保存在哪里

单局运行状态保存在 `RoguelikeConfig::status()`，包括：

- 当前希望、生命、层数、编队上限
- 已招募干员及精英化/等级
- 已获得藏品、队伍是否成型、商店是否不再购买
- 萨米：坍缩值、密文板状态
- 萨卡兹：构想和思维负荷
- 界园：票券状态

---

## 修改策略应该看哪里

| 目标 | 优先修改 |
|---|---|
| 改招募优先级、开局核心、技能使用 | `resource/roguelike/<主题>/recruitment.json` |
| 改某关怎么打 | `resource/roguelike/<主题>/autopilot/<关卡名>.json` |
| 改不期而遇选项 | `resource/roguelike/<主题>/encounter/default.json` |
| 改商店买什么 | `resource/roguelike/<主题>/shopping.json` |
| 改地图节点优先级 | `resource/tasks/Roguelike/<主题>.json` 中的 `StrategyChange_mode*` 和 `Stages*` |
| 改萨卡兹/界园特殊路线 | `RoguelikeRoutingTaskPlugin`、`RoguelikeBoskyPassageRoutingTaskPlugin` 及对应 `map.json` |
| 新增主题 | 补 `resource/tasks/Roguelike/<主题>.json`、`resource/roguelike/<主题>/...`，并在 `RoguelikeTheme`、`ResourceLoader` 中注册 |

---

## 读代码建议

建议按以下顺序读：

1. [`src/MaaCore/Task/Interface/RoguelikeTask.cpp`](../../../src/MaaCore/Task/Interface/RoguelikeTask.cpp)：先看入口、插件注册和 `set_params()`
2. [`resource/tasks/Roguelike/base.json`](../../../resource/tasks/Roguelike/base.json)：理解 `Begin`、`ChooseOper`、`Stages`、`DropsFlag`、`StartAction` 等任务节点
3. 一个主题文件，例如 [`resource/tasks/Roguelike/Sami.json`](../../../resource/tasks/Roguelike/Sami.json)：看主题如何覆盖基础任务
4. [`RoguelikeRecruitTaskPlugin`](../../../src/MaaCore/Task/Roguelike/RoguelikeRecruitTaskPlugin.cpp) + 一个 [`recruitment.json`](../../../resource/roguelike/Sami/recruitment.json)：理解"规则化招募"的核心
5. [`RoguelikeBattleTaskPlugin`](../../../src/MaaCore/Task/Roguelike/RoguelikeBattleTaskPlugin.cpp) + 一个 `autopilot/` 作业：理解战斗执行
6. [`RoguelikeStageEncounterTaskPlugin`](../../../src/MaaCore/Task/Roguelike/RoguelikeStageEncounterTaskPlugin.cpp) + `encounter/default.json`：理解事件选择
7. [`RoguelikeShoppingTaskPlugin`](../../../src/MaaCore/Task/Roguelike/RoguelikeShoppingTaskPlugin.cpp) + `shopping.json`：理解商店规则

---

## 辅助开发工具

`tools/` 目录下提供了几个脚本帮助维护配置数据：

| 工具 | 路径 | 用途 |
|---|---|---|
| RoguelikeRecruitmentTool | `tools/RoguelikeRecruitmentTool/` | 可视化编辑干员招募优先级 |
| RoguelikeOperSearch | `tools/RoguelikeOperSearch/` | 搜索干员在哪些 JSON 中被引用 |
| RoguelikeRelicsExtractor | `tools/RoguelikeRelicsExtractor/` | 从游戏数据提取藏品信息 |
