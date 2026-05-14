# Crew Demo

> 信息自己知道去哪 · Pheromone 链演示

## 场景

```
员工提交周报 → Boss Agent 自动汇总 → 分发给老板和HR审批
Agent 发现问题时主动创建 Task
```

## 核心概念

**Pheromone（信息素）**：信息的标准载体
- `id` / `type` / `sender` / `targets` / `content`
- `parent_pheromone_id`：父节点，形成链路
- `judgment_status`：pending / approved

**Agent Profile**：Agent 的认知档案
- 判断标准（judgment_criteria）
- 专长（specialty）
- 需要对齐的 EP（peer_eps）

**链路追溯**：从任意节点可追溯完整上下文

## 启动

```bash
cd crew_demo/src
python app.py
# 打开 http://localhost:5200
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /api/pheromones` | GET | 获取所有信息素 |
| `POST /api/pheromones` | POST | 创建信息素 |
| `GET /api/chain/<id>` | GET | 链路追溯 |
| `GET /api/agents/profiles` | GET | 获取 Agent Profile |
| `POST /api/agents/<id>/create_task` | POST | Agent 主动创建 Task |
| `POST /api/reset` | POST | 重置 |

## 验证

```bash
# 提交周报
curl -X POST http://localhost:5200/api/pheromones \
  -H "Content-Type: application/json" \
  -d '{"type":"weekly_report","sender":"employee_zeng","targets":["boss_agent"],"content":"完成了用户访谈"}'

# 查看链路
curl http://localhost:5200/api/chain/<id>
```

## 技术栈

- Python 3.14+
- Flask
- Vanilla JS（无框架）

## License

MIT