"""Open WebUI song generation through the packaged MiniMax Music 3 app."""
import os
import sys
from pathlib import Path

COMPONENTS = Path(os.environ.get("RHIZOME_STACK_ROOT", "~/.local/share/rhizome-stack")).expanduser() / "components"
if str(COMPONENTS) not in sys.path:
    sys.path.insert(0, str(COMPONENTS))
from openwebui_local_media import generate


class Tools:
    citation = False

    async def create_song(
        self,
        title: str,
        caption: str,
        lyrics: str = "[Instrumental]",
        duration_seconds: int = 60,
        __user__=None,
        __metadata__=None,
        __event_emitter__=None,
    ) -> str:
        """Create a complete song with local MiniMax Music 3.

        Call this only when the user asks to create/generate/render an actual song or music track,
        not when they merely discuss music. Write a detailed MiniMax caption with three labelled
        sections: Global Metadata, Vocal Details, and Arrangement. Put all sung words and section
        tags in lyrics, never in caption. For an instrumental, use structure tags such as
        [Intro], [Instrumental], [Outro]. The operation can take several minutes.

        :param title: A short 2-5 word song title.
        :param caption: Detailed production description using Global Metadata, Vocal Details, and Arrangement sections.
        :param lyrics: Complete singable lyrics with section tags, or instrumental structure tags.
        :param duration_seconds: Requested duration from 8 to 300 seconds.
        """

        if not caption.strip():
            return "Describe the music before generating."
        return await generate("music", {
            "title": title.strip(), "caption": caption.strip(), "lyrics": lyrics.strip(),
            "seconds": max(8, min(300, int(duration_seconds))), "quality": "V0",
        }, __user__, __metadata__, __event_emitter__)
