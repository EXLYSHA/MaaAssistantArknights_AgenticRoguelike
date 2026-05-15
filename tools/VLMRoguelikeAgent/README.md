# VLM Roguelike Agent

一个独立的 Python sidecar，负责用 VLM 替代 Sarkaz 集成战略中所有"决策类"环节。

## 角色分工

| 端 | 职责 |
|---|---|
| **MaaCore (C++)** | 任务链识别界面、截图、执行点击。新增 `RoguelikeVLMAgentPlugin` 在决策点把截图 + 状态 POST 给本 sidecar，收到结构化动作后执行。 |
| **VLM Agent (本目录, Python)** | 本地 HTTP server。维护每局会话状态，调 OpenAI 或 Claude API，把"决策请求"翻译成具体动作。 |

## 目录结构

```
tools/VLMRoguelikeAgent/
├── README.md              ← 本文件
├── PROTOCOL.md            ← C++ ↔ Python HTTP 协议定义
├── server.py              ← FastAPI 入口
├── build_prts_knowledge.py ← 从本地 PRTS raw cache 生成干员 / 藏品压缩知识
├── agent/                 ← 业务逻辑
│   ├── session.py         ← 单局会话状态（roster / relics / floor / history）
│   ├── vlm_client.py      ← OpenAI / Anthropic SDK 封装
│   ├── decisions/         ← 各决策类型的处理器
│   │   ├── recruit.py
│   │   ├── encounter.py
│   │   ├── shopping.py
│   │   └── map_node.py
│   └── knowledge_loader.py ← 加载 Sarkaz 静态知识
├── prompts/               ← 提示词模板（与代码解耦）
│   ├── system_base.md
│   ├── recruit.md
│   ├── encounter.md
│   ├── shopping.md
│   └── map_node.md
├── schemas/               ← 决策请求/响应 JSON Schema
│   ├── recruit.json
│   ├── encounter.json
│   ├── shopping.json
│   └── map_node.json
├── knowledge/             ← Sarkaz 主题知识（人工整理 + 预处理生成）
│   ├── sarkaz_overview.md          ← 主题机制总览（构想、思维负荷、路线节点）
│   ├── sarkaz_relics_full.json     ← PRTS 想象实体图鉴压缩索引
│   ├── sarkaz_skills.json          ← PRTS 干员技能压缩索引
│   ├── operators_prts_compact.json ← PRTS 干员属性 / 特性 / 天赋 / 技能压缩索引
│   ├── prts_raw/                   ← 已下载的 PRTS 原始 wikitext，本地生成输入
│   ├── prts_sources.md             ← 生成来源和条目计数
│   └── sarkaz_group_manifest.json  ← 由 autopilot/*.json 预处理生成的分组需求
├── build_group_manifest.py         ← 预处理脚本：扫 autopilot 生成 manifest
├── tests/
│   └── mock_session.py             ← 离线 mock：不调真 API，跑通流程
└── requirements.txt
```

## 启动方式

```bash
cd tools/VLMRoguelikeAgent
pip install -r requirements.txt
```

使用 OpenAI / ChatGPT API：

```bash
export OPENAI_API_KEY=sk-...
export VLM_PROVIDER=openai
export VLM_MODEL=gpt-5.4-mini
export VLM_MOCK=0
python server.py --port 8765 --trace
```

使用 Claude API：

```bash
export ANTHROPIC_API_KEY=sk-...
export VLM_PROVIDER=anthropic
export VLM_MOCK=0
python server.py --port 8765 --trace
```

MaaCore 端通过 `RoguelikeVLMAgentPlugin` 配置项指定 `agent_url=http://127.0.0.1:8765`。

未设置 `VLM_MOCK=0` 时默认走 mock，不会消耗真实 API。未显式设置 `VLM_PROVIDER` 时，优先沿用 `ANTHROPIC_API_KEY`，否则使用 `OPENAI_API_KEY`。

## 调试 GUI

sidecar 自带本地 Web 调试页：

```text
http://127.0.0.1:8765/debug
```

使用 `--trace` 启动后，每次 VLM 决策都会实时出现在页面左侧。点开一次决策可以看到截图、context、user prompt、system prompt、模型原始输出和最终归一化后的 decision。对应文件也会写入 `trace/`。

不想消耗真实 VLM 调用时可以用 mock 模式验证链路：

```bash
cd tools/VLMRoguelikeAgent
VLM_MOCK=1 python server.py --port 8765 --trace
python tests/mock_session.py
```

## 本地知识生成

```bash
cd tools/VLMRoguelikeAgent
python build_prts_knowledge.py
```

默认不访问网络，只从 `knowledge/prts_raw/` 的本地 PRTS 原始 wikitext 生成压缩知识，并结合 `resource/roguelike/Sarkaz/recruitment.json` 写入本地索引。运行 sidecar 时也只读取这些本地生成文件。

只有需要更新 PRTS 原始缓存时才显式联网：

```bash
python build_prts_knowledge.py --download
```

若只想生成 Maa 萨卡兹配置中引用的干员，可加 `--sarkaz-only`。

## 模式开关

在 `Roguelike` 任务参数中传入 `mode = 30001`（`RoguelikeMode::VLMAgent`）即可启用 VLM 决策路径。该 mode 仅对 Sarkaz 主题生效，其他主题报错。
