#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""Sci-fi hum generator for creating atmospheric audio backgrounds.

This module generates a sci-fi style hum sound that can be used as background
audio for vaporwave visualizations or other atmospheric effects. The hum consists
of multiple layered sine waves with modulation to create a futuristic sound.

Dependencies:
    pip install numpy scipy pydub
"""

import os

import numpy as np
from pydub import AudioSegment
from scipy import signal as sp_signal
from scipy.io.wavfile import write


def generate_sci_fi_hum(filename: str = "resonance.mp3", duration: int = 30, sample_rate: int = 44100) -> None:
    """Generate a sci-fi hum sound and save it as an MP3 file.

    This function creates a complex, layered sci-fi hum using multiple synthesis
    techniques including frequency modulation (FM), amplitude modulation (AM),
    filtered noise, and a reverb effect. The resulting audio has a futuristic,
    atmospheric quality suitable for background ambience.

    Args:
        filename: Output filename for the MP3 file. Defaults to "resonance.mp3".
        duration: Duration of the audio in seconds. Defaults to 30.
        sample_rate: Sample rate in Hz. Defaults to 44100.

    Returns:
        None. The audio is saved to the specified filename.

    Example:
        >>> generate_sci_fi_hum("my_hum.mp3", duration=60)
        Sci-fi hum saved to my_hum.mp3
    """
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # --- Synthesis Components ---

    # 1. Base hum and mid-tone
    base = np.sin(2 * np.pi * 60 * t) * 0.3
    mod1 = np.sin(2 * np.pi * 220 * t) * 0.15

    # 2. Frequency Modulated (FM) tone for vibrato effect
    fm_lfo = 5 * np.sin(2 * np.pi * 0.75 * t)  # LFO at 0.75 Hz
    fm_tone = np.sin(2 * np.pi * (440 + fm_lfo) * t) * 0.1

    # 3. Pulse modulation for a classic sci-fi feel
    pulse_mod = np.sin(2 * np.pi * (3 + 0.1 * np.sin(2 * np.pi * 0.25 * t)) * t) * 0.05

    # 4. Slow amplitude modulation for an evolving texture
    amp_lfo = 0.5 * (1 + np.sin(2 * np.pi * 0.1 * t))  # Slow LFO (0.1 Hz)
    evolving_tone = amp_lfo * np.sin(2 * np.pi * 330 * t) * 0.1

    # 5. Filtered noise for atmospheric texture
    noise = np.random.normal(0, 1, len(t))
    N = 100  # Moving average window size
    filtered_noise = np.convolve(noise, np.ones(N) / N, mode="same") * 0.05

    # --- Combine signals ---
    signal = base + mod1 + fm_tone + pulse_mod + evolving_tone + filtered_noise

    # 6. Reverb effect using a feedback comb filter
    delay_seconds = 0.4
    decay = 0.6
    delay_samples = int(delay_seconds * sample_rate)
    b = np.array([1.0])
    a = np.zeros(delay_samples)
    a[0] = 1
    a[-1] = decay
    output_signal = sp_signal.lfilter(b, a, signal)

    # --- Finalize ---
    output_signal = output_signal / np.max(np.abs(output_signal))  # Normalize

    wav_path = "resonance_temp.wav"
    write(wav_path, sample_rate, (output_signal * 32767).astype(np.int16))

    # Convert to MP3
    audio = AudioSegment.from_wav(wav_path)
    audio.export(filename, format="mp3")
    os.remove(wav_path)
    print(f"Sci-fi hum saved to {filename}")


if __name__ == "__main__":
    generate_sci_fi_hum()
