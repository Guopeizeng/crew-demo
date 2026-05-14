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
| `type` | weekly_report / weekly_digest / approval / task / issue |
| `sender` | 发送者 EP |
| `targets` | 目标 EP 列表 |
| `content` | 信息内容 |
| `parent_pheromone_id` | 父节点，形成链路 |
| `judgment_status` | pending → approved |

### Agent Profile

每个 Agent 的认知档案，决定它如何响应信息。

```json
{
  "agent_id": "boss_agent",
  "name": "Boss Agent",
  "role": "AI Agent",
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
| `/api/pheromones` | GET | 获取所有信息素 |
| `/api/pheromones` | POST | 创建信息素 |
| `/api/chain/<id>` | GET | 链路追溯 |
| `/api/reset` | POST | 重置数据 |

### Agent 操作

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/agents/profiles` | GET | 获取所有 Agent Profile |
| `/api/agents/<id>/create_task` | POST | Agent 主动创建 Task |

### 创建周报

```bash
curl -X POST http://localhost:5200/api/pheromones \
  -H "Content-Type: application/json" \
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
  -d '{
    "content": "周报提交率偏低，建议提醒未提交人员",
    "task_type": "issue",
    "priority": "high",
    "targets": ["manager_peng"]
  }'
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.14+ / Flask |
| 前端 | Vanilla JS（零依赖） |
| 存储 | 内存（可扩展 SQLite） |

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