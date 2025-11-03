"""
解析 git diff 格式的补丁，提取文件路径和修改的行号信息
"""
import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class HunkInfo:
    old_start: int
    old_count: int
    new_start: int
    new_count: int

    def get_old_line_range(self) -> Tuple[int, int]:
        return (self.old_start, self.old_start + self.old_count - 1)

    def get_new_line_range(self) -> Tuple[int, int]:
        return (self.new_start, self.new_start + self.new_count - 1)


@dataclass
class FilePatch:
    """表示单个文件的补丁信息"""
    old_path: str
    new_path: str
    hunks: List[HunkInfo]

    def get_all_modified_lines(self) -> List[Tuple[int, int]]:
        """返回所有修改的行号范围列表"""
        return [hunk.get_new_line_range() for hunk in self.hunks]


class PatchParser:
    """解析 git diff 格式的补丁"""

    # 匹配 diff --git a/path/to/file b/path/to/file
    FILE_PATTERN = re.compile(r'^diff --git a/(.*?) b/(.*?)$', re.MULTILINE)

    # 匹配 @@ -old_start,old_count +new_start,new_count @@
    HUNK_PATTERN = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', re.MULTILINE)

    @staticmethod
    def parse_patch(patch: str) -> List[FilePatch]:
        """
        解析 git diff 格式的补丁

        Args:
            patch: git diff 格式的补丁字符串

        Returns:
            FilePatch 对象列表
        """
        if not patch or not patch.strip():
            return []

        file_patches = []

        # 按文件分割补丁
        file_sections = re.split(r'(?=^diff --git)', patch, flags=re.MULTILINE)

        for section in file_sections:
            if not section.strip():
                continue

            # 提取文件路径
            file_match = PatchParser.FILE_PATTERN.search(section)
            if not file_match:
                continue

            old_path = file_match.group(1)
            new_path = file_match.group(2)

            # 提取所有 hunks
            hunks = []
            for hunk_match in PatchParser.HUNK_PATTERN.finditer(section):
                old_start = int(hunk_match.group(1))
                old_count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
                new_start = int(hunk_match.group(3))
                new_count = int(hunk_match.group(4)) if hunk_match.group(4) else 1

                hunks.append(HunkInfo(old_start, old_count, new_start, new_count))

            if hunks:  # 只添加有修改的文件
                file_patches.append(FilePatch(old_path, new_path, hunks))

        return file_patches

    @staticmethod
    def get_modified_files(patch: str) -> List[str]:
        """
        获取补丁中所有修改的文件路径

        Args:
            patch: git diff 格式的补丁字符串

        Returns:
            文件路径列表
        """
        file_patches = PatchParser.parse_patch(patch)
        return [fp.new_path for fp in file_patches]

    @staticmethod
    def get_file_line_ranges(patch: str, file_path: str) -> List[Tuple[int, int]]:
        """
        获取指定文件的所有修改行号范围

        Args:
            patch: git diff 格式的补丁字符串
            file_path: 文件路径

        Returns:
            (start_line, end_line) 元组列表
        """
        file_patches = PatchParser.parse_patch(patch)
        for fp in file_patches:
            if fp.new_path == file_path or fp.old_path == file_path:
                return fp.get_all_modified_lines()
        return []


def test_patch_parser():
    """测试补丁解析器"""
    sample_patch = """diff --git a/astropy/io/fits/fitsrec.py b/astropy/io/fits/fitsrec.py
index 574b4073b1..affab8f2eb 100644
--- a/astropy/io/fits/fitsrec.py
+++ b/astropy/io/fits/fitsrec.py
@@ -1259,9 +1259,10 @@ class FITS_rec(np.recarray):

             output_field[jdx] = value


         # Replace exponent separator in floating point numbers
         if 'D' in format:
-            output_field.replace(encode_ascii('E'), encode_ascii('D'))
+            output_field = output_field.replace(encode_ascii('E'), encode_ascii('D'))


 def _get_recarray_field(array, key):
"""

    parser = PatchParser()
    file_patches = parser.parse_patch(sample_patch)

    print(f"找到 {len(file_patches)} 个文件的修改")
    for fp in file_patches:
        print(f"\n文件: {fp.new_path}")
        print(f"  Hunks: {len(fp.hunks)}")
        for i, hunk in enumerate(fp.hunks):
            print(f"    Hunk {i+1}: 旧文件 {hunk.get_old_line_range()}, 新文件 {hunk.get_new_line_range()}")

    # 测试获取文件列表
    files = parser.get_modified_files(sample_patch)
    print(f"\n修改的文件: {files}")

    # 测试获取行号范围
    line_ranges = parser.get_file_line_ranges(sample_patch, "astropy/io/fits/fitsrec.py")
    print(f"行号范围: {line_ranges}")


if __name__ == "__main__":
    test_patch_parser()
