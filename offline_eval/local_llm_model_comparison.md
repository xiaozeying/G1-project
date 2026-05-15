# 本地大模型候选对比（面向现有功能保留与宇树 G1 适配）

## 1. 文档目的

本对比文档不是泛化的开源模型榜单，而是针对当前项目的真实目标进行筛选：

1. 尽量保留当前已完成的功能
2. 能接入现有 `OM1` 本地评测支线
3. 能输出稳定的结构化动作
4. 后续有机会适配宇树 `G1`
5. 尽量缩短本地推理时延
6. 不破坏当前 `interrupt` 主线能力边界

当前项目更看重的是：

- 普通话 / 粤语 / 英语三语言对话连续性
- 结构化动作稳定性
- 能力边界控制
- 本地部署成本
- 真机落地可能性

相比之下，纯数学推理分数、通用榜单名次、长文本能力，不是第一优先级。

## 2. 先说清楚：当前 `gemma4` 延迟数字的测试环境

这一点必须单独写清楚，否则会误导后续判断。

当前文档里提到的 `gemma4` 平均整轮时延约 `39s`，**不是 G1 Orin 板子的结果**，而是当前开发机上的本地 CPU 推理结果。

本次已知测试环境口径：

- 机器路径：`/home/zz/HongTu/...`
- CPU：`13th Gen Intel Core i7-13620H`
- 内存：`15 GiB`
- 推理方式：`Ollama` 本地 CPU 推理
- 当前机器未检测到可用 `nvidia-smi`

这意味着：

- 这组时延只能被视为“开发机 CPU 基线”
- **不能直接用来预测 G1 Orin 上的真实表现**
- 如果后续在 Orin 上能走 GPU/NPU 加速，时延表现可能明显不同

因此，本文档中所有 `gemma4` 时延结论都必须按下面这句话理解：

> `gemma4` 当前已证明功能可行，但当前时延结论仅代表开发机 CPU 基线，不代表 G1 Orin 真机结论。

## 3. 当前主线路与替换范围

根据当前项目记录，机器人主路径已经收口为：

```text
前门唤醒
  -> interrupt-frontgate.service
  -> realtime agent
  -> Gemini Live
  -> G1 / OM1 工具与本地反馈
```

见：

- [interrupt/PROJECT_PROGRESS.md](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/PROJECT_PROGRESS.md)

当前真机已验证能力包括：

- 三语言自适应对话
- assistant 回复支持被用户插话打断
- VLM 单帧视觉问答可工作

这意味着如果未来要把本地大模型从“评测支线”推进到“替代主链”，替换的不是单个 LLM，而是至少涉及三部分：

1. 对话 LLM
2. ASR
3. TTS

所以，**只比较文本 LLM 还不够**。

## 4. 当前已验证模型

### `gemma4:latest`

这是当前已经在本机 `Ollama` 上完成了完整 Phase 1 自动与手工评测的模型。

已落地产物：

- 自动批跑结果：[results_auto_gemma4.csv](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/offline_eval/results_auto_gemma4.csv)
- `ctx=2048` 对比结果：[results_auto_gemma4_ctx2048.csv](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/offline_eval/results_auto_gemma4_ctx2048.csv)
- 手工判读结果：[results_run_20260430_phase1_gemma4.csv](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/offline_eval/results_run_20260430_phase1_gemma4.csv)

优点：

- 已证明可以跑通本地离线闭环
- `speak / arm_movement / led_color` 三类动作可稳定输出
- 能较好控制能力边界
- 作为“功能可行性基线”价值很高

缺点：

- 当前时延结果是在开发机 CPU 上测得，不能外推到 G1 Orin
- 在当前开发机 CPU 环境下时延偏高
- 自动基线平均整轮时延约 `39s`
- 即便压缩 `num_ctx` 到 `2048`，平均时延改善也有限

结论：

`gemma4` 适合保留为“功能可行性基线模型”，但不适合在当前阶段直接被视为“G1 真机实时落地候选的最终结论”。

## 5. 粤语是单独维度，不等于“中文能力”

这一点需要和之前版本明确区分。

当前项目的真实需求不是“支持中文”，而是至少涉及：

- 普通话
- 粤语
- 英语

从现有项目记录看，`interrupt` 主线已经明确支持：

- 三语言自适应对话
- 粤语回答约束
- 专用粤语 TTS 回退链路

相关代码与记录见：

- [interrupt/PROJECT_PROGRESS.md](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/PROJECT_PROGRESS.md)
- [interrupt/src/agent.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/agent.py)
- [interrupt/src/cantonese_tts.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/cantonese_tts.py)

所以，模型筛选时不能再只写“中文能力强”，而要拆成两件事：

1. 普通话能力
2. 粤语能力

### 当前文档对粤语的真实状态

必须坦白说明：

- 目前 **还没有** 对 `Qwen2.5-3B`、`Qwen2.5-7B`、`Llama 3.2 3B`、`Phi-4-mini`、`Gemma 3 4B` 做过**独立粤语基准测试**
- 因此，现阶段所有“适合 G1 三语言目标”的判断，都还只是**候选优先级判断**，不是结论

### 现阶段能确认什么

基于官方材料，`Qwen2.5-3B-Instruct` 明确宣称支持 29+ 语言，并强调 instruction following 与 structured outputs / JSON 能力，但官方列出的语言说明并**没有单独对粤语做能力声明**。这意味着：

- 不能因为“支持中文”就推定“粤语也同样稳定”
- 必须单独测

参考：

- Qwen2.5-3B-Instruct model card: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct

### 粤语评估建议

后续 Phase 1.5 / Phase 2 应增加独立粤语集，至少覆盖：

1. 粤语自我介绍
2. 粤语动作命令
3. 粤语纠错命令
4. 粤语能力边界拒答
5. 粤语短期记忆回溯
6. 粤语与普通话混说

在没有这组测试之前，`Qwen2.5-3B` 只能说是：

> 最值得优先试的候选，不是已证明满足粤语目标的候选。

## 6. ASR / TTS 不是附属问题，而是整链核心

旧版本文档只比较了对话 LLM，这是不完整的。

如果目标是替换当前 `Gemini Realtime` 主链，必须同步看：

1. ASR
2. LLM
3. TTS

因为当前主线路里，Gemini Live 实际承担了“低延迟实时语音体验”的大头。

### 项目里已存在的本地 ASR / TTS 线索

从仓库现状看，已经存在几条本地或半本地路线：

#### ASR

- `OM1/config/conversation_local.json5` 使用 `RivaASRInput`
- `OM1` 里已有 `RivaASRInput` / `RivaASRRTSPInput` 相关测试
- 其他模式里大量使用 `GoogleASRInput`

#### TTS

- `OM1/config/conversation_local.json5` 使用 `kokoro_tts`
- `interrupt` 侧存在专用 `CantoneseTts` 回退实现
- 某些配置仍使用 `ElevenLabsTTS`

可参考：

- [OM1/config/conversation_local.json5](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1/config/conversation_local.json5)
- [interrupt/src/cantonese_tts.py](/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt/src/cantonese_tts.py)

### 这意味着什么

如果只替换 LLM 而不替换 ASR/TTS：

- 离线收益会打折
- 总时延不一定明显改善
- 粤语质量风险仍可能卡在 ASR/TTS，而不是卡在 LLM

### 因此，后续应把候选路线拆成两层

#### 路线 A：只替换 LLM

优点：

- 集成最小
- 最适合先验证动作协议稳定性

缺点：

- 不能回答“整条离线语音链路是否可替代”

#### 路线 B：替换 ASR + LLM + TTS

优点：

- 才能真正验证是否能替代 `Gemini Realtime`

缺点：

- 集成复杂度显著上升
- 粤语质量会成为第一风险点

### 建议增加一份并行选型表

后续技术选型建议按以下组合评估：

1. `ASR`
   - `RivaASR`
   - 现有云 ASR 保留
2. `LLM`
   - `Qwen2.5-3B`
   - `Qwen2.5-7B`
   - 其他对照组
3. `TTS`
   - `kokoro_tts`
   - 现有粤语 TTS 回退链
   - 当前主线路 TTS

结论：

> 旧版本文档只覆盖了 LLM，不能代表“整条替代链路”的完整结论。

## 7. 许可证风险不能只写成一个 bullet

这点你指出得非常对。

### `Qwen2.5-3B-Instruct` 当前许可证事实

截至当前可见官方模型卡与 LICENSE 文件：

- Hugging Face 模型页标识为 `License: qwen-research`
- LICENSE 文本标题为 `Qwen RESEARCH LICENSE AGREEMENT`
- 条款明确写到：
  - `Non-Commercial` 指“仅研究或评估用途”
  - 授予权利是“FOR NON-COMMERCIAL PURPOSES ONLY”
  - 商业使用需要向 Alibaba Cloud 申请单独许可

参考：

- 模型卡: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct
- LICENSE: https://huggingface.co/Qwen/Qwen2.5-3B/blob/main/LICENSE

### 这对当前项目意味着什么

如果这个项目只是内部研究、评测、技术验证：

- `Qwen2.5-3B-Instruct` 作为测试候选是合理的

如果这个项目未来可能：

- 商业部署
- 对外销售
- 随机器人整机交付
- 作为收费服务的一部分

那么：

- 不能把 `Qwen2.5-3B-Instruct` 直接视为默认可商用方案
- 必须尽早让法务 / 商务确认可接受范围
- 最好在技术选型阶段同时保留一条“许可更清晰”的备选模型路线

### 所以文档中的许可证结论应改成

`Qwen2.5-3B-Instruct` 是当前**技术上最值得优先测试**的候选之一，但在存在商业化可能的前提下，它同时是**许可证风险最高的候选之一**，不能只从性能角度决定。

## 8. 候选模型对比（修正版）

### A. `Qwen2.5-3B-Instruct`

定位：

- 技术上最值得优先测试
- 但许可证风险高，且粤语能力未验证

优点：

- 官方材料强调 instruction following、structured outputs、JSON
- 3B 量级更有机会降低本地推理时延
- 对“动作协议输出”这类任务较对口

缺点：

- 当前官方许可证是 `qwen-research`
- 已知许可证文本指向非商业 / 研究评测用途
- 粤语能力没有做独立验证
- 3B 小模型在复杂多轮场景下仍可能不稳定

适配 G1 评价：

- 作为“下一颗最该测的技术候选”成立
- 作为“可以放心商用落地的候选”目前不成立

建议优先级：

- `技术优先级最高`
- `许可证优先级需单独审查`

### B. `Qwen2.5-7B-Instruct`

定位：

- 如果 3B 不够稳时的上探档位

优点：

- 同一家族，迁移成本低
- 更可能提升复杂命令和结构化输出稳定性

缺点：

- 许可证问题不因参数变大而自动消失，仍需单独确认
- 更吃资源
- G1 真机时延和内存风险更高
- 粤语能力同样未单独验证

适配 G1 评价：

- 更像“能力增强候选”，不是第一颗下手模型

建议优先级：

- `高`

### C. `Llama 3.2 3B Instruct`

定位：

- 通用对照组

优点：

- 小尺寸，适合横向比较时延
- 通用生态成熟

缺点：

- 当前没有项目内粤语实测
- 对中文机器人动作场景不一定比 Qwen 更对口

适配 G1 评价：

- 适合做对照，不适合跳过 Qwen 直接主推

建议优先级：

- `中高`

### D. `Phi-4-mini-instruct`

定位：

- 轻量补充组

优点：

- 小模型路线明确
- 边缘部署友好

缺点：

- 当前没有项目内粤语实测
- 对机器人中文动作协议的贴合度暂不如 Qwen 明显

适配 G1 评价：

- 适合补充对照

建议优先级：

- `中`

### E. `Gemma 3 4B IT`

定位：

- Google 路线延续验证

优点：

- 与当前已验证 `gemma4` 家族衔接顺
- 4B 档更像边缘候选

缺点：

- 当前没有项目内粤语实测
- 即使家族相近，也不能直接继承 `gemma4` 的时延结论到 Orin

适配 G1 评价：

- 适合第二梯队

建议优先级：

- `中`

## 9. 不建议优先投入的模型

### `Qwen2.5-Coder`

不建议优先原因：

- 更偏代码，不是当前机器人语音动作主任务

### `Phi-4-mini-reasoning`

不建议优先原因：

- 更偏数学与逻辑推理，不是当前多语音交互主任务

## 10. 修正后的结论

如果目标是：

- 保住现有已完成功能
- 尽量不破坏当前 IA 主线
- 往宇树 G1 本地部署推进
- 兼顾普通话 / 粤语 / 英语
- 最终有商业化可能

那么修正后的结论应该是：

1. `gemma4` 已证明“开发机 CPU 上的离线功能可行”，但**不能**用 `39s` 去代表 G1 Orin 结论
2. `Qwen2.5-3B-Instruct` 仍然是**技术上最值得优先测试**的下一颗模型
3. 但 `Qwen2.5-3B-Instruct` 的**粤语能力和商业许可都还没有过关**
4. 文本 LLM 选型不能替代 ASR/TTS 选型，整链替代仍未完成

## 11. 下一步建议

建议按这个顺序继续推进：

1. 新增一份“开发机 CPU 结果不外推 G1 Orin”的说明
2. 新增粤语专测集
3. 为 ASR / TTS 单独补一份选型对比
4. 同时推进 `Qwen2.5-3B-Instruct` 技术验证与许可证确认
5. 在 Orin 真机上单独做一轮延迟与稳定性验证

一句话建议：

`Qwen2.5-3B-Instruct` 现在仍是最值得试的技术候选，但在“粤语能力、整链语音替代、商业许可证”这三件事没补齐之前，不能把它写成项目的确定答案。
