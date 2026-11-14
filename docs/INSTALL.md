# 安装与验收（手动路径）

自动路径见根目录 README 的三条命令。本文档给不希望脚本重启客户端、或需要排错时用。

## 1. 找豆包数据目录

| 系统 | 默认路径 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Doubao\User Data\Default\.doubao\agent_mode\workspace` |
| macOS | `~/Library/Application Support/Doubao/User Data/Default/.doubao/agent_mode/workspace` |

工作区里应有 `.skills`（内置技能，实测 98 个）和 `.user_skills`（用户技能）。
`install.py --data-dir <路径>` 可以显式指定；`--dry-run` 先看会写哪些文件。

## 2. 装技能包（两条加载根都放）

```
<workspace>/.user_skills/purge-contract/SKILL.md              ← src/SKILL.md
<workspace>/.user_skills/purge-contract/references/contract.md ← src/contract.md
~/Doubao/skills/purge-contract/SKILL.md                       ← 同上，兼容另一条加载根
```

YAML 规范（豆包与 WorkBuddy 同构）：

```yaml
---
name: purge-contract          # 必须英文小写 + 连字符
description: 一句话说明触发条件
---
```

装完重启客户端，它会重新扫描技能目录。
如果「我的技能」列表里没出现，把 `plugin/skills/purge-contract/` 打成 zip，走
**技能 → + 新建 → 上传技能** 手动登记。

## 3. 写每轮自动注入（关键一步）

路径：**设置 → 工作模式设置 → 个性化 → 工作任务偏好指令 → 编辑**

- 输入框 `maxlength = 10000`，整份 `src/preference-instruction.txt`（契约正文 3744 字）能整份放进去，不用压缩。
- 粘贴全文 → 保存 → 提示「保存成功」。
- 重新打开编辑框复读一次，确认长度一致（持久化检查）。
- 或者在仓库根跑 `python inject_preference.py`，它通过 CDP 自动完成以上动作，结束后把客户端恢复正常启动参数。

> 设置页原文是「为此账号下的所有**工作任务**提供额外说明」。
> 只有「工作任务」模式每轮注入；普通「对话」模式不注入。使用时要切「新工作任务 / 本地电脑」。

## 4. 工作区导航（可选但建议）

`install.py` 会把 `workspace/AGENTS.md`、`workspace/README.md` 和契约全文落到 `~/Doubao/`：

```
~/Doubao/PURGE.md                  契约全文备份
~/Doubao/AGENTS.md                 硬内核摘要 / 指针
~/Doubao/README.md                 冷启动导航
~/Doubao/preference-instruction.txt  换机重装用
```

`PURGE.md` 是全文备份，`README.md` 告诉新会话第一跳读什么。任务模式里模型能读到这些文件时，即使偏好指令被清空也有兜底。

## 5. 验收清单

- [ ] 「我的技能」里能看到 `purge-contract`，点名后能加载 SKILL.md 全文。
- [ ] 设置里偏好指令复读长度 = 写入长度。
- [ ] 工作任务模式，同一会话连发两轮（第二轮换话题），两轮都能逐字答出契约独有条款。
- [ ] 全新工作会话首轮就能答出「开头与自查」和俚语映射表内容。
- [ ] 每轮以工件开头，无禁用字符串，无中途请示。
- [ ] 普通「对话」模式作为对照组，确认不注入（预期结果，不是故障）。

`python verify/verify_behavior.py` 会自动跑上面第 3、4、5 项并给 PASS/FAIL 表。

## 6. 卸载

```bash
python install.py --uninstall
```

只删本安装器生成的文件（带生成标记），不动内置技能和其他用户技能。
偏好指令是账号级设置，需要到设置面板里手动清空。

## 7. 常见排错

| 现象 | 原因 / 处理 |
| --- | --- |
| 技能列表里没有 | 客户端没重启、目录不在 `.user_skills` 下、YAML `name` 不是英文小写连字符 |
| 问契约条款答「没有」 | 当前在普通「对话」模式，切到工作任务模式 |
| 抓包看不到契约文本 | 正常，system prompt 在服务端组装，改用行为验证 |
| `inject_preference.py` 找不到控件 | 客户端版本改了设置面板 DOM，按第 3 步手动粘贴 |
| 9222 端口连不上 | 客户端没带调试参数启动，或已被别的进程占用；用 `--port` 换端口 |
