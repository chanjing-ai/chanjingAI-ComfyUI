"""
ComfyUI 蝉镜 AI 插件
Cicada AI Plugin for ComfyUI

统一的蝉镜AI节点集合，包含所有功能
"""

import subprocess
import importlib
import sys
import os
import threading

__version__ = "1.0.0"

# ───────────────────────── 自动安装缺失依赖 ─────────────────────────
_DEPENDENCIES = [
    ("cv2", "opencv-python"),       # 视频尺寸检测
    ("requests", "requests"),       # HTTP 请求
    ("mutagen", "mutagen"),         # 音频时长检测（声音克隆）
]

for _module_name, _pip_name in _DEPENDENCIES:
    try:
        importlib.import_module(_module_name)
    except ImportError:
        print(f"📦 蝉镜AI插件：正在自动安装 {_pip_name} ...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", _pip_name],
                stdout=subprocess.DEVNULL,
            )
            print(f"✅ {_pip_name} 安装成功")
        except Exception as e:
            print(f"⚠️  {_pip_name} 自动安装失败: {e}")
            print(f"   请手动运行: pip install {_pip_name}")


# ───────────────────────── 自动更新检查 ─────────────────────────
def _check_and_update():
    """后台检查 GitHub 远程仓库是否有更新，如有则自动拉取。"""
    try:
        plugin_dir = os.path.dirname(os.path.abspath(__file__))

        # 确认是 git 仓库
        git_dir = os.path.join(plugin_dir, ".git")
        if not os.path.isdir(git_dir):
            return

        # fetch 远程最新信息（静默）
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=plugin_dir,
            capture_output=True,
            timeout=15,
        )

        # 获取本地和远程 HEAD 的 commit hash
        local_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()

        remote_hash = subprocess.run(
            ["git", "rev-parse", "@{u}"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()

        if not local_hash or not remote_hash:
            return

        if local_hash == remote_hash:
            print("✅ 蝉镜AI插件：已是最新版本")
            return

        # 检测本地是否有未提交的修改
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if status_result.stdout.strip():
            # 本地有修改，暂存后拉取再恢复
            print("🔄 蝉镜AI插件：检测到更新，正在暂存本地修改并拉取...")
            subprocess.run(
                ["git", "stash"],
                cwd=plugin_dir,
                capture_output=True,
                timeout=10,
            )
            pull_result = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=plugin_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "stash", "pop"],
                cwd=plugin_dir,
                capture_output=True,
                timeout=10,
            )
        else:
            print("🔄 蝉镜AI插件：检测到更新，正在自动拉取...")
            pull_result = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=plugin_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )

        if pull_result.returncode == 0:
            print("✅ 蝉镜AI插件：更新成功！请重启 ComfyUI 以使用最新版本。")
        else:
            stderr = pull_result.stderr.strip() if pull_result.stderr else ""
            print(f"⚠️  蝉镜AI插件：自动更新失败: {stderr}")
            print("   请手动执行: cd custom_nodes/chanjingAI-ComfyUI && git pull")

    except subprocess.TimeoutExpired:
        print("⚠️  蝉镜AI插件：更新检查超时，跳过本次检查")
    except Exception as e:
        print(f"⚠️  蝉镜AI插件：更新检查出错: {e}")


# 在后台线程中执行更新检查，不阻塞 ComfyUI 启动
_update_thread = threading.Thread(target=_check_and_update, daemon=True)
_update_thread.start()


# ───────────────────────── 导出节点 ─────────────────────────
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./js"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
