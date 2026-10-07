# Researcher 阶段并行度对比（真实 API）

> ⚠️ **这个数字会随下游状态波动**，所以请连「测量时间」一起看。
> 对比：结果可复现的**离线桩**版本见 [benchmark.md](benchmark.md)。
>
> 本文由脚本生成，不要手工编辑；重跑：
> `python -m scripts.bench_research --live --tasks 5 --repeat 2`

**测量时间**：2026-10-07 13:24（Asia/Shanghai）

# Researcher 阶段并行度对比（真实 API（受网络与限流影响））

- 子任务数：5　重复次数：2（取中位数）
- 环境：Python 3.12.7

| 模式 | 实现方式 | 耗时 | 加速比 | 成功/失败 |
|------|---------|------|--------|-----------|
| 串联 | `ThreadPoolExecutor(max_workers=1)` | 36.84 s | 1.00x | 5/0 |
| 并联 | `ThreadPoolExecutor(max_workers=5)` | 7.21 s | **5.11x** | 5/0 |

> 生成命令：`python -m scripts.bench_research --repeat 2 --live`

## 与项目早期测量的差异

同一脚本、同一口径（Researcher 阶段、5 子任务、取中位数），项目**早期**在真实 API 下
测得的是 **46 s → 23 s（2.0x）**。两次相差约 2.5 倍。

**这说明该加速比不是一个固定常数，而是高度依赖测量时下游的承载状态** ——
搜索 API 的并发限制、出口带宽共享、子任务耗时分布都会影响它。
因此本项目不再把这个数字写死在 README 里，而是提供脚本让任何人随时复测。
