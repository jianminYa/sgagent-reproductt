"""
使用 AST 分析代码，将行号映射到类级别信息
"""
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import json

# 添加项目根目录到 sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from kg.utils import parse_python_file


class ASTAnalyzer:
    """使用 AST 分析代码结构"""

    def __init__(self, repo_path: str):
        """
        初始化 AST 分析器

        Args:
            repo_path: 代码仓库的根路径
        """
        self.repo_path = Path(repo_path)

    def checkout_commit(self, commit_hash: str) -> bool:
        """
        切换到指定的 commit

        Args:
            commit_hash: commit hash

        Returns:
            是否成功切换
        """
        try:
            subprocess.run(
                ["git", "checkout", commit_hash],
                cwd=str(self.repo_path),
                check=True,
                capture_output=True,
                text=True
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error checking out commit {commit_hash}: {e.stderr}")
            return False

    def get_classes_at_lines(
        self,
        file_path: str,
        line_ranges: List[Tuple[int, int]]
    ) -> List[str]:
        """
        获取指定行号范围内的所有类的全限定名

        Args:
            file_path: 相对于 repo_path 的文件路径
            line_ranges: 行号范围列表 [(start, end), ...]

        Returns:
            类的全限定名列表（去重）
        """
        full_path = self.repo_path / file_path

        if not full_path.exists():
            print(f"Warning: File not found: {full_path}")
            return []

        # 构造 module_prefix
        # 例如: astropy/io/fits/fitsrec.py -> astropy.io.fits.fitsrec
        rel_path = Path(file_path).with_suffix('')
        module_prefix = ".".join(rel_path.parts)

        try:
            # 使用 kg/utils.py 的 parse_python_file
            classes, _, _, _ = parse_python_file(
                str(full_path),
                module_prefix
            )
        except Exception as e:
            print(f"Error parsing file {file_path}: {e}")
            return []

        # 查找在指定行号范围内的类
        matched_classes = set()
        for line_start, line_end in line_ranges:
            for cls in classes:
                cls_start = cls.get("start_line")
                cls_end = cls.get("end_line")

                # 检查是否有重叠
                if cls_start and cls_end:
                    if self._ranges_overlap(
                        (line_start, line_end),
                        (cls_start, cls_end)
                    ):
                        matched_classes.add(cls["full_qualified_name"])

        return sorted(list(matched_classes))

    @staticmethod
    def _ranges_overlap(range1: Tuple[int, int], range2: Tuple[int, int]) -> bool:
        """
        检查两个范围是否重叠

        Args:
            range1: (start, end)
            range2: (start, end)

        Returns:
            是否重叠
        """
        start1, end1 = range1
        start2, end2 = range2
        return not (end1 < start2 or end2 < start1)

    def get_function_at_lines(
        self,
        file_path: str,
        line_ranges: List[Tuple[int, int]]
    ) -> List[str]:
        """
        获取指定行号范围内的所有函数的全限定名

        Args:
            file_path: 相对于 repo_path 的文件路径
            line_ranges: 行号范围列表 [(start, end), ...]

        Returns:
            函数的全限定名列表（去重）
        """
        full_path = self.repo_path / file_path

        if not full_path.exists():
            print(f"Warning: File not found: {full_path}")
            return []

        rel_path = Path(file_path).with_suffix('')
        module_prefix = ".".join(rel_path.parts)

        try:
            classes, functions, _, _ = parse_python_file(
                str(full_path),
                module_prefix
            )
        except Exception as e:
            print(f"Error parsing file {file_path}: {e}")
            return []

        matched_functions = set()

        # 检查类方法
        for cls in classes:
            for method in cls.get("methods", []):
                method_start = method.get("start_line")
                method_end = method.get("end_line")
                if method_start and method_end:
                    for line_start, line_end in line_ranges:
                        if self._ranges_overlap(
                            (line_start, line_end),
                            (method_start, method_end)
                        ):
                            matched_functions.add(method["full_qualified_name"])

        # 检查独立函数
        for func in functions:
            func_start = func.get("start_line")
            func_end = func.get("end_line")
            if func_start and func_end:
                for line_start, line_end in line_ranges:
                    if self._ranges_overlap(
                        (line_start, line_end),
                        (func_start, func_end)
                    ):
                        matched_functions.add(func["full_qualified_name"])

        return sorted(list(matched_functions))


def test_ast_analyzer():
    """测试 AST 分析器"""
    # 这个测试需要一个实际的 git 仓库
    # 示例: 使用 astropy 仓库
    repo_path = "/Users/hanyu/projects/astropy"
    commit_hash = "d16bfe05a744909de4b27f5875fe0d4ed41ce607"

    analyzer = ASTAnalyzer(repo_path)

    # Checkout 到指定 commit
    print(f"Checking out to {commit_hash}...")
    if analyzer.checkout_commit(commit_hash):
        print("✓ Checkout successful")

        # 测试获取类信息
        file_path = "astropy/modeling/separable.py"
        line_ranges = [(242, 248)]  # 假设这是修改的行号范围

        classes = analyzer.get_classes_at_lines(file_path, line_ranges)
        print(f"\n在 {file_path} 的行 {line_ranges} 找到的类:")
        for cls in classes:
            print(f"  - {cls}")

        functions = analyzer.get_function_at_lines(file_path, line_ranges)
        print(f"\n在 {file_path} 的行 {line_ranges} 找到的函数:")
        for func in functions:
            print(f"  - {func}")
    else:
        print("✗ Checkout failed")


if __name__ == "__main__":
    test_ast_analyzer()
