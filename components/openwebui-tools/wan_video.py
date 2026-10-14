"""Open WebUI native video generation through the packaged WAN Video Desk."""
import os
import sys
from pathlib import Path

COMPONENTS = Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser() / "components"
if str(COMPONENTS) not in sys.path:
    sys.path.insert(0, str(COMPONENTS))
from openwebui_local_media import generate


T2V_MODEL = "wan2.2-t2v-rapid-aio-v10-nsfw-Q5_K.gguf"
I2V_MODEL = "wan2.2-i2v-rapid-aio-v10-nsfw-Q5_K.gguf"


class Tools:
    citation = False

    async def create_video(self, prompt: str, negative_prompt: str = "", aspect: str = "4:3",
                           quality: str = "480p", duration_seconds: int = 5, fps: int = 16,
                           steps: int = 4, input_mode: str = "t2v", video_model: str = T2V_MODEL,
                           reference_file_id: str = "", seed: int = -1,
                           __user__=None, __metadata__=None, __event_emitter__=None) -> str:
        """Create an MP4 with local WAN Video Desk and attach it to this saved chat.

        Use for requests to make a video, moving shot or animation, not video discussion.
        Call once and wait. The take stays in WAN Video Desk for editing, reuse and reruns.
        Defaults are WAN 2.2 Rapid T2V v10 Q5_K, 640x480, 16 fps, four steps and five seconds.

        Text input uses input_mode=t2v. To animate an uploaded image, use input_mode=i2v,
        supply its Open WebUI file UUID and explicitly select the I2V model. Input and model
        are independent controls; never silently rewrite one from the other.

        :param prompt: Detailed description of one moving shot.
        :param negative_prompt: Optional unwanted motion or visual traits.
        :param aspect: 16:9, 4:3 or mobile (9:16). Default 4:3.
        :param quality: 480p or 720p. Default 480p.
        :param duration_seconds: Whole seconds from 1 to 10. Default 5.
        :param fps: 16 or 24 frames per second. Default 16.
        :param steps: WAN sampling steps from 4 to 20. Default 4.
        :param input_mode: t2v for text input or i2v for image input.
        :param video_model: Exact installed WAN T2V or I2V GGUF filename.
        :param reference_file_id: Uploaded Open WebUI image UUID for i2v; never a path or URL.
        :param seed: Optional seed from 0 to 9223372036854775807; -1 chooses a random seed.
        """
        prompt = prompt.strip()
        negative_prompt = negative_prompt.strip()
        aspect = aspect.lower().strip()
        quality = quality.lower().strip()
        input_mode = input_mode.lower().strip()
        video_model = video_model.strip()
        if not prompt or len(prompt) > 12000:
            return "Provide a video prompt between 1 and 12000 characters."
        if len(negative_prompt) > 8000:
            return "Keep the negative prompt at 8000 characters or fewer."
        if aspect not in ("16:9", "4:3", "mobile"):
            return "Choose 16:9, 4:3 or mobile (9:16)."
        if quality not in ("480p", "720p"):
            return "Choose 480p or 720p."
        if not 1 <= int(duration_seconds) <= 10:
            return "Choose a duration from 1 to 10 whole seconds."
        if int(fps) not in (16, 24):
            return "Choose 16 or 24 fps."
        if not 4 <= int(steps) <= 20:
            return "Choose 4 to 20 sampling steps."
        if input_mode not in ("t2v", "i2v"):
            return "Choose t2v (Text input) or i2v (Image input)."
        if video_model not in (T2V_MODEL, I2V_MODEL):
            return "Choose one of WAN Video Desk's two installed GGUF models."
        if input_mode == "i2v" and video_model == T2V_MODEL:
            return "The T2V GGUF cannot use Image input. Select the installed WAN I2V GGUF."
        if input_mode == "i2v" and not reference_file_id:
            return "Image input needs an uploaded Open WebUI image file ID."
        if seed < -1 or seed >= 2**63:
            return "Seed must be -1 (random) or between 0 and 9223372036854775807."
        payload = {
            "final_prompt": prompt, "original_prompt": prompt, "negative": negative_prompt,
            "prompt_mode": "direct", "quality": quality, "aspect": aspect,
            "duration_seconds": int(duration_seconds), "fps": int(fps), "steps": int(steps),
            "batch_count": 1, "mode": input_mode, "video_model": video_model,
        }
        if seed >= 0:
            payload["seed"] = int(seed)
        return await generate("video", payload, __user__, __metadata__, __event_emitter__,
                              reference_file_id if input_mode == "i2v" else "")
