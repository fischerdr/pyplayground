# -*- coding: utf-8 -*-
"""Original Vaporwave video generator using spatialstudio.

This script is the original version of the Vaporwave video generator,
which uses the `spatialstudio` library for 3-D video encoding. It creates
a vaporwave-style video with audio-reactive 3D visualizations.

3‑D video example: https://www.splats.tv/watch/514
Tested with spatialstudio 1.1.0.41
This code is licensed under the MIT license.

Dependencies:
    pip install spatialstudio librosa noise tqdm numpy
"""

# 3‑D video example: https://www.splats.tv/watch/514
# Tested with spatialstudio 1.1.0.41
# pip install spatialstudio librosa noise tqdm
import copy
import hashlib
import math
import multiprocessing as mp
from typing import List, Tuple

import librosa
import numpy as np
from noise import pnoise2
from spatialstudio import splv
from tqdm import tqdm

# ────────────────────────── Utility ────────────────────────── #


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
    r = int((1 - t_local) * c1[0] + t_local * c2[0])
    g = int((1 - t_local) * c1[1] + t_local * c2[1])
    b = int((1 - t_local) * c1[2] + t_local * c2[2])
    return r, g, b


def sdf_triangle(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Signed distance function for a triangle.

    Args:
        p: Points to calculate the distance from.
        a: First vertex of the triangle.
        b: Second vertex of the triangle.
        c: Third vertex of the triangle.

    Returns:
        Array of distances from the points to the triangle.
    """
    ba, pa = b - a, p - a
    cb, pb = c - b, p - b
    ac, pc = a - c, p - c
    nor = np.cross(ba, ac)

    def dot2(v):
        return np.sum(v * v, axis=-1)

    sign = np.sign(np.sum(np.cross(ba, nor)[None] * pa, 1)) + np.sign(np.sum(np.cross(cb, nor)[None] * pb, 1)) + np.sign(np.sum(np.cross(ac, nor)[None] * pc, 1))
    outside = sign < 2
    ba_proj = np.clip(np.dot(pa, ba) / np.sum(ba * ba), 0.0, 1.0)
    cb_proj = np.clip(np.dot(pb, cb) / np.sum(cb * cb), 0.0, 1.0)
    ac_proj = np.clip(np.dot(pc, ac) / np.sum(ac * ac), 0.0, 1.0)
    d0 = dot2(ba[None] * ba_proj[:, None] - pa)
    d1 = dot2(cb[None] * cb_proj[:, None] - pb)
    d2 = dot2(ac[None] * ac_proj[:, None] - pc)
    dist_edge = np.minimum(np.minimum(d0, d1), d2)
    d_face = (np.dot(pa, nor) ** 2) / np.sum(nor * nor)
    return np.sqrt(np.where(outside, dist_edge, d_face))


def rasterize_triangle(
    density: Tuple[int, int, int],
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    spacing: int,
    z_off: float,
) -> np.ndarray:
    """Rasterize a triangle into a set of voxels.

    Args:
        density: Dimensions of the voxel grid.
        a: First vertex of the triangle.
        b: Second vertex of the triangle.
        c: Third vertex of the triangle.
        spacing: Spacing between voxels.
        z_off: Z-axis offset.

    Returns:
        Array of voxel coordinates within the triangle.
    """
    min_c = np.floor(np.min([a, b, c], 0)).astype(int)
    max_c = np.ceil(np.max([a, b, c], 0)).astype(int)
    xs, ys, zs = [np.arange(lo, hi + 1) for lo, hi in zip(min_c, max_c)]
    grid = np.stack(np.meshgrid(xs + 0.5, ys + 0.5, zs + 0.5, indexing="ij"), -1)
    points = grid.reshape(-1, 3)
    mask = sdf_triangle(points, a, b, c) < 0.5
    voxels = points[mask] - 0.5
    voxels[:, 2] -= z_off
    voxels = np.round(voxels).astype(int)

    w, h, d = density
    x, y, z = voxels.T
    in_bounds = (0 <= x) & (x < w) & (0 <= y) & (y < h) & (0 <= z) & (z < d)
    return voxels[in_bounds]


# ────────────────────────── Audio ────────────────────────── #


class AudioProcessor:
    """Audio processing and analysis for reactive visualizations."""

    def __init__(self, path: str, bands: int, sr: int = 44_100, hop: int = 512, thresh: float = 0.5):
        """Initialize the audio processor.

        Args:
            path: Path to the audio file.
            bands: Number of frequency bands for analysis.
            sr: Sample rate.
            hop: Hop length for STFT.
            thresh: Threshold for band activation.
        """
        self.sr, self.hop = sr, hop
        self.raw, _ = librosa.load(path, sr=sr)
        self.frames = 1 + len(self.raw) // hop
        mag = np.abs(librosa.stft(self.raw, hop_length=hop))
        basis = librosa.filters.mel(sr=sr, n_fft=mag.shape[0] * 2 - 2, n_mels=bands, fmin=50.0, fmax=20_000.0)
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

    def pcm_frame(self, start: int, n: int) -> List[int]:
        """Extract PCM audio data for a specific time range.

        Args:
            start: Starting sample index.
            n: Number of samples to extract.

        Returns:
            List of PCM audio samples.
        """
        buf = np.clip(self.raw[start : start + n], -1, 1)
        pcm = (buf * 32_767).astype(np.int16)
        return pcm.tolist()


# ────────────────────────── Visualiser ────────────────────────── #


class Visualizer:
    """3D visualizer for generating vaporwave-style visualizations."""

    def __init__(self, octaves: int = 4, scroll: float = 0.25, decay: float = 0.999):
        """Initialize the visualizer.

        Args:
            octaves: Number of noise octaves.
            scroll: Scroll speed.
            decay: Decay rate for audio-reactive weights.
        """
        self.z_off = 0.0
        self.sun_off = 0.0
        self.octaves = octaves
        self.weights = np.zeros(octaves)
        self.scroll = scroll
        self.decay = decay

    # 3‑D “vaporwave” sun
    def create_sun(self, n: int) -> splv.Frame:
        """Create a 3-D 'vaporwave' sun.

        Args:
            n: Size of the sun.

        Returns:
            A splv.Frame object representing the sun.
        """
        sun = splv.Frame(n, n, n)
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
                                interpolate_color([(255, 94, 0), (255, 42, 100), (180, 0, 255)], y_norm),
                            )
        return sun

    def update(self, dt: float, new_w: np.ndarray) -> None:
        """Update the visualizer state.

        Args:
            dt: Time delta.
            new_w: New audio-reactive weights.
        """
        self.weights -= self.weights * (1 - self.decay ** (1_000 * dt))
        self.weights = np.maximum(self.weights, new_w)
        self.z_off += np.mean(new_w) * dt * self.scroll
        self.sun_off -= dt * 30

    def copy(self) -> "Visualizer":
        """Create a deep copy of the visualizer.

        Returns:
            A deep copy of the visualizer instance.
        """
        c = copy.deepcopy(self)
        return c

    # height‑field → voxel indices
    def render(self, dims: Tuple[int, int, int]) -> Tuple[Tuple[int, int, int], np.ndarray, int, float]:
        """Render a height-field to voxel indices.

        Args:
            dims: Dimensions of the frame.

        Returns:
            A tuple containing dimensions, voxel data, spacing, and z-base.
        """
        w, h, d = dims
        spacing = int(min(w, d) / 25)
        noise_s = spacing
        v_size = 1 / np.array(dims)
        z_base = self.z_off * d
        min_z = (math.floor(z_base / spacing)) * spacing
        max_z = (math.ceil((z_base + d) / spacing)) * spacing
        vox = []

        def height(x, z):
            xn, zn = x / w, z / d
            n = 0
            for i in range(self.octaves):
                rand = int(hashlib.md5(f"{x}_{z}_{i}".encode()).hexdigest()[:2], 16)
                disable = rand < 180
                scale = noise_s ** (i + 1)
                octave = abs(pnoise2(xn * scale, zn * scale, base=i))
                n += octave * (0.75 if disable else self.weights[i]) * (0.25**i)
            return max(h * n * (math.cos(xn * 2 * math.pi) * 0.5 + 0.5), v_size[1] / 2)

        for x in range(0, w, spacing):
            for z in range(min_z, max_z, spacing):
                p0 = np.array([x, height(x, z), z])
                p1 = np.array([x + spacing, height(x + spacing, z), z])
                p2 = np.array([x, height(x, z + spacing), z + spacing])
                p3 = np.array([x + spacing, height(x + spacing, z + spacing), z + spacing])
                vox += [
                    rasterize_triangle(dims, p0, p1, p3, spacing, z_base),
                    rasterize_triangle(dims, p0, p3, p2, spacing, z_base),
                ]
        return dims, np.concatenate(vox), spacing, z_base

    def present(
        self,
        render_out: Tuple[Tuple[int, int, int], np.ndarray, int, float],
        sun_n: int,
        sun: splv.Frame,
    ) -> splv.Frame:
        """Present the rendered frame.

        Args:
            render_out: Output from the render method.
            sun_n: Size of the sun.
            sun: The sun frame.

        Returns:
            The final rendered frame.
        """
        dims, vox, spacing, z_base = render_out
        frame = splv.Frame(*dims)
        for x, y, z in vox:
            if int(z + z_base) % spacing == 0 or x % spacing == 0:
                col = interpolate_color([(25, 214, 252), (255, 20, 147), (232, 103, 23), (232, 224, 16)], y / dims[1])
            else:
                col = (0, 0, 0)
            frame.set_voxel(x, y, z, col)

        # sun
        cx = dims[0] // 2
        cy = int(dims[1] * 0.5 + self.sun_off / dims[1])
        cz = int(dims[2] * 0.9)
        frame.add(sun, cx - sun_n // 2, cy - sun_n // 2, cz - sun_n // 2)
        return frame


# ────────────────────────── Driver helpers ────────────────────────── #


def _render_job(
    args: Tuple[Visualizer, int],
) -> Tuple[Tuple[int, int, int], np.ndarray, int, float]:
    """Render job for parallel processing.

    Args:
        args: A tuple containing the visualizer and density.

    Returns:
        The output of the render method.
    """
    vis, n = args
    return vis.render((n, n, n * 2))


# ────────────────────────── Main ────────────────────────── #


def main() -> None:
    """Main function to generate the vaporwave video."""
    audio_path = "resonance.mp3"  # your audio here
    density = 128
    fps = 30.0
    octaves = 4
    sun_n = 64

    vis = Visualizer(octaves)
    audio = AudioProcessor(audio_path, octaves)
    sun = vis.create_sun(sun_n)

    encoder = splv.Encoder(
        width=density,
        height=density,
        depth=density * 2,
        framerate=fps,
        audioParams=(1, audio.sr, 2),
        gopSize=30,
        motionVectors="fast",
        vqRangeCutoff=0.05,
        vqMaxCentroids=255,
        outputPath="tmp/output/test.splv",
    )

    afps = audio.sr / audio.hop  # audio frames per second
    ratio = afps / fps  # audio‑to‑video frame ratio
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

            for state, ro, pcm in zip(states, renders, pcm_bufs):
                frame = state.present(ro, sun_n, sun)
                encoder.encode(frame)
                encoder.encode_audio(pcm)
            bar.update(b1 - b0)

    bar.close()
    encoder.finish()


if __name__ == "__main__":
    main()
