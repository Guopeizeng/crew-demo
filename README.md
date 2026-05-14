# Crew Demo

**让信息自己知道去哪。** Pheromone 链演示 —— 一个最小可运行的 Agent 协作原型。

---

## 场景

```
增 ──── 周报 ────→ Boss Agent
                      │
                 自动汇总生成
                 部门周报 digest
                      │
              ┌───────┴───────┐
              ↓               ↓
           彭老板            李HR
          （审批）          （归档）
```

> 员工提交周报 → Boss Agent 自动汇总 → 分发给老板和HR审批
> Agent 发现问题时主动创建 Task

---

## 安全协议（v1.2）

| 漏洞 | 协议 | 状态 |
|------|------|------|
| Pheromone Storm | hop_count ≥ MAX_HOPS → 强制 escalate | ✅ |
| 僵尸信息素 | 状态机 + DLQ（pending>600s） | ✅ |
| 上下文雪崩 | 链路压缩（chain>5 生成摘要） | ✅ |
| 身份伪造 | X-Agent-ID 强制验证 | ✅ |
| 薛定谔 JSON | 强类型校验（Enum + lowercasing） | ✅ |
| 并发双花 | 全局写锁（threading.Lock） | ✅ |

---

## 快速启动

```bash
# 克隆
git clone https://github.com/yourname/crew_demo.git
cd crew_demo/src

# 运行
python app.py

# 打开浏览器
open http://localhost:5200
```

---

## 核心概念

### Pheromone（信息素）

信息的标准载体，是 Crew Pro 协议的最小执行单元。

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识 |
| `type` | weekly_report / weekly_digest / approval / task / issue / summary |
| `sender` | 发送者 EP（强制从 X-Agent-ID 头读取） |
| `targets` | 目标 EP 列表 |
| `content` | 信息内容 |
| `parent_pheromone_id` | 父节点，形成链路 |
| `status` | pending → processing → approved / rejected / timeout / failed |
| `hop_count` | 跳转次数（防 Storm，上限 5） |

### Agent Profile

每个 Agent 的认知档案，决定它如何响应信息。

```json
{
  "agent_id": "boss_agent",
  "name": "Boss Agent",
  "role": "AI Agent",
  "ep": "EP002",
  "specialty": "团队协调、资源调配",
  "judgment_criteria": [
    "是否符合团队目标",
    "优先级是否合理",
    "资源是否够用"
  ],
  "peer_eps": ["EP001", "EP003", "EP004"]
}
```

### 链路追溯

任意 Pheromone 可向上追溯 parent，向下追溯 children。

```
GET /api/chain/<id>
→ [{ weekly_report }, { weekly_digest }, { approval }, { approval }]
```

---

## API 文档

### 信息素操作

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/pheromones` | GET | 获取所有信息素（含 DLQ 扫描） |
| `/api/pheromones` | POST | 创建信息素（原子锁保护） |
| `/api/chain/<id>` | GET | 链路追溯 |
| `/api/dlq` | GET | 查看死信队列 |
| `/api/reset` | POST | 重置数据 |

### Agent 操作

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/agents/profiles` | GET | 获取所有 Agent Profile |
| `/api/agents/<id>/create_task` | POST | Agent 主动创建 Task（强校验） |

### 创建周报

```bash
curl -X POST http://localhost:5200/api/pheromones \
  -H "Content-Type: application/json" \
  -H "X-Agent-ID: employee_zeng" \
  -d '{
    "type": "weekly_report",
    "sender": "employee_zeng",
    "targets": ["boss_agent"],
    "content": "完成了用户访谈和需求文档整理"
  }'
```

### Agent 主动创建 Task

```bash
curl -X POST http://localhost:5200/api/agents/boss_agent/create_task \
  -H "Content-Type: application/json" \
  -H "X-Agent-ID: boss_agent" \
  -d '{
    "content": "周报提交率偏低，建议提醒未提交人员",
    "task_type": "issue",
    "priority": "high",
    "targets": ["manager_peng"]
  }'
```

---

## Schema 校验（漏洞四）

`/api/agents/<id>/create_task` 对 payload 有强类型要求：

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_type` | `task` \| `issue` | 必填，大小写敏感 |
| `priority` | `low` \| `medium` \| `high` | 必填，大小写不敏感（自动规范化） |
| `content` | string | 必填，不能为空 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.14+ / Flask |
| 前端 | Vanilla JS（零依赖） |
| 存储 | 内存（可扩展 SQLite） |
| 校验 | Enum + lowercasing（无 Pydantic 依赖） |

---

## 启发来源

| 产品 | 启发 | 状态 |
|------|------|------|
| Crew Pro 原生 | Pheromone 链 + 链路追溯 | ✅ |
| AgentBridge | Agent Profile + 认知档案 | ✅ |
| Multica | Agent 主动创建 Task | ✅ |
| Bloome | — | 预留 visibility 字段 |
| Moxt | — | 预留学习能力扩展 |

---

## License

MIT