"""里程碑识别端到端测试脚本。

用法:
    python filemate/tests/test_milestone_e2e.py

功能:
    1. 扫描 datasets/raw/竞赛通知/ 下所有样本文件
    2. 用 FileParser 解析文件内容
    3. 用 MilestoneDetector 识别里程碑
    4. 将结果保存到 test_milestone_result.json 供人工标注评估

注意: 需要先配置好 .env 中的 API Key。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# 加载 .env
env_path = Path(__file__).resolve().parents[2] / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            import os
            os.environ[key.strip()] = value.strip()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from filemate.perception.file_parser import FileParser
from filemate.understanding.milestone_detector import MilestoneDetector
from filemate.llm_client import LLMClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

COMPETITION_DIR = PROJECT_ROOT / "datasets" / "raw" / "竞赛通知"
results: list[dict] = []


def scan_samples() -> list[Path]:
    samples = []
    if not COMPETITION_DIR.exists():
        logger.error("目录不存在: %s", COMPETITION_DIR)
        return samples
    for fp in sorted(COMPETITION_DIR.iterdir()):
        if fp.is_file():
            samples.append(fp)
    return samples


def run():
    samples = scan_samples()
    if not samples:
        logger.error("未找到竞赛通知样本文件")
        sys.exit(1)

    logger.info("共 %d 份竞赛通知样本", len(samples))

    llm_client = LLMClient()
    parser = FileParser()
    detector = MilestoneDetector(llm_client)

    for idx, fp in enumerate(samples, 1):
        logger.info("[%d/%d] %s", idx, len(samples), fp.name)

        try:
            parsed = parser.parse(fp)
            raw_text = parsed.get("raw_text", "")
            if parsed.get("error") or not raw_text.strip():
                results.append({
                    "file": fp.name,
                    "error": parsed.get("error", "空内容"),
                    "milestones": [],
                })
                logger.warning("  解析失败/空: %s", parsed.get("error", "空"))
                continue
        except Exception as exc:
            results.append({"file": fp.name, "error": str(exc), "milestones": []})
            continue

        try:
            milestones = detector.detect(raw_text)
        except Exception as exc:
            results.append({"file": fp.name, "error": f"识别失败: {exc}", "milestones": []})
            continue

        results.append({
            "file": fp.name,
            "error": None,
            "milestones": milestones,
        })

        if milestones:
            for m in milestones:
                logger.info("  [%s] %s", m["order"], m["date"])
        else:
            logger.info("  无里程碑")

    # 保存
    output = PROJECT_ROOT / "test_milestone_result.json"
    output.write_text(
        json.dumps({"summary": {"total": len(samples), "with_milestones": sum(1 for r in results if r.get("milestones"))}, "details": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n结果已保存到: {output}")
    print(f"共 {len(results)} 条，其中识别到里程碑 {sum(1 for r in results if r.get('milestones'))} 条")
    print("请人工标注 ground truth 后重新运行评估。")


if __name__ == "__main__":
    run()
