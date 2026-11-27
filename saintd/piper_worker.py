"""Piper in its own process, for saintd's reader.

One JSON request per line on stdin, one JSON answer per line on stdout:

    {"model": "/path/en_GB-alan-medium.onnx", "text": "...", "out": "/tmp/x.wav", "length_scale": 1.0}
    {"load": "/path/en_GB-alan-medium.onnx"}            (load a voice ahead of time)

The loaded voices are kept between requests. Running apart from the app keeps
onnxruntime's messages off the screen the app draws, and the app smooth while
the voice is being computed (this process runs at a lower priority).
"""

from __future__ import annotations

import json
import os
import sys
import wave


def main() -> int:
    try:
        os.nice(5)                                 # Windows has no nice(): saintd starts it at a lower priority
    except (OSError, AttributeError):
        pass
    try:
        import onnxruntime
        onnxruntime.set_default_logger_severity(3)
    except Exception:
        pass
    from piper import PiperVoice
    try:
        from piper import SynthesisConfig          # piper-tts 1.3 and later
    except ImportError:                            # pragma: no cover - older piper-tts
        SynthesisConfig = None

    voices: dict[str, object] = {}

    def voice(model: str):
        if model not in voices:
            voices.clear()                         # one voice at a time keeps the memory small
            voices[model] = PiperVoice.load(model)
        return voices[model]

    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if "load" in req:
                voice(req["load"])
                ans = {"ok": True}
            else:
                v = voice(req["model"])
                scale = float(req.get("length_scale") or 1.0)
                with wave.open(req["out"], "wb") as wf:
                    if SynthesisConfig is not None:
                        v.synthesize_wav(req["text"], wf, syn_config=SynthesisConfig(length_scale=scale))
                    else:                          # pragma: no cover
                        v.synthesize(req["text"], wf, length_scale=scale)
                ans = {"ok": True}
        except Exception as e:                     # report, and keep serving
            ans = {"ok": False, "error": f"{e.__class__.__name__}: {e}"[:300]}
        out.write(json.dumps(ans) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
