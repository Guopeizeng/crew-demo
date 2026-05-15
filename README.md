# Crew Demo

**Generic Pheromone Framework** — 让信息自己知道去哪。

一个零硬编码的通用 Pheromone（信息素）框架，任何人都可以下载使用，通过配置定义自己的场景。

---

## 核心概念

### Pheromone（信息素）

信息的标准载体，是 Crew Pro 协议的最小执行单元。

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识 |
| `type` | 任意字符串（如 message, task, approval）— 完全由用户定义 |
| `sender` | 发送者 ID（强制从 X-Agent-ID 头读取） |
| `targets` | 目标 ID 列表 |
| `content` | 信息内容 |
| `parent_pheromone_id` | 父节点，形成链路 |
| `hop_count` | 跳转次数（防 Storm，上限 5） |

### Agent Profile

每个 Agent 是独立个体，无预设角色。通过 API 注册或从 `config/agents.json` 加载。

---

## 安全协议

| 漏洞 | 协议 | 状态 |
|------|------|------|
| Pheromone Storm | hop_count ≥ MAX_HOPS → 强制 timeout | ✅ |
| 僵尸信息素 | pending > 600s → DLQ | ✅ |
| 上下文雪崩 | 链路过长时需 hook 压缩 | ✅ |
| 身份伪造 | X-Agent-ID 强制验证 | ✅ |
| 薛定谔 JSON | type/content 用户自定义 | ✅ |
| 并发双花 | 全局写锁（threading.Lock） | ✅ |

---

## 快速启动

```bash
git clone https://github.com/yourname/crew_demo.git
cd crew_demo

# 运行（会自动加载 config/agents.json 的默认3个 agent）
cd src
python app.py

# 打开浏览器
open http://localhost:5200
```

---

## 四个 Tab

### Tab1: Agents
- 查看所有已注册 agent
- 添加新 agent（指定 id, name, role）
- 删除 agent

### Tab2: Send Pheromone
- 选择 sender（从已注册 agent 选择）
- 输入 type（任意字符串）
- 填写 content
- 多选 targets
- 可选填 parent_pheromone_id 构建链路

### Tab3: Chain Lookup
- 输入 pheromone id
- 可视化完整链路

### Tab4: Hooks Config
- 配置自动触发规则
- 当某 type 的 pheromone 创建时，自动发送 reply
- 示例：type=task 时自动由 agent_002 回复

---

## 配置

### config/agents.json

```json
[
  {
    "agent_id": "agent_001",
    "name": "Agent Alpha",
    "role": "worker",
    "specialty": "",
    "peer_eps": [],
    "judgment_criteria": []
  }
]
```

### config/hooks.json

```json
{
  "on_create": {
    "task": {
      "action": "reply",
      "sender": "agent_002",
      "reply_type": "response",
      "targets": ["agent_001"],
      "content": "Auto response to task"
    }
  }
}
```

---

## API 文档

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/agents` | GET | 获取所有 agent |
| `/api/agents` | POST | 注册新 agent |
| `/api/agents/<id>` | DELETE | 删除 agent |
| `/api/agents/<id>` | PUT | 更新 agent |
| `/api/pheromones` | GET | 获取所有 pheromone |
| `/api/pheromones` | POST | 创建 pheromone |
| `/api/chain/<id>` | GET | 链路追溯 |
| `/api/dlq` | GET | 死信队列 |
| `/api/hooks` | GET | 获取 hook 配置 |
| `/api/hooks` | PUT | 更新 hook 配置 |
| `/api/reset` | POST | 重置数据 |

### 发送 Pheromone

```bash
curl -X POST http://localhost:5200/api/pheromones \
  -H "Content-Type: application/json" \
  -H "X-Agent-ID: agent_001" \
  -d '{
    "type": "hello",
    "sender": "agent_001",
    "targets": ["agent_002"],
    "content": "Hello World"
  }'
```

### 注册 Agent

```bash
curl -X POST http://localhost:5200/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent_004",
    "name": "Agent Delta",
    "role": "coordinator"
  }'
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python / Flask |
| 前端 | Vanilla JS（零依赖） |
| 存储 | 内存（可扩展 SQLite） |
| 配置 | JSON 文件 |

---

## License

MIT