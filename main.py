from core.orchestrator import run_swarm


def main():
    query = input("请输入你的研究问题：").strip()
    if not query:
        print("问题不能为空")
        return

    state = run_swarm(query, verbose=True)

    # 打印最终报告
    print("=" * 60)
    print("📄 最终报告")
    print("=" * 60)
    print(state.draft)

    # 保存报告到文件
    import os
    os.makedirs("notes", exist_ok=True)
    report_path = f"notes/report_{state.query[:20]}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(state.draft)
    print(f"\n📁 报告已保存到 {report_path}")
    
    # 打印执行日志
    print("\n" + "=" * 60)
    print("📊 执行日志")
    print("=" * 60)
    for entry in state.history:
        print(f"  [{entry['agent']}] {entry['action']}")


if __name__ == "__main__":
    main()