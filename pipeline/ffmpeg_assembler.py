"""
FFmpeg Automated Video Assembler
Inspired by MoneyPrinterTurbo post-production pipeline.
Merges individual shots into coherent cinematics with seamless transitions and audio handling.
"""

import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

log = logging.getLogger("ffmpeg_assembler")

CANDIDATE_FFMPEG_PATHS = [
    Path(r"D:\app\DataTool\resources\extraResources\ffmpeg.exe"),
    Path(r"D:\game\ACLOS\Cross\recorder-release\ffmpeg.exe"),
]


def find_ffmpeg() -> str:
    """Finds the best available ffmpeg binary."""
    for p in CANDIDATE_FFMPEG_PATHS:
        if p.exists():
            return str(p)
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    raise RuntimeError("FFmpeg executable not found! Please install or configure FFmpeg path.")


class FFmpegAssembler:
    """Automated post-production assembler using FFmpeg."""

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path or find_ffmpeg()
        log.info("FFmpegAssembler initialized with binary: %s", self.ffmpeg_path)

    def concat_fast(self, input_files: List[Path], output_file: Path) -> Path:
        """Rapid lossless concatenation using the concat demuxer."""
        if not input_files:
            raise ValueError("Input files list cannot be empty!")
        if len(input_files) == 1:
            shutil.copyfile(str(input_files[0]), str(output_file))
            return output_file

        output_file.parent.mkdir(parents=True, exist_ok=True)
        concat_list_file = output_file.parent / f"concat_{output_file.stem}.txt"

        lines = [f"file '{p.resolve().as_posix()}'" for p in input_files]
        concat_list_file.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-c", "copy",
            str(output_file)
        ]

        try:
            log.info("Running fast concat: %s", " ".join(cmd))
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return output_file
        except subprocess.CalledProcessError as e:
            log.warning("Fast concat failed (%s), falling back to re-encoding concat...", e.stderr[:300])
            return self.concat_reencode(input_files, output_file)
        finally:
            if concat_list_file.exists():
                try:
                    concat_list_file.unlink()
                except Exception:
                    pass

    def concat_reencode(self, input_files: List[Path], output_file: Path) -> Path:
        """Safe concatenation with video re-encoding (unifies fps, resolution, and timebases)."""
        output_file.parent.mkdir(parents=True, exist_ok=True)
        inputs_args: List[str] = []
        filter_inputs: List[str] = []

        for idx, f in enumerate(input_files):
            inputs_args.extend(["-i", str(f)])
            filter_inputs.append(f"[{idx}:v][{idx}:a]")

        # If files have audio or not
        # Create standard concat filter
        filter_str = "".join([f"[{i}:v]" for i in range(len(input_files))])
        filter_str += f"concat=n={len(input_files)}:v=1:a=0[outv]"

        cmd = [
            self.ffmpeg_path,
            "-y",
            *inputs_args,
            "-filter_complex", filter_str,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "18",
            str(output_file)
        ]

        log.info("Running re-encoding concat: %s", " ".join(cmd))
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return output_file

    def concat_with_crossfade(
        self,
        input_files: List[Path],
        output_file: Path,
        transition_duration: float = 0.5,
        shot_duration: float = 10.0
    ) -> Path:
        """Concatenates clips with cinema crossfade (xfade filter) between shots."""
        if len(input_files) < 2:
            return self.concat_fast(input_files, output_file)

        output_file.parent.mkdir(parents=True, exist_ok=True)

        inputs_args: List[str] = []
        for f in input_files:
            inputs_args.extend(["-i", str(f)])

        # Construct xfade filter chain:
        # [0:v][1:v]xfade=transition=fade:duration=0.5:offset=9.5[v01];
        # [v01][2:v]xfade=transition=fade:duration=0.5:offset=19.0[outv]
        filter_parts: List[str] = []
        last_stream = "[0:v]"
        curr_offset = shot_duration - transition_duration

        for i in range(1, len(input_files)):
            out_stream = f"[v_xfade_{i}]" if i < len(input_files) - 1 else "[outv]"
            filter_parts.append(
                f"{last_stream}[{i}:v]xfade=transition=fade:duration={transition_duration}:offset={curr_offset:.2f}{out_stream}"
            )
            last_stream = out_stream
            curr_offset += (shot_duration - transition_duration)

        filter_complex = ";".join(filter_parts)

        cmd = [
            self.ffmpeg_path,
            "-y",
            *inputs_args,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", "18",
            str(output_file)
        ]

        try:
            log.info("Running xfade crossfade concat...")
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return output_file
        except subprocess.CalledProcessError as e:
            log.warning("Crossfade failed (%s), falling back to fast concat...", e.stderr[:300])
            return self.concat_fast(input_files, output_file)

    def attach_audio(self, video_file: Path, audio_file: Path, output_file: Path, volume: float = 0.5) -> Path:
        """Attaches background music track to video with volume leveling and loop/trim."""
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", str(video_file),
            "-stream_loop", "-1",
            "-i", str(audio_file),
            "-filter_complex", f"[1:a]volume={volume}[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(output_file)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return output_file
