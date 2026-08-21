"""Veo 3.1 on Vertex AI: the 8-second opening shot for the demo video, seeded with the first composite.
Bonus-model integration, deliberately OUTSIDE the release path: store assets must be real pixels.
Usage: .venv/bin/python scripts/promo_clip.py out/<job>/composites/01_list.png docs/promo_clip.mp4
"""
import os
import sys
import time

from google.genai import Client, types

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else "docs/promo_clip.mp4"
client = Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location="us-central1")
prompt = ("Cinematic slow push-in on a phone screen showing this clipboard manager app, indigo-violet studio backdrop, "
          "soft rim light, subtle floating paper snippets drifting past, no text overlays, no people, clean.")
op = client.models.generate_videos(
    model=os.environ.get("VEO_MODEL", "veo-3.1-fast-generate-001"),
    prompt=prompt,
    image=types.Image.from_file(location=src),
    config=types.GenerateVideosConfig(aspect_ratio="9:16", duration_seconds=8, resolution="1080p", number_of_videos=1),
)
while not op.done:
    print("veo rendering…"); time.sleep(15)
    op = client.operations.get(op)
if op.error:
    sys.exit(f"veo failed: {op.error}")
vid = op.result.generated_videos[0]
if vid.video.video_bytes:
    open(dst, "wb").write(vid.video.video_bytes)
else:
    vid.video.save(dst)
print("wrote", dst)
