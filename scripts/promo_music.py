"""Lyria on Vertex AI: 30-second instrumental bed for the demo video. Bonus-model integration, outside the release path.
Usage: .venv/bin/python scripts/promo_music.py docs/promo_music.wav
"""
import base64
import os
import sys

import google.auth
import google.auth.transport.requests
import httpx

dst = sys.argv[1] if len(sys.argv) > 1 else "docs/promo_music.wav"
project = os.environ["GOOGLE_CLOUD_PROJECT"]
model = os.environ.get("LYRIA_MODEL", "lyria-002")
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
creds.refresh(google.auth.transport.requests.Request())
r = httpx.post(
    f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/locations/us-central1/publishers/google/models/{model}:predict",
    headers={"Authorization": f"Bearer {creds.token}", "x-goog-user-project": project},
    json={"instances": [{"prompt": "Warm minimal electronic, 100 bpm, soft synth pads and a light plucked melody, optimistic product-demo mood, instrumental, clean ending",
                         "negative_prompt": "vocals, lyrics, distortion"}], "parameters": {"sample_count": 1}},
    timeout=300,
)
r.raise_for_status()
pred = r.json()["predictions"][0]
audio = pred.get("bytesBase64Encoded") or pred.get("audioContent")
with open(dst, "wb") as f:
    f.write(base64.b64decode(audio))
print("wrote", dst, pred.get("mimeType"))
