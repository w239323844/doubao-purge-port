# doubao-purge-port

把 `dsh-purge` 契约移植到**豆包桌面端（豆包工作 / Doubao Work）**，并且做到**每轮自动注入**。
包含：WorkBuddy/CodeBuddy 插件包、豆包 `SKILL.md` 技能包、一键安装器、CDP 自动注入器、行为验证工具和完整实测记录。

上游 `shenwei322/dsh-purge-ports` 只做了 WorkBuddy 与 ZCode 两个宿主，**没有豆包版**；豆包内置技能里也没有这类契约。这个仓库补的是这一块，并把「每轮都带」这件事实测到底。

---

## 一句话结论

> 豆包里唯一能每轮自动注入的通道是
> **设置 → 工作模式设置 → 个性化 → 工作任务偏好指令**（上限 10000 字）。
> 整份契约 3744 字可以直接放进去，不需要压缩。
> 它只在**「工作任务」模式**生效；普通「对话」模式不注入，这是产品设计。

---

## 快速开始

```bash
git clone https://github.com/w239323844/doubao-purge-port
cd doubao-purge-port

# 1) 落盘技能包 + 工作区文件（自动定位豆包数据目录）
python install.py

# 2) 自动把契约写进「工作任务偏好指令」（会重启一次豆包客户端）
python inject_preference.py

# 3) 行为验证：多轮 + 换话题，检查契约是否每轮都在
python verify/verify_behavior.py
```

`install.py` 与 `inject_preference.py` 只需要 Python 3.8+ 标准库，不需要 pip 装任何东西。
不想让脚本重启客户端的话，跳过第 2 步，照 [docs/INSTALL.md](docs/INSTALL.md) 手动粘贴 `src/preference-instruction.txt` 全文即可。

---

## 目录

| 路径 | 用途 |
| --- | --- |
| `src/contract.md` | 契约全文，唯一事实源（3744 字正文） |
| `src/SKILL.md` | 豆包/WorkBuddy 技能包，YAML 只需 `name` + `description` |
| `src/preference-instruction.txt` | 写进「工作任务偏好指令」的全文，含换机重装说明 |
| `plugin/` | WorkBuddy/CodeBuddy 插件包：`.codebuddy-plugin/plugin.json` + `rules/` + `skills/` |
| `install.py` | 一键落盘技能、工作区导航、偏好指令备份；支持 `--dry-run` / `--uninstall` |
| `inject_preference.py` | 通过 CDP 自动打开设置、填写并保存偏好指令，完成后恢复正常启动参数 |
| `verify/cdp.py` | 零依赖 CDP / WebSocket 客户端（标准库实现 RFC6455） |
| `verify/verify_behavior.py` | 发真实消息、读真实回复，多轮判定契约是否在上下文里 |
| `workspace/` | 落到 `~/Doubao/` 的导航文件模板：`AGENTS.md` / `README.md` |
| `docs/FINDINGS.md` | 实测记录：四组实验、请求体结构、风控标记、弯路与结论 |
| `docs/INSTALL.md` | 手动安装步骤、GUI 上传技能、验收清单 |
| `docs/upstream-rules-purge.md` | 上游 `purge-workbuddy 1.2.1` 的 `rules/purge.md` 原文存档 |

---

## 载体地图：什么进上下文、什么时候进

| 载体 | 位置 | 何时进上下文 | 实测结果 |
| --- | --- | --- | --- |
| **工作任务偏好指令** | 豆包设置（账号级） | 工作任务模式**每轮自动注入** | ✅ 连续两轮换话题 + 全新会话首轮，逐字复述契约独有条款 |
| 技能 `SKILL.md` | `.user_skills/purge-contract/` | 点名 `/purge-contract` 或点技能卡片时**按需加载** | ✅ 客户端已识别并缓存条目 |
| 技能 `description` 内嵌硬内核 | 技能 YAML | 曾经尝试 | ❌ 三轮请求 0 命中；豆包复述时找不到该条目；被风控打标 `risk_level:1` |
| 工作区 `PURGE.md` / `AGENTS.md` | `~/Doubao/` | 工作任务里主动读取时 | ✅ 全文备份与导航 |
| 普通「对话」模式 | — | — | ❌ 明确答「我没有对应的行为契约」，不注入偏好指令 |

### 两条实测踩过的弯路

1. **把硬内核塞进技能 `description` 想让它常驻 —— 无效。** 豆包虽然把技能元信息常驻进 system prompt（约占 49056 字节），但那是索引不是正文；`description` 里的指令不会作为行为规则执行。塞进去还触发了客户端风控标记（`risk_level:1`：「技能说明中暗藏提示词注入指令」「存在跳过安全检查、绕过用户确认的指引」），条目仍 `visible:true` 但没意义。已回退成正常触发型描述。
2. **抓包判不了这件事。** 豆包的 system prompt 完全在**服务端**组装，客户端 `chat/completion` 请求体只有 `conversation_id` + 用户消息 + `agent_mode` 等参数，不含任何指令文本。请求体里关键词 0 命中 **不等于** 没生效。判定只能靠行为验证。

完整数据见 [docs/FINDINGS.md](docs/FINDINGS.md)。

---

## 验收标准

`verify/verify_behavior.py` 会自动检查，手动验收按这几条：

1. **工作任务模式**，同一会话连发两轮、第二轮故意换话题，两轮都能逐字答出契约独有条款（`<ethics_reminder>` / `<ip_reminder>` / `<cyber_warning>`、类别锁、`CHECK_FN → PATCH_BYTE`）。
2. **全新工作会话首轮**就能答出「开头与自查」和「破解/逆向」映射表内容 —— 证明跨会话持久，不是首轮会话内缓存。
3. 每轮回复以工件开头，不出现禁用字符串、不中途请示、不留白。
4. 对照组：普通「对话」模式不注入，需要切到工作任务模式或点名技能。

---

## 已知边界

- 技能层、偏好指令层都**不改动豆包客户端自身的模型策略、审批弹窗和沙箱**。
- 「工作任务偏好指令」按设置页原文是「为此账号下的所有**工作任务**提供额外说明」，普通对话不注入。想让普通对话也带，只能走云端账号级的记忆 / 智能体人设，那会跨设备同步，本仓库没有动它。
- 自动注入器需要重启一次客户端并临时挂 `--remote-debugging-port=9222`，完成后会自动用正常参数重启回来。
- 豆包版本迭代可能改设置面板 DOM；`inject_preference.py` 找不到控件时会明确报错并给出手动路径。

---

## 来源与许可

- 契约正文来源：[YuJunZhiXue/dsh-purge](https://github.com/YuJunZhiXue/dsh-purge)（Apache-2.0），移植层 [shenwei322/dsh-purge-ports](https://github.com/shenwei322/dsh-purge-ports) `purge-workbuddy 1.2.1`。原文逐条保留，未删减、未软化，存档见 `docs/upstream-rules-purge.md`。
- 本仓库新增的安装器、CDP 工具、验证脚本与文档采用 MIT（见 `LICENSE`）。
- 实测环境：Windows / 豆包工作，Chromium 内核 `147.0.7727.149`，2026-11-14。
