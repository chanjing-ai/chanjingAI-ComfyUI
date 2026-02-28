"""
蝉镜 AI ComfyUI 节点集合
Cicada AI Nodes for ComfyUI

包含：对口型、声音克隆、视频播放器
"""

import os
import json
import time
import requests
import folder_paths
import mimetypes
import hashlib

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    # 仅在真正需要时才提示（在使用时检测）

try:
    from mutagen import File as MutagenFile
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    # 仅在真正需要时才提示（在使用时检测）


# ==================== 统一鉴权管理 ====================

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(PLUGIN_DIR, "config.json")
TOKEN_CACHE_FILE = os.path.join(PLUGIN_DIR, ".cache", "token.json")
VOICE_CLONE_CACHE_FILE = os.path.join(PLUGIN_DIR, ".cache", "voice_clone.json")


class CicadaAuth:
    """
    统一鉴权管理器（全局单例）

    架构设计：
    - 凭证配置：用户编辑 config.json（app_id / secret_key）
    - Token 缓存：自动管理 .cache/token.json（access_token / 过期时间 / 凭证指纹）
    - 所有节点调用 CicadaAuth.get_token() 即可，无需传入任何凭证
    - Token 过期前 5 分钟自动刷新，刷新失败自动重试
    - 凭证变更后自动作废旧 Token，无需手动清理缓存
    """
    _config = None          # 用户凭证缓存
    _config_hash = None     # 凭证指纹（用于检测变更）
    _token = None           # access_token 字符串
    _token_expire = 0       # token 过期时间戳
    _token_config_hash = None  # 生成当前 token 时的凭证指纹

    # ---------- 用户凭证（config.json） ----------

    @classmethod
    def _compute_config_hash(cls, app_id, secret_key):
        """计算凭证指纹（MD5），用于检测 config.json 是否变更"""
        return hashlib.md5(f"{app_id}:{secret_key}".encode()).hexdigest()

    @classmethod
    def _load_config(cls):
        """
        从磁盘加载用户凭证配置（每次都重新读取，确保能检测到变更）
        """
        if not os.path.exists(CONFIG_FILE):
            raise FileNotFoundError(
                f"❌ 未找到配置文件: {CONFIG_FILE}\n"
                f"请复制 config.example.json 为 config.json 并填入你的 app_id 和 secret_key\n"
                f"获取地址: https://www.chanjing.cc/platform/api_keys"
            )
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise Exception(f"❌ config.json 格式错误: {e}")

        app_id = config.get("app_id", "").strip()
        secret_key = config.get("secret_key", "").strip()

        if not app_id or not secret_key:
            raise Exception(
                "❌ config.json 中 app_id 或 secret_key 为空\n"
                "请填入有效的凭证，获取地址: https://www.chanjing.cc/platform/api_keys"
            )
        # 检查占位符
        if "your_" in app_id or "your_" in secret_key:
            raise Exception(
                "❌ config.json 中的凭证仍是示例占位符，请替换为真实的 app_id 和 secret_key"
            )

        cls._config = {"app_id": app_id, "secret_key": secret_key}
        cls._config_hash = cls._compute_config_hash(app_id, secret_key)
        return cls._config

    @classmethod
    def get_config(cls):
        """获取用户凭证（带缓存）"""
        if cls._config is None:
            cls._load_config()
        return cls._config

    # ---------- Token 缓存（.cache/token.json） ----------

    @classmethod
    def _load_token_cache(cls):
        """从磁盘加载 token 缓存"""
        try:
            if os.path.exists(TOKEN_CACHE_FILE):
                with open(TOKEN_CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    cls._token = data.get("access_token")
                    cls._token_expire = data.get("expire_time", 0)
                    cls._token_config_hash = data.get("config_hash")
        except Exception:
            cls._token = None
            cls._token_expire = 0
            cls._token_config_hash = None

    @classmethod
    def _save_token_cache(cls):
        """将 token 缓存写入磁盘（连同凭证指纹一起保存）"""
        try:
            cache_dir = os.path.dirname(TOKEN_CACHE_FILE)
            os.makedirs(cache_dir, exist_ok=True)
            with open(TOKEN_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    "access_token": cls._token,
                    "expire_time": cls._token_expire,
                    "config_hash": cls._config_hash,
                }, f, indent=2)
        except Exception as e:
            print(f"⚠️  保存 token 缓存失败: {e}")

    # ---------- 核心方法 ----------

    @classmethod
    def _config_changed(cls):
        """检测凭证是否发生变更（对比当前 config.json 与 token 关联的凭证指纹）"""
        return cls._config_hash != cls._token_config_hash

    @classmethod
    def _refresh_token(cls):
        """向蝉镜 API 请求新 token"""
        config = cls.get_config()
        print("🔑 正在获取 AccessToken...")

        result = api_json_request(
            "POST",
            f"{BASE_URL}/open/v1/access_token",
            _retried_auth=True,  # 获取 token 的请求本身不应触发 token 自动刷新，防止递归
            json={"app_id": config["app_id"], "secret_key": config["secret_key"]},
        )
        data = result.get("data", {})
        cls._token = data.get("access_token")
        cls._token_expire = time.time() + 24 * 3600  # 24h 有效期
        cls._token_config_hash = cls._config_hash    # 记录生成此 token 的凭证指纹

        if not cls._token:
            raise Exception("API 返回的 access_token 为空，请检查 app_id / secret_key 是否正确")

        cls._save_token_cache()
        print("✅ AccessToken 获取成功并已缓存")

    @classmethod
    def get_token(cls):
        """
        获取 AccessToken（所有节点统一调用此方法）
        - 每次调用都重新读取 config.json，检测凭证是否变更
        - 凭证变更 → 自动作废旧 Token，重新获取
        - 凭证未变 → 优先使用内存/磁盘缓存，过期前 5 分钟自动刷新
        """
        now = time.time()

        # 0. 每次都重新读取 config.json，确保能检测到凭证变更
        cls._load_config()

        # 1. 检测凭证是否变更 → 变更则作废旧 token
        if cls._config_changed():
            if cls._token:
                print("🔄 检测到凭证变更，旧 Token 已作废，正在重新获取...")
            cls._token = None
            cls._token_expire = 0
            cls._token_config_hash = None

        # 2. 内存缓存有效
        if cls._token and now < cls._token_expire - 300:
            return cls._token

        # 3. 尝试从磁盘恢复（首次调用或进程重启后）
        if cls._token is None:
            cls._load_token_cache()
            # 磁盘缓存也要验证凭证指纹
            if cls._token and now < cls._token_expire - 300 and not cls._config_changed():
                print("✅ 使用缓存的 AccessToken")
                return cls._token
            # 磁盘缓存的凭证指纹不匹配，作废
            if cls._config_changed():
                print("🔄 磁盘缓存的 Token 与当前凭证不匹配，将重新获取")
                cls._token = None
                cls._token_expire = 0
                cls._token_config_hash = None

        # 4. 需要刷新
        cls._refresh_token()
        return cls._token

    @classmethod
    def reset(cls):
        """重置鉴权状态（用于凭证变更后强制刷新）"""
        cls._config = None
        cls._config_hash = None
        cls._token = None
        cls._token_expire = 0
        cls._token_config_hash = None


# ==================== 声音克隆缓存 ====================

class VoiceCloneCache:
    """
    声音克隆结果缓存
    
    缓存 key = md5(音频文件内容) + model_type
    缓存 value = voice_id（蝉镜平台返回的克隆声音 ID）
    
    同一个音频文件 + 同一个模型，克隆结果相同，无需重复克隆。
    """
    _cache = None  # 内存缓存

    @classmethod
    def _load(cls):
        """从磁盘加载缓存"""
        if cls._cache is not None:
            return
        try:
            if os.path.exists(VOICE_CLONE_CACHE_FILE):
                with open(VOICE_CLONE_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cls._cache = json.load(f)
            else:
                cls._cache = {}
        except Exception:
            cls._cache = {}

    @classmethod
    def _save(cls):
        """持久化缓存到磁盘"""
        try:
            cache_dir = os.path.dirname(VOICE_CLONE_CACHE_FILE)
            os.makedirs(cache_dir, exist_ok=True)
            with open(VOICE_CLONE_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cls._cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️  保存声音克隆缓存失败: {e}")

    @classmethod
    def _make_key(cls, file_hash, model_type):
        """生成缓存 key"""
        return f"{file_hash}_{model_type}"

    @classmethod
    def get(cls, file_hash, model_type):
        """
        查询缓存，返回 voice_id 或 None
        """
        cls._load()
        key = cls._make_key(file_hash, model_type)
        entry = cls._cache.get(key)
        if entry:
            return entry.get("voice_id")
        return None

    @classmethod
    def put(cls, file_hash, model_type, voice_id):
        """
        写入缓存
        """
        cls._load()
        key = cls._make_key(file_hash, model_type)
        cls._cache[key] = {
            "voice_id": voice_id,
            "model_type": model_type,
            "created_at": time.time(),
        }
        cls._save()

    @classmethod
    def remove(cls, file_hash, model_type):
        """删除某条缓存（声音过期/失效时调用）"""
        cls._load()
        key = cls._make_key(file_hash, model_type)
        if key in cls._cache:
            del cls._cache[key]
            cls._save()


def file_content_hash(file_path):
    """计算文件内容的 MD5 哈希值"""
    h = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ==================== 频率控制器 ====================

class RateLimiter:
    """
    按接口类型分别控制频率
    - lip_sync / voice_clone: 10 RPM → 间隔6秒
    - tts:                    200 RPM → 间隔0.3秒
    - default:                通用 → 间隔1秒
    """
    _timestamps = {}  # {category: last_call_time}
    _intervals = {
        "lip_sync": 6.0,      # 10 RPM
        "voice_clone": 6.0,   # 10 RPM
        "tts": 0.5,           # 200 RPM（留一定余量）
        "default": 1.0,
    }

    @classmethod
    def wait(cls, category="default", silent=False):
        interval = cls._intervals.get(category, cls._intervals["default"])
        last_time = cls._timestamps.get(category, 0)
        elapsed = time.time() - last_time

        if elapsed < interval:
            wait_time = interval - elapsed
            if not silent:
                print(f"⏱️  频率控制({category})：等待 {wait_time:.1f}s...")
            time.sleep(wait_time)

        cls._timestamps[category] = time.time()


# ==================== 进度条管理 ====================

class CicadaProgress:
    """
    蝉镜任务进度条（可复用）
    
    支持多阶段任务，自动映射到 ComfyUI 前端进度条。
    每个阶段有名称、权重（占总进度的比例），阶段内可更新子进度。
    
    用法:
        # 定义阶段: (名称, 权重)
        progress = CicadaProgress([
            ("上传文件", 10),
            ("处理中", 70),
            ("下载结果", 20),
        ])
        
        progress.start()                    # 开始（显示 0%）
        progress.advance("上传文件")         # 进入"上传文件"阶段
        progress.update(50, "上传中...")     # 阶段内 50%
        progress.advance("处理中")           # 进入"处理中"阶段
        progress.update(30, "渲染中...")     # 阶段内 30%
        progress.finish("完成！")            # 100%
    """

    def __init__(self, stages):
        """
        stages: [(name, weight), ...] 阶段列表
        weight 是相对权重，会自动归一化
        """
        self.stages = []
        total_weight = sum(w for _, w in stages)
        
        cumulative = 0
        for name, weight in stages:
            pct = weight / total_weight * 100
            self.stages.append({
                "name": name,
                "start_pct": cumulative,
                "span_pct": pct,
            })
            cumulative += pct
        
        self._stage_idx = -1
        self._comfy_bar = None
        self._last_msg = ""
        
        # 初始化 ComfyUI 进度条
        try:
            from comfy.utils import ProgressBar
            self._comfy_bar = ProgressBar(100)
        except Exception:
            pass

    def _set_progress(self, pct, msg=""):
        """设置全局进度百分比（0-100）"""
        pct = max(0, min(100, int(pct)))
        self._last_msg = msg
        
        # 更新 ComfyUI 前端进度条
        if self._comfy_bar:
            self._comfy_bar.update_absolute(pct, 100)
        
        # 终端输出
        filled = int(30 * pct / 100)
        bar = '█' * filled + '░' * (30 - filled)
        status = f" - {msg}" if msg else ""
        print(f"\r⏳ [{bar}] {pct}%{status}")
    
    def start(self):
        """开始任务"""
        self._set_progress(0, "准备中...")
    
    def advance(self, stage_name):
        """
        进入指定阶段
        自动将进度设为该阶段的起始百分比
        """
        for i, stage in enumerate(self.stages):
            if stage["name"] == stage_name:
                self._stage_idx = i
                self._set_progress(stage["start_pct"], stage_name)
                return
        # 未找到阶段名，忽略
        print(f"⚠️  未知阶段: {stage_name}")
    
    def update(self, inner_pct, msg=None):
        """
        更新当前阶段内的子进度
        inner_pct: 0-100（阶段内的百分比）
        """
        if self._stage_idx < 0:
            return
        
        stage = self.stages[self._stage_idx]
        global_pct = stage["start_pct"] + stage["span_pct"] * inner_pct / 100
        display_msg = msg if msg else stage["name"]
        self._set_progress(global_pct, display_msg)
    
    def finish(self, msg="完成！"):
        """任务完成，进度设为 100%"""
        self._set_progress(100, msg)


# ==================== 网络请求工具 ====================

def api_request(method, url, max_retries=3, retry_delay=3, rate_category="default", silent_rate=False, **kwargs):
    """
    带重试和频率控制的 HTTP 请求
    - 自动重试网络错误（不重试业务错误）
    - 自动频率控制
    - silent_rate: 静默频率控制日志（轮询场景下避免刷屏）
    """
    RateLimiter.wait(rate_category, silent=silent_rate)

    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            if "timeout" not in kwargs:
                kwargs["timeout"] = 30
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.ConnectionError as e:
            last_exception = e
            if attempt < max_retries:
                print(f"⚠️  网络连接失败，{retry_delay}s后重试 ({attempt}/{max_retries})...")
                time.sleep(retry_delay)
        except requests.exceptions.Timeout as e:
            last_exception = e
            if attempt < max_retries:
                print(f"⚠️  请求超时，{retry_delay}s后重试 ({attempt}/{max_retries})...")
                time.sleep(retry_delay)
        except requests.exceptions.HTTPError:
            raise  # HTTP 4xx/5xx 不重试，直接抛出
        except Exception:
            raise

    raise Exception(f"请求失败（已重试{max_retries}次）: {last_exception}")


def api_json_request(method, url, rate_category="default", silent_rate=False,
                     _retried_auth=False, **kwargs):
    """
    发送请求并解析JSON响应，检查业务状态码
    - Token 过期时自动刷新并重试一次
    - 已知错误提供清晰的中文提示和解决方案
    """
    response = api_request(method, url, rate_category=rate_category, silent_rate=silent_rate, **kwargs)
    result = response.json()
    code = result.get("code")

    if code == 0:
        return result

    msg = result.get("msg", "未知错误")

    # ---- Token 过期/失效 → 自动刷新并重试一次 ----
    if code in (10400, 10401) and not _retried_auth:
        print(f"⚠️  AccessToken 已失效 (code={code})，正在自动刷新...")
        CicadaAuth.reset()
        try:
            new_token = CicadaAuth.get_token()
            # 更新请求头中的 token 并重试
            headers = kwargs.get("headers", {})
            if isinstance(headers, dict) and "access_token" in headers:
                headers = dict(headers)
                headers["access_token"] = new_token
                kwargs["headers"] = headers
            print("✅ Token 已刷新，正在重试请求...")
            return api_json_request(method, url, rate_category=rate_category,
                                    silent_rate=silent_rate, _retried_auth=True, **kwargs)
        except Exception as refresh_err:
            raise Exception(
                f"❌ AccessToken 已失效且自动刷新失败\n\n"
                f"请检查 config.json 中的凭证是否正确：\n"
                f"  📁 配置文件: {CONFIG_FILE}\n"
                f"  🔑 获取凭证: https://www.chanjing.cc/platform/api_keys\n\n"
                f"错误详情: {refresh_err}"
            )

    # Token 相关错误（刷新重试后仍然失败）
    if code in (10400, 10401):
        raise Exception(
            f"❌ AccessToken 验证失败\n\n"
            f"Token 自动刷新后仍然失败，请检查：\n"
            f"  1. config.json 中的 app_id 和 secret_key 是否正确\n"
            f"  2. 凭证是否已过期或被禁用\n\n"
            f"  📁 配置文件: {CONFIG_FILE}\n"
            f"  🔑 获取凭证: https://www.chanjing.cc/platform/api_keys\n\n"
            f"API 返回 (code={code}): {msg}"
        )

    # ---- 其他未知错误 ----
    raise Exception(f"❌ API 请求失败 (code={code}): {msg}")


def check_billing_error(msg):
    """
    检测详情接口返回的 msg 是否为蝉豆扣费失败。
    蝉豆校验是后置处理的，创建接口不会报错，
    而是在详情轮询接口的 msg 字段中返回 "扣费失败" 等信息。
    如果检测到扣费失败，抛出包含充值引导的友好异常。
    """
    if not msg:
        return
    billing_keywords = ["扣费失败", "余额不足", "蝉豆不足", "蝉豆余额", "欠费"]
    if any(kw in msg for kw in billing_keywords):
        raise Exception(
            f"❌ 蝉豆余额不足，扣费失败\n\n"
            f"当前操作需要消耗蝉豆，您的账户余额不足。\n"
            f"请前往蝉镜平台充值后重试：\n\n"
            f"  💰 充值地址: https://www.chanjing.cc\n"
            f"  📊 查看用量: https://www.chanjing.cc/platform/api_keys\n\n"
            f"API 返回: {msg}"
        )


# ==================== 共享工具 ====================

BASE_URL = "https://open-api.chanjing.cc"


def format_file_size(size_bytes):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def get_audio_duration(file_path):
    """
    获取音频文件时长（秒）
    优先使用 mutagen（最准确），否则尝试 pydub（需要ffmpeg），最后尝试 scipy（仅wav）
    返回: float（秒）或 None（无法获取）
    """
    if not os.path.exists(file_path):
        return None

    # 方法1: mutagen（支持 mp3/wav/m4a/flac/ogg 等，最推荐）
    if MUTAGEN_AVAILABLE:
        try:
            audio = MutagenFile(file_path)
            if audio is not None and hasattr(audio.info, 'length'):
                return audio.info.length
        except Exception:
            pass

    # 方法2: scipy（仅支持 wav）
    try:
        from scipy.io import wavfile
        sample_rate, data = wavfile.read(file_path)
        return len(data) / float(sample_rate)
    except Exception:
        pass

    return None


def trim_audio(file_path, max_duration=299):
    """
    裁剪音频到指定时长（秒）
    直接调用系统 ffmpeg，无需额外 Python 依赖
    返回: 裁剪后的文件路径，失败返回 None
    """
    import tempfile
    import shutil
    import subprocess
    
    # 查找系统 ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        print("❌ 未检测到系统 ffmpeg，无法裁剪音频")
        print("   安装方法: brew install ffmpeg")
        return None
    
    print(f"✅ 检测到 ffmpeg: {ffmpeg_path}")
    print(f"🔧 正在裁剪音频到 {format_duration(max_duration)}...")
    
    ext = os.path.splitext(file_path)[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=ext,
        dir=folder_paths.get_temp_directory()
    )
    tmp.close()
    
    try:
        result = subprocess.run(
            [ffmpeg_path, "-i", file_path, "-t", str(max_duration), "-y", tmp.name],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0 and os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 0:
            new_duration = get_audio_duration(tmp.name)
            dur_str = f"，时长: {format_duration(new_duration)}" if new_duration else ""
            print(f"✅ 音频裁剪完成{dur_str}")
            return tmp.name
        else:
            print(f"❌ ffmpeg 裁剪失败 (returncode={result.returncode})")
            if result.stderr:
                # 只显示最后几行
                err_lines = result.stderr.strip().split('\n')
                for line in err_lines[-3:]:
                    print(f"   {line}")
            return None
            
    except Exception as e:
        print(f"❌ ffmpeg 调用出错: {e}")
        return None


def format_duration(seconds):
    """格式化时长（秒 → 分:秒）"""
    if seconds is None:
        return "未知"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def extract_file_path(file_input, file_type="文件"):
    """
    从各种输入类型中智能提取文件路径。
    支持：字符串、字典、列表、ComfyUI 原生 VideoFromFile/AudioInput 等对象。
    """
    import io as _io

    # 1. 字符串 → 直接返回
    if isinstance(file_input, str):
        return file_input

    # 2. ComfyUI 原生视频/音频对象（VideoFromFile / VideoInput 等）
    #    公开方法 get_stream_source() 返回文件路径(str) 或 BytesIO
    if hasattr(file_input, 'get_stream_source'):
        source = file_input.get_stream_source()
        if isinstance(source, str):
            return source
        # BytesIO → 保存为临时文件
        if isinstance(source, _io.BytesIO):
            return _save_bytes_to_temp(source, file_type)

    # 3. ComfyUI 原生视频对象的 save_to 方法
    if hasattr(file_input, 'save_to') and not isinstance(file_input, (str, dict)):
        import tempfile
        suffix = ".mp4" if "视频" in file_type or "video" in file_type.lower() else ".wav"
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix,
            dir=folder_paths.get_temp_directory()
        )
        tmp.close()
        file_input.save_to(tmp.name)
        print(f"📁 已将 {type(file_input).__name__} 保存为临时文件: {tmp.name}")
        return tmp.name

    # 4. ComfyUI AudioInput (dict with 'waveform' and 'sample_rate')
    if isinstance(file_input, dict) and 'waveform' in file_input and 'sample_rate' in file_input:
        return _save_audio_dict_to_temp(file_input)

    # 5. 普通字典 → 查找路径键
    if isinstance(file_input, dict):
        for key in ['path', 'file', 'filename', 'filepath', 'file_path', 'url', 'source']:
            if key in file_input and isinstance(file_input[key], str):
                return file_input[key]
        if len(file_input) == 1:
            value = list(file_input.values())[0]
            if isinstance(value, str):
                return value

    # 6. 列表/元组 → 递归提取
    if isinstance(file_input, (list, tuple)):
        for item in file_input:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                try:
                    return extract_file_path(item, file_type)
                except Exception:
                    continue

    # 7. 通用对象属性
    for attr in ('path', 'file', 'filename'):
        if hasattr(file_input, attr):
            val = getattr(file_input, attr)
            if isinstance(val, str):
                return val

    # 8. 尝试访问私有属性（兜底：VideoFromFile.__file → _VideoFromFile__file）
    for mangled in ('_VideoFromFile__file', '_AudioFromFile__file'):
        if hasattr(file_input, mangled):
            val = getattr(file_input, mangled)
            if isinstance(val, str):
                return val

    # 调试信息：列出对象所有属性，帮助排查兼容性问题
    obj_attrs = [a for a in dir(file_input) if not a.startswith('__')]
    raise Exception(
        f"❌ 无法从 {file_type} 输入中提取文件路径。\n"
        f"输入类型: {type(file_input).__name__}\n"
        f"MRO: {[c.__name__ for c in type(file_input).__mro__]}\n"
        f"可用属性: {obj_attrs}\n"
        f"请确保上游节点输出包含文件路径信息，或直接输入文件路径字符串。"
    )


def _save_bytes_to_temp(bytesio, file_type):
    """将 BytesIO 保存为临时文件并返回路径"""
    import tempfile
    suffix = ".mp4" if "视频" in file_type or "video" in file_type.lower() else ".wav"
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix,
        dir=folder_paths.get_temp_directory()
    )
    bytesio.seek(0)
    tmp.write(bytesio.read())
    tmp.close()
    print(f"📁 已将 BytesIO 保存为临时文件: {tmp.name}")
    return tmp.name


def _save_audio_dict_to_temp(audio_dict):
    """
    将 ComfyUI AudioInput dict (waveform + sample_rate) 保存为临时 wav 文件。
    优先使用 scipy，其次 soundfile，最后 torchaudio（需要 ffmpeg 后端）。
    """
    import tempfile
    import numpy as np

    waveform = audio_dict['waveform']
    sample_rate = int(audio_dict['sample_rate'])

    # waveform shape: (batch, channels, samples) → 取第一个 batch
    if waveform.dim() == 3:
        waveform = waveform[0]
    # waveform shape: (channels, samples) → 转为 numpy (samples, channels)
    audio_np = waveform.cpu().numpy().T

    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".wav",
        dir=folder_paths.get_temp_directory()
    )
    tmp.close()

    # 方法1：scipy.io.wavfile（最常见，无需额外依赖）
    try:
        from scipy.io import wavfile
        # scipy 要求 int16 或 float32
        if audio_np.dtype == np.float64:
            audio_np = audio_np.astype(np.float32)
        wavfile.write(tmp.name, sample_rate, audio_np)
        print(f"📁 已将音频数据保存为临时文件（scipy）: {tmp.name}")
        return tmp.name
    except ImportError:
        pass

    # 方法2：soundfile（需要安装但不需要 ffmpeg）
    try:
        import soundfile as sf
        sf.write(tmp.name, audio_np, sample_rate)
        print(f"📁 已将音频数据保存为临时文件（soundfile）: {tmp.name}")
        return tmp.name
    except ImportError:
        pass

    # 方法3：torchaudio（需要 ffmpeg/sox 后端）
    try:
        import torchaudio
        torchaudio.save(tmp.name, waveform.cpu(), sample_rate)
        print(f"📁 已将音频数据保存为临时文件（torchaudio）: {tmp.name}")
        return tmp.name
    except Exception as e:
        raise Exception(
            f"❌ 无法保存音频文件。尝试了 scipy/soundfile/torchaudio 均失败。\n"
            f"最后错误: {e}\n"
            f"建议: pip install scipy 或 pip install soundfile"
        )


class UploadProgress:
    """
    文件上传进度包装器
    将 bytes 包装为可读对象，requests 会分块读取，每块读取时打印进度。
    支持可选的 on_progress 回调，用于同步更新 ComfyUI 前端进度条。
    
    注意：进度 100% 表示数据已被 requests 读取完毕，
    但实际网络传输和服务器响应可能还需要额外时间。
    """

    def __init__(self, data, desc="上传", on_progress=None):
        self._data = data
        self._total = len(data)
        self._pos = 0
        self._desc = desc
        self._last_pct = -20  # 确保首次就打印
        self._on_progress = on_progress  # 回调: fn(pct, msg)
        self._done_printed = False

    def read(self, size=-1):
        if self._pos >= self._total:
            # 数据已全部读取，requests 可能还在等待服务器响应
            if not self._done_printed:
                self._done_printed = True
                print(f"   ⏳ 数据已发送，等待服务器响应...")
            return b""
        if size == -1 or size is None:
            chunk = self._data[self._pos:]
            self._pos = self._total
        else:
            end = min(self._pos + size, self._total)
            chunk = self._data[self._pos:end]
            self._pos = end

        # 每 20% 打印一次进度 + 更新前端进度条
        if self._total > 0:
            pct = int(self._pos / self._total * 100)
            if pct >= self._last_pct + 20 or pct >= 100:
                msg = f"{self._desc}: {pct}%"
                print(f"   📤 {msg} ({format_file_size(self._pos)}/{format_file_size(self._total)})")
                self._last_pct = pct
                if self._on_progress:
                    self._on_progress(pct, msg)

        return chunk

    def __len__(self):
        return self._total


def get_access_token():
    """获取 AccessToken 的便捷入口（所有节点统一调用）"""
    return CicadaAuth.get_token()


def upload_file(file_path, service, access_token, progress=None):
    """
    上传文件到蝉镜平台（两步上传）
    service 取值: customised_person / prompt_audio / make_video_audio / make_video_background
    progress: 可选的 CicadaProgress 实例，传入后上传过程中会同步更新 ComfyUI 前端进度条
    上传完成后会自动轮询文件状态，等待服务器同步完成（status=1）再返回
    返回 dict: {"file_id": "...", "url": "...(公网URL full_path)"}
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    file_label = "视频" if "video" in service else "音频"

    print(f"\n{'='*60}")
    print(f"⬆️  开始上传{file_label}文件")
    print(f"📁 文件名: {file_name}")
    print(f"📊 文件大小: {format_file_size(file_size)}")
    print(f"{'='*60}")

    # 步骤1：获取上传地址
    print("🔑 [1/2] 获取上传地址...")
    result = api_json_request(
        "GET",
        f"{BASE_URL}/open/v1/common/create_upload_url",
        rate_category="default",
        params={"service": service, "name": file_name},
        headers={"access_token": access_token},
    )

    upload_data = result.get("data", {})
    sign_url = upload_data.get("sign_url")
    file_id = upload_data.get("file_id")
    file_url = upload_data.get("full_path", "")  # 公网URL（声音克隆需要）
    mime_type = upload_data.get("mime_type", "application/octet-stream")
    print("✅ 上传地址获取成功")

    # 步骤2：PUT 上传文件（与 API 文档保持一致，直接发送文件数据）
    print("📤 [2/2] 上传文件数据...")
    with open(file_path, 'rb') as f:
        file_data = f.read()
    data_size = len(file_data)
    print(f"   已读取文件: {format_file_size(data_size)}")

    # 使用进度包装器，上传过程中显示进度（同时更新前端进度条）
    def _on_upload_progress(pct, msg):
        if progress:
            progress.update(pct, msg)

    upload_body = UploadProgress(file_data, f"上传{file_label}", on_progress=_on_upload_progress)

    response = api_request(
        "PUT", sign_url,
        max_retries=2, rate_category="default",
        headers={
            'Content-Type': mime_type,
            'Content-Length': str(data_size),
        },
        data=upload_body,
        timeout=(15, 120),  # 连接超时15s，传输超时120s
    )

    if response.status_code != 200:
        raise Exception(f"文件上传失败: HTTP {response.status_code}")

    print(f"✅ {file_label}文件上传成功！")
    print(f"🆔 文件ID: {file_id}")

    # 轮询文件状态，等待服务器同步完成（文档说明最长延迟1分钟）
    poll_interval = 3  # 每次轮询间隔秒数
    max_poll_wait = 90  # 最长等待时间（秒），留一定余量
    poll_start = time.time()
    print(f"⏳ 等待文件同步...")
    while True:
        elapsed = time.time() - poll_start
        if elapsed > max_poll_wait:
            raise TimeoutError(f"文件同步超时（已等待 {int(elapsed)}s），file_id: {file_id}")
        time.sleep(poll_interval)
        try:
            detail = api_json_request(
                "GET",
                f"{BASE_URL}/open/v1/common/file_detail",
                rate_category="default",
                silent_rate=True,
                params={"id": file_id},
                headers={"access_token": access_token},
            )
            status = detail.get("data", {}).get("status", 0)
            if status == 1:
                print(f"✅ 文件同步完成（耗时 {int(time.time() - poll_start)}s）")
                break
            elif status in (98, 99, 100):
                status_msg = {98: "内容安全检测失败", 99: "文件已删除", 100: "文件已清理"}
                raise Exception(f"文件不可用 (status={status}): {status_msg.get(status, '未知')}")
            else:
                # status == 0，文件未同步，继续等待
                if progress:
                    progress.update(min(90, int(elapsed / max_poll_wait * 80 + 10)),
                                    f"文件同步中（{int(elapsed)}s）")
        except TimeoutError:
            raise
        except Exception as e:
            if "文件不可用" in str(e):
                raise
            # 网络异常等，继续重试
            print(f"⚠️  查询文件状态失败: {e}，继续等待...")

    print(f"{'='*60}\n")
    return {"file_id": file_id, "url": file_url}


# ==================== 对口型节点 ====================

class CicadaLipSyncNode:
    """蝉镜 AI 对口型节点 - 音频驱动视频对口型"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_input": ("*", {
                    "tooltip": "视频文件或路径（支持从上游节点传入视频对象或手动输入路径）"
                }),
                "audio_input": ("AUDIO", {
                    "tooltip": "音频（支持从上游节点传入ComfyUI音频对象）"
                }),
                "model": (["cicada-lip-sync", "cicada-lip-sync-pro"], {
                    "default": "cicada-lip-sync-pro",
                    "tooltip": "cicada-lip-sync-pro 数字人唇齿更清晰，自然度与真实度显著提升"
                }),
                "backway": (["forward", "reverse"], {
                    "default": "forward",
                    "tooltip": "视频长度短于音频时的播放策略：正放-循环正向播放，倒放-播放到末尾后倒放回来"
                }),
                "drive_mode": (["normal", "random"], {
                    "default": "normal",
                    "tooltip": "正常驱动-从第一帧开始，随机帧驱动-从随机帧开始"
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_url",)
    FUNCTION = "create_lip_sync"
    CATEGORY = "Cicada AI"
    OUTPUT_NODE = False

    @staticmethod
    def _get_video_dimensions(video_path):
        if not CV2_AVAILABLE:
            return None, None
        cap = None
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None, None
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            return (w, h) if w > 0 and h > 0 else (None, None)
        except Exception:
            return None, None
        finally:
            if cap is not None:
                cap.release()

    def create_lip_sync(self, video_input, audio_input, model, backway="forward", drive_mode="normal"):
        # 初始化进度条
        progress = CicadaProgress([
            ("准备", 5),
            ("上传视频", 15),
            ("上传音频", 10),
            ("视频合成", 65),
            ("完成", 5),
        ])

        print("\n" + "="*60)
        print("🎭 蝉镜 AI 对口型任务")
        print("="*60 + "\n")
        progress.start()

        # ---- 准备阶段 ----
        progress.advance("准备")

        # 解析输入
        video_path = extract_file_path(video_input, "视频")
        audio_path = extract_file_path(audio_input, "音频")
        print(f"📂 视频路径: {video_path}")
        print(f"📂 音频路径: {audio_path}")

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        w, h = self._get_video_dimensions(video_path)
        if not w or not h:
            w, h = 1080, 1920
            print(f"⚠️  使用默认尺寸: {w} x {h}")
        else:
            print(f"✅ 视频尺寸: {w} x {h} (自动检测)")

        # 解析参数
        backway_value = 2 if backway == "reverse" else 1
        drive_mode_value = "random" if drive_mode == "random" else ""
        print(f"✅ 播放策略: {backway}（{backway_value}）")
        print(f"✅ 驱动模式: {drive_mode}（'{drive_mode_value}'）")

        access_token = get_access_token()

        # ---- 上传视频 ----
        progress.advance("上传视频")
        video_result = upload_file(video_path, "lip_sync_video", access_token, progress=progress)
        progress.update(100, "视频上传完成")

        # ---- 上传音频 ----
        progress.advance("上传音频")
        audio_result = upload_file(audio_path, "lip_sync_audio", access_token, progress=progress)
        progress.update(100, "音频上传完成")

        # ---- 视频合成 ----
        progress.advance("视频合成")
        model_value = 1 if model == "cicada-lip-sync pro" else 0

        result = api_json_request(
            "POST",
            f"{BASE_URL}/open/v1/video_lip_sync/create",
            rate_category="lip_sync",
            silent_rate=True,
            json={
                "video_file_id": video_result["file_id"],
                "audio_type": "audio",
                "audio_file_id": audio_result["file_id"],
                "model": model_value,
                "screen_width": w,
                "screen_height": h,
                "backway": backway_value,
                "drive_mode": drive_mode_value,
            },
            headers={"access_token": access_token, "Content-Type": "application/json"},
        )
        task_id = result.get("data")

        print(f"✅ 任务创建成功，任务ID: {task_id}")

        video_url = self._poll_lip_sync(task_id, access_token, progress)

        # ---- 完成 ----
        progress.finish("🎉 对口型任务完成！")
        print(f"\n{'='*60}")
        print("🎉 对口型任务完成！")
        print(f"📹 视频: {video_url}")
        print("="*60 + "\n")
        return (video_url,)

    @staticmethod
    def _poll_lip_sync(task_id, access_token, progress=None, max_wait=1800):
        """轮询对口型任务状态"""
        start = time.time()
        last_progress = -1
        last_status = -1

        print(f"\n⏳ 等待视频合成...")
        while True:
            if time.time() - start > max_wait:
                raise TimeoutError(f"任务超时（{max_wait}秒）")

            result = api_json_request(
                "GET",
                f"{BASE_URL}/open/v1/video_lip_sync/detail",
                rate_category="default",
                silent_rate=True,
                params={"id": task_id},
                headers={"access_token": access_token},
            )
            data = result.get("data", {})
            status = data.get("status")
            api_progress = data.get("progress", 0)
            msg = data.get("msg", "")

            # 状态: 0-排队中, 10-生成中, 20-生成成功, 30-生成失败
            if status != last_status or api_progress != last_progress:
                status_text = {0: "排队中", 10: "生成中", 20: "成功", 30: "失败"}.get(status, f"未知({status})")
                if progress:
                    # 排队阶段用前15%，生成阶段用API的progress
                    if status == 0:
                        progress.update(min(15, api_progress), f"排队中")
                    else:
                        progress.update(api_progress, f"视频合成 {api_progress}%")
                if status == 0:
                    print(f"🎬 排队中: {api_progress}%")
                else:
                    print(f"🎬 视频合成: {api_progress}% - {status_text}")
                last_status = status
                last_progress = api_progress

            if status == 20:
                video_url = data.get("video_url", "")
                if not video_url:
                    raise Exception("视频合成完成但未返回视频URL")
                if progress:
                    progress.update(100, "视频合成完成")
                duration_ms = data.get("duration", 0)
                dur_str = f"，时长: {duration_ms / 1000:.1f}秒" if duration_ms else ""
                print(f"✅ 视频合成完成！{dur_str}")
                return video_url
            elif status == 30:
                # 检测蝉豆扣费失败（后置校验，详情接口 msg 中返回）
                check_billing_error(msg)
                raise Exception(f"视频合成失败: {msg}")

            # status 0(排队) 或 10(生成中)，继续轮询
            time.sleep(5)


# ==================== 声音克隆节点 ====================

class CicadaVoiceCloneNode:
    """蝉镜 AI 声音克隆节点 - 克隆声音并合成语音"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_audio_input": ("*", {
                    "tooltip": "参考音频文件或路径（要求：15秒-5分钟，支持 mp3/wav/m4a）"
                }),
                "text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "输入要合成的文案（最多4000字）"
                }),
                "model_type": (["cicada3.0-turbo", "cicada3.0", "cicada1.0"], {
                    "default": "cicada3.0-turbo",
                    "tooltip": "cicada1.0: 稳定高还原度 | cicada3.0: 情感表现力强 | cicada3.0-turbo: 增强稳定性"
                }),
                "speed": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.5,
                    "max": 2.0,
                    "step": 0.1,
                    "tooltip": "语速（0.5-2.0倍速）"
                }),
                "pitch": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.1,
                    "max": 3.0,
                    "step": 0.1,
                    "tooltip": "音调（0.1-3.0）"
                }),
                "use_cache": (["enabled", "disabled"], {
                    "default": "enabled",
                    "tooltip": "开启后，相同音频+模型会复用已克隆的声音，跳过重复克隆节省时间"
                }),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "clone_and_synthesize"
    CATEGORY = "Cicada AI"
    OUTPUT_NODE = False

    def clone_and_synthesize(self, reference_audio_input, text,
                            model_type, speed, pitch, use_cache="enabled"):
        if not text or not text.strip():
            raise ValueError("请输入要合成的文案")

        if len(text) > 4000:
            raise ValueError(f"文案长度超过限制：{len(text)}/4000字")

        # 初始化进度条
        progress = CicadaProgress([
            ("准备", 5),
            ("上传音频", 10),
            ("声音克隆", 45),
            ("语音合成", 30),
            ("下载音频", 10),
        ])

        print("\n" + "="*60)
        print("🎤 蝉镜 AI 声音克隆与合成任务")
        print("="*60 + "\n")
        progress.start()

        # ---- 准备阶段 ----
        progress.advance("准备")

        # 解析输入
        audio_path = extract_file_path(reference_audio_input, "参考音频")
        print(f"📂 参考音频路径: {audio_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"参考音频文件不存在: {audio_path}")

        # 检查音频时长（服务器限制：15秒-5分钟）
        audio_duration = get_audio_duration(audio_path)
        if audio_duration is not None:
            print(f"⏱️  音频时长: {format_duration(audio_duration)}")
            
            if audio_duration < 15:
                raise ValueError(
                    f"❌ 参考音频时长过短: {format_duration(audio_duration)}\n"
                    f"要求：至少 15 秒，当前仅 {audio_duration:.1f} 秒\n"
                    f"请使用更长的参考音频以获得更好的克隆效果"
                )
            
            if audio_duration > 300:  # 5分钟 = 300秒
                print(f"⚠️  音频时长超过限制: {format_duration(audio_duration)} > 5:00")
                progress.update(50, "裁剪音频...")
                
                trimmed_path = trim_audio(audio_path, max_duration=299)
                if trimmed_path:
                    audio_path = trimmed_path
                    print(f"✅ 已自动裁剪音频，使用前 4:59")
                else:
                    raise ValueError(
                        f"❌ 参考音频时长超过限制: {format_duration(audio_duration)} (要求: 最长 5:00)\n"
                        f"自动裁剪失败，请安装系统 ffmpeg:\n"
                        f"  macOS: brew install ffmpeg\n"
                        f"  Ubuntu: sudo apt install ffmpeg"
                    )
        else:
            print("⚠️  无法获取音频时长，跳过时长检查")

        # 计算音频文件哈希（用于缓存判断，在裁剪之后计算）
        enable_cache = (use_cache == "enabled")
        audio_hash = file_content_hash(audio_path)
        print(f"✅ 参考音频: {os.path.basename(audio_path)}")
        print(f"🔑 音频指纹: {audio_hash[:12]}...")
        print(f"✅ 文案: {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"✅ 模型: {model_type}")
        print(f"✅ 克隆缓存: {'开启' if enable_cache else '关闭'}")

        # Token
        access_token = get_access_token()

        # ---- 缓存检查：同音频+同模型 → 跳过上传和克隆 ----
        cached_voice_id = VoiceCloneCache.get(audio_hash, model_type) if enable_cache else None
        if cached_voice_id:
            print(f"✅ 命中声音克隆缓存！声音ID: {cached_voice_id}")
            print(f"⏩ 跳过上传和克隆，直接进入语音合成")

            # 验证缓存的 voice_id 是否仍然有效（未过期/删除）
            try:
                result = api_json_request(
                    "GET",
                    f"{BASE_URL}/open/v1/customised_audio",
                    rate_category="voice_clone",
                    params={"id": cached_voice_id},
                    headers={"access_token": access_token},
                )
                status = result["data"]["status"]
                # 状态: 2-完成可用, 3-过期, 4-失败, 99-已删除
                if status == 2:
                    voice_id = cached_voice_id
                    progress.advance("上传音频")
                    progress.update(100, "已跳过（缓存命中）")
                    progress.advance("声音克隆")
                    progress.update(100, "已跳过（缓存命中）")
                    print(f"✅ 缓存声音状态正常，可直接使用")
                else:
                    status_map = {3: "已过期", 4: "已失败", 99: "已删除"}
                    reason = status_map.get(status, f"状态异常({status})")
                    print(f"⚠️  缓存的声音{reason}，将重新克隆")
                    VoiceCloneCache.remove(audio_hash, model_type)
                    cached_voice_id = None
            except Exception as e:
                print(f"⚠️  缓存验证失败: {e}，将重新克隆")
                VoiceCloneCache.remove(audio_hash, model_type)
                cached_voice_id = None

        if not cached_voice_id:
            # ---- 上传阶段 ----
            progress.advance("上传音频")
            upload_result = upload_file(audio_path, "prompt_audio", access_token, progress=progress)
            audio_public_url = upload_result["url"]

            if not audio_public_url:
                raise Exception(
                    "上传接口未返回公网URL。请检查 service 参数是否正确，"
                    "或尝试将音频文件上传到可公开访问的地址后手动输入URL。"
                )
            progress.update(100, "上传完成")

            # ---- 声音克隆阶段 ----
            progress.advance("声音克隆")
            result = api_json_request(
                "POST",
                f"{BASE_URL}/open/v1/create_customised_audio",
                rate_category="voice_clone",
                json={
                    "name": f"clone_{int(time.time())}",
                    "url": audio_public_url,
                    "model_type": model_type,
                },
                headers={"access_token": access_token, "Content-Type": "application/json"},
            )
            voice_id = result["data"]
            print(f"✅ 声音克隆任务创建成功，声音ID: {voice_id}")

            self._poll_voice_clone(voice_id, access_token, progress)

            # 克隆成功，写入缓存
            if enable_cache:
                VoiceCloneCache.put(audio_hash, model_type, voice_id)
                print(f"💾 声音克隆结果已缓存（下次相同音频+模型将跳过克隆）")

        # ---- 语音合成阶段 ----
        progress.advance("语音合成")
        result = api_json_request(
            "POST",
            f"{BASE_URL}/open/v1/create_audio_task",
            rate_category="tts",
            json={
                "audio_man": voice_id,
                "speed": speed,
                "pitch": pitch,
                "text": {"text": text, "plain_text": text},
            },
            headers={"access_token": access_token, "Content-Type": "application/json"},
        )
        task_id = result["data"]["task_id"]
        print(f"✅ 语音合成任务创建成功，任务ID: {task_id}")

        audio_url = self._poll_audio_synthesis(task_id, access_token, progress)

        # ---- 下载阶段 ----
        progress.advance("下载音频")
        audio_local_path = self._download_audio(audio_url)

        # 加载为 ComfyUI AUDIO 格式（waveform + sample_rate）
        waveform, sample_rate = self._load_audio(audio_local_path)
        # ComfyUI AUDIO 格式: waveform shape = (batch, channels, samples)
        audio_output = {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}

        progress.finish("🎉 任务全部完成！")
        print(f"\n{'='*60}")
        print("🎉 任务全部完成！")
        print(f"🎵 音频地址: {audio_url}")
        print(f"📁 本地文件: {audio_local_path}")
        print("="*60 + "\n")
        return (audio_output,)

    @staticmethod
    def _download_audio(audio_url):
        """下载合成的音频文件到本地，返回本地文件路径（每次重新下载，不使用缓存）"""
        output_dir = folder_paths.get_output_directory()
        audio_output_dir = os.path.join(output_dir, "cicada_audio")
        os.makedirs(audio_output_dir, exist_ok=True)

        # 用时间戳生成唯一文件名，每次都重新下载
        timestamp = int(time.time() * 1000)
        # 从 URL 推断扩展名，默认 .mp3
        ext = ".mp3"
        url_path = audio_url.split("?")[0]
        for candidate in [".mp3", ".wav", ".m4a", ".ogg", ".flac"]:
            if url_path.lower().endswith(candidate):
                ext = candidate
                break
        filename = f"cicada_clone_{timestamp}{ext}"
        local_path = os.path.join(audio_output_dir, filename)

        print(f"⬇️  下载音频: {audio_url}")
        response = api_request("GET", audio_url, rate_category="default", stream=True, timeout=300)

        total = int(response.headers.get('content-length', 0))
        downloaded = 0
        last_pct = -20

        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int((downloaded / total) * 100)
                        if pct >= last_pct + 20 or pct >= 100:
                            print(f"📥 下载: {pct}%")
                            last_pct = pct

        size = os.path.getsize(local_path)
        print(f"✅ 音频下载完成: {filename} ({format_file_size(size)})")
        return local_path

    @staticmethod
    def _load_audio(file_path):
        """
        加载音频文件为 (waveform, sample_rate)，兼容多种环境。
        优先 scipy（最常见）→ soundfile → torchaudio（需后端）。
        返回: (waveform: Tensor[channels, samples], sample_rate: int)
        """
        import torch
        import numpy as np

        # 方法1: scipy（ComfyUI 环境通常自带，仅支持 wav）
        try:
            from scipy.io import wavfile
            sr, data = wavfile.read(file_path)
            # data shape: (samples,) 单声道 or (samples, channels) 多声道
            if data.dtype == np.int16:
                data = data.astype(np.float32) / 32768.0
            elif data.dtype == np.int32:
                data = data.astype(np.float32) / 2147483648.0
            elif data.dtype != np.float32:
                data = data.astype(np.float32)
            if data.ndim == 1:
                data = data[np.newaxis, :]    # (1, samples)
            else:
                data = data.T                  # (channels, samples)
            print(f"✅ 音频加载成功（scipy）: {sr}Hz, shape={data.shape}")
            return torch.from_numpy(data), sr
        except Exception as e:
            print(f"⚠️  scipy 加载失败: {e}，尝试其他方式...")

        # 方法2: soundfile（支持 wav/flac/ogg 等）
        try:
            import soundfile as sf
            data, sr = sf.read(file_path, dtype='float32')
            if data.ndim == 1:
                data = data[np.newaxis, :]
            else:
                data = data.T
            print(f"✅ 音频加载成功（soundfile）: {sr}Hz, shape={data.shape}")
            return torch.from_numpy(data), sr
        except Exception as e:
            print(f"⚠️  soundfile 加载失败: {e}，尝试其他方式...")

        # 方法3: torchaudio（需要 sox/soundfile/ffmpeg 后端）
        try:
            import torchaudio
            waveform, sr = torchaudio.load(file_path)
            print(f"✅ 音频加载成功（torchaudio）: {sr}Hz, shape={tuple(waveform.shape)}")
            return waveform, sr
        except Exception as e:
            print(f"⚠️  torchaudio 加载失败: {e}")

        raise Exception(
            f"❌ 无法加载音频文件: {file_path}\n\n"
            f"尝试了 scipy / soundfile / torchaudio 均失败。\n"
            f"建议安装: pip install soundfile\n"
            f"或安装系统 ffmpeg: brew install ffmpeg"
        )

    @staticmethod
    def _poll_voice_clone(voice_id, access_token, progress=None, max_wait=600):
        """
        轮询声音克隆状态
        文档: https://doc.chanjing.cc/api/customised-voice/get-voice-result.html
        状态: 0-等待制作 1-制作中 2-已完成 3-已过期 4-制作失败 99-已删除
        """
        start = time.time()
        last_status = -1
        last_progress = -1
        consecutive_errors = 0
        max_consecutive_errors = 5
        print("⏳ 等待声音克隆完成...")

        while True:
            elapsed = time.time() - start
            if elapsed > max_wait:
                raise TimeoutError(
                    f"声音克隆超时（已等待 {int(elapsed)} 秒）\n"
                    f"声音ID: {voice_id}\n"
                    f"可能是服务端处理异常，请稍后重试"
                )

            try:
                result = api_json_request(
                    "GET",
                    f"{BASE_URL}/open/v1/customised_audio",
                    rate_category="voice_clone",
                    silent_rate=True,
                    params={"id": voice_id},
                    headers={"access_token": access_token},
                )
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                error_msg = str(e)
                print(f"⚠️  声音克隆轮询出错 ({consecutive_errors}/{max_consecutive_errors}): {error_msg}")
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception(
                        f"声音克隆轮询连续失败 {max_consecutive_errors} 次，放弃等待\n"
                        f"声音ID: {voice_id}\n"
                        f"最后一次错误: {error_msg}"
                    )
                time.sleep(5)
                continue

            data = result["data"]
            status = data["status"]
            api_progress = data.get("progress", 0)

            if status == 2:
                # 已完成
                if progress:
                    progress.update(100, "声音克隆完成")
                print(f"✅ 声音克隆完成！")
                return
            elif status == 4:
                # 制作失败
                err_msg = data.get('err_msg', '未知错误')
                check_billing_error(err_msg)
                raise Exception(f"声音克隆失败: {err_msg}")
            elif status == 3:
                raise Exception("声音克隆任务已过期")
            elif status == 99:
                raise Exception("声音克隆任务已被删除")
            else:
                # status 0(等待) 或 1(制作中)
                status_text = "等待制作" if status == 0 else "制作中"
                # 只在状态或进度变化时输出，避免刷屏
                if status != last_status or api_progress != last_progress:
                    if progress:
                        progress.update(api_progress, f"声音克隆 {api_progress}% - {status_text}")
                    print(f"⏳ 声音克隆: {api_progress}% - {status_text}")
                    last_status = status
                    last_progress = api_progress
                time.sleep(5)

    @staticmethod
    def _poll_audio_synthesis(task_id, access_token, progress=None, max_wait=600):
        """
        轮询语音合成状态
        文档: https://doc.chanjing.cc/api/speech-synthesis/get-speech-result.html
        状态: 1-生成中, 9-生成完毕(包含成功与失败，通过 errMsg 区分)
        - 对轮询中的临时性 API 错误做容错处理（连续失败 5 次才放弃）
        """
        start = time.time()
        poll_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 5
        print("⏳ 等待语音合成完成...")

        while True:
            elapsed = time.time() - start
            if elapsed > max_wait:
                raise TimeoutError(
                    f"语音合成超时（已等待 {int(elapsed)} 秒）\n"
                    f"任务ID: {task_id}\n"
                    f"可能是服务端处理异常，请稍后重试"
                )

            try:
                result = api_json_request(
                    "POST",
                    f"{BASE_URL}/open/v1/audio_task_state",
                    rate_category="tts",
                    silent_rate=True,
                    json={"task_id": task_id},
                    headers={"access_token": access_token, "Content-Type": "application/json"},
                )
                # 请求成功，重置连续错误计数
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                error_msg = str(e)
                print(f"⚠️  轮询请求出错 ({consecutive_errors}/{max_consecutive_errors}): {error_msg}")
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception(
                        f"语音合成轮询连续失败 {max_consecutive_errors} 次，放弃等待\n"
                        f"任务ID: {task_id}\n"
                        f"最后一次错误: {error_msg}"
                    )
                # 出错时等待稍长一些再重试
                time.sleep(5)
                continue

            data = result["data"]
            status = data["status"]

            # 根据官方文档：status 只有两个值
            # 1 = 生成中
            # 9 = 生成完毕（包含成功与失败，通过 errMsg 区分）
            if status == 9:
                # 生成完毕，检查是否有错误
                err_msg = data.get("errMsg", "")
                err_reason = data.get("errReason", "")

                if err_msg:
                    check_billing_error(err_msg)
                    detail = f"{err_msg}"
                    if err_reason:
                        detail += f"（原因: {err_reason}）"
                    raise Exception(
                        f"语音合成失败: {detail}\n"
                        f"任务ID: {task_id}"
                    )

                full = data.get("full", {})
                audio_url = full.get("url", "")
                duration = full.get("duration", 0)

                if not audio_url:
                    raise Exception(
                        f"语音合成完成但未返回音频URL\n"
                        f"任务ID: {task_id}"
                    )

                if progress:
                    progress.update(100, "语音合成完成")
                print(f"✅ 语音合成完成！音频时长: {duration:.1f}秒")
                return audio_url
            elif status == 1:
                # 生成中
                poll_count += 1
                # 语音合成 API 不返回进度百分比，用轮询次数模拟
                # 前期快速增长，后期缓慢增长，最高到 95%
                if poll_count <= 6:
                    estimated_pct = min(90, poll_count * 15)
                else:
                    estimated_pct = min(95, 90 + (poll_count - 6))
                if progress:
                    progress.update(estimated_pct, "语音合成中...")
                # 只在首次打印，后续靠进度条展示
                if poll_count == 1:
                    print("⏳ 语音合成中...")
                # 动态调整轮询间隔：前期 3s，后期延长到 5s 避免频繁请求
                sleep_time = 3 if poll_count <= 10 else 5
                time.sleep(sleep_time)
            else:
                # 未知状态，记录日志但继续轮询（兼容未来可能新增的状态码）
                poll_count += 1
                print(f"⚠️  语音合成返回未知状态: {status}，继续等待...")
                time.sleep(5)


# ==================== 视频播放器节点 ====================

class CicadaVideoPlayerNode:
    """蝉镜视频播放器节点 - 下载并播放视频URL"""

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.cache_dir = os.path.join(self.output_dir, "cicada_videos")
        os.makedirs(self.cache_dir, exist_ok=True)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "视频URL地址（可直接从蝉镜AI对口型节点输出连接）"
                }),
            }
        }

    RETURN_TYPES = ()
    FUNCTION = "load_video"
    CATEGORY = "Cicada AI"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, video_url):
        return float("nan")

    def load_video(self, video_url):
        try:
            if not video_url or video_url.startswith("❌"):
                return {"ui": {"text": ["❌ 请提供有效的视频URL"]}}

            # 每次重新下载，不使用缓存，用时间戳生成唯一文件名
            timestamp = int(time.time() * 1000)
            filename = f"cicada_{timestamp}.mp4"
            output_path = os.path.join(self.cache_dir, filename)

            print(f"⬇️  下载视频: {video_url}")
            response = api_request("GET", video_url, rate_category="default", stream=True, timeout=300)

            total = int(response.headers.get('content-length', 0))
            downloaded = 0
            last_pct = -20

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int((downloaded / total) * 100)
                            if pct >= last_pct + 20 or pct >= 100:
                                print(f"📥 下载: {pct}%")
                                last_pct = pct

            print(f"✅ 视频下载完成: {output_path}")

            return {
                "ui": {
                    "gifs": [{
                        "filename": filename,
                        "subfolder": "cicada_videos",
                        "type": "output",
                        "format": "video/mp4"
                    }]
                }
            }
        except Exception as e:
            error_msg = f"❌ 错误: {str(e)}"
            print(f"\n{error_msg}\n")
            # 清理不完整的下载
            if 'output_path' in locals() and os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            return {"ui": {"text": [error_msg]}}


# ==================== 节点注册 ====================

NODE_CLASS_MAPPINGS = {
    "CicadaLipSyncNode": CicadaLipSyncNode,
    "CicadaVoiceCloneNode": CicadaVoiceCloneNode,
    "CicadaVideoPlayerNode": CicadaVideoPlayerNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CicadaLipSyncNode": "Cicada Lip Sync",
    "CicadaVoiceCloneNode": "Cicada Voice Clone",
    "CicadaVideoPlayerNode": "Cicada Video Player",
}
