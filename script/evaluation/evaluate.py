"""
主评估脚本：计算补丁定位的文件级、类级、函数级、行级准确率
直接从 predictions.json 评估
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
from tqdm import tqdm

# 添加项目根目录到 sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from script.evaluation.patch_parser import PatchParser
from script.evaluation.ast_analyzer import ASTAnalyzer
from script.evaluation.metrics import MetricsCalculator, EvaluationResult


class PatchEvaluator:
    """补丁定位评估器"""

    def __init__(
        self,
        dataset_path: str,
        predictions_path: str,
        projects_dir: str
    ):
        """
        初始化评估器

        Args:
            dataset_path: lite_dataset.json 的路径
            predictions_path: predictions.json 的路径
            projects_dir: 项目代码目录路径（如 /Users/hanyu/projects）
        """
        self.dataset_path = Path(dataset_path)
        self.predictions_path = Path(predictions_path)
        self.projects_dir = Path(projects_dir)

        # 加载 ground truth
        with open(self.dataset_path, 'r') as f:
            self.dataset = json.load(f)

        # 加载预测结果
        with open(self.predictions_path, 'r') as f:
            self.predictions = json.load(f)

        # 构建 instance_id -> ground truth 的映射
        self.gt_map = {item["instance_id"]: item for item in self.dataset}

        self.parser = PatchParser()

    def extract_patch_info(
        self,
        patch: str,
        repo_path: Path,
        commit_hash: str
    ) -> Tuple[List[str], Dict[str, List[str]], Dict[str, List[str]], Dict[str, List[Tuple[int, int]]]]:
        """
        从补丁中提取文件、类、函数、行号信息

        Args:
            patch: git diff 格式的补丁
            repo_path: 代码仓库路径
            commit_hash: commit hash

        Returns:
            (files, classes_per_file, functions_per_file, lines_per_file)
        """
        file_patches = self.parser.parse_patch(patch)
        files = [fp.new_path for fp in file_patches]

        classes_per_file = {}
        functions_per_file = {}
        lines_per_file = {}

        # 创建 AST 分析器
        analyzer = ASTAnalyzer(str(repo_path))

        # Checkout 到指定 commit
        if not analyzer.checkout_commit(commit_hash):
            print(f"Warning: Failed to checkout to {commit_hash}")
            return files, {}, {}, {}

        # 对每个文件提取类、函数和行号信息
        for fp in file_patches:
            file_path = fp.new_path
            line_ranges = fp.get_all_modified_lines()

            # 获取类信息
            try:
                classes = analyzer.get_classes_at_lines(file_path, line_ranges)
                classes_per_file[file_path] = classes
            except Exception as e:
                print(f"Warning: Failed to get classes for {file_path}: {e}")
                classes_per_file[file_path] = []

            # 获取函数信息
            try:
                functions = analyzer.get_function_at_lines(file_path, line_ranges)
                functions_per_file[file_path] = functions
            except Exception as e:
                print(f"Warning: Failed to get functions for {file_path}: {e}")
                functions_per_file[file_path] = []

            lines_per_file[file_path] = line_ranges

        return files, classes_per_file, functions_per_file, lines_per_file

    def evaluate_single_prediction(
        self,
        instance_id: str,
        pred_patch: str,
        gt_item: Dict
    ) -> EvaluationResult:
        """
        评估单个预测

        Args:
            instance_id: instance ID
            pred_patch: 预测的补丁
            gt_item: ground truth 条目

        Returns:
            EvaluationResult
        """
        # 提取 ground truth 信息
        gt_patch = gt_item["patch"]
        base_commit = gt_item["base_commit"]
        repo_name = gt_item["repo"].split("/")[-1]  # 例如: astropy/astropy -> astropy

        # 构建仓库路径
        repo_path = self.projects_dir / repo_name

        if not repo_path.exists():
            print(f"Warning: Repository not found: {repo_path}")
            return EvaluationResult(
                instance_id=instance_id,
                file_level_match=False,
                class_level_match=False,
                function_level_match=False,
                line_level_match=False,
                line_level_iou=0.0,
                gt_files=[],
                pred_files=[],
                gt_classes=[],
                pred_classes=[],
                gt_functions=[],
                pred_functions=[],
                gt_line_ranges=[],
                pred_line_ranges=[]
            )

        # 提取 ground truth 信息
        gt_files, gt_classes_per_file, gt_functions_per_file, gt_lines_per_file = self.extract_patch_info(
            gt_patch, repo_path, base_commit
        )

        # 提取预测信息
        pred_files, pred_classes_per_file, pred_functions_per_file, pred_lines_per_file = self.extract_patch_info(
            pred_patch, repo_path, base_commit
        )

        # 汇总所有类、函数和行号
        gt_classes = []
        for classes in gt_classes_per_file.values():
            gt_classes.extend(classes)

        pred_classes = []
        for classes in pred_classes_per_file.values():
            pred_classes.extend(classes)

        gt_functions = []
        for functions in gt_functions_per_file.values():
            gt_functions.extend(functions)

        pred_functions = []
        for functions in pred_functions_per_file.values():
            pred_functions.extend(functions)

        gt_line_ranges = []
        for lines in gt_lines_per_file.values():
            gt_line_ranges.extend(lines)

        pred_line_ranges = []
        for lines in pred_lines_per_file.values():
            pred_line_ranges.extend(lines)

        # 计算匹配
        calc = MetricsCalculator()
        file_match = calc.calculate_file_level_match(gt_files, pred_files)
        class_match = calc.calculate_class_level_match(gt_classes, pred_classes)
        function_match = calc.calculate_function_level_match(gt_functions, pred_functions)
        line_match = calc.calculate_line_level_match(gt_line_ranges, pred_line_ranges)
        line_iou = calc.calculate_line_level_iou(gt_line_ranges, pred_line_ranges)

        return EvaluationResult(
            instance_id=instance_id,
            file_level_match=file_match,
            class_level_match=class_match,
            function_level_match=function_match,
            line_level_match=line_match,
            line_level_iou=line_iou,
            gt_files=gt_files,
            pred_files=pred_files,
            gt_classes=gt_classes,
            pred_classes=pred_classes,
            gt_functions=gt_functions,
            pred_functions=pred_functions,
            gt_line_ranges=gt_line_ranges,
            pred_line_ranges=pred_line_ranges
        )

    def evaluate_all(
        self,
        output_file: str = None
    ):
        """
        评估所有实例

        Args:
            output_file: 输出文件路径（可选）
        """
        print(f"找到 {len(self.predictions)} 个预测")
        print(f"Ground truth 包含 {len(self.gt_map)} 个 instance")

        # 汇总结果
        all_results = {}
        summary = {
            "file_match": 0,
            "class_match": 0,
            "function_match": 0,
            "line_match": 0,
            "total_iou": 0.0,
            "instances_evaluated": 0
        }

        # 评估每个 instance
        for instance_id in tqdm(sorted(self.predictions.keys())):
            if instance_id not in self.gt_map:
                print(f"Skipping {instance_id}: not in ground truth")
                continue

            gt_item = self.gt_map[instance_id]
            pred_patch = self.predictions[instance_id]["model_patch"]

            # 评估
            result = self.evaluate_single_prediction(instance_id, pred_patch, gt_item)
            all_results[instance_id] = result

            summary["instances_evaluated"] += 1
            if result.file_level_match:
                summary["file_match"] += 1
            if result.class_level_match:
                summary["class_match"] += 1
            if result.function_level_match:
                summary["function_match"] += 1
            if result.line_level_match:
                summary["line_match"] += 1
            summary["total_iou"] += result.line_level_iou

        # 计算准确率
        total_instances = summary["instances_evaluated"]
        print(f"\n评估完成！")
        print(f"  评估的 instance 数: {total_instances}")

        print("\n" + "="*60)
        print("定位准确率统计:")
        print("="*60)

        if total_instances > 0:
            file_acc = summary["file_match"] / total_instances
            class_acc = summary["class_match"] / total_instances
            function_acc = summary["function_match"] / total_instances
            line_acc = summary["line_match"] / total_instances
            avg_iou = summary["total_iou"] / total_instances

            print(f"\n文件级准确率:   {file_acc:.2%} ({summary['file_match']}/{total_instances})")
            print(f"类级准确率:     {class_acc:.2%} ({summary['class_match']}/{total_instances})")
            print(f"函数级准确率:   {function_acc:.2%} ({summary['function_match']}/{total_instances})")
            print(f"行级准确率:     {line_acc:.2%} ({summary['line_match']}/{total_instances})")
            print(f"平均行级IoU:    {avg_iou:.4f}")
        else:
            print("\n无有效的评估结果")

        # 保存结果
        if output_file:
            output_data = {
                "summary": {
                    "total_instances": total_instances,
                    "file_accuracy": summary["file_match"] / total_instances if total_instances > 0 else 0,
                    "class_accuracy": summary["class_match"] / total_instances if total_instances > 0 else 0,
                    "function_accuracy": summary["function_match"] / total_instances if total_instances > 0 else 0,
                    "line_accuracy": summary["line_match"] / total_instances if total_instances > 0 else 0,
                    "avg_line_iou": summary["total_iou"] / total_instances if total_instances > 0 else 0,
                    "file_match_count": summary["file_match"],
                    "class_match_count": summary["class_match"],
                    "function_match_count": summary["function_match"],
                    "line_match_count": summary["line_match"]
                },
                "per_instance_results": {
                    instance_id: {
                        "file_match": result.file_level_match,
                        "class_match": result.class_level_match,
                        "function_match": result.function_level_match,
                        "line_match": result.line_level_match,
                        "line_iou": result.line_level_iou,
                        "gt_files": result.gt_files,
                        "pred_files": result.pred_files,
                        "gt_classes": result.gt_classes,
                        "pred_classes": result.pred_classes,
                        "gt_functions": result.gt_functions,
                        "pred_functions": result.pred_functions
                    }
                    for instance_id, result in all_results.items()
                }
            }

            with open(output_file, 'w') as f:
                json.dump(output_data, f, indent=2)

            print(f"\n结果已保存到: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="评估补丁定位准确率")
    parser.add_argument(
        "--dataset",
        type=str,
        default="/Users/hanyu/isea/lite_dataset.json",
        help="lite_dataset.json 路径"
    )
    parser.add_argument(
        "--predictions",
        type=str,
        default="/Users/hanyu/isea/predictions.json",
        help="predictions.json 路径"
    )
    parser.add_argument(
        "--projects",
        type=str,
        default="/Users/hanyu/projects",
        help="项目代码目录路径"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/Users/hanyu/isea/script/evaluation/results.json",
        help="输出结果文件路径"
    )

    args = parser.parse_args()

    evaluator = PatchEvaluator(
        dataset_path=args.dataset,
        predictions_path=args.predictions,
        projects_dir=args.projects
    )

    evaluator.evaluate_all(output_file=args.output)


if __name__ == "__main__":
    main()
