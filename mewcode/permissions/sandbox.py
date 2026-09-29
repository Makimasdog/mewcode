"""路径沙箱（五层权限体系的第 2 层能力）。

PathSandbox 的作用是：把 Agent 可访问的文件范围限定在"项目根目录"以及
额外的允许目录内，防止它读写项目目录之外（如 /etc、~/.ssh）的敏感路径。
"""
from __future__ import annotations

import tempfile
from pathlib import Path


class PathSandbox:
    """限制路径访问范围的安全边界。

    构造时确定"允许访问的根目录列表"；check() 用来判断某个路径是否落在这个范围内。
    """


    def __init__(
        self,
        project_root: str,
        extra_allowed: list[str] | None = None,
    ) -> None:
        """初始化沙箱。

        :param project_root: 项目根目录（主允许范围）。
        :param extra_allowed: 额外允许的目录列表（可选），例如某个工具产生的临时数据目录。
        """
        root = Path(project_root).resolve()  # resolve() 把相对路径变成规范化的绝对路径
        # 默认允许两个根：项目根 + 系统临时目录（tempfile）。resolve 保证可比性。
        self._allowed_roots: list[Path] = [root, Path(tempfile.gettempdir()).resolve()]
        if extra_allowed:
            for p in extra_allowed:
                self._allowed_roots.append(Path(p).resolve())


    @property
    def project_root(self) -> Path:
        """只读属性：返回主允许根（项目根目录），供外面读取当前项目根。"""
        return self._allowed_roots[0]


    def check(self, path: str) -> tuple[bool, str]:
        """判断路径是否在沙箱允许范围内。

        :param path: 要检查的路径（相对或绝对都可以）。
        :return: (是否允许, 不允许时的原因)。允许时 second 为空字符串。
        """
        p = Path(path).expanduser()  # 展开 ~ 为真实用户目录
        if not p.is_absolute():
            # 相对路径：以项目根为基准解析成绝对路径
            p = self.project_root / p
        abs_path = p.absolute()

        try:
            # 尽量解析真实路径：resolve(strict=True) 会跟随符号链接，防止通过 symlink 逃出沙箱
            real_path = abs_path.resolve(strict=True)
        except OSError:
            # 目标文件本身不存在（比如要新建的新文件），采用"逐步向上找已存在祖先"的策略：
            # 找到离得最近的已存在父目录，并基于它完成规范化，以正确处理新文件路径。
            ancestor = abs_path
            while not ancestor.exists():
                parent = ancestor.parent
                if parent == ancestor:  # 已到根目录都找不到，说明路径不可解析
                    return False, f"无法解析路径: {path}"
                ancestor = parent
            try:
                resolved_ancestor = ancestor.resolve(strict=True)
            except OSError:
                return False, f"无法解析路径: {path}"
            real_path = resolved_ancestor / abs_path.relative_to(ancestor)

        # 逐个允许根判断：real_path 若在某个允许根下（relative_to 不抛异常），则允许
        for root in self._allowed_roots:
            try:
                real_path.relative_to(root)
                return True, ""
            except ValueError:
                continue  # 不在这个根下，试下一个

        # 所有根都不匹配 → 超出沙箱范围，拒绝
        return False, f"路径 {path} 超出沙箱范围"