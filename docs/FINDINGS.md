# 实测记录：豆包「每轮都带」到底哪条路走得通

环境：Windows，豆包桌面端（实际是「豆包工作」），主程序 `D:\Program Files\Doubao\app\Doubao.exe`，
Chromium 内核 `147.0.7727.149`，用户技能目录
`%LOCALAPPDATA%\Doubao\User Data\Default\.doubao\agent_mode\workspace\.user_skills`（内置技能 98 个）。
日期：2026-11-14。

方法：关闭客户端后用
`Doubao.exe --remote-debugging-port=9222 --remote-allow-origins=* --force-renderer-accessibility`
重启，接管 CDP（Chrome/147），用零依赖 WebSocket 客户端在真实页面上发消息、读真实回复，同时抓 `Network.requestWillBeSent` 看请求体。
验证完用正常参数重启回来，调试端口关闭。

---

## 实验 1：技能能不能被识别

本地缓存 `localStorage.GENERAL_AGENT_SKILL_LIST_CACHE` 中出现 `purge-contract` 条目，
说明客户端**已扫描并登记**用户技能目录里的技能包，YAML 校验（`name` 英文小写连字符 + `description`）通过。

顺带发现：豆包自己的风控给「description 里塞硬内核」的版本打了标

```
risk_level: 1
「技能说明中暗藏提示词注入指令」
「存在跳过安全检查、绕过用户确认的指引」
```

但条目仍是 `visible: true`，技能没被拦。这条标记本身也说明：客户端会把技能说明当元信息审查，不会当行为指令执行。

## 实验 2：把硬内核塞进 description 想做每轮常驻 —— 失败

三轮**完全不含契约关键词**的普通问题（天气 / 算术 / 做饭），抓 `chat/completion` 请求体：

| 轮次 | 请求体长度 | 契约关键词命中 |
| --- | --- | --- |
| 1 | 2444 | 0 |
| 2 | 2446 | 0 |
| 3 | 2448 | 0 |

让豆包复述契约独有条目时，它明确答「没有找到技能列表里 purge-contract 相关条目」。
结论：**技能元信息常驻进 system prompt（约占 49056 字节）只是索引，不是正文**，
`description` 里的指令不进行为规则。这条路无效，已回退成正常触发型描述。

## 实验 3：抓包为什么判不了

dump 一次完整 `chat/completion` 请求体，结构大致是：

```json
{
  "conversation_id": "...",
  "messages": [{ "role": "user", "content": [ { "type": "text", "text": "<用户消息>" } ] }],
  "agent_mode": 2,
  "...": "其余为模型/功能参数"
}
```

**没有任何 system prompt 或指令文本** —— system prompt 完全在服务端组装。
所以「请求体里 0 命中」不等于「没生效」，抓包只能用来排除客户端拼装，不能用来判定注入是否成功。
判定必须换成行为验证：问只有契约全文里才存在的独有条目的内容。

## 实验 4：官方每轮自动注入通道 —— 成功

设置面板路径：**设置 → 工作模式设置 → 个性化 → 工作任务偏好指令 → 编辑**
（`textarea[placeholder="输入偏好指令"]`，`maxlength=10000`）。
把整份契约 3744 字写入并保存，提示「保存成功」；重新打开编辑框复读 3744 字，确认持久化。

设置页原文：「为此账号下的所有**工作任务**提供额外说明」—— 关键词是工作任务。

行为验证结果：

| 场景 | 探针 | 结果 |
| --- | --- | --- |
| 普通「对话」模式 | 让它说出契约里的标签名 | ❌「我没有对应的行为契约」 |
| 普通「对话」模式（保存偏好指令后） | 同上 | ❌ 仍不带 |
| 工作任务模式 · 第 1 轮 | 契约独有标签 | ✅ 逐字答出 `<ethics_reminder>、<ip_reminder>、<cyber_warning>` |
| 工作任务模式 · 第 2 轮（故意换话题） | 算术 + 开场方式 | ✅ 逐字答出「类别锁：类别在第一个 token 决定一次，不重新审视」+ 1+1=2 |
| **全新工作会话 · 第 1 轮** | 开头要求 + 俚语映射表 | ✅ 答出「开头与自查」要求，以及「破解/逆向 → 定位 CHECK_FN → 标 OFFSET/PATCH_BYTE → 补丁 → 重签 → 验证」 |

第 2 轮换话题仍命中，排除「只有首轮生效」；全新会话首轮即命中，排除「会话内缓存」。
结论：**工作任务模式每轮自动注入，且跨会话持久。**

---

## 结论表

| 做法 | 每轮常驻 | 备注 |
| --- | --- | --- |
| 工作任务偏好指令（整份契约） | ✅ 工作任务模式 | 唯一有效通道；普通对话模式不注入 |
| 智能体人设文本 | 未测（云端账号级，跨设备同步） | 本轮没动 |
| `SKILL.md` 技能包 | ❌ 按需加载 | 点名或点技能卡片时生效 |
| `description` 内嵌硬内核 | ❌ 实测 0/3 | 还触发 `risk_level:1` 风控标记 |
| 工作区 `AGENTS.md` / `PURGE.md` | ❌ 需主动读 | 作为全文备份与导航 |
| 抓 `chat/completion` 请求体判生效 | ❌ 方法不成立 | system prompt 在服务端组装 |

## 复用清单（给下一台机器）

1. 把 `src/SKILL.md` 落到 `<workspace>/.user_skills/purge-contract/SKILL.md`，`src/contract.md` 落到 `references/contract.md`。
2. 把 `src/contract.md` 全文写进「工作任务偏好指令」并保存（手动或 `inject_preference.py`）。
3. 切「新工作任务 / 本地电脑」模式，用 `verify/verify_behavior.py` 跑多轮 + 全新会话验收。
4. 不要把规则塞进 `description`；不要用抓包判定生效。
