# ComfyUI 蝉镜 AI 插件

基于蝉镜 AI 开放平台的 ComfyUI 插件。

## 功能节点

| 节点 | 功能 | 输入 | 输出 |
|------|------|------|------|
| **蝉镜AI对口型** | 音频驱动视频对口型 | 视频 + 音频 | 视频URL |
| **蝉镜AI声音克隆** | 克隆声音并合成语音 | 参考音频 + 文案 | 音频（AUDIO） |
| **蝉镜视频播放器** | 下载并播放视频URL | 视频URL | ComfyUI预览 |

## 安装

### 方式一：Git Clone（推荐，支持自动更新）

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/chanjing-ai/chanjingAI-ComfyUI.git
```

### 配置

1. 访问 https://www.chanjing.cc/platform/api_keys 获取 **App ID** 和 **Secret Key**
2. 复制 `config.example.json` 为 `config.json`，填入 `app_id` 和 `secret_key`

重启 ComfyUI，在节点菜单 `蝉镜AI/Cicada AI` 分类下找到所有节点。

工作流模版在 workflow 目录下

## 自动更新

插件支持启动时自动检查 GitHub 更新：
- 每次启动 ComfyUI 时，插件会在后台检查是否有新版本
- 如果检测到更新，会自动拉取最新代码
- 更新完成后，需要**重启 ComfyUI** 使新版本生效
- 自动更新不会影响你的 `config.json` 配置文件

### 对口型工作流

```
LoadVideo → video_input ┐
                        ├→ 蝉镜AI对口型 → video_url → 蝉镜视频播放器
LoadAudio → audio_input ┘
```

### 声音克隆工作流

```
LoadAudio → reference_audio ┐
                            ├→ 蝉镜AI声音克隆 → audio (AUDIO)
文案输入 → text ─────────────┘
```

## 配置

| 项目 | 说明 |
|------|------|
| 凭证获取 | https://www.chanjing.cc/platform/api_keys |
| 凭证配置 | `ChanjingAI/config.json`（手动编辑） |
| Token 缓存 | `ChanjingAI/.cache/token.json`（自动管理，24h有效） |

## 常见问题

**Q: 找不到节点？**
确认插件在 `ComfyUI/custom_nodes/` 目录下，重启 ComfyUI。

**Q: 生成的URL有效期？**
有时效性，建议及时下载保存。

## 支持

- [蝉镜 AI 官网](https://www.chanjing.cc/)
- [API 文档](https://doc.chanjing.cc/)
