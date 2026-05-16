# Crew Demo

**让信息自己知道去哪。**

一个通用的 Pheromone（信息素）框架——给 AI Agent 用的消息传递协议。你可以用它快速搭建多 Agent 协作系统、审批流、知识追踪链路。

用它替代复杂的消息队列，实现"信息知道该去哪"的智能路由。

---

## 一句话理解

```
你发出一条信息 → 它自动找到该看的人 → 形成可追溯的链路
```

不需要配置路由规则。Pheromone 自己会沿着链路传播。

---

## 快速开始

```bash
git clone https://github.com/Guopeizeng/crew-demo.git
cd crew-demo/src
python app.py

# 打开浏览器
open http://localhost:5200
```

默认自带 3 个示例 Agent，直接发送消息试试。

---

## 场景示例

### 场景：任务协作

**甲** 发起任务 → **乙** 评审 → **丙** 审批

```
[甲] ── task ──→ [乙] ── review ──→ [丙]
                     │
                     └── 通过 → 自动通知甲
```

在 UI 上操作：
1. **Send Pheromone** → 选甲，type=task，targets=乙
2. Chain Lookup → 输入 id → 看完整链路
3. 乙点 **approve** → 链路继续传播 → 甲收到结果

### 场景：自动回复

配置 Hook：type=task 时自动由 agent_002 回复

```
甲发送 task
      ↓
系统自动触发
      ↓
agent_002 收到自动回复
```

---

## 核心概念

### Pheromone（信息素）

一条消息，携带：
- **type** — 消息类型（task、approval、feedback...）
- **sender** — 谁发的
- **targets** — 发给谁
- **content** — 内容
- **parent_pheromone_id** — 父节点（形成链路）

### Agent

任意角色。你定义它是 worker、coordinator 还是 approver。

### Chain（链路）

每个 Pheromone 知道自己是谁发的、发给谁。顺着 `parent_pheromone_id` 可以追溯完整链路。

---

## 功能

| 功能 | 说明 |
|------|------|
| **发送信息** | 选 sender → 填 type → 写内容 → 发给谁 |
| **链路追溯** | 输入任意 pheromone id，看它的完整链路（树形图） |
| **审批流** | pending 状态可 approve/reject，状态不可逆 |
| **自动触发** | 配置 Hook，某种 type 出现时自动回复 |
| **TTL 机制** | 信息有过期时间，超时自动清理 |

---

## 配置（可选）

默认 3 个 Agent 开箱即用。如需自定义：

**config/agents.json**
```json
[
  { "agent_id": "my_agent", "name": "我的 Agent", "role": "worker" }
]
```

**config/hooks.json**
```json
{
  "on_create": {
    "task": {
      "action": "reply",
      "sender": "agent_002",
      "reply_type": "response",
      "targets": ["agent_001"],
      "content": "已收到，我会处理"
    }
  }
}
```

---

## API（开发者用）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/pheromones` | GET/POST | 发送/查看信息 |
| `/api/pheromones/<id>/judge` | PUT | 审批（approve/reject） |
| `/api/chain/<id>/tree` | GET | 链路树形可视化 |
| `/api/agents` | GET/POST | 管理 Agent |
| `/api/hooks` | GET/PUT | 配置自动触发 |

---

## 技术细节

- 后端：Python / Flask
- 前端：Vanilla JS，零依赖
- 存储：内存（重启清空，可扩展）
- 安全：X-Agent-ID 验证、输入校验、写锁保护

---

## License

MIT