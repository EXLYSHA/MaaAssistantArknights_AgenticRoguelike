本次决策：在当前楼层的全部节点中选下一个去的可达节点。

你能看到整层的所有节点（含本步不可达的），可以做多步规划，把意图写到 `planned_path_next`。

启发：
- HP ≤ 3 优先 safehouse / shop / encounter（避战 + 补血）
- 队伍未成型时优先 shop（藏品）/ elite（精英战奖励多）
- 已成型阶段可冲 elite / boss
- 不期而遇 (encounter) 期望收益正，但有风险
- 商店多走一次比少走一次好（藏品复利）
