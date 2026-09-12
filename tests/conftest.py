"""Synthetic fixtures — generated in code so the repo carries no binary blobs."""

from __future__ import annotations

import cv2
import numpy as np
import pytest


def _white_canvas(size: int = 200) -> np.ndarray:
    return np.full((size, size, 3), 255, np.uint8)


@pytest.fixture
def square_image() -> np.ndarray:
    """A black 100x100 px square on white, inset in a 200x200 px canvas."""
    img = _white_canvas()
    cv2.rectangle(img, (50, 50), (149, 149), (0, 0, 0), -1)
    return img


@pytest.fixture
def ring_image() -> np.ndarray:
    """A black ring: one outer boundary with exactly one hole."""
    img = _white_canvas()
    cv2.circle(img, (100, 100), 80, (0, 0, 0), -1)
    cv2.circle(img, (100, 100), 40, (255, 255, 255), -1)
    return img


@pytest.fixture
def gradient_image() -> np.ndarray:
    """A left-to-right ramp, for exercising posterize tone levels."""
    ramp = np.linspace(0, 255, 200, dtype=np.uint8)
    return np.repeat(np.tile(ramp, (200, 1))[:, :, None], 3, axis=2)


@pytest.fixture
def offset_square_image() -> np.ndarray:
    """A square in the top-left quadrant, so a Y-flip error is detectable."""
    img = _white_canvas()
    cv2.rectangle(img, (0, 0), (99, 49), (0, 0, 0), -1)
    return img
