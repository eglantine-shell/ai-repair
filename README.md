# AI Manuscript Repair

一个面向已接收中文 AI 稿件的独立 Codex Skill。它不负责判断文本是否由
AI 生成，也不进行整段改写；它先理解上下文，再把能够确定的语言问题压缩
成局部、最小、可直接执行的修改。

这个项目不是 Humanizer。它不要求模型先判断“哪里像 AI”，也不要求模型
主动模仿所谓“人类文风”。项目最初处理的一类典型 AI 稿具有明显的共同问题：
文字表面流畅、修辞很多，但细看存在搭配失当、隐喻混用、语义角色错位、
机械强化等普通编辑本来就应该处理的问题。对于这类稿件，正常精修本身就能
同时削弱一部分明显的 AI 味。

因此这里区分两个目标：**去 AI 味是不像 AI，Humanizer 是像人。** AI
Manuscript Repair 选择前者的另一条路径：不主动制造口语、顿挫、个人感、
随机句式等“人类特征”，而只删除按普通编辑标准能够证成的问题。它不声称
所有 AI 味都是语病，也不声称这些问题只存在于 AI 文本；它只提供一种不依赖
稳定 AI 文风识别的编辑式去 AI 方法。

默认生成：

- `minimal-edits.pdf`：在原文位置以红色下划线标出问题，批注内保存完整改文；
- `minimal-edits.md`：只包含“页码、原句、修改”三列。

黄色局部一致性标记属于实验性可选功能，默认关闭。只有编辑明确需要时才用
`--include-consistency` 开启；黄标不附说明，也不替编辑决定统一成哪一种说法。
它是附加的编辑辅助功能，不是上述去 AI 路线成立的前提。

## 安装

需要 Python 3.12 或 3.13，以及已经登录的 Codex 环境。

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

## 使用

默认只运行最小语言修复：

```bash
.venv/bin/ai-manuscript-repair input.pdf --output-dir output
```

限定 PDF 页码：

```bash
.venv/bin/ai-manuscript-repair input.pdf --output-dir output --pages 19-23
```

显式开启黄色一致性标记：

```bash
.venv/bin/ai-manuscript-repair input.pdf --output-dir output --include-consistency
```

当前仅支持具有可用文本层的横排中文 PDF。扫描页、竖排和复杂多栏版面不在
当前版本的承诺范围内。模型结果是专业编辑的工作入口，不代替编辑的最终判断。

详细方法与输出约束见 [SKILL.md](SKILL.md)。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```
