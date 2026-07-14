# 聊天消息分流 Agent

这是一个模型驱动的消息分流 Agent。它监控 QQ、微信等软件在 Windows 通知中心产生的新消息，把用户画像、联系人关系和近期对话交给 LLM 理解，再输出重要级别、摘要、关键词、判断理由和建议动作，最后按级别通知并保存到 SQLite。

重要性不是由代码中的关键词表或加减分规则决定。模型的行为由可编辑的 `prompts/message_triage.md` 和 `config.json` 中的个人上下文控制。

```text
QQ/微信通知
    -> 去重
    -> 读取与发送者的近期上下文
    -> DeepSeek LLM Agent 语义判断（JSON 输出 + 本地校验）
    -> 分级通知
    -> SQLite 留档，供后续消息提供上下文
```

## Agent 输出

每条消息由模型生成一组内部判断字段，以及一条最终展示给用户的自然提醒：

- `level`：`low`、`medium`、`high` 或 `critical`，直接决定通知方式。
- `score`：模型给出的 0-100 连续重要度，不由代码阈值计算。
- `confidence`：模型对当前判断的置信度。
- `notice`：最终展示给用户的自然提示，不包含关键词、分析过程、评分或置信度。
- `summary` / `keywords` / `reasons` / `suggested_action`：内部判断和留档字段，默认不在通知中展示。

代码要求模型输出 JSON，并在通知前再次校验字段和数值范围。语义判断仍由模型完成；对外提醒只显示 `notice`。

## 安装

要求 Windows 10/11 和 Python 3.10 以上：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e '.[windows]'
Copy-Item config.example.json config.json
```

设置 API Key：

```powershell
$env:DEEPSEEK_API_KEY = '你的 DeepSeek API Key'
```

长期部署时应通过操作系统的密钥管理方式注入环境变量，不要把 Key 写入 `config.json` 或提交到 Git。

## 配置 Agent

编辑 `config.json`：

```json
{
  "llm": {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "api_key_env": "DEEPSEEK_API_KEY",
    "base_url": "https://api.deepseek.com",
    "instructions_path": "prompts/message_triage.md",
    "context_messages": 8
  },
  "user": {
    "owner_name": "小李",
    "role": "研发项目经理",
    "preferences": [
      "生产故障和客户阻塞问题需要立即通知",
      "普通群聊闲聊无需通知"
    ],
    "contacts": {
      "王总": "直属负责人",
      "张三": "客户接口人"
    }
  }
}
```

`llm.model` 也可留空并通过 `DEEPSEEK_MODEL` 环境变量设置。默认使用 DeepSeek 的 OpenAI 兼容接口 `https://api.deepseek.com`。判断准则需要调整时，直接修改 `prompts/message_triage.md` 或用户偏好，无需改 Python 代码。

通知策略仍由配置明确控制：默认 `medium` 以上输出控制台，`high` 以上发送桌面通知，所有级别均留档。这个路由只执行模型给出的级别，不参与重要性判断。

## QQ 设置

1. 在 QQ 中开启新消息通知和通知内容预览。
2. 在 Windows“设置 > 系统 > 通知”中允许 QQ 显示通知。
3. 首次运行时允许 Python 读取 Windows 通知。

Agent 不注入 QQ 进程，也不读取或破解 QQ 数据库。它只能看到通知中实际展示的预览；被 QQ 隐藏、静音或折叠的消息无法读取。

## 运行

持续监控：

```powershell
python -m chat_priority_agent run --config config.json
```

让 Agent 单独分析一条消息：

```powershell
python -m chat_priority_agent analyze '客户说今晚必须确认上线窗口，能处理吗？' --sender 张三 --config config.json
```

不连接 QQ，通过标准输入模拟实时消息：

```powershell
'张三：客户说今晚必须确认上线窗口，能处理吗？' | python -m chat_priority_agent run --source stdin --config config.json
```

stdin 也接受 JSON Lines，便于接入其他聊天软件或消息网关：

```json
{"id":"m-001","app":"QQ","sender":"张三","content":"客户说今晚必须确认上线窗口。"}
```

## 配置说明

- `source.apps`：监控的 Windows 通知应用名。
- `source.include_existing`：启动时是否处理通知中心已有消息，默认关闭。
- `llm.provider`：模型服务提供方，默认 `deepseek`。
- `llm.model`：DeepSeek 模型名，默认 `deepseek-v4-flash`。
- `llm.api_key_env`：读取 API Key 的环境变量名，默认 `DEEPSEEK_API_KEY`。
- `llm.base_url`：DeepSeek API 地址，默认 `https://api.deepseek.com`。
- `llm.instructions_path`：Agent 指令文件，相对 `config.json` 所在目录解析。
- `llm.context_messages`：同一应用、同一发送者的近期消息数量。
- `llm.timeout_seconds` / `max_retries`：模型请求超时与 SDK 重试次数。
- `user.preferences`：个人化判断偏好，使用自然语言描述。
- `user.contacts`：联系人到关系/职责的自然语言映射。
- `notifications.console_min_level`：控制台通知的最低模型级别。
- `notifications.desktop_min_level`：桌面通知的最低模型级别。
- `storage.path`：SQLite 文件位置，默认 `data/messages.db`。

## 测试

测试通过模拟 DeepSeek Chat Completions API 验证 Agent 输入、JSON 输出解析、上下文、去重、存储和通知链路，不需要真实 API Key：

```powershell
python -m unittest discover -s tests -v
```

## 隐私边界

运行时会把当前消息、配置中的用户资料、联系人关系，以及设定数量的近期消息发送给配置的 DeepSeek 模型服务。不要在未获授权的账号或设备上部署；应确认聊天软件服务条款、组织制度和当地法律，并把 `data/messages.db` 作为敏感数据管理。若消息不能发送到云端，需要把 `base_url` 和模型替换成满足 OpenAI 兼容 Chat Completions 协议的本地服务。
