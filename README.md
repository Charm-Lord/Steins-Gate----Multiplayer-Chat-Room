# 未来道具研究所 · 闲聊群 (`lab_chat.py`)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Flask](https://img.shields.io/badge/Flask-Web_App-black)
![OpenAI SDK](https://img.shields.io/badge/OpenAI-SDK-10a37f)
![Streaming](https://img.shields.io/badge/Streaming-SSE-orange)
![Status](https://img.shields.io/badge/Status-Playable-brightgreen)
![License](https://img.shields.io/badge/License-Recommend_MIT-lightgrey)

一个基于 Flask + OpenAI SDK 的多角色群聊模拟项目。  
你在网页里输入一句话后，系统会由“导演（Director）”决定谁来接话、是否继续聊、何时自然收束，尽量还原真实群聊的节奏感。

## 目录

- [为什么这个项目有趣](#为什么这个项目有趣)
- [核心机制（代码亮点）](#核心机制代码亮点)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [安全与开源建议](#安全与开源建议)
- [可能的扩展方向](#可能的扩展方向)

## 为什么这个项目有趣

> 关键词：`多角色` `人设稳定` `群聊节奏` `流式输出` `上下文控量`

- **不是固定轮流发言**：通过 Director 状态机 + LLM 混合决策，动态选择下一位角色或结束回合。
- **角色人格更稳定**：每个角色都有独立 `character_memory`，减少“聊着聊着人设跑偏”。
- **群聊节奏更像真人**：加入“短句优先”“长度权重”“防连发”“反复读规则”等策略。
- **流式体验更顺滑**：后端使用 SSE (`text/event-stream`) 推送事件，前端用渲染队列模拟“正在输入”和逐字出现。
- **上下文控量**：短上下文 + 长摘要（`maybe_summarize`）结合，降低 token 压力。

## 核心机制（代码亮点）

### 1) Director 决策层

`标签：#状态机 #LLM决策 #JSON输出 #防死循环`

- 文件中的 `director_decide()` 不是纯随机，也不是纯 prompt。
- 它先有硬规则兜底（如 `MAX_ROUND`），再让 LLM 按“是否该继续聊”输出 JSON 决策。
- 对异常/无效决策有 fallback（例如首轮不能 `END`）。

### 2) Speaker 生成层

`标签：#角色记忆 #长度权重 #短句风格 #上下文拼装`

- `build_speaker_context()` 为每个角色构造独立上下文，注入：
  - 角色记忆
  - 群聊共通规则
  - 动态句数提示（1/2/3 句）
- `LENGTH_BIAS` + `pick_length()` 让不同角色“话痨程度”不同。

### 3) 前端节奏层

`标签：#SSE #渲染队列 #逐字动画 #可打断轮次`

- 使用“生产者-消费者”渲染队列（`renderQueue` + `renderLoop`）。
- 新输入会中断旧轮次（`currentRoundId` + `cancelRender`），避免消息串台。
- AI 回复会按 `||` 切分为多条短气泡，观感更接近微信聊天。

### 4) 对话压缩层

`标签：#摘要记忆 #Token控制 #长聊优化`

- 达到阈值后，`maybe_summarize()` 会把较早消息压缩为 2~3 句摘要。
- 后续生成继续看“摘要 + 最近消息”，在连贯性和成本之间平衡。

## 技术栈

> 关键词：`Flask` `OpenAI SDK` `SSE` `Vanilla JS`

- Python 3.9+
- Flask
- OpenAI Python SDK（兼容 `base_url` 指向第三方 API）
- 浏览器端原生 JavaScript + SSE

> 参考：SSE 是浏览器与服务端进行单向流式推送的常见方案，见 [MDN EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource)。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 填写 API Key（当前仓库默认留空）

`提示标签：#必做 #安全配置`

打开 `lab_chat.py`，在 `TEAM` 中填写你自己的密钥：

- `TEAM["冈部"]["api_key"]`
- `TEAM["Daru"]["api_key"]`
- `TEAM["红莉栖"]["api_key"]`
- `TEAM["真由理"]["api_key"]`

> `BASE_URL` 与 `MODEL` 也可按你的服务商调整。

### 3. 运行

```bash
python lab_chat.py
```

### 4. 打开页面

浏览器访问：`http://127.0.0.1:5002`

## 使用说明

`场景标签：#本地运行 #沉浸聊天 #记录导出`

- 在输入框发送任意消息，系统会自动开始多角色接话。
- 点击右上角“刷新”可重置当前会话。
- 点击“保存”会将聊天记录写入 `lab_chats/` 目录（JSON）。

## 安全与开源建议

`风险标签：#密钥泄露 #仓库合规 #许可证`

- 不要把真实 API Key 提交到 Git。
- 建议后续改为环境变量读取密钥（例如 `os.getenv`），进一步降低泄露风险。
- 建议添加开源许可证（如 MIT），方便他人合法复用。

## 可能的扩展方向

`Roadmap 标签：#可观测性 #可配置化 #易分享`

- 改成“一个总 Key + 多角色提示词”模式，降低密钥管理成本。
- 增加可视化控制面板（调温度、轮数、上下文长度、角色权重）。
- 为 Director 决策写回放日志，便于分析“为什么这轮结束/继续”。
- 支持导出 Markdown 对话记录，方便二次整理和分享。
