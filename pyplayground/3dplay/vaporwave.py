#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""Vaporwave video generator - a Python port of the original Vaporwave visualizer.

This is a port of the original Vaporwave video generator to Python.
The script generates a vaporwave-style video with audio-reactive 3D visualizations.

Original code: https://gist.github.com/DanielHabib/5a731da1ff423942d5c7b506d0c4f4f0

This code is licensed under the MIT license.

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

# ────────────────────────── Replacement for splv.Frame ────────────────────────── #


class Frame:
    """3D voxel frame representation for video generation.

    This class represents a 3D frame with voxel data that can be converted
    to 2D images for video encoding. It provides methods for setting voxels,
    combining frames, and converting to PIL images.
    """

    def __init__(self, width: int, height: int, depth: int) -> None:
        """Initialize a 3D frame with specified dimensions.

        Args:
            width: Width of the frame in voxels.
            height: Height of the frame in voxels.
            depth: Depth of the frame in voxels.
        """
        self.shape = (width, height, depth)
        self.data = np.zeros((width, height, depth, 3), dtype=np.uint8)

    def set_voxel(self, x: int, y: int, z: int, color: Tuple[int, int, int]) -> None:
        """Set a voxel at the specified position with the given color.

        Args:
            x: X coordinate of the voxel.
            y: Y coordinate of the voxel.
            z: Z coordinate of the voxel.
            color: RGB color tuple (r, g, b) with values 0-255.
        """
        if 0 <= x < self.shape[0] and 0 <= y < self.shape[1] and 0 <= z < self.shape[2]:
            self.data[x, y, z] = color

    def add(self, other: "Frame", ox: int, oy: int, oz: int) -> None:
        """Add another frame to this frame at the specified offset.

        Args:
            other: Frame to add to this frame.
            ox: X offset for positioning the other frame.
            oy: Y offset for positioning the other frame.
            oz: Z offset for positioning the other frame.
        """
        for x in range(other.shape[0]):
            for y in range(other.shape[1]):
                for z in range(other.shape[2]):
                    color = other.data[x, y, z]
                    if np.any(color):
                        self.set_voxel(x + ox, y + oy, z + oz, color)

    def to_image(self, axis: int = 2) -> Image.Image:
        """Convert the 3D frame to a 2D PIL image by taking the maximum along an axis.

        Args:
            axis: Axis along which to take the maximum (0=x, 1=y, 2=z).

        Returns:
            PIL Image object representing the 2D projection of the 3D frame.
        """
        slice_img = np.max(self.data, axis=axis)
        return Image.fromarray(slice_img, mode="RGB")


# ────────────────────────── Replacement for splv.Encoder ────────────────────────── #


class Encoder:
    """Video encoder for creating MP4 files from frames and audio.

    This class handles the encoding of individual frames to PNG files and
    combines them with audio to create a final MP4 video file using ffmpeg.
    """

    def __init__(self, output_dir: str, framerate: float) -> None:
        """Initialize the encoder with output directory and framerate.

        Args:
            output_dir: Directory where output files will be saved.
            framerate: Frames per second for the output video.
        """
        self.frames = []
        self.audio_pcm = []
        self.output_dir = output_dir
        self.fps = framerate
        os.makedirs(output_dir, exist_ok=True)

    def encode(self, frame: Frame, index: int) -> None:
        """Encode a single frame to a PNG file.

        Args:
            frame: Frame object to encode.
            index: Frame index for filename generation.
        """
        img = frame.to_image()
        path = f"{self.output_dir}/frame_{index:04d}.png"
        img.save(path)
        self.frames.append(path)

    def encode_audio(self, pcm_bytes: bytes) -> None:
        """Add PCM audio data to the encoder buffer.

        Args:
            pcm_bytes: Raw PCM audio bytes to be included in the final video.
        """
        self.audio_pcm.append(pcm_bytes)

    def finish(self) -> None:
        """Finalize the video encoding process.

        This method writes the audio file, uses ffmpeg to combine
        all frames and audio into a final MP4 video file, and then
        attempts to open the video with the default system player.
        """
        audio_path = os.path.join(self.output_dir, "audio.raw")
        with open(audio_path, "wb") as f:
            f.write(b"".join(self.audio_pcm))

        video_out = os.path.join(self.output_dir, "output.mp4")
        os.system(
            f"ffmpeg -framerate {self.fps} -i {self.output_dir}/frame_%04d.png "
            f"-f s16le -ar 44100 -ac 1 -i {audio_path} "
            f"-pix_fmt yuv420p -y {video_out}"
        )

        # Attempt to open the video with the default system player
        if os.path.exists(video_out):
            print(f"Video saved to {video_out}. Attempting to open...")
            try:
                system = platform.system()
                if system == "Darwin":  # macOS
                    subprocess.run(["open", video_out], check=True)
                elif system == "Windows":
                    os.startfile(video_out)  # type: ignore
                else:  # Linux and other UNIX-like systems
                    subprocess.run(["xdg-open", video_out], check=True)
            except (OSError, AttributeError):
                print(f"Could not open video automatically. Please open it from: {video_out}")
        else:
            print(f"Error: Output video not found at {video_out}")


# ────────────────────────── Audio ────────────────────────── #


class AudioProcessor:
    """Audio processing and analysis for reactive visualizations.

    This class handles loading audio files, performing spectral analysis,
    and providing audio-reactive data for the visualizer.
    """

    def __init__(
        self, path: str, bands: int, sr: int = 44100, hop: int = 512, thresh: float = 0.5
    ) -> None:
        """Initialize the audio processor with an audio file.

        Args:
            path: Path to the audio file to process.
            bands: Number of frequency bands for analysis.
            sr: Sample rate for audio processing.
            hop: Hop length for STFT analysis.
            thresh: Threshold for frequency band activation.
        """
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
        """Get frequency band data for a specific frame index.

        Args:
            idx: Frame index to retrieve band data for.

        Returns:
            Normalized frequency band activation values.
        """
        f = self.spec[:, idx]
        return np.where(f > self.thresh, (f - self.thresh) / (1 - self.thresh), 0)

    def pcm_frame(self, start: int, n: int) -> bytes:
        """Extract PCM audio data for a specific time range.

        Args:
            start: Starting sample index.
            n: Number of samples to extract.

        Returns:
            Raw PCM audio bytes for the specified time range.
        """
        buf = np.clip(self.raw[start : start + n], -1, 1)
        pcm = (buf * 32767).astype(np.int16)
        return pcm.tobytes()


# ────────────────────────── Visualizer ────────────────────────── #


def interpolate_color(colors: List[Tuple[int, int, int]], t: float) -> Tuple[int, int, int]:
    """Interpolate between colors based on a time parameter.

    Args:
        colors: List of RGB color tuples to interpolate between.
        t: Time parameter (0.0 to 1.0) for interpolation.

    Returns:
        Interpolated RGB color tuple.
    """
    t %= 1.0
    n = len(colors)
    t_scaled = t * n
    idx = int(t_scaled) % n
    t_local = t_scaled - idx
    c1, c2 = colors[idx], colors[(idx + 1) % n]
    return tuple(int((1 - t_local) * c1[i] + t_local * c2[i]) for i in range(3))


class Visualizer:
    """3D visualizer for generating vaporwave-style visualizations.

    This class creates 3D terrain-like visualizations using Perlin noise
    and audio-reactive parameters for dynamic effects.
    """

    def __init__(self, octaves: int = 4, scroll: float = 0.25, decay: float = 0.999) -> None:
        """Initialize the visualizer with noise and animation parameters.

        Args:
            octaves: Number of noise octaves for terrain generation.
            scroll: Scroll speed for the visualization.
            decay: Decay rate for audio-reactive weights.
        """
        self.z_off = 0.0
        self.sun_off = 0.0
        self.octaves = octaves
        self.weights = np.zeros(octaves)
        self.scroll = scroll
        self.decay = decay

    def create_sun(self, n: int) -> Frame:
        """Create a 3-D 'vaporwave' sun.

        Args:
            n: Size of the sun.

        Returns:
            A Frame object representing the sun.
        """
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
                            )
        return sun

    def update(self, dt: float, new_w: np.ndarray) -> None:
        """Update the visualizer state with new audio data.

        Args:
            dt: Time delta since last update.
            new_w: New audio-reactive weights for each octave.
        """
        self.weights -= self.weights * (1 - self.decay ** (1000 * dt))
        self.weights = np.maximum(self.weights, new_w)
        self.z_off += np.mean(new_w) * dt * self.scroll
        self.sun_off -= dt * 30

    def copy(self) -> "Visualizer":
        """Create a deep copy of the current visualizer state.

        Returns:
            Deep copy of the visualizer instance.
        """
        return copy.deepcopy(self)

    def render(self, dims: Tuple[int, int, int]) -> Tuple[Tuple[int, int, int], Frame, int, float]:
        """Render a 3D frame with the current visualizer state.

        Args:
            dims: Dimensions (width, height, depth) for the frame.

        Returns:
            Tuple containing (dims, frame, spacing, z_base) for rendering.
        """
        w, h, d = dims
        spacing = int(min(w, d) / 25)
        v_size = 1 / np.array(dims)
        z_base = self.z_off * d
        min_z = (math.floor(z_base / spacing)) * spacing
        max_z = (math.ceil((z_base + d) / spacing)) * spacing

        def height(x: int, z: int) -> float:
            """Calculate terrain height at a given position.

            Args:
                x: X coordinate.
                z: Z coordinate.

            Returns:
                Height value for the terrain at the given position.
            """
            xn, zn = x / w, z / d
            n = 0
            for i in range(self.octaves):
                rand = int(hashlib.md5(f"{x}_{z}_{i}".encode()).hexdigest()[:2], 16)
                disable = rand < 180
                scale = spacing ** (i + 1)
                octave = abs(pnoise2(xn * scale, zn * scale, base=i))
                n += octave * (0.75 if disable else self.weights[i]) * (0.25**i)
            return max(h * n * (math.cos(xn * 2 * math.pi) * 0.5 + 0.5), v_size[1] / 2)

        frame = Frame(*dims)
        for x in range(0, w, spacing):
            for z in range(min_z, max_z, spacing):
                y = int(height(x, z))
                col = interpolate_color(
                    [(25, 214, 252), (255, 20, 147), (232, 103, 23), (232, 224, 16)], y / h
                )
                frame.set_voxel(x, y, int(z - z_base), col)
        return dims, frame, spacing, z_base

    def present(self, render_out: Tuple[Tuple[int, int, int], Frame, int, float]) -> Frame:
        """Extract the frame from render output.

        Args:
            render_out: Output from the render method.

        Returns:
            Rendered frame object.
        """
        _, frame, _, _ = render_out
        return frame


# ────────────────────────── Worker and Main ────────────────────────── #


def _render_job(args: Tuple[Visualizer, int]) -> Tuple[Tuple[int, int, int], Frame, int, float]:
    """Worker function for parallel rendering.

    Args:
        args: Tuple containing (visualizer, density) for rendering.

    Returns:
        Render output tuple from the visualizer.
    """
    vis, n = args
    return vis.render((n, n, n * 2))


def verify_dir(dir: str) -> None:
    """Verify that a directory exists and create it if it doesn't.

    Args:
        dir: Directory to verify.
    """
    if not os.path.exists(dir):
        os.makedirs(dir)


def main() -> None:
    """Main function to generate a vaporwave video from audio.

    This function orchestrates the entire video generation process:
    1. Loads and processes audio
    2. Creates visualizer and encoder instances
    3. Renders frames in parallel
    4. Combines everything into a final MP4 video
    """
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
