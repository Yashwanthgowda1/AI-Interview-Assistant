"""
image_client.py — Screenshot capture + AI vision analysis.
Uses the configured AI provider's vision model to extract interview questions.
"""
from __future__ import annotations
import base64, io, logging
import os
import subprocess
import tempfile
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)

_WINDOWS_OCR_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]

function Await($Operation, [Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } | Select-Object -First 1
    if (-not $method) { throw 'Windows OCR async bridge is unavailable.' }
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:BOT_PROXY_OCR_IMAGE)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { throw 'Windows OCR has no supported language installed for the current user.' }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$result.Text
"""

VISION_PROMPT = (
    "Look at this screenshot carefully. "
    "Extract ONLY the interview question or coding problem visible on screen. "
    "Return just the question text, nothing else. "
    "If there are multiple questions, return all of them. "
    "If there is NO interview question or coding problem visible, "
    "reply with exactly: NONE"
)

VISION_MODELS = {
    "groq": "qwen/qwen3.8-27b",
    "mistral": "mistral-small-2506",
    "openai": "gpt-4o-mini",
}


def capture_screen(region=None) -> Optional[Image.Image]:
    """Grab the full screen (or a region) using PyAutoGUI."""
    try:
        import pyautogui
        return pyautogui.screenshot(region=region)
    except Exception as exc:
        logger.exception("Screenshot failed: %s", exc)
        return None


def image_to_base64(image: Image.Image) -> str:
    """Encode PIL image as base64 PNG string."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def extract_text_offline(image: Image.Image) -> str:
    """Extract visible text with the built-in Windows OCR engine."""
    if os.name != "nt":
        raise RuntimeError("Offline screen reading is currently supported on Windows only.")

    image_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_path = image_file.name
        image.save(image_path, format="PNG")

        env = os.environ.copy()
        env["BOT_PROXY_OCR_IMAGE"] = image_path
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_OCR_SCRIPT],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.strip() or "Windows OCR could not read the screenshot."
            raise RuntimeError(detail)
        text = result.stdout.strip()
        if not text:
            raise RuntimeError("No readable text was found on the screen.")
        return text
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Windows screen text recognition timed out.") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start Windows screen text recognition: {exc}") from exc
    finally:
        if image_path and os.path.exists(image_path):
            os.unlink(image_path)


def extract_question_from_screen(
    image: Image.Image,
    provider: str,
    api_key: str = "",
    model: str = "",
    ollama_url: str = "http://localhost:11434",
) -> str:
    """
    Send a screenshot to the configured provider's vision model.
    For Ollama, model must name a locally installed vision-capable model.
    """
    provider = provider.lower().strip()
    if provider not in (*VISION_MODELS, "ollama"):
        raise ValueError(f"Screen analysis is not supported for provider '{provider}'.")
    if provider != "ollama" and not api_key.strip():
        raise ValueError(f"{provider.title()} API key is missing.")
    if provider == "ollama" and not model.strip():
        raise ValueError("Select a vision-capable Ollama model for screen analysis.")

    b64 = image_to_base64(image)
    data_url = f"data:image/png;base64,{b64}"
    vision_model = model if provider == "ollama" else VISION_MODELS[provider]
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                },
                {"type": "text", "text": VISION_PROMPT},
            ],
        }
    ]

    try:
        if provider == "groq":
            from groq import Groq

            client = Groq(api_key=api_key.strip())
            response = client.chat.completions.create(
                model=vision_model,
                messages=messages,
                max_completion_tokens=512,
                temperature=1,
            )
        elif provider == "mistral":
            try:
                from mistralai import Mistral
            except ImportError:
                from mistralai.client import Mistral

            client = Mistral(api_key=api_key.strip())
            response = client.chat.complete(
                model=vision_model,
                messages=messages,
                max_tokens=512,
                temperature=0,
            )
        elif provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=api_key.strip())
            response = client.chat.completions.create(
                model=vision_model,
                messages=messages,
                max_tokens=512,
                temperature=0,
            )
        else:
            import requests

            response = requests.post(
                f"{ollama_url.rstrip('/')}/api/chat",
                json={
                    "model": vision_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": VISION_PROMPT,
                            "images": [b64],
                        }
                    ],
                    "stream": False,
                    "options": {"num_predict": 512, "temperature": 0},
                },
                timeout=60,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            if not content:
                raise RuntimeError("The vision model returned an empty response.")
            return content.strip()

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("The vision model returned an empty response.")
        return content.strip()
    except Exception as exc:
        logger.exception("Vision request failed for provider %s: %s", provider, exc)
        if isinstance(exc, (ImportError, ValueError)):
            raise
        raise RuntimeError(f"{provider.title()} vision request failed: {exc}") from exc


def pil_to_qpixmap(image: Image.Image):
    """Convert PIL Image → QPixmap for display in PyQt5."""
    from PyQt5.QtGui import QPixmap, QImage
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    qimg = QImage()
    qimg.loadFromData(buf.read())
    return QPixmap.fromImage(qimg)
