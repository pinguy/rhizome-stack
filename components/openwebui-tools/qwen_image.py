"""Open WebUI image generation/editing through the packaged Qwen Image Desk."""
import os
import sys
from pathlib import Path

COMPONENTS = Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser() / "components"
if str(COMPONENTS) not in sys.path:
    sys.path.insert(0, str(COMPONENTS))
from openwebui_local_media import generate


class Tools:
    citation = False

    async def create_image(self, prompt: str, shape: str = "square", reference_file_id: str = "",
                           __user__=None, __metadata__=None, __event_emitter__=None) -> str:
        """Create or edit an actual image using local Qwen Image Desk.

        Use for requests to make, draw, illustrate or generate a picture, not image discussion.
        Call once and wait. To edit an uploaded image, supply its Open WebUI file ID.

        :param prompt: Detailed image description, or precise requested changes when editing.
        :param shape: square, landscape or portrait. Default square.
        :param reference_file_id: Optional uploaded Open WebUI image UUID to edit; never a path or URL.
        """
        shape = shape.lower().strip()
        if shape not in ("square", "landscape", "portrait"):
            return "Choose square, landscape or portrait."
        if not prompt.strip() or len(prompt) > 12000:
            return "Provide an image prompt between 1 and 12000 characters."
        return await generate("image", {
            "final_prompt": prompt.strip(), "original_prompt": prompt.strip(),
            "prompt_mode": "direct", "preset": shape + "-standard", "batch_count": 1,
        }, __user__, __metadata__, __event_emitter__, reference_file_id)
