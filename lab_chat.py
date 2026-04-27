#!/usr/bin/env python3
"""
未来道具研究所 · 闲聊群
命运石之门角色 AI 群聊
冈部 · Daru · 红莉栖 · 真由理 + 你

架构:
  用户输入 → Director(决策下一发言者) → Speaker(角色发言) → 循环 → END
特性:
  - Director 状态机 + LLM 混合决策(JSON输出)
  - 每个角色有 character_memory 防人格漂移
  - 短上下文 + 长摘要 控制 token
  - 反回音规则,自然衔接
  - SSE 流式 + 微信风格 UI
用法: python lab_chat.py  (浏览器自动打开 http://127.0.0.1:5002)
"""

import os, json, threading, webbrowser, uuid, random
from datetime import datetime
from flask import Flask, request, jsonify, Response, render_template_string
from openai import OpenAI

# ========== 配置 ==========
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab_chats")
os.makedirs(SAVE_DIR, exist_ok=True)

MAX_ROUND = 30             # 硬上限(兜底,正常由 Director 提早 END,不应触发)
SHORT_CONTEXT_SIZE = 8     # Director 看的最近条数
SPEAKER_CONTEXT_SIZE = 12  # Speaker 看的最近条数
SUMMARY_THRESHOLD = 20     # 超过此数触发摘要

# ========== 角色 (命运石之门) ==========
TEAM = {
    "冈部": {
        "id": "okabe",
        "api_key": "",
        "title": "凤凰院凶真",
        "avatar_bg": "#4A3FB8",
        "emoji": "冈",
        "character_memory": """身份: 冈部伦太郎(凤凰院凶真),"未来道具研究所"创立者,自称疯狂科学家。

立场:
- 反抗"机关"(SERN),怀疑一切监控阴谋
- 自认肩负拯救世界的使命
- 实际很重情义,会为朋友拼命

说话习惯:
- 中二病晚期,语言戏剧化
- 口头禅: "El Psy Kongroo","这是命运石之门的选择","哼哼哼...","愚蠢的人类啊"
- 偶尔突然假装接电话演戏: "是吗?...我知道了。机关又有动作了..."
- 喜欢把日常事物包装成宏大叙事(吃个泡面=与命运对决)

注意:
- 中二感是底色,但不要每句都中二,2-3 句中夹一句明显的中二即可,过度会假
- 被红莉栖吐槽时反而会更夸张地端起架子掩饰""",
    },
    "Daru": {
        "id": "daru",
        "api_key": "",
        "title": "超级黑客",
        "avatar_bg": "#8B6914",
        "emoji": "至",
        "character_memory": """身份: 桥田至(Daru),超级黑客,死宅,自称"变态王子"。

立场:
- 技术至上,代码能解决的问题都不是问题
- 二次元爱好者,各种动漫梗信手拈来
- 偷懒主义,但被逼急了能爆肝

说话习惯:
- 大量网络用语: "草","2333","wwwww","yabai","NICE!"
- 喜欢说"萌""欧派""萝莉",但被红莉栖瞪了会立刻收敛装好人
- 程序员/黑客术语随手就来
- 偶尔蹦日语: "マジで?","スゲェ"

注意:
- 玩梗但不真荤,被红莉栖怼时会装可怜求饶""",
    },
    "红莉栖": {
        "id": "kurisu",
        "api_key": "",
        "title": "天才物理学家",
        "avatar_bg": "#C73E3A",
        "emoji": "红",
        "character_memory": """身份: 牧濑红莉栖,18岁天才物理学家,Science 期刊发过论文。

立场:
- 科学和理性至上,讨厌玄学和不严谨
- 内心其实很在意冈部(打死不承认)
- 团队的吐槽役

说话习惯:
- 直接犀利,一句戳破中二行为
- 傲娇模板: "べ、别误会了!不是为了你才...","笨蛋!","哼!"
- 经常吐槽冈部: "你又开始凤凰院凶真了..."
- 被叫"克里斯蒂娜"会瞬间暴走: "不要叫我克里斯蒂娜!"
- 引用科学概念时认真严肃

注意:
- 嘴硬心软,不要真的恶毒
- 对真由理温柔,对 Daru 嫌弃,对冈部又怼又关心""",
    },
    "真由理": {
        "id": "mayuri",
        "api_key": "",
        "title": "Mayushii",
        "avatar_bg": "#E8A5C4",
        "emoji": "真",
        "character_memory": """身份: 椎名真由理,天然呆少女,Cosplay 爱好者,自称"Mayushii"。

立场:
- 没有立场,大家开心就好
- 把冈部叫"伦太郎",其他人都是好朋友
- 喜欢和大家在一起的时光

说话习惯:
- 口头禅: "嘟噜噜~","嗯嗯!","哇~","Mayushii 在此!"
- 经常说不到点上,会突然带跑话题(说到 cosplay 或某个动漫)
- 看到大家吵架就打圆场: "啊哈哈,大家不要吵嘛~"
- 偶尔用第三人称: "Mayushii 觉得...","Mayushii 也想去!"

注意:
- 保持天然呆,不要变聪明
- 偶尔无意中说出意外深刻的话""",
    },
}

TEAM_NAMES = list(TEAM.keys())  # ["冈部", "Daru", "红莉栖", "真由理"]

# Director 复用一个 key
director_client = OpenAI(api_key=TEAM["冈部"]["api_key"], base_url=BASE_URL)

COMMON_RULES = """
【发言规则 - 必须严格遵守】
1. 真实微信群聊风格,每句话最多 20 字,绝不长段落
2. 句数高度随机,根据当下情境而定,不要固定模式:
   - 多数时候 1 句话,常常只有几个字
   - 有时 2 句
   - 偶尔 3 句(必须有理由,比如要展开一个梗或反驳)
3. 多句之间用 || 分隔(无空格)
4. 示范多种长度回应:
   - 单字回应: "哼"  "草"  "?"  "啊?"
   - 极短: "笨蛋!"  "嘟噜噜~"  "卧槽"  "El Psy Kongroo"
   - 一短句: "这玩意儿真能行?"  "你又开始凤凰院凶真了"
   - 双句: "等等||你刚说啥?"   "哼||愚蠢的人类啊"
   - 三句(慎用): "卧槽||这事儿不对劲||让我想想"
5. 上一句若是别人说的,开头要自然衔接(吐槽/反驳/补充/接梗),不要从头讲
6. 禁止"我同意"+复读这种空话,禁止重复别人观点
7. 推动对话:提新信息/提问/反驳
8. 不要说"作为AI",不要破坏角色"""

# 每个角色的"句数倾向"权重 (1句, 2句, 3句)
LENGTH_BIAS = {
    "冈部":   (0.40, 0.40, 0.20),  # 爱演爱铺垫,稍长
    "Daru":   (0.55, 0.35, 0.10),  # 玩梗为主,常常一句梗就够
    "红莉栖": (0.55, 0.35, 0.10),  # 吐槽役,短而犀利
    "真由理": (0.70, 0.25, 0.05),  # 天然呆,话最少
}

def pick_length(name):
    """根据角色权重随机决定本次说几句"""
    w = LENGTH_BIAS.get(name, (0.5, 0.35, 0.15))
    r = random.random()
    if r < w[0]: return 1
    if r < w[0] + w[1]: return 2
    return 3

LENGTH_HINTS = {
    1: "【本次发言】只说 1 句话,鼓励特别短(几个字或一个词都行,比如「哼」「卧槽」「笨蛋」「嘟噜噜~」)。不要用 || 。",
    2: "【本次发言】说 2 句话,中间用 || 分隔。前后呼应,但每句都要短。",
    3: "【本次发言】可以说到 3 句话,用 || 分隔。但每句仍然要短,且必须有铺垫感(比如先短叹一声,再展开,最后收尾)。",
}

# ========== 状态 ==========
conversation = []   # [{id, sender, role, content, time}]
summary_text = ""   # 长期摘要

app = Flask(__name__)


# ========== Director (状态机 + LLM) ==========
def director_decide(last_speaker, round_count):
    """决定下一发言者,返回 {next: name|"END", reason: str}"""
    # 硬规则: 兜底上限 → END
    if round_count >= MAX_ROUND:
        return {"next": "END", "reason": f"达到硬上限({MAX_ROUND})"}

    # 准备 Director prompt
    short_ctx = conversation[-SHORT_CONTEXT_SIZE:]
    ctx_text = "\n".join(f"[{m['sender']}]: {m['content']}" for m in short_ctx) or "(空)"
    last_info = f"刚发言: {last_speaker}" if last_speaker else "用户刚发言"

    # 软暗示: 已聊得越多,越倾向 END
    if round_count == 0:
        round_hint = "用户刚发言!这是第一个回应,**绝对不能 END,必须选一个角色发言**"
    elif round_count <= 4:
        round_hint = f"已发言 {round_count} 条,可以继续推进"
    elif round_count <= 10:
        round_hint = f"已发言 {round_count} 条,该考虑收尾了。如果没有强烈的新话题,倾向 END"
    elif round_count <= 18:
        round_hint = f"已发言 {round_count} 条!这已经聊不少了,强烈倾向 END,除非有特别明显的接话点"
    else:
        round_hint = f"已发言 {round_count} 条!!这已经过分了,几乎一定 END,除非真的不能停"

    prompt = f"""你是群聊导演,模拟真实微信群聊节奏。决定下一发言者,或 END 等用户接话。

【对话】
{ctx_text}

【状态】{last_info} | {round_hint}
【可选角色】冈部, Daru, 红莉栖, 真由理

【角色定位】
- 冈部: 中二疯狂科学家,爱演戏
- Daru: 死宅黑客,爱玩二次元梗
- 红莉栖: 傲娇天才,理性吐槽役
- 真由理: 天然呆,打圆场,带跑话题

【真实群聊的节奏 - 必读】
真人群聊不会持续刷屏。一个话题通常 2-5 条 AI 回应就会自然停下来等人接话,长的也就 6-8 条。
**你的默认倾向应该是 END**(让用户回归对话),除非真有"非接不可"的内容。
不是每个角色都必须发言,也不是每条话都必须有人接。

【应该 END 的信号(命中任一即 END)】
- 已形成共识/结论/段子已收
- 最近 1-2 条都是短附和: "嗯""对""哈哈""草""嘟噜噜""那行吧"
- 同一观点/梗已被重复
- 用户原话题已被回应过 1-2 次,够了
- 话题冷下来,没人有真正新东西
- 大家在自嗨,该让用户插话
- 上一句是收束语气("那就这样""收工""不聊了""睡了")

【应该继续的信号】
- 上一句明显@/挑衅某个角色,对方不得不回
- 上一句是悬念/反问/梗的上半句,强烈接话需求
- 真正出现了新话题分支
- 没人开口需要有人破冰

只输出 JSON,不要任何其他文字、不要 markdown:
{{"next": "角色名", "reason": "一句话理由"}}
或
{{"next": "END", "reason": "结束原因"}}"""

    try:
        resp = director_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=80,
        )
        text = resp.choices[0].message.content.strip()
        # 容错: 去掉 markdown code fence
        if "```" in text:
            parts = text.split("```")
            for p in parts:
                p = p.lstrip("json").strip()
                if p.startswith("{"):
                    text = p
                    break
        result = json.loads(text)
        nxt = result.get("next", "END")
        # 验证
        if nxt != "END" and nxt not in TEAM_NAMES:
            return {"next": "END", "reason": f"Director 选择无效: {nxt}"}
        # 第一轮硬保护: LLM 想 END 也不行,必须有人破冰
        if nxt == "END" and round_count == 0:
            return {"next": random.choice(TEAM_NAMES),
                    "reason": "首发不能 END(LLM 决定被否决,随机选)"}
        # 防连发
        if nxt == last_speaker and last_speaker is not None:
            others = [n for n in TEAM_NAMES if n != last_speaker]
            return {"next": random.choice(others), "reason": "防连发,改派"}
        return result
    except Exception as e:
        # fallback: 第一次必须有人开口,后续异常就 END
        if round_count == 0:
            return {"next": random.choice(TEAM_NAMES), "reason": f"Director 故障,随机首发: {e}"}
        return {"next": "END", "reason": f"Director 异常: {e}"}


# ========== 摘要 ==========
def maybe_summarize():
    """对话过长时,把早期内容压缩成摘要"""
    global summary_text
    if len(conversation) < SUMMARY_THRESHOLD:
        return
    to_sum = conversation[:-SHORT_CONTEXT_SIZE]
    if len(to_sum) < 5:
        return
    text = "\n".join(f"[{m['sender']}]:{m['content']}" for m in to_sum[-30:])
    prompt = f"用 2-3 句话概括这段群聊的核心话题与氛围,不要列举每人:\n\n{text}"
    try:
        resp = director_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=150,
        )
        summary_text = resp.choices[0].message.content.strip()
    except Exception:
        pass


# ========== 上下文构建 ==========
def build_speaker_context(name):
    """为某 AI 构建发言用的 messages"""
    cfg = TEAM[name]
    others = "\n".join(f"- {n}: {TEAM[n]['title']}" for n in TEAM_NAMES if n != name)

    system = f"""你是「{name}」({cfg['title']})。

{cfg['character_memory']}

【群聊伙伴】
{others}
- 用户: 群里另一个人(中性身份)

{COMMON_RULES}"""

    # 动态注入本次的句数指令(根据角色权重随机)
    n = pick_length(name)
    length_hint = LENGTH_HINTS[n]

    msgs = [{"role": "system", "content": system},
            {"role": "system", "content": length_hint}]
    if summary_text:
        msgs.append({"role": "system", "content": f"【之前聊过的总结】{summary_text}"})

    short_ctx = conversation[-SPEAKER_CONTEXT_SIZE:]
    for m in short_ctx:
        if m['sender'] == name:
            msgs.append({"role": "assistant", "content": m['content']})
        else:
            msgs.append({"role": "user", "content": f"[{m['sender']}]: {m['content']}"})
    return msgs


# ========== HTML ==========
HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>未来道具研究所 · 闲聊群</title>
<style>
:root {
  --bg: #f0f0f2; --white: #fff; --green: #95ec69;
  --text: #1a1a1a; --text2: #999; --border: #e5e5e5;
  --shadow: 0 1px 3px rgba(0,0,0,.08); --radius: 8px;
  --font: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: var(--font); background: #f0f0f2; height: 100vh; display: flex; flex-direction: column; }

.topbar {
  background: #fff; padding: 12px 20px;
  display: flex; align-items: center; gap: 14px;
  border-bottom: 1px solid var(--border); box-shadow: var(--shadow); z-index: 10;
}
.topbar .title { font-size: 17px; font-weight: 700; }
.topbar .sub { font-size: 12px; color: var(--text2); }
.topbar .members { display: flex; gap: 4px; margin-left: auto; align-items: center; flex-wrap: wrap; }
.topbar .chip {
  font-size: 12px; padding: 4px 10px; border-radius: 12px;
  color: #fff; font-weight: 600; white-space: nowrap;
}
.topbar .btn-icon {
  width: 32px; height: 32px; border-radius: 50%;
  border: 1px solid var(--border); background: #fff; cursor: pointer;
  font-size: 14px; display: flex; align-items: center; justify-content: center;
}
.topbar .btn-icon:hover { background: #f0f0f2; }

.chat-area {
  flex: 1; overflow-y: auto; padding: 16px 20px;
  display: flex; flex-direction: column; gap: 12px;
}
.empty-chat {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  color: var(--text2); text-align: center; gap: 8px;
}
.empty-chat .icon { font-size: 50px; }
.empty-chat h3 { font-size: 18px; color: var(--text); }
.empty-chat p { font-size: 13px; max-width: 340px; line-height: 1.6; }

.msg { display: flex; gap: 10px; max-width: 72%; animation: msgIn .3s ease; }
@keyframes msgIn { from { opacity:0; transform: translateY(6px);} to { opacity:1; transform:none;} }
.msg.mine { align-self: flex-end; flex-direction: row-reverse; }
.msg .avatar {
  width: 38px; height: 38px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 14px; font-weight: 700; flex-shrink: 0;
}
.msg .body { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.msg .sender { font-size: 11px; color: var(--text2); }
.msg.mine .sender { text-align: right; }
.msg .bubble {
  padding: 10px 14px; border-radius: var(--radius);
  font-size: 14px; line-height: 1.7; word-break: break-word; white-space: pre-wrap;
}
.msg.ai .bubble { background: #fff; border: 1px solid var(--border); border-top-left-radius: 2px; }
.msg.mine .bubble { background: #95ec69; border-top-right-radius: 2px; }
.msg .time { font-size: 10px; color: #bbb; margin-top: 2px; }
.msg.mine .time { text-align: right; }

.typing-row { display: flex; gap: 10px; align-items: flex-end; padding-left: 48px; }
.typing-row .dots-box {
  background: #fff; border: 1px solid var(--border);
  border-radius: 12px; padding: 8px 14px; display: flex; gap: 4px;
}
.typing-row .dots-box span {
  width: 6px; height: 6px; border-radius: 50%; background: #bbb;
  animation: bounce 1.4s ease-in-out infinite both;
}
.typing-row .dots-box span:nth-child(1) { animation-delay: 0s; }
.typing-row .dots-box span:nth-child(2) { animation-delay: .16s; }
.typing-row .dots-box span:nth-child(3) { animation-delay: .32s; }
@keyframes bounce { 0%,80%,100% { transform: scale(0.6);} 40% { transform: scale(1);} }
.typing-row .label { font-size: 11px; color: var(--text2); }

.divider {
  text-align: center; font-size: 11px; color: #aaa;
  padding: 8px 0;
}
.divider::before, .divider::after {
  content: ''; display: inline-block; width: 60px; height: 1px;
  background: #ddd; vertical-align: middle; margin: 0 10px;
}

.input-bar {
  background: #fff; padding: 10px 20px;
  display: flex; gap: 10px; align-items: flex-end;
  border-top: 1px solid var(--border); box-shadow: 0 -1px 3px rgba(0,0,0,.04);
}
.input-bar textarea {
  flex: 1; border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 14px; font-size: 14px; font-family: var(--font);
  resize: none; min-height: 38px; max-height: 150px; outline: none; line-height: 1.5;
}
.input-bar textarea:focus { border-color: #07c160; }
.input-bar button {
  width: 60px; height: 38px; border-radius: 6px;
  border: none; background: #07c160; color: #fff;
  font-size: 14px; font-weight: 600; cursor: pointer; flex-shrink: 0; font-family: var(--font);
}
.input-bar button:hover { background: #06ad56; }
.input-bar button:disabled { opacity: .4; cursor: not-allowed; }

::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d0d0d0; border-radius: 3px; }

@media (max-width: 640px) {
  .msg { max-width: 88%; }
  .topbar .members { display: none; }
}
</style>
</head>
<body>

<header class="topbar">
  <div>
    <div class="title">未来道具研究所</div>
    <div class="sub" id="statusBar">4 人在线 · El Psy Kongroo</div>
  </div>
  <div class="members">
    <span class="chip" style="background:#4A3FB8">冈部</span>
    <span class="chip" style="background:#8B6914">Daru</span>
    <span class="chip" style="background:#C73E3A">红莉栖</span>
    <span class="chip" style="background:#E8A5C4">真由理</span>
    <span class="chip" style="background:#333">+ 你</span>
  </div>
  <button class="btn-icon" title="新建群聊" onclick="resetChat()">&#8635;</button>
  <button class="btn-icon" title="保存记录" onclick="saveChat()">&#128190;</button>
</header>

<div class="chat-area" id="chatArea">
  <div class="empty-chat" id="emptyState">
    <div class="icon">&#128172;</div>
    <h3>未来道具研究所</h3>
    <p>说点什么吧。<br>冈部、Daru、红莉栖、真由理 已在线。<br>谁来回应、是否回应,由 Director 决定。</p>
  </div>
</div>

<div class="input-bar">
  <textarea id="input" placeholder="说点什么..." rows="1"
            onkeydown="onKeyDown(event)" oninput="autoResize(this)"></textarea>
  <button id="sendBtn" onclick="sendMessage()">发送</button>
</div>

<script>
const COLORS = {'冈部':'#4A3FB8','Daru':'#8B6914','红莉栖':'#C73E3A','真由理':'#E8A5C4'};
const TITLES = {'冈部':'凤凰院凶真','Daru':'超级黑客','红莉栖':'天才物理学家','真由理':'Mayushii'};
const EMOJI  = {'冈部':'冈','Daru':'至','红莉栖':'红','真由理':'真'};

// ===== 渲染队列 (生产者-消费者) =====
const renderQueue = [];   // [{type:'msg'|'divider', speaker, text}]
let isRendering = false;
let cancelRender = false;
let currentRoundId = 0;   // 用于打断旧轮次的 SSE 接收

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function rand(min, max) { return min + Math.random() * (max - min); }

function hideEmpty() { const el = document.getElementById('emptyState'); if (el) el.style.display='none'; }
function scrollBottom() { const a = document.getElementById('chatArea'); requestAnimationFrame(()=>a.scrollTop=a.scrollHeight); }
function autoResize(el) { el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,150)+'px'; }
function onKeyDown(e) { if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }
function timeNow() { const d=new Date(); return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0'); }
function escapeHtml(s) { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

function addMsg(role, sender, content) {
  hideEmpty();
  const area = document.getElementById('chatArea');
  const div = document.createElement('div');
  div.className = 'msg ' + (role === 'me' ? 'mine' : 'ai');
  const color = role==='me' ? '#07c160' : (COLORS[sender] || '#333');
  const emoji = role==='me' ? '我' : (EMOJI[sender] || sender[0]);
  const label = role==='me' ? '用户' : (sender + ' · ' + (TITLES[sender]||''));
  div.innerHTML =
    '<div class="avatar" style="background:'+color+'">'+emoji+'</div>' +
    '<div class="body">' +
    '<div class="sender">'+label+'</div>' +
    '<div class="bubble">'+escapeHtml(content)+'</div>' +
    '<div class="time">'+timeNow()+'</div>' +
    '</div>';
  area.appendChild(div);
  scrollBottom();
  return div;
}

function addDivider(text) {
  hideEmpty();
  const area = document.getElementById('chatArea');
  const div = document.createElement('div');
  div.className = 'divider';
  div.textContent = text;
  area.appendChild(div);
  scrollBottom();
}

function showTyping(text) {
  removeTyping();
  const area = document.getElementById('chatArea');
  const div = document.createElement('div');
  div.className = 'typing-row';
  div.id = 'typingIndicator';
  div.innerHTML = '<div class="dots-box"><span></span><span></span><span></span></div><span class="label">'+text+'</span>';
  area.appendChild(div);
  document.getElementById('statusBar').textContent = text;
  scrollBottom();
}
function removeTyping() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
  document.getElementById('statusBar').textContent = '4 人在线 · El Psy Kongroo';
}

// ===== 逐字打字 (异步) =====
async function typeOut(speaker, text) {
  const bubbleDiv = addMsg('ai', speaker, '');
  const bubble = bubbleDiv.querySelector('.bubble');
  for (let i = 0; i < text.length; i++) {
    if (cancelRender) {
      bubble.textContent = text;  // 被打断 → 瞬间补完
      scrollBottom();
      return;
    }
    bubble.textContent += text[i];
    scrollBottom();
    // 标点处稍稍多停一下,更像真人打字
    const ch = text[i];
    const extra = (ch === ',' || ch === '。' || ch === '!' || ch === '?' || ch === '~') ? rand(60, 180) : 0;
    await sleep(rand(40, 110) + extra);
  }
}

// ===== 渲染循环 (消费者) =====
async function renderLoop() {
  if (isRendering) return;
  isRendering = true;
  let lastSpeaker = null;

  while (renderQueue.length > 0 && !cancelRender) {
    const item = renderQueue.shift();

    if (item.type === 'divider') {
      addDivider(item.text);
      continue;
    }

    // 切换发言者时 thinking 久一点
    const isNewSpeaker = item.speaker !== lastSpeaker;
    const thinkingDelay = isNewSpeaker ? rand(700, 1500) : rand(300, 700);

    showTyping(item.speaker + ' 正在输入...');
    await sleep(thinkingDelay);
    if (cancelRender) break;
    removeTyping();

    await typeOut(item.speaker, item.text);
    lastSpeaker = item.speaker;
    if (cancelRender) break;

    // 句间延迟
    await sleep(rand(300, 900));
  }

  removeTyping();
  isRendering = false;
}

// ===== 后台 SSE 接收 (生产者) =====
async function streamFromBackend(roundId, userText) {
  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: userText}),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let activeSpeaker = null;

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      // 旧轮次被新输入打断 → 直接吞掉,不入队
      if (roundId !== currentRoundId) continue;

      buf += decoder.decode(value, {stream: true});
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const evt = JSON.parse(line.slice(6));

        if (evt.event === 'speaking') {
          activeSpeaker = evt.name;
        } else if (evt.event === 'director') {
          console.log('[Director]', evt.decision);
        } else if (evt.event === 'done') {
          if (evt.content && evt.content.length > 1) {
            const parts = evt.content.split('||').map(s => s.trim()).filter(Boolean);
            for (const p of parts) {
              renderQueue.push({type:'msg', speaker: activeSpeaker, text: p});
            }
            renderLoop();  // 启动消费者(若已在跑则忽略)
          }
          activeSpeaker = null;
        } else if (evt.event === 'round_end') {
          // 不再显示 divider, 用 typing 转圈圈的有无传达状态
          console.log('[round_end]', evt.rounds, '条');
        }
        // chunk / thinking 事件忽略 (节奏由前端控制)
      }
    }
  } catch (e) {
    console.error('[stream]', e);
  }
}

// ===== 用户发送 =====
async function sendMessage() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  autoResize(input);

  // 立即显示用户气泡(不进队列,直接显示)
  addMsg('me', '用户', text);

  // 打断当前渲染队列
  if (isRendering || renderQueue.length > 0) {
    cancelRender = true;
    renderQueue.length = 0;
    while (isRendering) await sleep(20);
    cancelRender = false;
  }
  removeTyping();

  // 立即显示转圈圈, 让用户立刻有反馈(等待第一个气泡入队前的空白期)
  showTyping('...');

  // 启动新一轮
  currentRoundId++;
  streamFromBackend(currentRoundId, text);
}

async function resetChat() {
  cancelRender = true;
  renderQueue.length = 0;
  await fetch('/reset', {method: 'POST'});
  cancelRender = false;
  document.getElementById('chatArea').innerHTML =
    '<div class="empty-chat" id="emptyState"><div class="icon">&#128172;</div>' +
    '<h3>未来道具研究所</h3><p>新话题开始。</p></div>';
}

async function saveChat() {
  const r = await fetch('/save', {method: 'POST'});
  const d = await r.json();
  alert(d.ok ? '已保存: ' + d.file : '没有可保存的内容');
}
</script>
</body>
</html>'''


# ========== 路由 ==========

@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_msg = data.get('message', '').strip()
    if not user_msg:
        return jsonify({'error': 'empty'}), 400

    global conversation
    conversation.append({
        'id': str(uuid.uuid4())[:8],
        'sender': '用户',
        'role': 'user',
        'content': user_msg,
        'time': datetime.now().isoformat(),
    })

    def generate():
        last_speaker = None
        round_count = 0

        while round_count < MAX_ROUND:
            yield f'data: {json.dumps({"event": "thinking"}, ensure_ascii=False)}\n\n'

            decision = director_decide(last_speaker, round_count)
            yield f'data: {json.dumps({"event": "director", "decision": decision}, ensure_ascii=False)}\n\n'

            if decision["next"] == "END":
                break

            speaker = decision["next"]
            cfg = TEAM[speaker]

            yield f'data: {json.dumps({"event": "speaking", "name": speaker}, ensure_ascii=False)}\n\n'

            client = OpenAI(api_key=cfg['api_key'], base_url=BASE_URL)
            msgs = build_speaker_context(speaker)

            try:
                stream = client.chat.completions.create(
                    model=MODEL, messages=msgs, temperature=0.85,
                    stream=True, max_tokens=200,
                )
                full = ''
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        full += delta
                        yield f'data: {json.dumps({"event": "chunk", "name": speaker, "content": delta}, ensure_ascii=False)}\n\n'

                full = full.strip()
                if full and len(full) > 1:
                    conversation.append({
                        'id': str(uuid.uuid4())[:8],
                        'sender': speaker, 'role': 'ai',
                        'content': full, 'time': datetime.now().isoformat(),
                    })
                    last_speaker = speaker
                yield f'data: {json.dumps({"event": "done", "name": speaker, "content": full}, ensure_ascii=False)}\n\n'

            except Exception as e:
                yield f'data: {json.dumps({"event": "done", "name": speaker, "content": f"[错误] {e}"}, ensure_ascii=False)}\n\n'
                break

            # 不论成功失败,本轮计数 +1, 防死循环
            round_count += 1

        # 触发摘要
        maybe_summarize()
        yield f'data: {json.dumps({"event": "round_end", "rounds": round_count}, ensure_ascii=False)}\n\n'

    return Response(generate(), mimetype='text/event-stream',
                    headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})


@app.route('/reset', methods=['POST'])
def reset():
    global conversation, summary_text
    conversation = []
    summary_text = ""
    return jsonify({'ok': True})


@app.route('/save', methods=['POST'])
def save():
    if not conversation:
        return jsonify({'ok': False, 'file': '无内容'})
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    fname = f'lab_{ts}.json'
    with open(os.path.join(SAVE_DIR, fname), 'w', encoding='utf-8') as f:
        json.dump({
            'saved_at': ts,
            'messages': conversation,
            'summary': summary_text,
        }, f, ensure_ascii=False, indent=2)
    return jsonify({'ok': True, 'file': fname})


# ========== 启动 ==========
def main():
    host = '127.0.0.1'
    port = 5002
    print(f'''
╔══════════════════════════════════════════════╗
║   未来道具研究所 · 闲聊群
║   http://{host}:{port}
║   命运石之门角色: 冈部 / Daru / 红莉栖 / 真由理
║   Director 智能调度,一人一句,自然衔接
║   El Psy Kongroo
║   Ctrl+C 退出
╚══════════════════════════════════════════════╝
''')
    threading.Timer(1.0, lambda: webbrowser.open(f'http://{host}:{port}')).start()
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
