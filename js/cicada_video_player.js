import { app } from "/scripts/app.js";

app.registerExtension({
    name: "Comfy.CicadaVideoPlayer",

    async beforeRegisterNodeDef(nodeType, nodeData, _app) {
        if (nodeData.name !== "CicadaVideoPlayerNode") return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            const gifs = message?.gifs;
            if (!gifs || gifs.length === 0) return;

            const info = gifs[0];
            const params = new URLSearchParams({
                filename: info.filename,
                subfolder: info.subfolder || "",
                type: info.type || "output",
            });
            const src = `/view?${params.toString()}`;

            // 复用或创建 video 元素
            if (!this._cicadaVideo) {
                const video = document.createElement("video");
                video.controls = true;
                video.loop = false;
                video.autoplay = true;
                video.muted = false;
                video.style.width = "100%";
                video.style.borderRadius = "4px";
                video.style.marginTop = "4px";

                // 播放结束后自动暂停
                video.addEventListener("ended", () => {
                    video.pause();
                });

                // 添加为 ComfyUI 节点 widget
                const widget = this.addDOMWidget("video_preview", "custom", video, {
                    serialize: false,
                });
                widget.computeSize = () => [this.size[0], 240];

                this._cicadaVideo = video;
                this._cicadaWidget = widget;
            }

            this._cicadaVideo.src = src;
            this._cicadaVideo.load();
            // 显式触发播放，处理浏览器自动播放限制
            const playPromise = this._cicadaVideo.play();
            if (playPromise !== undefined) {
                playPromise.catch(() => {
                    // 若浏览器阻止有声自动播放，则静音后重试
                    this._cicadaVideo.muted = true;
                    this._cicadaVideo.play();
                });
            }

            // 调整节点大小
            this.setSize([
                Math.max(this.size[0], 320),
                Math.max(this.size[1], 340),
            ]);
            this.setDirtyCanvas(true, true);
        };
    },
});
