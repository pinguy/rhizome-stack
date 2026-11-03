"""Open WebUI native video generation through the packaged WAN Video Desk."""
import os
import sys
from pathlib import Path
from typing import Literal

COMPONENTS = Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser() / "components"
if str(COMPONENTS) not in sys.path:
    sys.path.insert(0, str(COMPONENTS))
from openwebui_local_media import generate


T2V_MODEL = "wan2.2-t2v-rapid-aio-v10-nsfw-Q5_K.gguf"
I2V_MODEL = "wan2.2-i2v-rapid-aio-v10-nsfw-Q5_K.gguf"
H3_MODEL = "minimax-h3-fl2va-pruned-nf4.safetensors"


class Tools:
    citation = False

    async def create_video(self, prompt: str, negative_prompt: str = "", aspect: str = "4:3",
                           quality: str = "480p", duration_seconds: int = 5, fps: int = 0,
                           steps: int = 0, input_mode: str = "t2v",
                           video_model: Literal[
                               "wan2.2-t2v-rapid-aio-v10-nsfw-Q5_K.gguf",
                               "wan2.2-i2v-rapid-aio-v10-nsfw-Q5_K.gguf",
                               "minimax-h3-fl2va-pruned-nf4.safetensors",
                           ] = T2V_MODEL,
                           reference_file_id: str = "", seed: int = -1, idempotency_key: str = "",
                           __user__=None, __metadata__=None, __event_emitter__=None) -> str:
        """Create an MP4 with local WAN Video Desk and attach it to this saved chat.

        Use for requests to make a video, moving shot or animation, not video discussion.
        Call once and wait. The take stays in WAN Video Desk for editing, reuse and reruns.
        WAN is the fast silent default. MiniMax H3 FL2VA pruned NF4 is the low-VRAM
        option with fixed 24 fps, native stereo audio, and text or first-frame input.

        Text input uses input_mode=t2v. To animate an uploaded image, use input_mode=i2v,
        supply its Open WebUI file UUID and explicitly select the I2V model. Input and model
        are independent controls; never silently rewrite one from the other.

        :param prompt: Detailed description of one moving shot.
        :param negative_prompt: Optional unwanted motion or visual traits.
        :param aspect: 16:9, 4:3 or mobile (9:16). Default 4:3.
        :param quality: 480p or 720p. Default 480p.
        :param duration_seconds: Whole seconds from 1 to 10 for WAN or 1 to 15 for H3.
        :param fps: 0 selects the model default; WAN accepts 16/24 and H3 is fixed at 24.
        :param steps: 0 selects the model default; WAN accepts 4–20 and H3 accepts 4–50.
        :param input_mode: t2v for text input or i2v for image input.
        :param video_model: Exact installed WAN T2V/I2V GGUF or MiniMax H3 NF4 filename.
        :param reference_file_id: Uploaded Open WebUI image UUID for i2v; never a path or URL.
        :param seed: Optional seed from 0 to 9223372036854775807; -1 chooses a random seed.
        :param idempotency_key: Stable caller retry key, required only when Open WebUI supplies no message ID.
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
        is_h3 = video_model == H3_MODEL
        max_seconds = 15 if is_h3 else 10
        if not 1 <= int(duration_seconds) <= max_seconds:
            return f"Choose a duration from 1 to {max_seconds} whole seconds."
        resolved_fps = 24 if is_h3 else (16 if int(fps) == 0 else int(fps))
        resolved_steps = (20 if is_h3 else 4) if int(steps) == 0 else int(steps)
        if is_h3 and int(fps) not in (0, 24):
            return "MiniMax H3 runs at its native 24 fps."
        if not is_h3 and resolved_fps not in (16, 24):
            return "Choose 16 or 24 fps for WAN."
        if not 4 <= resolved_steps <= (50 if is_h3 else 20):
            return "Choose 4–50 steps for MiniMax H3 or 4–20 for WAN."
        if input_mode not in ("t2v", "i2v"):
            return "Choose t2v (Text input) or i2v (Image input)."
        if video_model not in (T2V_MODEL, I2V_MODEL, H3_MODEL):
            return "Choose one of Video Desk's installed models."
        if input_mode == "i2v" and video_model == T2V_MODEL:
            return "The T2V GGUF cannot use Image input. Select the installed WAN I2V GGUF."
        if input_mode == "i2v" and not reference_file_id:
            return "Image input needs an uploaded Open WebUI image file ID."
        if seed < -1 or seed >= 2**63:
            return "Seed must be -1 (random) or between 0 and 9223372036854775807."
        payload = {
            "final_prompt": prompt, "original_prompt": prompt, "negative": negative_prompt,
            "prompt_mode": "direct", "quality": quality, "aspect": aspect,
            "duration_seconds": int(duration_seconds), "fps": resolved_fps, "steps": resolved_steps,
            "batch_count": 1, "mode": input_mode, "video_model": video_model,
        }
        if seed >= 0:
            payload["seed"] = int(seed)
        return await generate("video", payload, __user__, __metadata__, __event_emitter__,
                              reference_file_id if input_mode == "i2v" else "", idempotency_key)
