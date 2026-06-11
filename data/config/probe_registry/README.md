# Probe 实现注册表

机器真相源，供 Cursor/CI 按 `t1_pipeline` / `update_trigger` / `cache_group` 路由实现。

**规约**：`diting-doc/03_原子目标与规约/_共享规约/28_` §2.13

| 文件 | 标的 | JL3 |
|------|------|:---:|
| `601138.yaml` | 工业富联 | 27 |
| `300308.yaml` | 中际旭创 | 21 |
| `300502.yaml` | 新易盛 | 21 |
| `300394.yaml` | 天孚通信 | 22 |
| `688008.yaml` | 澜起科技 | 19 |
| `002837.yaml` | 英维克 | 14 |

再生成（除 601138 外五 Profile）：

```bash
cd diting-src && python scripts/generate_probe_registry.py
```
