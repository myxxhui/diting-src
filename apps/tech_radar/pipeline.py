#!/usr/bin/env python3
"""技术雷达 · 微信视频号技术知识采掘管道

通过 3 步将技术视频转为可分析文字：
    1. ffmpeg 提取音频（mp4 → mp3）
    2. DashScope ASR 转写（mp3 → 文字）
    3. 输出 Markdown 到 ./文本输出/

使用方法：
    # 首次：创建 workspace 目录
    mkdir -p ~/tech-radar-workspace/原始视频

    # 把 WeChatVideoDownloader 下载的 .mp4 放入原始视频/

    # 运行（可指定工作目录，默认 ~/tech-radar-workspace）
    python3 -m apps.tech_radar.pipeline
    python3 -m apps.tech_radar.pipeline --workspace ~/my-workspace
    python3 -m apps.tech_radar.pipeline --dry-run     # 预览处理列表，不实际执行

DNA 键: tech_radar.pipeline
[Ref: 03_/_共享规约/41_微信视频号技术雷达模块_全栈工程化设计.md]
"""
import os
import sys
import argparse
from pathlib import Path

# 确保 diting-src 根在 Python 路径中（允许从任何目录执行）
script_dir = Path(__file__).resolve().parent.parent.parent.parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from apps.tech_radar.config.settings import load_config
from apps.tech_radar.audio_extractor import extract_audio, get_video_duration_sec
from apps.tech_radar.asr_client import transcribe_sync
from apps.tech_radar.dedup import compute_quick_hash, PipelineState
from apps.tech_radar.cost_tracker import CostTracker


def parse_args():
    parser = argparse.ArgumentParser(
        description="技术雷达 · 微信视频号技术知识采掘管道",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python3 -m apps.tech_radar.pipeline
  python3 -m apps.tech_radar.pipeline --workspace ~/my-workspace
  python3 -m apps.tech_radar.pipeline --dry-run
        """,
    )
    parser.add_argument(
        "--workspace", "-w",
        default=None,
        help="工作目录路径（默认 ~/tech-radar-workspace）",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="预览模式：列出待处理文件，不实际执行",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = load_config(workspace_dir=args.workspace)

    # ── 确保目录存在 ──
    for key in ("video_dir", "audio_dir", "output_dir"):
        os.makedirs(cfg[key], exist_ok=True)
    print(f"📁 工作目录: {cfg['workspace_dir']}")
    print(f"📁 输入: {cfg['video_dir']}")
    print(f"📁 输出: {cfg['output_dir']}")
    print(f"💰 每日预算: {cfg['daily_budget_minutes']} 分钟")

    # ── 初始化状态 & 成本追踪 ──
    state = PipelineState(cfg["state_file"])
    tracker = CostTracker(
        daily_budget_minutes=cfg["daily_budget_minutes"],
        cost_per_minute=cfg["cost_per_minute"],
    )
    tracker.sync_usage(state.get_today_usage())

    # ── 列出待处理文件 ──
    video_files = sorted([
        f for f in os.listdir(cfg["video_dir"])
        if f.lower().endswith(".mp4")
    ])

    if not video_files:
        print(f"\n🔍 {cfg['video_dir']} 中没有 .mp4 文件。")
        print(f"   请先将视频放入 {cfg['video_dir']}/")
        print(f"   然后重新运行: python3 -m apps.tech_radar.pipeline")
        return

    pending = []
    for file in video_files:
        mp4_path = os.path.join(cfg["video_dir"], file)
        fhash = compute_quick_hash(mp4_path)

        if state.is_processed(fhash):
            print(f"⏭️  跳过（已处理）: {file}")
            continue

        duration_sec = get_video_duration_sec(mp4_path)
        if duration_sec < cfg["min_duration_sec"]:
            print(f"⏭️  跳过（过短 {duration_sec:.0f}s < {cfg['min_duration_sec']}s）: {file}")
            state.mark(fhash, "skipped", reason="too_short", source_file=file)
            continue

        pending.append((file, mp4_path, fhash, duration_sec))

    if not pending:
        print("\n🎉 所有文件已处理完毕。")
        print(state.summary())
        return

    # ── 预览模式 ──
    if args.dry_run:
        print(f"\n📋 待处理文件列表（共 {len(pending)} 个）:\n")
        for i, (file, _, _, dur_sec) in enumerate(pending, 1):
            print(f"  {i}. {file}  ({dur_sec:.0f}s = {dur_sec/60:.1f} 分钟)")
        total_min = sum(d[3] for d in pending) / 60
        cost = total_min * cfg["cost_per_minute"]
        print(f"\n   预估: {total_min:.0f} 分钟 · ¥{cost:.2f}")
        return

    # ── 逐个处理 ──
    print(f"\n🔧 开始处理 {len(pending)} 个文件...\n")

    for file, mp4_path, fhash, duration_sec in pending:
        duration_min = duration_sec / 60
        base_name = os.path.splitext(file)[0]
        mp3_path = os.path.join(cfg["audio_dir"], f"{base_name}.mp3")
        md_path = os.path.join(cfg["output_dir"], f"{base_name}.md")

        # ── 预算检查 ──
        if not tracker.check_budget(duration_min):
            print(f"⏸️  剩余 {len(pending) - pending.index((file, mp4_path, fhash, duration_sec)) - 1} 个文件已保留")
            print(f"   明早再跑 pipline.py 即可继续")
            break

        try:
            # Step 1: 提取音频
            print(f"🎬 [1/2] 提取音频: {file} ...", end=" ", flush=True)
            extract_audio(mp4_path, mp3_path)
            print(f"✅ ({duration_sec:.0f}s 视频)")

            # Step 2: ASR 转写
            print(f"🎤 [2/2] 语音转文字 → {base_name}.md ...", end=" ", flush=True)
            text = transcribe_sync(
                mp3_path,
                api_key=cfg["dashscope_api_key"],
            )
            print("✅")

            # 记录花费
            usage = tracker.record_usage(duration_min)

            # 写入 Markdown
            from datetime import datetime
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# {file}\n\n")
                f.write("---\n\n")
                f.write(f"- **时长**: {duration_sec:.0f}s\n")
                f.write(f"- **ASR 费用**: ¥{usage['cost']:.2f}\n")
                f.write(f"- **处理时间**: {datetime.now().isoformat()}\n\n")
                f.write("---\n\n")
                f.write("## 转录文本\n\n")
                f.write(text)
                f.write("\n")

            # 标记完成
            state.mark(
                fhash,
                "completed",
                source_file=file,
                duration_minutes=duration_min,
            )
            print(f"✅ 完成: {md_path}\n")

        except Exception as e:
            print(f"❌ 失败: {e}")
            state.mark(fhash, "failed", error=str(e), source_file=file)
            # 继续下一个文件，不中断整个管道
            continue

    # ── 最终汇总 ──
    print("=" * 50)
    print(state.summary())
    print(f"🔗 下一步: 在 Cursor 中打开 {cfg['output_dir']}/ 下的 .md 文件进行分析")
    print("=" * 50)


if __name__ == "__main__":
    main()
