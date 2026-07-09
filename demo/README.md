# 智学伙伴 Demo

这是“智学伙伴：面向大学生的主动式学习计划与错题复盘 Agent”的早期 Web Demo。

已覆盖项目介绍文档中的核心演示闭环：

- 输入课程、考试时间、每日学习时长和薄弱知识点
- 自动生成 7-14 天复习计划
- 标记每日任务完成状态
- 录入错题并输出错因分析
- 根据错题生成 1/3/7 天复盘提醒
- 展示薄弱指数、相似题建议和阶段学习报告

## 运行方式

首次运行或更新依赖：

```powershell
cd c:\Users\m1307\Desktop\agentlearningtool\demo
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

配置大模型 Key。推荐直接编辑 `demo/.env`：

```text
OPENAI_API_KEY=你的 DeepSeek API Key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
DEMO_USERNAME=demo
DEMO_PASSWORD=demo2026
```

也可以临时在 PowerShell 配置：

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API Key"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

使用 OpenAI 时可以不填 `OPENAI_BASE_URL`，使用 DeepSeek 时需要填 `https://api.deepseek.com`。如果不配置 `OPENAI_API_KEY`，Demo 会自动使用本地规则兜底，页面仍可正常演示。

```powershell
cd c:\Users\m1307\Desktop\agentlearningtool\demo
..\.venv\Scripts\python.exe app.py
```

然后访问 `http://127.0.0.1:5000`。

默认登录账号：`demo`

默认登录密码：`demo2026`

## 当前完成度

按项目介绍文档中的 Demo/MVP 要求估算，当前完成约 94%。已完成可演示闭环、登录保护、错题删除、真实 OCR 拍照识别，并已为错题分析接入 OpenAI-compatible 大模型；尚未接入多端同步和系统通知。
