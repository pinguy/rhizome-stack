# Browser showcase

The standalone-app captures began with the accepted reference-machine browser
paths on 16 October 2026. The saved-chat captures were refreshed on 12 November
2026. They demonstrate UI integration; they do not bundle the pictured media,
chats, user database, browser profile or model weights. The Open WebUI captures
use real saved canary chats with the identity sidebar hidden and no local
absolute filesystem paths shown.

## Standalone creative apps

### MiniMax Music 3

![MiniMax Music 3 with dynamic writer models and track controls](screenshots/minimax-music-3.png)

### Qwen Image Desk

![Qwen Image Desk with a generated cobalt-blue mug](screenshots/qwen-image-desk.png)

### WAN Video Desk

![WAN Video Desk with a retained toy-boat take](screenshots/wan-video-desk.png)

## Open WebUI saved-chat embeds

These captures use Qwen3.8-Flash-Next Gyro-S served by
[Strata](https://github.com/Niko1221/Strata) as the local OpenClaw model.
Alpha.19 can install the pinned Strata source and configuration, while the model
weights remain separate downloads and are not bundled by Rhizome Stack.

### Qwen text-to-image

![Qwen Image Desk returning a generated black cat on a blue chair inside Open WebUI](screenshots/openwebui-qwen-image-generation.png)

![The saved chat showing the complete Qwen image result and tool receipt](screenshots/openwebui-qwen-image-proof.png)

### Qwen reference-conditioned edit

![Qwen Image Desk editing the saved blue-chair image into a yellow armchair result](screenshots/openwebui-qwen-reference-edit.png)

![The saved chat showing that the edit used the earlier Open WebUI file as its reference](screenshots/openwebui-qwen-reference-edit-proof.png)

### Open WebUI native MiniMax MP3 Preview

![MiniMax Music 3 output opened in Open WebUI's native Preview player](screenshots/openwebui-minimax-music-preview.png)

### One saved-chat media sequence

![A single saved chat retaining a MiniMax MP3 card and the following MiniMax H3 video result](screenshots/openwebui-music-video-sequence.png)

### Inline MiniMax H3 MP4

![MiniMax H3 MP4 rendered in Open WebUI's patched inline HTML5 player](screenshots/openwebui-minimax-h3-video.png)

The generated and edited PNGs use Open WebUI's normal image branch. The MP3 uses
its native File card and Preview tab. The MP4 uses the version-pinned,
hash-guarded frontend replacement documented in
[Open WebUI local media](OPENWEBUI_MEDIA.md). The screenshots prove these
specific reference-machine browser paths; they are not clean-machine acceptance
for Strata or the creative profile.
