"""CUDA availability detection and GPU-accelerated OpenCV helpers.

CUDA support requires opencv-contrib-python built with CUDA.
The standard pip package does NOT include CUDA — see docs/BUILD.md.
All functions degrade gracefully to CPU when CUDA is unavailable.
"""
from __future__ import annotations
import functools
from typing import Optional
import numpy as np

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

# ------------------------------------------------------------------ detection
@functools.lru_cache(maxsize=1)
def cuda_device_count() -> int:
    if not _CV2_OK:
        return 0
    try:
        return cv2.cuda.getCudaEnabledDeviceCount()
    except (AttributeError, cv2.error):
        return 0


def cuda_available() -> bool:
    return cuda_device_count() > 0


def cuda_info() -> str:
    n = cuda_device_count()
    if n == 0:
        return "CUDA недоступна (используется CPU)"
    lines = [f"CUDA: {n} устройств"]
    for i in range(n):
        try:
            dev = cv2.cuda.DeviceInfo(i)
            lines.append(f"  [{i}] {dev.name()}  "
                         f"{dev.totalMemory() // (1024**2)} МБ")
        except Exception:
            lines.append(f"  [{i}] <нет информации>")
    return "\n".join(lines)


# ------------------------------------------------------------------ operations
def bgr2gray(frame: np.ndarray) -> np.ndarray:
    """BGR → grayscale; uses GPU when available."""
    if cuda_available():
        try:
            gpu = cv2.cuda_GpuMat()
            gpu.upload(frame)
            gpu_gray = cv2.cuda.cvtColor(gpu, cv2.COLOR_BGR2GRAY)
            return gpu_gray.download()
        except Exception:
            pass
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def bgr2rgb(frame: np.ndarray) -> np.ndarray:
    """BGR → RGB; uses GPU when available."""
    if cuda_available():
        try:
            gpu = cv2.cuda_GpuMat()
            gpu.upload(frame)
            gpu_rgb = cv2.cuda.cvtColor(gpu, cv2.COLOR_BGR2RGB)
            return gpu_rgb.download()
        except Exception:
            pass
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


# ------------------------------------------------------------------ optical flow
class OpticalFlowTracker:
    """Sparse optical flow (Lucas–Kanade).

    Uses cv2.cuda.SparsePyrLKOpticalFlow on GPU when CUDA is available,
    falls back to cv2.calcOpticalFlowPyrLK on CPU otherwise.
    """

    _LK_WIN = (15, 15)
    _LK_MAX_LEVEL = 2
    _LK_CRITERIA = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT if _CV2_OK else 0,
        10, 0.03
    )
    _MAX_CORNERS = 80

    def __init__(self):
        self._use_cuda = False
        self._gpu_lk = None
        self._prev_gray: Optional[np.ndarray] = None
        self._prev_pts: Optional[np.ndarray] = None

        if cuda_available() and _CV2_OK:
            try:
                self._gpu_lk = cv2.cuda.SparsePyrLKOpticalFlow_create(
                    winSize=self._LK_WIN,
                    maxLevel=self._LK_MAX_LEVEL,
                )
                self._use_cuda = True
            except (AttributeError, cv2.error):
                pass

    @property
    def backend(self) -> str:
        return "CUDA" if self._use_cuda else "CPU"

    def track(self, frame_bgr: np.ndarray) -> list:
        """Return list of (old_pt, new_pt) flow vectors for this frame."""
        if not _CV2_OK:
            return []
        gray = bgr2gray(frame_bgr)
        vectors = []

        if self._prev_gray is not None and self._prev_pts is not None:
            if self._use_cuda:
                vectors = self._track_cuda(gray)
            else:
                vectors = self._track_cpu(gray)

        # Refresh keypoints
        self._prev_gray = gray
        pts = cv2.goodFeaturesToTrack(
            gray, maxCorners=self._MAX_CORNERS,
            qualityLevel=0.01, minDistance=8
        )
        if pts is not None:
            self._prev_pts = pts

        return vectors

    def _track_cpu(self, gray: np.ndarray) -> list:
        new_pts, status, _ = cv2.calcOpticalFlowPyrLK(
            self._prev_gray, gray, self._prev_pts, None,
            winSize=self._LK_WIN, maxLevel=self._LK_MAX_LEVEL,
            criteria=self._LK_CRITERIA,
        )
        vectors = []
        if new_pts is not None and status is not None:
            for new, old, ok in zip(new_pts, self._prev_pts, status):
                if ok[0]:
                    vectors.append((
                        tuple(old.ravel().astype(int)),
                        tuple(new.ravel().astype(int)),
                    ))
        return vectors

    def _track_cuda(self, gray: np.ndarray) -> list:
        try:
            gpu_prev = cv2.cuda_GpuMat()
            gpu_curr = cv2.cuda_GpuMat()
            gpu_pts = cv2.cuda_GpuMat()
            gpu_prev.upload(self._prev_gray)
            gpu_curr.upload(gray)
            gpu_pts.upload(self._prev_pts)

            gpu_new, gpu_status, _ = self._gpu_lk.calc(
                gpu_prev, gpu_curr, gpu_pts, None
            )
            new_pts = gpu_new.download()
            status = gpu_status.download()
            vectors = []
            for new, old, ok in zip(new_pts, self._prev_pts, status):
                if ok[0]:
                    vectors.append((
                        tuple(old.ravel().astype(int)),
                        tuple(new.ravel().astype(int)),
                    ))
            return vectors
        except Exception:
            # Graceful fallback to CPU
            return self._track_cpu(gray)
