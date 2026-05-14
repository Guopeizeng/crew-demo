# Crew Demo

> 信息自己知道去哪 · Pheromone 链演示

一个最小可运行的 Demo，演示 Crew Pro 的核心概念：**Pheromone 链**。

## 场景

```
员工提交周报 → Boss Agent 自动汇总 → 分发给老板和HR审批
```

当你提交周报后：
1. Boss Agent 自动生成部门周报
2. 老板和 HR 自动收到通知
3. 所有人可以审批，全程链路可追溯

## 快速启动

```bash
cd crew_demo/src
python app.py
```

然后打开 http://localhost:5200

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /api/participants` | GET | 获取所有参与者 |
| `GET /api/pheromones` | GET | 获取所有信息素 |
| `POST /api/pheromones` | POST | 创建新的信息素 |
| `GET /api/chain/<id>` | GET | 获取信息素链路 |
| `POST /api/reset` | POST | 重置数据 |

## 验证

```bash
# Test with curl
# 1. 提交周报
curl -X POST http://localhost:5200/api/pheromones \
  -H "Content-Type: application/json" \
  -d '{"type":"weekly_report","sender":"employee_zeng","targets":["boss_agent"],"content":"完成了用户访谈"}'

# 2. 查看所有信息素
curl http://localhost:5200/api/pheromones

# 3. 查看链路
curl http://localhost:5200/api/chain/<id>
```

## 核心概念

**Pheromone（信息素）**：信息的标准载体，包含：
- `id`：唯一标识
- `type`：类型（weekly_report / weekly_digest / approval）
- `sender`：发送者
- `targets`：目标列表
- `content`：内容
- `parent_pheromone_id`：父节点，形成链路
- `judgment_status`：状态（pending / approved / rejected）

**链路（Chain）**：通过 `parent_pheromone_id` 形成，从任意节点可以追溯完整上下文。

## 技术栈

- Python 3.14+
- Flask
- Vanilla JS（无框架）

## License

MIT