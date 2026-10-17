"""Hosted OCR models on Modal: granite-docling through Docling's VLM pipeline, and olmOCR 2 on vLLM.

Two steps, so GPU time is spent only on reading pages:

    modal run ocr_modal.py::download    # CPU only: fetch both models' weights into a Modal Volume, once

Then extract_ocr.py uses the GPU classes below inside an ephemeral app run. Modal starts a
container on demand, loads the weights from the Volume (no download), and scales back to zero
when idle.

- GraniteServer serves ibm-granite/granite-docling-258M with vLLM's OpenAI-compatible API,
  behind an API key made for each run. Docling runs locally with its VLM pipeline pointed at
  it (Docling's own GRANITEDOCLING_VLLM_API settings), so the page comes back as a
  DoclingDocument: text items and tables, each with its box. Docling only renders pages and
  parses the model's DocTags locally; the model runs on Modal's GPU.
- OlmOCR runs allenai/olmOCR-2-7B-1025-FP8 with olmOCR's own prompt and image size, and
  returns the page as Markdown (with HTML tables). It gives no positions.
"""

import io
import os
import secrets
import subprocess
import time

import modal

app = modal.App("k1-ocr-models")
weights = modal.Volume.from_name("k1-ocr-weights", create_if_missing=True)
HF_CACHE = "/weights/hf"
GRANITE = "ibm-granite/granite-docling-258M"
OLMOCR = "allenai/olmOCR-2-7B-1025-FP8"

# olmOCR 2's prompt and settings, from olmocr/prompts/prompts.py (build_no_anchoring_v4_yaml_prompt) and pipeline.py.
OLMOCR_PROMPT = (
    "Attached is one page of a document that you must process. "
    "Just return the plain text representation of this document as if you were reading it naturally. "
    "Convert equations to LateX and tables to HTML.\n"
    "If there are any figures or charts, label them with the following markdown syntax "
    "![Alt text describing the contents of the figure](page_startx_starty_width_height.png)\n"
    "Return your output as markdown, with a front matter section on top specifying values for the primary_language, "
    "is_rotation_valid, rotation_correction, is_table, and is_diagram parameters."
)
OLMOCR_IMAGE_DIM = 1288  # longest side, in pixels

download_image = (modal.Image.debian_slim(python_version="3.11")
                  .pip_install("huggingface_hub==0.35.3", "hf_transfer==0.1.9")
                  .env({"HF_HUB_CACHE": HF_CACHE, "HF_HUB_ENABLE_HF_TRANSFER": "1"}))

vllm_image = (modal.Image.debian_slim(python_version="3.12")
              .pip_install("vllm==0.11.0", "transformers==4.57.1", "pillow==12.0.0")  # vLLM 0.11 predates Transformers 5
              .env({"HF_HUB_CACHE": HF_CACHE, "HF_HUB_OFFLINE": "1"}))


@app.function(image=download_image, volumes={"/weights": weights}, cpu=2, memory=4096, timeout=3600)
def download():
    """Fetch the weights into the Volume on a small CPU container. Skips what's already there."""
    from huggingface_hub import snapshot_download

    for repo in (GRANITE, OLMOCR):
        t0 = time.time()
        path = snapshot_download(repo)
        print(f"{repo}: {path} ({time.time() - t0:.0f}s)")
    weights.commit()


# Ephemeral runs of this app share the server's web URL, so run one at a time (run.sh does).
# The key the granite-docling server checks. Made fresh when this module is imported locally and handed to the
# container through a Secret, so the server is only usable from this run.
API_KEY = os.environ.get("VLLM_API_KEY") or secrets.token_urlsafe(32)
GRANITE_PORT = 8000


@app.cls(image=vllm_image, gpu="L4", volumes={"/weights": weights}, timeout=3600, scaledown_window=120,
         secrets=[modal.Secret.from_dict({"VLLM_API_KEY": API_KEY})])
@modal.concurrent(max_inputs=32)
class GraniteServer:
    @modal.web_server(port=GRANITE_PORT, startup_timeout=900)
    def serve(self):
        subprocess.Popen(["vllm", "serve", GRANITE, "--port", str(GRANITE_PORT), "--api-key", os.environ["VLLM_API_KEY"],
                          "--max-model-len", "8192", "--limit-mm-per-prompt", '{"image": 1}'])


@app.cls(image=vllm_image, gpu="L4", volumes={"/weights": weights}, timeout=1800, scaledown_window=120)
class OlmOCR:
    @modal.enter()
    def load(self):
        from vllm import LLM

        self.llm = LLM(model=OLMOCR, max_model_len=16384, gpu_memory_utilization=0.9, limit_mm_per_prompt={"image": 1})

    @modal.method()
    def ocr(self, pngs: list[bytes]) -> list[dict]:
        """Each page image as olmOCR reads it. Images are scaled so the longest side is 1288 pixels."""
        import base64

        from PIL import Image
        from vllm import SamplingParams

        messages = []
        for png in pngs:
            img = Image.open(io.BytesIO(png))
            scale = OLMOCR_IMAGE_DIM / max(img.size)
            img = img.resize((round(img.width * scale), round(img.height * scale)))
            buf = io.BytesIO()
            img.save(buf, "PNG")
            url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            messages.append([{"role": "user", "content": [{"type": "text", "text": OLMOCR_PROMPT},
                                                          {"type": "image_url", "image_url": {"url": url}}]}])
        t0 = time.time()
        outs = self.llm.chat(messages, SamplingParams(temperature=0.0, max_tokens=8000))
        seconds = round((time.time() - t0) / max(1, len(pngs)), 1)
        return [{"markdown": o.outputs[0].text, "seconds": seconds} for o in outs]
