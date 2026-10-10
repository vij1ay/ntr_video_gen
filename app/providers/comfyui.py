"""
ComfyUI provider — HTTP API integration.

ComfyUI exposes a WebSocket + REST API at http://127.0.0.1:8188.
This provider handles:
  - Queueing workflows
  - Polling for completion
  - Downloading output images/videos
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

from app.core.config import ComfyUISettings
from app.core.logging import get_logger
from app.providers.base import ImageProvider, VideoProvider

logger = get_logger("providers.comfyui")


class ComfyUIProvider(ImageProvider, VideoProvider):
    """
    Provider that submits workflows to ComfyUI and retrieves outputs.

    Workflows are loaded from JSON files (workflows/ directory).
    Parameters are injected into the workflow graph at call time.
    """

    def __init__(self, settings: Optional[ComfyUISettings] = None) -> None:
        self.settings = settings or ComfyUISettings()
        self._client_id = f"{self.settings.client_id}-{uuid.uuid4().hex[:8]}"
        logger.debug(
            "ComfyUIProvider initialised: base_url=%s client_id=%s",
            self.settings.base_url,
            self._client_id,
        )

    # ── Health check ──────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Return True if ComfyUI system stats endpoint responds."""
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    urljoin(self.settings.base_url, "/system_stats")
                )
                response.raise_for_status()
                logger.debug("ComfyUI health check OK: %s", response.json())
                return True
        except Exception as exc:
            logger.error("ComfyUI health check failed: %s", exc)
            return False

    # ── ImageProvider interface ───────────────────────────────────────────────

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        seed: Optional[int] = None,
        output_path: Optional[Path] = None,
        extra_params: Optional[dict] = None,
        workflow_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate a still image via ComfyUI.

        Args:
            prompt: Positive generation prompt.
            negative_prompt: Negative generation prompt.
            width: Output image width.
            height: Output image height.
            seed: Optional fixed seed.
            output_path: Where to save the downloaded image.
            extra_params: Additional workflow parameter overrides.
            workflow_path: Path to the workflow JSON file.

        Returns:
            Path to the saved image file.
        """
        workflow_path = workflow_path or Path("workflows") / "image_generation.json"
        params = {
            "positive_prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed if seed is not None else int(time.time() * 1000) % (2**31),
            **(extra_params or {}),
        }
        return self._run_workflow(
            workflow_path=workflow_path,
            params=params,
            output_path=output_path,
            expected_type="image",
        )

    # ── VideoProvider interface ───────────────────────────────────────────────

    def generate_video(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        duration_seconds: int,
        seed: Optional[int] = None,
        output_path: Optional[Path] = None,
        extra_params: Optional[dict] = None,
        workflow_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate a short video clip via ComfyUI.

        Returns:
            Path to the saved video file.
        """
        workflow_path = workflow_path or Path("workflows") / "text_to_video.json"
        params = {
            "positive_prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "duration_seconds": duration_seconds,
            "seed": seed if seed is not None else int(time.time() * 1000) % (2**31),
            **(extra_params or {}),
        }
        return self._run_workflow(
            workflow_path=workflow_path,
            params=params,
            output_path=output_path,
            expected_type="video",
        )

    # ── Public lower-level API ────────────────────────────────────────────────

    def queue_workflow(self, workflow: dict) -> str:
        """
        Submit a workflow to ComfyUI's queue.

        Args:
            workflow: The workflow graph dict (with parameters already injected).

        Returns:
            The prompt_id assigned by ComfyUI.
        """
        # Filter out comments/documentation keys that ComfyUI rejects
        clean_workflow = {k: v for k, v in workflow.items() if not str(k).startswith("_")}

        payload = {
            "prompt": clean_workflow,
            "client_id": self._client_id,
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                urljoin(self.settings.base_url, "/prompt"),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            prompt_id: str = data["prompt_id"]
            logger.info("ComfyUI workflow queued: prompt_id=%s", prompt_id)
            return prompt_id

    def wait_for_result(self, prompt_id: str) -> dict:
        """
        Poll ComfyUI history until the prompt completes.

        Args:
            prompt_id: The prompt_id returned by queue_workflow.

        Returns:
            The history entry dict for this prompt.

        Raises:
            TimeoutError: If the workflow does not complete within timeout.
            RuntimeError: If ComfyUI reports an execution error.
        """
        deadline = time.monotonic() + self.settings.timeout_seconds
        logger.info("Waiting for ComfyUI prompt_id=%s …", prompt_id)

        while time.monotonic() < deadline:
            history = self._get_history(prompt_id)
            if history:
                entry = history.get(prompt_id, {})
                outputs = entry.get("outputs", {})
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(
                        f"ComfyUI reported error for prompt {prompt_id}: {status}"
                    )
                if outputs:
                    logger.info("ComfyUI prompt completed: %s", prompt_id)
                    return entry
            time.sleep(self.settings.poll_interval_seconds)

        raise TimeoutError(
            f"ComfyUI prompt {prompt_id} did not complete within "
            f"{self.settings.timeout_seconds}s"
        )

    def download_result(
        self,
        history_entry: dict,
        output_path: Path,
        expected_type: str = "image",
    ) -> Path:
        """
        Download the first output file from a completed workflow.

        Args:
            history_entry: The history entry returned by wait_for_result.
            output_path: Destination file path.
            expected_type: "image" or "video".

        Returns:
            Path to the downloaded file.
        """
        outputs = history_entry.get("outputs", {})
        for node_id, node_output in outputs.items():
            files: list[dict] = []
            if expected_type == "image":
                files = node_output.get("images", [])
            elif expected_type == "video":
                files = (
                    node_output.get("gifs", [])
                    or node_output.get("videos", [])
                    or node_output.get("images", [])
                )

            if files:
                first = files[0]
                filename = first.get("filename", "")
                subfolder = first.get("subfolder", "")
                file_type = first.get("type", "output")
                downloaded = self._download_file(filename, subfolder, file_type, output_path)

                # If caller expected .mp4 but ComfyUI produced .webp/.gif, convert using FFmpeg
                if output_path.suffix.lower() == ".mp4" and downloaded.suffix.lower() in (".webp", ".gif", ".png"):
                    import subprocess
                    converted_path = output_path.with_suffix(".mp4")
                    conv_cmd = [
                        "ffmpeg", "-y",
                        "-i", str(downloaded),
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        str(converted_path),
                    ]
                    try:
                        subprocess.run(conv_cmd, check=True, capture_output=True)
                        return converted_path
                    except Exception:
                        pass
                return downloaded

        raise RuntimeError(
            f"No {expected_type} output found in history entry: {outputs}"
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _run_workflow(
        self,
        workflow_path: Path,
        params: dict,
        output_path: Optional[Path],
        expected_type: str,
    ) -> Path:
        """Load workflow, inject params, queue, wait, download."""
        if not workflow_path.exists():
            raise FileNotFoundError(
                f"ComfyUI workflow not found: {workflow_path}\n"
                f"Please copy the appropriate workflow JSON to that path."
            )

        with open(workflow_path, "r", encoding="utf-8") as fh:
            workflow = json.load(fh)

        workflow = self._inject_params(workflow, params)
        prompt_id = self.queue_workflow(workflow)
        history = self.wait_for_result(prompt_id)

        if output_path is None:
            ext = ".png" if expected_type == "image" else ".mp4"
            output_path = Path(f"output_{prompt_id}{ext}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        return self.download_result(history, output_path, expected_type)

    def _inject_params(self, workflow: dict, params: dict) -> dict:
        """
        Inject parameters into a ComfyUI API workflow graph.

        Convention: workflow nodes may contain "__param__<key>" placeholder strings.
        This method replaces them with the corresponding param values.

        For standard node types (KSampler, CLIPTextEncode etc.) it also applies
        known mappings for common parameters.
        """
        import copy
        workflow = copy.deepcopy(workflow)
        workflow_str = json.dumps(workflow)

        # Replace __param__<key> placeholders
        for key, value in params.items():
            placeholder = f"__param__{key}"
            workflow_str = workflow_str.replace(f'"{placeholder}"', json.dumps(value))
            workflow_str = workflow_str.replace(placeholder, str(value))

        return json.loads(workflow_str)

    def _get_history(self, prompt_id: str) -> dict:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    urljoin(self.settings.base_url, f"/history/{prompt_id}")
                )
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            logger.debug("ComfyUI history fetch error: %s", exc)
            return {}

    def _download_file(
        self,
        filename: str,
        subfolder: str,
        file_type: str,
        output_path: Path,
    ) -> Path:
        params = {"filename": filename, "subfolder": subfolder, "type": file_type}
        url = urljoin(self.settings.base_url, "/view")
        logger.info("Downloading ComfyUI output: %s → %s", filename, output_path)
        with httpx.Client(timeout=120.0) as client:
            with client.stream("GET", url, params=params) as response:
                response.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as fh:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        fh.write(chunk)
        logger.info("Downloaded: %s (%d bytes)", output_path, output_path.stat().st_size)
        return output_path
