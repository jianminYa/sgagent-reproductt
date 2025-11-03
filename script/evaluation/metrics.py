"""
评估指标计算：文件级、类级、行级准确率
"""
from typing import List, Tuple, Set, Dict
from dataclasses import dataclass


@dataclass
class EvaluationResult:
    """评估结果"""
    instance_id: str
    file_level_match: bool
    class_level_match: bool
    function_level_match: bool
    line_level_match: bool
    line_level_iou: float

    # 详细信息
    gt_files: List[str]
    pred_files: List[str]
    gt_classes: List[str]
    pred_classes: List[str]
    gt_functions: List[str]
    pred_functions: List[str]
    gt_line_ranges: List[Tuple[int, int]]
    pred_line_ranges: List[Tuple[int, int]]


class MetricsCalculator:
    """计算各级别的准确率指标"""

    @staticmethod
    def calculate_file_level_match(
        gt_files: List[str],
        pred_files: List[str]
    ) -> bool:
        """
        计算文件级别匹配

        策略：预测的文件集合是否包含所有 ground truth 文件

        Args:
            gt_files: ground truth 文件路径列表
            pred_files: 预测的文件路径列表

        Returns:
            是否匹配
        """
        if not gt_files:
            return not pred_files  # 两者都为空才匹配

        gt_set = set(gt_files)
        pred_set = set(pred_files)

        # 检查是否所有 gt 文件都在预测中
        return gt_set.issubset(pred_set)

    @staticmethod
    def calculate_class_level_match(
        gt_classes: List[str],
        pred_classes: List[str]
    ) -> bool:
        """
        计算类级别匹配

        策略：预测的类集合是否包含所有 ground truth 类

        Args:
            gt_classes: ground truth 类全限定名列表
            pred_classes: 预测的类全限定名列表

        Returns:
            是否匹配
        """
        if not gt_classes:
            # 如果 gt 没有类（可能是修改全局函数），则预测也不应该有类
            return not pred_classes

        gt_set = set(gt_classes)
        pred_set = set(pred_classes)

        # 检查是否所有 gt 类都在预测中
        return gt_set.issubset(pred_set)

    @staticmethod
    def calculate_function_level_match(
        gt_functions: List[str],
        pred_functions: List[str]
    ) -> bool:
        """
        计算函数级别匹配

        策略：预测的函数集合是否包含所有 ground truth 函数

        Args:
            gt_functions: ground truth 函数全限定名列表
            pred_functions: 预测的函数全限定名列表

        Returns:
            是否匹配
        """
        if not gt_functions:
            # 如果 gt 没有函数，则预测也不应该有函数
            return not pred_functions

        gt_set = set(gt_functions)
        pred_set = set(pred_functions)

        # 检查是否所有 gt 函数都在预测中
        return gt_set.issubset(pred_set)

    @staticmethod
    def calculate_line_level_match(
        gt_line_ranges: List[Tuple[int, int]],
        pred_line_ranges: List[Tuple[int, int]],
        tolerance: int = 5
    ) -> bool:
        """
        计算行级别匹配（使用容忍度）

        策略：预测的行号范围是否与 ground truth 行号范围足够接近

        Args:
            gt_line_ranges: ground truth 行号范围列表
            pred_line_ranges: 预测的行号范围列表
            tolerance: 容忍的行数差异

        Returns:
            是否匹配
        """
        if not gt_line_ranges:
            return not pred_line_ranges

        # 对每个 gt 范围，检查是否有预测范围接近
        for gt_start, gt_end in gt_line_ranges:
            match_found = False
            for pred_start, pred_end in pred_line_ranges:
                # 检查是否在容忍范围内
                if (abs(gt_start - pred_start) <= tolerance and
                    abs(gt_end - pred_end) <= tolerance):
                    match_found = True
                    break
            if not match_found:
                return False

        return True

    @staticmethod
    def calculate_line_level_iou(
        gt_line_ranges: List[Tuple[int, int]],
        pred_line_ranges: List[Tuple[int, int]]
    ) -> float:
        """
        计算行级别 IoU (Intersection over Union)

        策略：将所有行号范围转换为行号集合，计算交集和并集的比例

        Args:
            gt_line_ranges: ground truth 行号范围列表
            pred_line_ranges: 预测的行号范围列表

        Returns:
            IoU 值 (0-1)
        """
        if not gt_line_ranges and not pred_line_ranges:
            return 1.0

        if not gt_line_ranges or not pred_line_ranges:
            return 0.0

        # 转换为行号集合
        gt_lines = set()
        for start, end in gt_line_ranges:
            gt_lines.update(range(start, end + 1))

        pred_lines = set()
        for start, end in pred_line_ranges:
            pred_lines.update(range(start, end + 1))

        # 计算 IoU
        intersection = len(gt_lines & pred_lines)
        union = len(gt_lines | pred_lines)

        if union == 0:
            return 0.0

        return intersection / union

    @staticmethod
    def calculate_per_file_metrics(
        gt_files: List[str],
        gt_classes_per_file: Dict[str, List[str]],
        gt_lines_per_file: Dict[str, List[Tuple[int, int]]],
        pred_files: List[str],
        pred_classes_per_file: Dict[str, List[str]],
        pred_lines_per_file: Dict[str, List[Tuple[int, int]]]
    ) -> Dict[str, Dict]:
        """
        计算每个文件的详细指标

        Returns:
            {file_path: {class_match: bool, line_match: bool, line_iou: float}}
        """
        results = {}

        for gt_file in gt_files:
            gt_classes = gt_classes_per_file.get(gt_file, [])
            gt_lines = gt_lines_per_file.get(gt_file, [])

            pred_classes = pred_classes_per_file.get(gt_file, [])
            pred_lines = pred_lines_per_file.get(gt_file, [])

            class_match = MetricsCalculator.calculate_class_level_match(
                gt_classes, pred_classes
            )
            line_match = MetricsCalculator.calculate_line_level_match(
                gt_lines, pred_lines
            )
            line_iou = MetricsCalculator.calculate_line_level_iou(
                gt_lines, pred_lines
            )

            results[gt_file] = {
                "class_match": class_match,
                "line_match": line_match,
                "line_iou": line_iou
            }

        return results


def test_metrics():
    """测试指标计算"""
    calc = MetricsCalculator()

    # 测试文件级别匹配
    gt_files = ["astropy/io/fits/fitsrec.py"]
    pred_files = ["astropy/io/fits/fitsrec.py", "other.py"]
    assert calc.calculate_file_level_match(gt_files, pred_files) == True

    pred_files2 = ["other.py"]
    assert calc.calculate_file_level_match(gt_files, pred_files2) == False

    # 测试类级别匹配
    gt_classes = ["astropy.io.fits.fitsrec.FITS_rec"]
    pred_classes = ["astropy.io.fits.fitsrec.FITS_rec", "Other"]
    assert calc.calculate_class_level_match(gt_classes, pred_classes) == True

    # 测试函数级别匹配
    gt_functions = ["astropy.io.fits.fitsrec.FITS_rec._convert_format"]
    pred_functions = ["astropy.io.fits.fitsrec.FITS_rec._convert_format", "other_func"]
    assert calc.calculate_function_level_match(gt_functions, pred_functions) == True

    pred_functions2 = ["other_func"]
    assert calc.calculate_function_level_match(gt_functions, pred_functions2) == False

    # 测试行级别匹配
    gt_lines = [(1259, 1264)]
    pred_lines = [(1260, 1265)]
    assert calc.calculate_line_level_match(gt_lines, pred_lines, tolerance=5) == True

    pred_lines2 = [(1300, 1310)]
    assert calc.calculate_line_level_match(gt_lines, pred_lines2, tolerance=5) == False

    # 测试 IoU
    iou = calc.calculate_line_level_iou([(10, 20)], [(15, 25)])
    print(f"IoU: {iou:.3f}")
    assert 0 < iou < 1

    print("✓ All metrics tests passed!")


if __name__ == "__main__":
    test_metrics()
