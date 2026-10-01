# Researcher 阶段并行度对比（离线桩（固定延迟，可复现））

- 子任务数：5　重复次数：2（取中位数）
- 环境：Python 3.12.7

| 模式 | 实现方式 | 耗时 | 加速比 | 成功/失败 |
|------|---------|------|--------|-----------|
| 串联 | `ThreadPoolExecutor(max_workers=1)` | 12.01 s | 1.00x | 5/0 |
| 并联 | `ThreadPoolExecutor(max_workers=5)` | 2.40 s | **5.00x** | 5/0 |

> 生成命令：`python -m scripts.bench_research --repeat 2`
