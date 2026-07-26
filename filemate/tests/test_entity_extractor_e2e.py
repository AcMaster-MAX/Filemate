"""实体抽取端到端测试脚本。

用法:
    python filemate/tests/test_entity_extractor_e2e.py

功能:
    1. 扫描 datasets/raw/ 下所有样本文件
    2. 用 FileParser 解析文件内容
    3. 用 EntityExtractor 抽取实体
    4. 将结果保存到 test_entity_result.json 供人工标注评估

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
from filemate.understanding.classifier import Classifier
from filemate.understanding.entity_extractor import EntityExtractor
from filemate.llm_client import LLMClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATASETS_DIR = PROJECT_ROOT / "datasets" / "raw"
results: list[dict] = []


def scan_samples() -> list[tuple[Path, str]]:
    samples = []
    if not DATASETS_DIR.exists():
        return samples
    for category_dir in sorted(DATASETS_DIR.iterdir()):
        if not category_dir.is_dir() or category_dir.name == ".gitkeep":
            continue
        for fp in sorted(category_dir.iterdir()):
            if fp.is_file():
                samples.append((fp, category_dir.name))
    return samples


def run():
    samples = scan_samples()
    if not samples:
        logger.error("未找到样本文件")
        sys.exit(1)

    logger.info("共 %d 份样本", len(samples))

    llm_client = LLMClient()
    parser = FileParser()
    classifier = Classifier(llm_client)
    extractor = EntityExtractor(llm_client)

    for idx, (fp, actual_cat) in enumerate(samples, 1):
        logger.info("[%d/%d] %s (真实: %s)", idx, len(samples), fp.name, actual_cat)

        try:
            parsed = parser.parse(fp)
            raw_text = parsed.get("raw_text", "")
            if parsed.get("error") or not raw_text.strip():
                results.append({
                    "file": fp.name,
                    "actual_category": actual_cat,
                    "error": parsed.get("error", "空内容"),
                    "entities": None,
                })
                logger.warning("  解析失败/空: %s", parsed.get("error", "空"))
                continue
        except Exception as exc:
            results.append({"file": fp.name, "actual_category": actual_cat, "error": str(exc), "entities": None})
            continue

        try:
            cat_result = classifier.classify(raw_text, fp.name)
            category = cat_result.get("category", "待确认")
        except Exception:
            category = "待确认"

        try:
            entities = extractor.extract(raw_text)
        except Exception as exc:
            results.append({"file": fp.name, "actual_category": actual_cat, "error": f"抽取失败: {exc}", "entities": None})
            continue

        results.append({
            "file": fp.name,
            "actual_category": actual_cat,
            "predicted_category": category,
            "entities": entities,
        })

        # 简要输出
        ce = entities.get("course_name") or "—"
        te = entities.get("task_description") or "—"
        de = entities.get("deadline") or "—"
        lo = entities.get("location") or "—"
        logger.info("  [分类] %s | 课程=%s 任务=%s 截止=%s 地点=%s", category, ce, te, de, lo)

    # 保存
    output = PROJECT_ROOT / "test_entity_result.json"
    output.write_text(
        json.dumps({"summary": {"total": len(samples), "results": len(results)}, "details": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n结果已保存到: {output}")
    print(f"共 {len(results)} 条，请人工标注 recall 后重新运行评估。")


if __name__ == "__main__":
    run()
