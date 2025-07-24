#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""Enhanced Vaporwave video generator with triangle rasterization and solid surfaces.

This is an enhanced version of the vaporwave video generator that implements:
- Triangle rasterization for solid terrain surfaces
- Grid-based wireframe coloring
- Improved 3D-to-2D projection with depth information
- Continuous triangulated surfaces instead of sparse points

Dependencies:
    pip install Pillow noise librosa tqdm numpy
"""

import copy
import hashlib
import math
import multiprocessing as mp
import os
import platform
import subprocess
from typing import List, Tuple

import librosa
import numpy as np
from noise import pnoise2
from PIL import Image
from tqdm import tqdm

# ────────────────────────── Enhanced Frame with Triangle Rasterization ────────────────────────── #


class Frame:
    """Enhanced 3D voxel frame with triangle rasterization support."""

    def __init__(self, width: int, height: int, depth: int) -> None:
        """Initialize a 3D frame with specified dimensions."""
        self.shape = (width, height, depth)
        self.data = np.zeros((width, height, depth, 3), dtype=np.uint8)
        self.depth_buffer = np.zeros((width, height, depth), dtype=np.float32)

    def set_voxel(
        self, x: int, y: int, z: int, color: Tuple[int, int, int], depth: float = 0.0
    ) -> None:
        """Set a voxel with depth information for better 3D rendering."""
        if 0 <= x < self.shape[0] and 0 <= y < self.shape[1] and 0 <= z < self.shape[2]:
            self.data[x, y, z] = color
            self.depth_buffer[x, y, z] = depth

    def add(self, other: "Frame", ox: int, oy: int, oz: int) -> None:
        """Add another frame with proper depth blending."""
        for x in range(other.shape[0]):
            for y in range(other.shape[1]):
                for z in range(other.shape[2]):
                    color = other.data[x, y, z]
                    if np.any(color):
                        nx, ny, nz = x + ox, y + oy, z + oz
                        if (
                            0 <= nx < self.shape[0]
                            and 0 <= ny < self.shape[1]
                            and 0 <= nz < self.shape[2]
                        ):
                            self.set_voxel(nx, ny, nz, color, other.depth_buffer[x, y, z])

    def rasterize_triangle(
        self,
        p1: np.ndarray,
        p2: np.ndarray,
        p3: np.ndarray,
        color: Tuple[int, int, int],
        is_grid_line: bool = False,
    ) -> None:
        """Rasterize a triangle into the voxel grid with proper 3D filling."""
        # Convert points to integer coordinates
        points = [p1.astype(int), p2.astype(int), p3.astype(int)]

        # Calculate bounding box
        min_coords = np.minimum(np.minimum(points[0], points[1]), points[2])
        max_coords = np.maximum(np.maximum(points[0], points[1]), points[2])

        # Clamp to frame boundaries
        min_coords = np.maximum(min_coords, [0, 0, 0])
        max_coords = np.minimum(
            max_coords, [self.shape[0] - 1, self.shape[1] - 1, self.shape[2] - 1]
        )

        # Rasterize triangle using barycentric coordinates
        for x in range(min_coords[0], max_coords[0] + 1):
            for y in range(min_coords[1], max_coords[1] + 1):
                for z in range(min_coords[2], max_coords[2] + 1):
                    point = np.array([x, y, z], dtype=float)

                    # Check if point is inside triangle using barycentric coordinates
                    if self._point_in_triangle_3d(point, p1, p2, p3):
                        # Apply grid-based coloring logic
                        if is_grid_line:
                            self.set_voxel(x, y, z, color, y / self.shape[1])
                        else:
                            # For non-grid areas, use darker color or skip
                            dark_color = tuple(int(c * 0.3) for c in color)
                            self.set_voxel(x, y, z, dark_color, y / self.shape[1])

    def _point_in_triangle_3d(
        self, p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray
    ) -> bool:
        """Check if a 3D point is inside a triangle using barycentric coordinates."""
        # Project to 2D by finding the dominant axis
        normal = np.cross(b - a, c - a)
        abs_normal = np.abs(normal)

        # Choose projection plane based on largest normal component
        if abs_normal[0] >= abs_normal[1] and abs_normal[0] >= abs_normal[2]:
            # Project onto yz plane
            p2d = p[[1, 2]]
            a2d = a[[1, 2]]
            b2d = b[[1, 2]]
            c2d = c[[1, 2]]
        elif abs_normal[1] >= abs_normal[2]:
            # Project onto xz plane
            p2d = p[[0, 2]]
            a2d = a[[0, 2]]
            b2d = b[[0, 2]]
            c2d = c[[0, 2]]
        else:
            # Project onto xy plane
            p2d = p[[0, 1]]
            a2d = a[[0, 1]]
            b2d = b[[0, 1]]
            c2d = c[[0, 1]]

        # Barycentric coordinate test
        v0 = c2d - a2d
        v1 = b2d - a2d
        v2 = p2d - a2d

        dot00 = np.dot(v0, v0)
        dot01 = np.dot(v0, v1)
        dot02 = np.dot(v0, v2)
        dot11 = np.dot(v1, v1)
        dot12 = np.dot(v1, v2)

        inv_denom = 1 / (dot00 * dot11 - dot01 * dot01)
        u = (dot11 * dot02 - dot01 * dot12) * inv_denom
        v = (dot00 * dot12 - dot01 * dot02) * inv_denom

        return (u >= 0) and (v >= 0) and (u + v <= 1)

    def to_image(self, axis: int = 2) -> Image.Image:
        """Enhanced 3D-to-2D projection with depth-based intensity."""
        if axis == 2:  # Z-axis projection (most common)
            # Create depth-weighted composite
            result = np.zeros((self.shape[0], self.shape[1], 3), dtype=np.float32)
            depth_sum = np.zeros((self.shape[0], self.shape[1]), dtype=np.float32)

            for z in range(self.shape[2]):
                mask = np.any(self.data[:, :, z], axis=2)
                if np.any(mask):
                    # Weight by depth and color intensity
                    depth_weight = 1.0 - (z / self.shape[2]) * 0.7  # Closer objects are brighter
                    color_intensity = np.mean(self.data[:, :, z], axis=2) / 255.0
                    combined_weight = depth_weight * color_intensity

                    for i in range(3):
                        result[:, :, i] += self.data[:, :, z, i] * combined_weight
                    depth_sum += combined_weight

            # Normalize by accumulated weights
            mask = depth_sum > 0
            for i in range(3):
                result[:, :, i][mask] /= depth_sum[mask]

            # Clamp and convert to uint8
            result = np.clip(result, 0, 255).astype(np.uint8)
            return Image.fromarray(result, mode="RGB")
        else:
            # Fallback to simple max projection for other axes
            slice_img = np.max(self.data, axis=axis)
            return Image.fromarray(slice_img, mode="RGB")


# ────────────────────────── Keep Original Encoder Class ────────────────────────── #


class Encoder:
    """Video encoder for creating MP4 files from frames and audio."""

    def __init__(self, output_dir: str, framerate: float) -> None:
        """Initialize the video encoder with output directory and framerate."""
        self.frames = []
        self.audio_pcm = []
        self.output_dir = output_dir
        self.fps = framerate
        os.makedirs(output_dir, exist_ok=True)

    def encode(self, frame: Frame, index: int) -> None:
        """Encode a frame to PNG format and save to disk."""
        img = frame.to_image()
        path = f"{self.output_dir}/frame_{index:04d}.png"
        img.save(path)
        self.frames.append(path)

    def encode_audio(self, pcm_bytes: bytes) -> None:
        """Add PCM audio data to the encoder buffer."""
        self.audio_pcm.append(pcm_bytes)

    def finish(self) -> None:
        """Finalize the video encoding process and create MP4 file."""
        audio_path = os.path.join(self.output_dir, "audio.raw")
        with open(audio_path, "wb") as f:
            f.write(b"".join(self.audio_pcm))

        video_out = os.path.join(self.output_dir, "output.mp4")
        os.system(
            f"ffmpeg -framerate {self.fps} -i {self.output_dir}/frame_%04d.png "
            f"-f s16le -ar 44100 -ac 1 -i {audio_path} "
            f"-pix_fmt yuv420p -y {video_out}"
        )

        if os.path.exists(video_out):
            print(f"Video saved to {video_out}. Attempting to open...")
            try:
                system = platform.system()
                if system == "Darwin":
                    subprocess.run(["open", video_out], check=True)
                elif system == "Windows":
                    os.startfile(video_out)
                else:
                    subprocess.run(["xdg-open", video_out], check=True)
            except (OSError, AttributeError):
                print(f"Could not open video automatically. Please open it from: {video_out}")
        else:
            print(f"Error: Output video not found at {video_out}")


# ────────────────────────── Keep Original AudioProcessor Class ────────────────────────── #


class AudioProcessor:
    """Audio processing and analysis for reactive visualizations."""

    def __init__(
        self, path: str, bands: int, sr: int = 44100, hop: int = 512, thresh: float = 0.5
    ) -> None:
        """Initialize audio processor with audio file and analysis parameters."""
        self.sr, self.hop = sr, hop
        self.raw, _ = librosa.load(path, sr=sr)
        self.frames = 1 + len(self.raw) // hop
        mag = np.abs(librosa.stft(self.raw, hop_length=hop))
        basis = librosa.filters.mel(
            sr=sr, n_fft=mag.shape[0] * 2 - 2, n_mels=bands, fmin=50.0, fmax=20000.0
        )
        db = librosa.power_to_db(basis @ mag, ref=np.max)
        self.spec = (db - db.min()) / (db.max() - db.min())
        self.thresh = thresh

    def band_frame(self, idx: int) -> np.ndarray:
        """Get frequency band data for a specific frame index."""
        f = self.spec[:, idx]
        return np.where(f > self.thresh, (f - self.thresh) / (1 - self.thresh), 0)

    def pcm_frame(self, start: int, n: int) -> bytes:
        """Extract PCM audio data for a specific time range."""
        buf = np.clip(self.raw[start : start + n], -1, 1)
        pcm = (buf * 32767).astype(np.int16)
        return pcm.tobytes()


# ────────────────────────── Enhanced Visualizer with Triangle Surfaces ────────────────────────── #


def interpolate_color(colors: List[Tuple[int, int, int]], t: float) -> Tuple[int, int, int]:
    """Interpolate between colors based on a time parameter."""
    t %= 1.0
    n = len(colors)
    t_scaled = t * n
    idx = int(t_scaled) % n
    t_local = t_scaled - idx
    c1, c2 = colors[idx], colors[(idx + 1) % n]
    return tuple(int((1 - t_local) * c1[i] + t_local * c2[i]) for i in range(3))


class Visualizer:
    """Enhanced 3D visualizer with triangle rasterization and solid surfaces."""

    def __init__(self, octaves: int = 4, scroll: float = 0.25, decay: float = 0.999) -> None:
        """Initialize the visualizer with noise and animation parameters."""
        self.z_off = 0.0
        self.sun_off = 0.0
        self.octaves = octaves
        self.weights = np.zeros(octaves)
        self.scroll = scroll
        self.decay = decay

    def create_sun(self, n: int) -> Frame:
        """Create a 3-D 'vaporwave' sun."""
        sun = Frame(n, n, n)
        max_strip, min_strip = n // 16, n // 32
        for x in range(n):
            for y in range(n):
                for z in range(n):
                    dx, dy, dz = x + 0.5 - n / 2, y + 0.5 - n / 2, z + 0.5 - n / 2
                    if math.sqrt(dx * dx + dy * dy + dz * dz) <= n / 2:
                        y_norm = y / n
                        stripes = int(min_strip + y_norm * (max_strip - min_strip))
                        if (y // stripes) % 2 == 0:
                            sun.set_voxel(
                                x,
                                y,
                                z,
                                interpolate_color(
                                    [(255, 94, 0), (255, 42, 100), (180, 0, 255)], y_norm
                                ),
                                y_norm,
                            )
        return sun

    def update(self, dt: float, new_w: np.ndarray) -> None:
        """Update the visualizer state with new audio data."""
        self.weights -= self.weights * (1 - self.decay ** (1000 * dt))
        self.weights = np.maximum(self.weights, new_w)
        self.z_off += np.mean(new_w) * dt * self.scroll
        self.sun_off -= dt * 30

    def copy(self) -> "Visualizer":
        """Create a deep copy of the current visualizer state."""
        return copy.deepcopy(self)

    def get_height(self, x: int, z: int, w: int, h: int, d: int, spacing: int) -> float:
        """Calculate terrain height at a given position with audio reactivity."""
        xn, zn = x / w, z / d
        n = 0
        for i in range(self.octaves):
            rand = int(hashlib.md5(f"{x}_{z}_{i}".encode()).hexdigest()[:2], 16)
            disable = rand < 180
            scale = spacing ** (i + 1)
            octave = abs(pnoise2(xn * scale, zn * scale, base=i))
            n += octave * (0.75 if disable else self.weights[i]) * (0.25**i)
        return max(h * n * (math.cos(xn * 2 * math.pi) * 0.5 + 0.5), 1.0 / h / 2)

    def render(self, dims: Tuple[int, int, int]) -> Tuple[Tuple[int, int, int], Frame, int, float]:
        """Enhanced render with triangulated surfaces."""
        w, h, d = dims
        spacing = int(min(w, d) / 25)
        z_base = self.z_off * d
        min_z = (math.floor(z_base / spacing)) * spacing
        max_z = (math.ceil((z_base + d) / spacing)) * spacing

        frame = Frame(*dims)

        # Generate triangulated terrain surfaces
        for x in range(0, w - spacing, spacing):
            for z in range(min_z, max_z - spacing, spacing):
                # Calculate heights at grid corners
                h00 = int(self.get_height(x, z, w, h, d, spacing))
                h10 = int(self.get_height(x + spacing, z, w, h, d, spacing))
                h01 = int(self.get_height(x, z + spacing, w, h, d, spacing))
                h11 = int(self.get_height(x + spacing, z + spacing, w, h, d, spacing))

                # Create 3D points
                p0 = np.array([x, h00, int(z - z_base)], dtype=float)
                p1 = np.array([x + spacing, h10, int(z - z_base)], dtype=float)
                p2 = np.array([x, h01, int(z + spacing - z_base)], dtype=float)
                p3 = np.array([x + spacing, h11, int(z + spacing - z_base)], dtype=float)

                # Skip if any point is outside frame bounds
                if (
                    p0[2] < 0
                    or p0[2] >= d
                    or p1[2] < 0
                    or p1[2] >= d
                    or p2[2] < 0
                    or p2[2] >= d
                    or p3[2] < 0
                    or p3[2] >= d
                ):
                    continue

                # Calculate colors based on height
                avg_height = (h00 + h10 + h01 + h11) / 4.0
                color = interpolate_color(
                    [(25, 214, 252), (255, 20, 147), (232, 103, 23), (232, 224, 16)], avg_height / h
                )

                # Determine if this is a grid line for wireframe effect
                is_grid_x = int(z + z_base) % spacing == 0
                is_grid_z = x % spacing == 0
                is_grid_line = is_grid_x or is_grid_z

                # Create two triangles to form a quad
                frame.rasterize_triangle(p0, p1, p2, color, is_grid_line)
                frame.rasterize_triangle(p1, p3, p2, color, is_grid_line)

        return dims, frame, spacing, z_base

    def present(self, render_out: Tuple[Tuple[int, int, int], Frame, int, float]) -> Frame:
        """Extract the frame from render output."""
        _, frame, _, _ = render_out
        return frame


# ────────────────────────── Keep Original Worker and Main Functions ────────────────────────── #


def _render_job(args: Tuple[Visualizer, int]) -> Tuple[Tuple[int, int, int], Frame, int, float]:
    """Worker function for parallel rendering."""
    vis, n = args
    return vis.render((n, n, n * 2))


def verify_dir(dir: str) -> None:
    """Verify that a directory exists and create it if it doesn't."""
    if not os.path.exists(dir):
        os.makedirs(dir)


def main() -> None:
    """Main function to generate an enhanced vaporwave video from audio."""
    audio_path = "resonance.mp3"
    density = 128
    fps = 30.0
    octaves = 4
    output_dir = "tmp/output"
    sun_n = 64

    verify_dir(output_dir)
    vis = Visualizer(octaves)
    audio = AudioProcessor(audio_path, octaves)
    encoder = Encoder(output_dir, fps)
    sun = vis.create_sun(sun_n)

    afps = audio.sr / audio.hop
    ratio = afps / fps
    smp_per_vf = int(audio.sr / fps)
    total_vf = min(int(audio.frames / ratio), 300)

    batch = mp.cpu_count()
    bar = tqdm(total=total_vf, unit="frames")

    with mp.Pool(batch) as pool:
        for b0 in range(0, total_vf, batch):
            b1 = min(b0 + batch, total_vf)
            states, pcm_bufs = [], []
            for i in range(b0, b1):
                aud_idx = int(i * ratio)
                vis.update(1 / fps, audio.band_frame(aud_idx))
                states.append(vis.copy())

                s0 = int(i * smp_per_vf)
                pcm_bufs.append(audio.pcm_frame(s0, smp_per_vf))

            renders = pool.map(_render_job, [(s, density) for s in states])

            for i, (state, ro, pcm) in enumerate(zip(states, renders, pcm_bufs)):
                frame = state.present(ro)
                # Add the sun to the frame
                cx = density // 2
                cy = int(density * 0.5 + state.sun_off / density)
                cz = int(density * 2 * 0.9)
                frame.add(sun, cx - sun_n // 2, cy - sun_n // 2, cz - sun_n // 2)

                encoder.encode(frame, b0 + i)
                encoder.encode_audio(pcm)
            bar.update(b1 - b0)

    bar.close()
    encoder.finish()


if __name__ == "__main__":
    main()
