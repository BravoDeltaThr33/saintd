"""Reading aloud: text-to-speech engines, their voices, audio players and the
reader that speaks a saint's life paragraph by paragraph.

Engines, best first ("Automatic" takes the first one that works):

* Piper — natural neural voices, offline (Python package ``piper-tts``; the
  voices are downloaded on request into the voices folder of saintd's data).
* macOS: the system's own voices (``say``).
* Windows: the system's own voices (SAPI, through Windows PowerShell).
* Linux: RHVoice — good classic voices (apt: rhvoice rhvoice-english).
* Linux: SVOX Pico — clear, small voices (apt: libttspico-utils).
* eSpeak NG — robotic but light (apt: espeak-ng; Homebrew; the Windows installer).
* Linux: Speech Dispatcher — the desktop's own speech service (spd-say).
* Linux: Festival — the classic Edinburgh system (apt: festival).

Every engine except Speech Dispatcher is turned into WAV audio first and then
played with the first player that works (Linux: pw-play, paplay, aplay; macOS:
afplay; Windows: Python's winsound; anywhere: ffplay, mpv, play). Playing from
a file lets the reader pause in the middle of a sentence and prepare the next
paragraph while the current one is heard.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import system
from .config import TTS_ENGINES, cache_dir, data_dir


class TTSError(Exception):
    pass


@dataclass
class Voice:
    id: str
    label: str
    note: str = ""
    installed: bool = True
    size: int = 0                 # bytes to download (Piper voices not yet on this computer)


ENGINE_ORDER = list(TTS_ENGINES)            # the engines this kind of computer can have, best first
ENGINE_CHOICES = ["auto", *ENGINE_ORDER]
RATES = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.75]
SAMPLE = "Holy Apostle Cleopas, pray to God for us. This is how the lives of the saints will sound."

_QUIET = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}

# what to install when nothing can play the audio, or nothing can speak
PLAYER_INSTALL = system.pick("sudo apt install pipewire-bin (or pulseaudio-utils)",
                             "afplay comes with macOS; or brew install ffmpeg",
                             "install ffmpeg or mpv")
NO_ENGINE = system.pick("No speech engine was found. Install one, e.g.  sudo apt install espeak-ng  — "
                        "or Piper for natural voices (Settings → Voice & Reading aloud).",
                        "No speech engine was found. Install Piper for natural voices "
                        "(Settings → Voice & Reading aloud).",
                        "No speech engine was found. Install Piper for natural voices "
                        "(Settings → Voice & Reading aloud).")
# the English of a voice, from its language code
_ENGLISH = {"en_US": "American English", "en_GB": "British English", "en_AU": "Australian English",
            "en_IE": "Irish English", "en_IN": "Indian English", "en_ZA": "South African English",
            "en_SC": "Scottish English", "en_NZ": "New Zealand English", "en_CA": "Canadian English"}


def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _run(cmd: list[str], text: str | None = None, timeout: float = 120,
         env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, input=text.encode("utf-8") if text is not None else None,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env,
                              **system.detached())
    except subprocess.TimeoutExpired as e:
        raise TTSError(f"{Path(cmd[0]).name} took too long") from e
    except OSError as e:
        raise TTSError(f"{Path(cmd[0]).name} could not be started: {e}") from e


def _check_wav(path: Path, what: str) -> None:
    try:
        with wave.open(str(path)) as w:
            if w.getnframes() <= 0:
                raise TTSError(f"{what} produced no audio")
    except (OSError, EOFError, wave.Error) as e:
        raise TTSError(f"{what} produced no audio") from e


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


# ---------------------------------------------------------------- engines

class Engine:
    id = ""
    label = ""
    blurb = ""
    install = ""                  # how to get it on this kind of computer
    direct = False                # speaks by itself instead of making WAV audio
    _voices: list[Voice] | None = None

    def available(self) -> bool:
        return False

    def voices(self) -> list[Voice]:
        if self._voices is None:
            try:
                self._voices = self._list_voices() if self.available() else []
            except Exception:
                self._voices = []
        return self._voices

    def forget(self) -> None:
        """Forget the cached voice list (a voice was downloaded or deleted)."""
        self._voices = None

    def _list_voices(self) -> list[Voice]:
        return []

    def default_voice(self) -> str:
        installed = [v for v in self.voices() if v.installed]
        return installed[0].id if installed else ""

    def voice_label(self, voice_id: str) -> str:
        for v in self.voices():
            if v.id == voice_id:
                return v.label
        return voice_id or "default voice"

    def synth(self, text: str, voice: str, rate: float, out: Path) -> None:
        raise TTSError(f"{self.label} cannot make audio files")

    def say(self, text: str, voice: str, rate: float) -> subprocess.Popen:
        raise TTSError(f"{self.label} cannot speak directly")

    def cancel(self) -> None:
        pass


# -- Piper --------------------------------------------------------

PIPER_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"

# English voices worth suggesting, with a word about each; the first ones are offered first.
PIPER_VOICES: dict[str, tuple[str, str]] = {
    "en_GB-alan-medium": ("Alan", "British English, male"),
    "en_US-ryan-high": ("Ryan", "American English, male, high quality"),
    "en_GB-cori-high": ("Cori", "British English, female, high quality"),
    "en_US-lessac-medium": ("Lessac", "American English, female"),
    "en_GB-northern_english_male-medium": ("Northern English", "British English, male"),
    "en_US-john-medium": ("John", "American English, male, deep"),
    "en_US-norman-medium": ("Norman", "American English, male, older"),
    "en_GB-jenny_dioco-medium": ("Jenny", "British English, female"),
    "en_US-joe-medium": ("Joe", "American English, male"),
    "en_US-amy-medium": ("Amy", "American English, female"),
    "en_US-kristin-medium": ("Kristin", "American English, female"),
    "en_US-ryan-medium": ("Ryan", "American English, male"),
    "en_US-lessac-high": ("Lessac", "American English, female, high quality"),
    "en_GB-alba-medium": ("Alba", "Scottish English, female"),
    "en_US-hfc_male-medium": ("HFC male", "American English, male"),
    "en_US-hfc_female-medium": ("HFC female", "American English, female"),
    "en_US-bryce-medium": ("Bryce", "American English, male"),
    "en_US-ljspeech-high": ("LJ Speech", "American English, female, high quality"),
    "en_GB-cori-medium": ("Cori", "British English, female"),
    "en_GB-southern_english_female-low": ("Southern English", "British English, female, small"),
    "en_GB-alan-low": ("Alan", "British English, male, small"),
    "en_US-amy-low": ("Amy", "American English, female, small"),
}
_APPROX_SIZE = {"x_low": 28_000_000, "low": 63_000_000, "medium": 63_000_000, "high": 114_000_000}


def voices_dir() -> Path:
    p = data_dir() / "voices"
    p.mkdir(parents=True, exist_ok=True)
    return p


def piper_quality(key: str) -> str:
    return key.rsplit("-", 1)[-1] if "-" in key else ""


def piper_files(key: str, catalog: dict | None = None) -> list[tuple[str, int, str]]:
    """(path in the voices repository, size, md5) of a voice's model and its settings."""
    entry = (catalog or {}).get(key)
    if entry and entry.get("files"):
        out = [(p, int(f.get("size_bytes") or 0), f.get("md5_digest") or "")
               for p, f in entry["files"].items() if p.endswith((".onnx", ".onnx.json"))]
        if len(out) == 2:
            return sorted(out, key=lambda x: x[0].endswith(".onnx"))      # the small settings file first
    m = re.match(r"^([a-z]+)_([A-Z]+)-(.+)-([a-z_]+)$", key)
    if not m:
        raise TTSError(f"not a Piper voice name: {key}")
    fam, region, name, quality = m.groups()
    base = f"{fam}/{fam}_{region}/{name}/{quality}/{key}"
    return [(base + ".onnx.json", 5000, ""), (base + ".onnx", _APPROX_SIZE.get(quality, 63_000_000), "")]


def piper_catalog(http_get: Callable[[str], bytes] | None = None, max_age: float = 30 * 86400) -> dict:
    """The list of Piper voices (Hugging Face's voices.json), kept for a month."""
    path = cache_dir() / "piper-voices.json"
    try:
        if path.exists() and time.time() - path.stat().st_mtime < max_age:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if http_get is None:
        http_get = _http_get
    try:
        data = json.loads(http_get(PIPER_HF + "voices.json?download=true"))
        if isinstance(data, dict) and data:
            path.write_text(json.dumps(data), encoding="utf-8")
            return data
    except Exception:
        pass
    try:
        return json.loads(path.read_text(encoding="utf-8"))          # an old copy is better than none
    except (OSError, ValueError):
        return {}


def _http_get(url: str) -> bytes:
    import httpx
    with httpx.Client(follow_redirects=True, timeout=30) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.content


def download_piper_voice(key: str, progress: Callable[[int, int], None] = lambda d, t: None,
                         stop: threading.Event | None = None, catalog: dict | None = None) -> Path:
    """Download a Piper voice (model + settings) into the voices folder."""
    import httpx
    files = piper_files(key, catalog)
    total = sum(size for _, size, _ in files)
    done = 0
    dest_dir = voices_dir()
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, read=60)) as c:
        for rel, size, md5 in files:
            name = rel.rsplit("/", 1)[-1]
            dest = dest_dir / name
            tmp = dest.with_suffix(dest.suffix + ".part")
            h = hashlib.md5()
            try:
                with c.stream("GET", PIPER_HF + rel + "?download=true") as r:
                    if r.status_code != 200:
                        raise TTSError(f"the voice server answered {r.status_code}")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(1 << 16):
                            if stop is not None and stop.is_set():
                                raise TTSError("download cancelled")
                            f.write(chunk)
                            h.update(chunk)
                            done += len(chunk)
                            progress(done, max(total, done))
                if md5 and h.hexdigest() != md5:
                    raise TTSError(f"{name} arrived damaged; please try again")
                os.replace(tmp, dest)
            except httpx.HTTPError as e:
                raise TTSError(f"could not download {name}: {e.__class__.__name__}") from e
            finally:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
    return dest_dir / f"{key}.onnx"


def delete_piper_voice(key: str) -> None:
    if system.WINDOWS:
        _piper_worker.close()                   # Windows cannot delete a voice that is loaded
    for suffix in (".onnx", ".onnx.json"):
        try:
            (voices_dir() / f"{key}{suffix}").unlink(missing_ok=True)
        except OSError as e:
            raise TTSError(f"could not delete {key}{suffix}: {e.strerror or e}") from e


class _PiperWorker:
    """Piper runs in its own process (python -m saintd.piper_worker): the voice
    stays loaded between paragraphs, and onnxruntime can never print over the
    screen the app draws."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def _ensure(self) -> subprocess.Popen:
        if self.proc is None or self.proc.poll() is not None:
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", ORT_LOGGING_LEVEL="3")
            self.proc = subprocess.Popen([sys.executable, "-m", "saintd.piper_worker"], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                         encoding="utf-8", bufsize=1, env=env,
                                         **system.detached(low_priority=True))
        return self.proc

    def request(self, req: dict) -> dict:
        with self.lock:
            proc = self._ensure()
            try:
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
            except (OSError, ValueError):
                line = ""
            if not line:
                self.close()
                raise TTSError("Piper stopped unexpectedly")
            try:
                return json.loads(line)
            except ValueError:
                return {"ok": False, "error": line.strip()[:120]}

    def close(self) -> None:
        p, self.proc = self.proc, None
        if p is not None and p.poll() is None:
            try:
                p.kill()
                p.wait(timeout=2)
            except Exception:
                pass


_piper_worker = _PiperWorker()


class PiperEngine(Engine):
    id = "piper"
    label = "Piper (natural neural voices)"
    blurb = "Natural-sounding voices that run on this computer, no internet needed once a voice is downloaded."
    install = system.pick("pipx inject saint-directory piper-tts", "pipx inject saint-directory piper-tts",
                          "press Install Piper below")

    def available(self) -> bool:
        return importlib.util.find_spec("piper") is not None

    def installed_keys(self) -> list[str]:
        d = voices_dir()
        return sorted(p.name[:-5] for p in d.glob("*.onnx") if (d / (p.name + ".json")).exists())

    def _list_voices(self) -> list[Voice]:
        out: list[Voice] = []
        have = self.installed_keys()
        order = list(PIPER_VOICES) + [k for k in have if k not in PIPER_VOICES]
        for key in order:
            name, note = PIPER_VOICES.get(key, (key.split("-")[1].replace("_", " ").title(), key.split("-")[0]))
            q = piper_quality(key)
            label = f"{name} — {note}" + (f" ({q})" if q and "quality" not in note and "small" not in note else "")
            size = sum(s for _, s, _ in piper_files(key)) if key not in have else 0
            out.append(Voice(key, label, note, installed=key in have, size=size))
        return sorted(out, key=lambda v: not v.installed)

    def synth(self, text: str, voice: str, rate: float, out: Path) -> None:
        if not self.available():
            raise TTSError("Piper is not installed")
        model = voices_dir() / f"{voice}.onnx"
        if not voice or not model.exists():
            raise TTSError("this Piper voice is not downloaded yet")
        ans = _piper_worker.request({"model": str(model), "text": text, "out": str(out),
                                     "length_scale": round(1.0 / max(0.3, rate), 3)})
        if not ans.get("ok"):
            raise TTSError(f"Piper: {ans.get('error', 'failed')}")
        _check_wav(out, "Piper")

    def preload(self, voice: str) -> None:
        model = voices_dir() / f"{voice}.onnx"
        if self.available() and model.exists():
            try:
                _piper_worker.request({"load": str(model)})
            except TTSError:
                pass


# -- RHVoice --------------------------------------------------------

_RHVOICE_DIRS = ["/usr/share/RHVoice/voices", "/usr/local/share/RHVoice/voices",
                 str(Path.home() / ".local/share/RHVoice/voices")]
_RHVOICE_NOTES = {"alan": "Scottish English, male", "bdl": "American English, male", "clb": "American English, female",
                  "slt": "American English, female", "evgeniy-eng": "English with a Russian accent, male",
                  "lyubov": "English with a Russian accent, female"}


class RHVoiceEngine(Engine):
    id = "rhvoice"
    label = "RHVoice"
    blurb = "Clear classic voices; small and quick."
    install = "sudo apt install rhvoice rhvoice-english"

    def available(self) -> bool:
        return _which("RHVoice-test") is not None

    def _list_voices(self) -> list[Voice]:
        out = []
        for d in _RHVOICE_DIRS:
            base = Path(d)
            if not base.is_dir():
                continue
            for v in sorted(base.iterdir()):
                info = {}
                try:
                    for line in (v / "voice.info").read_text(encoding="utf-8", errors="replace").splitlines():
                        k, _, val = line.partition("=")
                        info[k.strip()] = val.strip()
                except OSError:
                    continue
                if info.get("language", "").lower() != "english":
                    continue
                vid = v.name
                if any(x.id == vid for x in out):
                    continue
                note = _RHVOICE_NOTES.get(vid.lower(), f"English, {info.get('gender', '')}".rstrip(", "))
                name = info.get("name", vid)
                name = name.upper() if len(name) <= 3 else name.title()
                out.append(Voice(vid, f"{name} — {note}", note))
        return out

    def synth(self, text: str, voice: str, rate: float, out: Path) -> None:
        cmd = [_which("RHVoice-test") or "RHVoice-test", "-r", str(int(round(100 * rate))), "-o", str(out)]
        if voice:
            cmd[1:1] = ["-p", voice]
        r = _run(cmd, text)
        if r.returncode != 0:
            raise TTSError(f"RHVoice: {r.stderr.decode('utf-8', 'replace').strip()[:100] or 'failed'}")
        _check_wav(out, "RHVoice")


# -- Pico -----------------------------------------------------------

class PicoEngine(Engine):
    id = "pico"
    label = "SVOX Pico"
    blurb = "A small, clear female voice (British or American)."
    install = "sudo apt install libttspico-utils"

    def available(self) -> bool:
        return _which("pico2wave") is not None

    def _list_voices(self) -> list[Voice]:
        return [Voice("en-GB", "British English — female", "British English, female"),
                Voice("en-US", "American English — female", "American English, female")]

    def synth(self, text: str, voice: str, rate: float, out: Path) -> None:
        body = text.replace("<", " ").replace(">", " ")
        if abs(rate - 1.0) > 0.01:
            body = f'<speed level="{int(round(100 * rate))}">{body}</speed>'
        r = _run([_which("pico2wave") or "pico2wave", "-l", voice or "en-GB", "-w", str(out), body])
        if r.returncode != 0:
            raise TTSError("Pico could not speak this text")
        _check_wav(out, "Pico")


# -- eSpeak NG -----------------------------------------------------

class EspeakEngine(Engine):
    id = "espeak"
    label = "eSpeak NG"
    blurb = "Robotic, but quick and light; many accents."
    install = system.pick("sudo apt install espeak-ng", "brew install espeak-ng",
                          "the eSpeak NG installer (github.com/espeak-ng/espeak-ng/releases)")

    def _bin(self) -> str | None:
        found = _which("espeak-ng", "espeak")
        if found or not system.WINDOWS:
            return found
        for var in ("ProgramFiles", "ProgramFiles(x86)"):        # its installer does not add it to PATH
            exe = Path(os.environ.get(var) or "C:/Program Files") / "eSpeak NG" / "espeak-ng.exe"
            if exe.is_file():
                return str(exe)
        return None

    def available(self) -> bool:
        return self._bin() is not None

    def _list_voices(self) -> list[Voice]:
        r = _run([self._bin() or "espeak-ng", "--voices=en"], timeout=15)
        out: list[Voice] = []
        for line in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
            parts = line.split()
            if len(parts) < 5 or not parts[4].startswith(("gmw/", "en")):
                continue                              # mbrola voices need extra programs
            lang, name = parts[1], parts[3].replace("_", " ")
            if any(v.id == lang for v in out):
                continue
            out.append(Voice(lang, f"{name} — male", "male"))
            out.append(Voice(f"{lang}+f3", f"{name} — female", "female"))
        if not out:
            out = [Voice("en", "English — male", "male"), Voice("en+f3", "English — female", "female")]
        return sorted(out, key=lambda v: (not v.id.startswith("en-gb"), not v.id.startswith("en-us"),
                                          v.id.split("+")[0], "+" in v.id))

    def synth(self, text: str, voice: str, rate: float, out: Path) -> None:
        r = _run([self._bin() or "espeak-ng", "-v", voice or "en-gb", "-s", str(int(round(165 * rate))),
                  "-w", str(out), "--stdin"], text)
        if r.returncode != 0:
            raise TTSError("eSpeak could not speak this text")
        _check_wav(out, "eSpeak")


# -- Festival --------------------------------------------------------

class FestivalEngine(Engine):
    id = "festival"
    label = "Festival"
    blurb = "The classic Edinburgh speech system."
    install = "sudo apt install festival"

    def available(self) -> bool:
        return _which("text2wave") is not None

    def _list_voices(self) -> list[Voice]:
        names: list[str] = []
        if _which("festival"):
            r = _run(["festival", "--pipe"], "(print (voice.list))\n", timeout=20)
            m = re.search(r"\(([^()]*)\)", r.stdout.decode("utf-8", "replace"))
            if m:
                names = m.group(1).split()
        return [Voice(n, n.replace("_", " ")) for n in names] or [Voice("", "default voice")]

    def synth(self, text: str, voice: str, rate: float, out: Path) -> None:
        cmd = [_which("text2wave") or "text2wave", "-o", str(out)]
        if voice and re.fullmatch(r"[\w-]+", voice):
            cmd += ["-eval", f"(voice_{voice})"]
        if abs(rate - 1.0) > 0.01:
            cmd += ["-eval", f"(Parameter.set 'Duration_Stretch {1.0 / max(0.3, rate):.3f})"]
        r = _run(cmd, text)
        if r.returncode != 0:
            raise TTSError("Festival could not speak this text")
        _check_wav(out, "Festival")


# -- Speech Dispatcher ----------------------------------------------

class SpeechDispatcherEngine(Engine):
    id = "speechd"
    label = "Speech Dispatcher (system voice)"
    blurb = "The desktop's speech service; uses whatever voices it is set up with."
    install = "sudo apt install speech-dispatcher"
    direct = True

    def available(self) -> bool:
        return _which("spd-say") is not None

    def _list_voices(self) -> list[Voice]:
        out = [Voice("", "The system's default voice")]
        try:
            r = _run(["spd-say", "-O"], timeout=8)
        except TTSError:
            return out
        modules = [m.strip() for m in r.stdout.decode("utf-8", "replace").splitlines()[1:] if m.strip()]
        for mod in modules[:6]:
            try:
                rr = _run(["spd-say", "-o", mod, "-L"], timeout=8)
            except TTSError:
                continue
            for line in rr.stdout.decode("utf-8", "replace").splitlines()[1:]:
                cols = re.split(r"\s{2,}", line.strip())
                if len(cols) >= 2 and cols[1].lower().startswith("en"):
                    vid = f"{mod}|{cols[0]}"
                    if not any(v.id == vid for v in out):
                        out.append(Voice(vid, f"{cols[0]} ({mod})"))
                if len(out) > 60:
                    break
        return out

    def default_voice(self) -> str:
        return ""                                 # the service's own default (no need to ask it for a list)

    def voice_label(self, voice_id: str) -> str:
        if not voice_id:
            return "the system's default voice"
        mod, _, name = voice_id.partition("|")
        return f"{name} ({mod})" if name else voice_id

    def say(self, text: str, voice: str, rate: float) -> subprocess.Popen:
        cmd = ["spd-say", "-w", "-r", str(max(-100, min(100, int(round((rate - 1.0) * 100)))))]
        if voice:
            mod, _, name = voice.partition("|")
            if mod:
                cmd += ["-o", mod]
            if name:
                cmd += ["-y", name]
        cmd += ["--", text]
        try:
            return subprocess.Popen(cmd, start_new_session=True, **_QUIET)
        except OSError as e:
            raise TTSError(f"spd-say could not be started: {e}") from e

    def cancel(self) -> None:
        try:
            subprocess.run(["spd-say", "-C"], timeout=5, **_QUIET)
        except Exception:
            pass


# -- macOS: say -------------------------------------------------------

# the novelty voices of macOS (bells, bubbles, a whisper...) are not for reading the lives of the saints
_SAY_NOVELTY = {"Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Deranged", "Fred",
                "Good News", "Hysterical", "Jester", "Junior", "Kathy", "Organ", "Pipe Organ", "Princess",
                "Ralph", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox"}


class SayEngine(Engine):
    id = "say"
    label = "macOS voices"
    blurb = "The voices that come with macOS (System Settings → Accessibility → Spoken Content adds more)."
    install = "comes with macOS"

    def available(self) -> bool:
        return system.MACOS and _which("say") is not None

    def _list_voices(self) -> list[Voice]:
        out = [Voice("", "The system voice (System Settings → Accessibility → Spoken Content)")]
        r = _run(["say", "-v", "?"], timeout=15)
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            # "Daniel              en_GB    # Hello! My name is Daniel."  (names may hold spaces and brackets)
            m = re.match(r"^(.+?)\s+([a-z]{2,3}[_-][A-Za-z0-9]+)\s+#", line)
            if not m:
                continue
            name, lang = m.group(1).strip(), m.group(2).replace("-", "_")
            if not lang.startswith("en_") or name.split(" (")[0] in _SAY_NOVELTY or any(v.id == name for v in out):
                continue
            note = _ENGLISH.get(lang, "English")
            out.append(Voice(name, f"{name} — {note}", note))
        return out

    def default_voice(self) -> str:
        return ""                                 # the voice chosen in System Settings

    def voice_label(self, voice_id: str) -> str:
        return super().voice_label(voice_id) if voice_id else "the system voice"

    def synth(self, text: str, voice: str, rate: float, out: Path) -> None:
        cmd = ["say", "-o", str(out), "--data-format=LEI16@22050", "-f", "-"]
        if voice:
            cmd[1:1] = ["-v", voice]
        if abs(rate - 1.0) > 0.01:
            cmd[1:1] = ["-r", str(int(round(180 * rate)))]          # words a minute
        r = _run(cmd, text)
        if r.returncode != 0:
            raise TTSError(f"say: {r.stderr.decode('utf-8', 'replace').strip()[:100] or 'failed'}")
        _check_wav(out, "macOS speech")


# -- Windows: SAPI ----------------------------------------------------

# System.Speech is part of Windows PowerShell 5.1 (not of the newer pwsh). Values come in through the
# environment and the text through a UTF-8 file, so no quoting can go wrong.
_SAPI = ("$ErrorActionPreference = 'Stop'; Add-Type -AssemblyName System.Speech; "
         "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; ")
_SAPI_LIST = _SAPI + ("foreach ($v in $s.GetInstalledVoices()) { if ($v.Enabled) { $i = $v.VoiceInfo; "
                      "[Console]::Out.WriteLine($i.Name + '|' + $i.Culture.Name + '|' + $i.Gender) } }")
_SAPI_SPEAK = _SAPI + ("if ($env:SAINTD_TTS_VOICE) { $s.SelectVoice($env:SAINTD_TTS_VOICE) }; "
                       "$s.Rate = [int]$env:SAINTD_TTS_RATE; $s.SetOutputToWaveFile($env:SAINTD_TTS_OUT); "
                       "$s.Speak([IO.File]::ReadAllText($env:SAINTD_TTS_TEXT, [Text.Encoding]::UTF8)); "
                       "$s.Dispose()")


def _powershell() -> str | None:
    p = _which("powershell")
    if p or not system.WINDOWS:
        return p
    exe = Path(os.environ.get("SystemRoot") or "C:/Windows") / "System32" / "WindowsPowerShell" / "v1.0" / \
        "powershell.exe"
    return str(exe) if exe.is_file() else None


def _sapi_name(voice_id: str) -> str:
    """'Microsoft Zira Desktop' -> 'Zira'"""
    return re.sub(r"^Microsoft\s+|\s+Desktop$", "", voice_id)


class SapiEngine(Engine):
    id = "sapi"
    label = "Windows voices"
    blurb = "The voices that come with Windows, such as David and Zira."
    install = "comes with Windows (Windows PowerShell)"

    def available(self) -> bool:
        return system.WINDOWS and _powershell() is not None

    def _ps(self, script: str, timeout: float = 120, env: dict | None = None) -> subprocess.CompletedProcess:
        return _run([_powershell() or "powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                    timeout=timeout, env=env)

    def _list_voices(self) -> list[Voice]:
        out = [Voice("", "The Windows default voice")]
        r = self._ps(_SAPI_LIST, timeout=60)
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            parts = line.strip().split("|")
            if len(parts) != 3 or not parts[1].lower().startswith("en") or any(v.id == parts[0] for v in out):
                continue
            name, culture, gender = parts
            note = _ENGLISH.get(culture.replace("-", "_"), "English") + (
                f", {gender.lower()}" if gender.lower() in ("male", "female") else "")
            out.append(Voice(name, f"{_sapi_name(name)} — {note}", note))
        return out

    def default_voice(self) -> str:
        return ""                                 # the voice chosen in Windows Settings

    def voice_label(self, voice_id: str) -> str:
        return _sapi_name(voice_id) if voice_id else "the Windows default voice"

    def synth(self, text: str, voice: str, rate: float, out: Path) -> None:
        src = out.with_suffix(".txt")
        src.write_text(text, encoding="utf-8")
        speed = max(-10, min(10, round(10 * math.log(max(0.1, rate)) / math.log(3))))   # 10 = three times as fast
        env = dict(os.environ, SAINTD_TTS_TEXT=str(src), SAINTD_TTS_OUT=str(out), SAINTD_TTS_VOICE=voice or "",
                   SAINTD_TTS_RATE=str(speed))
        r = self._ps(_SAPI_SPEAK, env=env)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip().splitlines()
            raise TTSError(f"Windows speech: {err[0][:100] if err else 'failed'}")
        _check_wav(out, "Windows speech")


ENGINES: dict[str, Engine] = {e.id: e for e in (PiperEngine(), SayEngine(), SapiEngine(), RHVoiceEngine(),
                                                  PicoEngine(), EspeakEngine(), SpeechDispatcherEngine(),
                                                  FestivalEngine())}


def engine(eid: str) -> Engine | None:
    return ENGINES.get(eid)


def forget_voices() -> None:
    for e in ENGINES.values():
        e.forget()


def usable(e: Engine) -> bool:
    """Installed, with a voice ready, and (unless it speaks by itself) something to play the audio."""
    if not e.available():
        return False
    if e.id == "piper" and not any(v.installed for v in e.voices()):
        return False
    return e.direct or player() is not None


def resolve(cfg) -> tuple[Engine | None, str]:
    """The engine and voice to read with: the chosen ones, or the best that works."""
    want = cfg["tts_engine"]
    voices = cfg["tts_voices"] or {}
    order = ([want] if want in ENGINE_ORDER else []) + [e for e in ENGINE_ORDER if e != want]
    for eid in order:
        e = ENGINES[eid]
        if not usable(e):
            continue
        v = voices.get(eid, "")
        if v and not e.direct and not any(x.id == v and x.installed for x in e.voices()):
            v = ""                                 # a voice that is no longer there
        return e, v or e.default_voice()
    return None, ""


# ---------------------------------------------------------------- audio players

# Windows: Python's own winsound, in a small process of its own (stopping the process stops the sound)
_WINSOUND = "import sys, winsound; winsound.PlaySound(sys.argv[1], winsound.SND_FILENAME | winsound.SND_NODEFAULT)"
_ANYWHERE = [
    ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "{f}"]),
    ("mpv", ["mpv", "--no-video", "--really-quiet", "--no-terminal", "{f}"]),
    ("play", ["play", "-q", "{f}"]),
]
if system.WINDOWS:
    _PLAYERS = [("Windows audio", [sys.executable, "-I", "-c", _WINSOUND, "{f}"]), *_ANYWHERE]
elif system.MACOS:
    _PLAYERS = [("afplay", ["afplay", "{f}"]), *_ANYWHERE]
else:
    _PLAYERS = [("pw-play", ["pw-play", "{f}"]), ("paplay", ["paplay", "{f}"]), ("aplay", ["aplay", "-q", "{f}"]),
                *_ANYWHERE]
_player_ok: str | None = None            # the player that worked last
_player_bad: set[str] = set()


def players() -> list[str]:
    """The audio players this computer has, best first."""
    return [name for name, cmd in _PLAYERS if _which(cmd[0])]


def _player_choice() -> tuple[str, list[str]] | None:
    """(name, command with {f} for the file) of the audio player to use."""
    env = os.environ.get("SAINTD_PLAYER")
    if env:
        return "SAINTD_PLAYER", env.split() + (["{f}"] if "{f}" not in env else [])
    names = [n for n in ([_player_ok] if _player_ok else []) + players() if n and n not in _player_bad]
    for name, cmd in _PLAYERS:
        if names and name == names[0]:
            return name, list(cmd)
    return None


def player() -> list[str] | None:
    """The command (with {f} for the file) of the audio player to use."""
    choice = _player_choice()
    return choice[1] if choice else None


def _launch(cmd: list[str], path: Path) -> subprocess.Popen:
    return subprocess.Popen([c.replace("{f}", str(path)) for c in cmd], stdin=subprocess.DEVNULL, **_QUIET,
                            **system.detached())


def _cut_wav(path: Path, seconds: float, dest: Path) -> bool:
    """Write what follows the first `seconds` of a WAV file to `dest`; False if (almost) nothing is left."""
    try:
        with wave.open(str(path)) as w:
            params, rate, total = w.getparams(), w.getframerate(), w.getnframes()
            start = int(seconds * rate)
            if start >= total - rate // 20:
                return False
            w.setpos(start)
            frames = w.readframes(total - start)
        with wave.open(str(dest), "wb") as o:
            o.setparams(params)
            o.writeframes(frames)
        return True
    except (OSError, EOFError, wave.Error) as e:
        raise TTSError("the audio could not be resumed") from e


class Playback:
    """A WAV file being played (or a direct engine speaking), which the reader can pause,
    resume and stop. On Linux the player is frozen and thawed (SIGSTOP, SIGCONT), which
    pauses mid-word. macOS and Windows players cannot be frozen that way: they are stopped,
    and Resume plays the rest of the file from where it was stopped."""

    FREEZE = system.LINUX and hasattr(os, "killpg") and hasattr(signal, "SIGSTOP")
    LEAD = 0.25                     # seconds heard again on Resume, so that no syllable is lost

    def __init__(self, proc: subprocess.Popen, cmd: list[str] | None = None, path: Path | None = None) -> None:
        self.proc, self.cmd, self.path = proc, cmd, path
        self.offset = 0.0           # where in the file the running player started
        self.started = time.monotonic()
        self.paused = False
        self.killed = False         # stopped by the reader (not an error of the player)
        self.done_code: int | None = None
        self._part = 0

    @property
    def returncode(self) -> int | None:
        return self.done_code if self.done_code is not None else self.proc.returncode

    @property
    def failed(self) -> bool:
        """The player stopped with an error (not because the reader stopped it)."""
        code = self.returncode
        return code is not None and code != 0 and not self.killed

    def poll(self) -> int | None:
        """None while the sound plays or is paused; the exit code once it is over."""
        if self.done_code is not None:
            return self.done_code
        if self.paused and not self.FREEZE:
            return None                         # stopped for a pause: the rest is still to come
        return self.proc.poll()

    def _signal(self, sig: int) -> None:
        try:
            os.killpg(self.proc.pid, sig)       # the player's own session: it and anything it started
        except (ProcessLookupError, PermissionError):
            pass

    def _end_process(self) -> None:
        if self.proc.poll() is not None:
            return
        if system.WINDOWS:
            try:
                self.proc.terminate()
            except OSError:
                pass
            return
        if self.FREEZE:
            self._signal(signal.SIGCONT)        # a frozen player must be thawed to hear the signal
        self._signal(signal.SIGTERM)

    def pause(self) -> None:
        if self.paused or self.poll() is not None:
            return
        self.paused = True
        if self.FREEZE:
            self._signal(signal.SIGSTOP)
            return
        self.offset = max(0.0, self.offset + time.monotonic() - self.started - self.LEAD)
        self._end_process()
        try:
            self.proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

    def resume(self) -> None:
        if not self.paused:
            return
        self.paused = False
        if self.FREEZE:
            self._signal(signal.SIGCONT)
            return
        if self.done_code is not None:
            return
        if self.cmd is None or self.path is None:
            self.done_code = 0                  # nothing to start again: count the piece as heard
            return
        self._part += 1
        rest = self.path.with_name(f"{self.path.stem}-rest{self._part}.wav")
        try:
            if not _cut_wav(self.path, self.offset, rest):
                self.done_code = 0              # it was paused at the very end
                return
            self.proc, self.started = _launch(self.cmd, rest), time.monotonic()
        except (OSError, TTSError):
            self.done_code = 1                  # reported as an error of the player

    def stop(self) -> None:
        """Stop for good (the reader is stopped or moves elsewhere)."""
        self.killed = True
        self.paused = False
        self._end_process()
        if self.done_code is None and self.proc.poll() is None:
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if self.done_code is None:
            self.done_code = self.proc.returncode if self.proc.returncode is not None else -1


def start_player(path: Path) -> Playback:
    """Start playing a WAV file; a player that fails at once is skipped for the next one."""
    global _player_ok
    tried = 0
    while True:
        choice = _player_choice()
        if choice is None:
            raise TTSError(f"no audio player found ({PLAYER_INSTALL})")
        name, cmd = choice
        try:
            p = _launch(cmd, path)
        except OSError:
            _player_bad.add(name)
            tried += 1
            if tried > len(_PLAYERS):
                raise TTSError("no audio player works on this computer")
            continue
        if os.environ.get("SAINTD_PLAYER"):
            return Playback(p, cmd, path)
        try:
            code = p.wait(timeout=0.25)                  # a player without a sound server gives up at once
        except subprocess.TimeoutExpired:
            _player_ok = name
            return Playback(p, cmd, path)
        if code == 0 and wav_seconds(path) < 0.3:
            _player_ok = name
            return Playback(p, cmd, path)
        _player_bad.add(name)
        tried += 1
        if tried > len(_PLAYERS):
            raise TTSError("no audio player works on this computer (" +
                           system.pick("is the sound server running?", "is a sound output chosen?",
                                       "is a sound device connected?") + ")")


# ---------------------------------------------------------------- making text speakable

_ORDINALS = {"I": "the First", "II": "the Second", "III": "the Third", "IV": "the Fourth", "V": "the Fifth",
             "VI": "the Sixth", "VII": "the Seventh", "VIII": "the Eighth", "IX": "the Ninth", "X": "the Tenth",
             "XI": "the Eleventh", "XII": "the Twelfth", "XIII": "the Thirteenth", "XIV": "the Fourteenth",
             "XV": "the Fifteenth", "XVI": "the Sixteenth"}
_TITLES = r"(?:Saint|St|Emperor|Empress|King|Queen|Tsar|Prince|Pope|Patriarch|Leo|Basil|Constantine|Michael|John|Joseph)"
_FOREIGN = re.compile(r"[Ͱ-Ͽἀ-῿Ѐ-ԯⷠ-ⷿꙀ-ꚟ֐-ۿႠ-ჿ]+")
_REPLACE = [
    (re.compile(r"https?://\S+"), ""),
    (re.compile(r"\[(?:\d+|[a-z]|citation needed|note \d+)\]"), ""),
    (re.compile(r"\bSts?\.?\s+(?=[A-Z])"), lambda m: "Saints " if m.group(0).lower().startswith("sts") else "Saint "),
    (re.compile(r"\bSs\.\s+(?=[A-Z])"), "Saints "),
    (re.compile(r"\bVen\.\s+"), "Venerable "),
    (re.compile(r"\bFr\.\s+(?=[A-Z])"), "Father "),
    (re.compile(r"\bBp\.\s+"), "Bishop "),
    (re.compile(r"\bAbp\.\s+"), "Archbishop "),
    (re.compile(r"\bMetr\.\s+"), "Metropolitan "),
    (re.compile(r"\bBl\.\s+(?=[A-Z])"), "Blessed "),
    (re.compile(r"\bMt\.\s+(?=[A-Z])"), "Mount "),
    (re.compile(r"\b(\d+)(st|nd|rd|th)\s+c\.(?=\W|$)"), r"\1\2 century"),
    (re.compile(r"\bcc?\.\s*(\d{2,4})\b"), r"about \1"),
    (re.compile(r"\bca\.\s*(\d{2,4})\b"), r"about \1"),
    (re.compile(r"\bb\.\s*(\d{3,4})\b"), r"born \1"),
    (re.compile(r"\bd\.\s*(\d{3,4})\b"), r"died \1"),
    (re.compile(r"\br\.\s*(\d{3,4})\b"), r"reigned \1"),
    (re.compile(r"†\s*(\d)"), r"died \1"),
    # Colossians 4.10-18 -> Colossians, chapter 4, verses 10 to 18
    (re.compile(r"\b([1-3]\s)?([A-Z][a-z]+\.?)\s+(\d{1,3})[.:](\d{1,3})\s*[-–]\s*(\d{1,3})\b"),
     lambda m: f"{m.group(1) or ''}{m.group(2).rstrip('.')}, chapter {m.group(3)}, verses {m.group(4)} to {m.group(5)}"),
    (re.compile(r"\b([1-3]\s)?([A-Z][a-z]+\.?)\s+(\d{1,3})[.:](\d{1,3})\b"),
     lambda m: f"{m.group(1) or ''}{m.group(2).rstrip('.')}, chapter {m.group(3)}, verse {m.group(4)}"),
    (re.compile(r"\b(\d{3,4})\s*[–—-]\s*(\d{2,4})\b"), r"\1 to \2"),
    (re.compile(r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?) (II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI)\b"),
     lambda m: f"{m.group(1)} {_ORDINALS[m.group(2)]}"),
    (re.compile(r"\b(" + _TITLES + r") ([A-Z][a-z]+) I\b(?=[,;:)]| of\b| the\b|\s*$)"),
     lambda m: f"{m.group(1)} {m.group(2)} the First"),
    (re.compile(r"\b([A-Z][a-z]{2,}) I\b(?=, (?:Patriarch|Emperor|King|Pope|Bishop|Archbishop|Tsar))"),
     r"\1 the First"),
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"\s+[—–]\s+|—"), ", "),
    (re.compile(r"\s*·\s*"), ", "),
    (re.compile(r"[★☆✦☦✠✚⊕≈∽•◦◉▶◀‹›«»¶§♪♫⏎→←↑↓]"), " "),
    (re.compile(r"\(\s*[,;:]?\s*\)"), ""),
    (re.compile(r"\s+([,.;:!?])"), r"\1"),
    (re.compile(r"([,;:])(?=[^\s\d])"), r"\1 "),
    (re.compile(r"[ \t]+"), " "),
]


def speakable(text: str) -> str:
    """Text as it should be read: no links or footnote marks, abbreviations
    spelt out (St -> Saint, 4th c. -> 4th century), Scripture references and
    regnal numbers in words, and nothing in scripts an English voice cannot read."""
    t = re.sub(r"(?:https?://|www\.)\S*[^\s.,;:!?)\]]", "", text or "")
    t = _FOREIGN.sub("", t)
    t = re.sub(r"\s*/{1,2}\s*", ", ", t)                         # the phrase marks of hymns
    lines = [x.strip() for x in t.splitlines()]
    t = " ".join(x if x.endswith((".", ",", ";", ":", "!", "?")) or i == len(lines) - 1 else x + ","
                 for i, x in enumerate(lines) if x)
    for pat, rep in _REPLACE:
        t = pat.sub(rep, t)
    t = re.sub(r"([,;])(\s*[,;])+", r"\1", t)
    t = re.sub(r"([.!?])\s*[,;]", r"\1", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    return t.strip(" ,;")


_SENTENCE = re.compile(r"(?<=[.!?…])[\"”’)]?\s+(?=[\"“‘(\[]?[A-Z0-9])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def chunks_of(text: str, max_chars: int = 320) -> list[str]:
    """Speakable pieces of a paragraph: whole sentences, a few at a time (the
    first piece is kept short so that reading starts quickly)."""
    out: list[str] = []
    cur = ""
    limit = max_chars // 2
    for s in sentences(text):
        while len(s) > max_chars * 1.5:              # a very long sentence: break it at a comma or a space
            cut = s.rfind(", ", 0, max_chars)
            if cut < max_chars // 3:
                cut = s.rfind(" ", 0, max_chars)
            if cut <= 0:
                break
            head, s = s[:cut + 1].strip(), s[cut + 1:].strip()
            if cur:
                out.append(cur)
                cur = ""
            out.append(head)
        if cur and len(cur) + 1 + len(s) > limit:
            out.append(cur)
            cur = s
            limit = max_chars
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- the reader

@dataclass
class Chunk:
    text: str
    target: Any = None            # what the app highlights while this is read
    section: str = ""
    anchor: str = ""              # the start of the highlighted text, to find it again after a redraw


@dataclass
class _Session:
    sid: int
    chunks: list[Chunk]
    engine: Engine
    voice: str
    rate: float
    index: int = 0
    stop: threading.Event = None    # type: ignore[assignment]
    paused: bool = False
    jump: int | None = None
    tmp: Path | None = None

    def __post_init__(self) -> None:
        self.stop = threading.Event()


class Reader:
    """Speaks a list of chunks in a background thread. Every change is reported
    through `emit(event)` from that thread ("state", "chunk", "error", "done")."""

    def __init__(self, cfg, emit: Callable[[str], None] | None = None) -> None:
        self.cfg = cfg
        self.emit = emit or (lambda ev: None)
        self.state = "idle"          # idle | loading | playing | paused
        self.title = ""
        self.owner: Any = None       # what is being read, e.g. ("saint", 42)
        self.error = ""
        self.engine: Engine | None = None
        self.voice = ""
        self._sess: _Session | None = None
        self._ids = 0
        self._lock = threading.RLock()
        self._proc: Playback | None = None

    # -- what the app asks for
    @property
    def active(self) -> bool:
        return self.state != "idle"

    @property
    def chunks(self) -> list[Chunk]:
        return self._sess.chunks if self._sess else []

    @property
    def index(self) -> int:
        return self._sess.index if self._sess else 0

    @property
    def rate(self) -> float:
        try:
            return max(0.5, min(2.5, float(self.cfg["tts_rate"])))
        except (TypeError, ValueError):
            return 1.0

    def start(self, title: str, chunks: list[Chunk], owner: Any = None, index: int = 0,
              engine: Engine | None = None, voice: str | None = None) -> bool:
        self.stop()
        chunks = [c for c in chunks if c.text and c.text.strip()]
        if not chunks:
            self.error = "There is nothing to read here yet."
            self.emit("error")
            return False
        if engine is None:
            engine, v = resolve(self.cfg)
            voice = voice or v
        if engine is None:
            self.error = NO_ENGINE
            self.emit("error")
            return False
        with self._lock:
            self._ids += 1
            sess = _Session(self._ids, chunks, engine, voice or "", self.rate, index=max(0, min(index, len(chunks) - 1)))
            sess.tmp = Path(tempfile.mkdtemp(prefix="saintd-voice-"))
            self._sess = sess
            self.title, self.owner, self.error = title, owner, ""
            self.engine, self.voice = engine, sess.voice
            self.state = "loading"
        self.emit("state")
        threading.Thread(target=self._run, args=(sess,), name="saintd-reader", daemon=True).start()
        return True

    def toggle(self) -> None:
        if self.state == "paused":
            self.resume()
        elif self.state in ("playing", "loading"):
            self.pause()

    def pause(self) -> None:
        with self._lock:
            if self._sess and self.state in ("playing", "loading"):
                self._sess.paused = True
                self.state = "paused"
                self._apply_pause()
        self.emit("state")

    def resume(self) -> None:
        with self._lock:
            if self._sess and self.state == "paused":
                self._sess.paused = False
                self.state = "playing"
                self._apply_pause()
        self.emit("state")

    def stop(self) -> None:
        with self._lock:
            sess, self._sess = self._sess, None
            if sess is not None:
                sess.stop.set()
                self._kill_proc(sess)
            was = self.state
            self.state = "idle"
            self.owner = None
        if sess is not None and was != "idle":
            self.emit("state")

    def skip(self, step: int) -> None:
        """To the previous / next paragraph (chunks with the same target belong together)."""
        with self._lock:
            sess = self._sess
            if not sess:
                return
            chunks, i = sess.chunks, sess.index

            def same(a: int, b: int) -> bool:
                return chunks[a].target is not None and chunks[a].target is chunks[b].target

            if step > 0:
                j = i + 1
                while j < len(chunks) and same(j, i):
                    j += 1
            else:
                j = i
                while j > 0 and same(j - 1, i):
                    j -= 1                                      # the start of this paragraph...
                if j == i:
                    j = max(0, i - 1)                           # ...or, from its start, of the one before
                    while j > 0 and same(j - 1, j):
                        j -= 1
        if j >= len(chunks):
            self.stop()                                         # past the last paragraph: the end
            return
        self.jump_to(j)

    def jump_to(self, i: int) -> None:
        with self._lock:
            sess = self._sess
            if not sess or not (0 <= i < len(sess.chunks)):
                return
            sess.jump = i
            if sess.paused:
                sess.paused = False
                self.state = "playing"
            self._kill_proc(sess)
        self.emit("state")

    def set_rate(self, rate: float) -> None:
        self.cfg.set("tts_rate", round(max(0.5, min(2.5, rate)), 2))
        with self._lock:
            if self._sess:
                self._sess.rate = self.rate

    def shutdown(self) -> None:
        self.stop()
        _piper_worker.close()

    # -- the reading thread
    def _apply_pause(self) -> None:
        p = self._proc
        if p is None or p.poll() is not None or self._sess is None:
            return
        if self._sess.engine.direct:
            if self._sess.paused:                    # spd-say cannot pause: stop, and say the piece again later
                self._kill_proc(self._sess)
            return
        if self._sess.paused:
            p.pause()
        else:
            p.resume()

    def _kill_proc(self, sess: _Session) -> None:
        p = self._proc
        if p is not None:
            p.stop()
        if sess.engine.direct:
            sess.engine.cancel()

    @staticmethod
    def _wait_while_paused(sess: _Session) -> bool:
        """Wait out a pause; False if the reader was stopped or sent elsewhere meanwhile."""
        while sess.paused and not sess.stop.is_set() and sess.jump is None:
            time.sleep(0.05)
        return not sess.stop.is_set() and sess.jump is None

    def _synth(self, sess: _Session, i: int, rate: float) -> Path:
        path = sess.tmp / f"{i:04d}-{int(rate * 100)}.wav"
        if not path.exists():
            sess.engine.synth(sess.chunks[i].text, sess.voice, rate, path)
        return path

    def _set_state(self, sess: _Session, state: str) -> None:
        with self._lock:
            if self._sess is sess and self.state != state and not (self.state == "paused" and state == "playing"):
                self.state = state
                changed = True
            else:
                changed = False
        if changed:
            self.emit("state")

    def _run(self, sess: _Session) -> None:
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="saintd-voice")
        ahead: dict[tuple[int, float], Any] = {}
        finished = False
        try:
            if isinstance(sess.engine, PiperEngine):
                pool.submit(sess.engine.preload, sess.voice)
            i = sess.index
            while not sess.stop.is_set():
                if sess.jump is not None:
                    i, sess.jump = sess.jump, None
                if not 0 <= i < len(sess.chunks):
                    break
                sess.index = i
                self.emit("chunk")
                rate = sess.rate
                if sess.engine.direct:
                    if not self._wait_while_paused(sess):
                        continue                              # stopped, or told to go elsewhere
                    proc = Playback(sess.engine.say(sess.chunks[i].text, sess.voice, rate))
                else:
                    fut = ahead.pop((i, rate), None) or pool.submit(self._synth, sess, i, rate)
                    while not fut.done() and not sess.stop.is_set() and sess.jump is None:
                        time.sleep(0.03)
                    if sess.stop.is_set() or sess.jump is not None:
                        continue
                    path = fut.result()                       # raises TTSError
                    if not self._wait_while_paused(sess):
                        continue
                    proc = start_player(path)
                    if i + 1 < len(sess.chunks) and (i + 1, rate) not in ahead:
                        ahead[(i + 1, rate)] = pool.submit(self._synth, sess, i + 1, rate)
                with self._lock:
                    self._proc = proc
                    if sess.stop.is_set():
                        self._kill_proc(sess)
                        break
                    if sess.paused:
                        self._apply_pause()
                self._set_state(sess, "playing")
                while proc.poll() is None and not sess.stop.is_set() and sess.jump is None:
                    time.sleep(0.04)
                with self._lock:
                    if proc.poll() is None:
                        self._kill_proc(sess)
                    self._proc = None
                if sess.stop.is_set() or sess.jump is not None:
                    continue
                if sess.engine.direct and sess.paused:
                    continue                                  # interrupted by Pause: say it again on Resume
                if not sess.engine.direct and proc.failed and not os.environ.get("SAINTD_PLAYER"):
                    raise TTSError("the audio player stopped with an error")
                for k in [k for k in ahead if k[0] <= i]:
                    ahead.pop(k, None)
                i += 1
            finished = not sess.stop.is_set()
        except TTSError as e:
            with self._lock:
                if self._sess is sess:
                    self.error = str(e)
            if self._sess is sess:
                self.emit("error")
        except Exception as e:                       # never let the reader take the app down
            with self._lock:
                if self._sess is sess:
                    self.error = f"Reading stopped: {e.__class__.__name__}: {e}"
            if self._sess is sess:
                self.emit("error")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            with self._lock:
                mine = self._sess is sess
                if mine:
                    self._sess = None
                    self.state = "idle"
                    self.owner = None
            shutil.rmtree(sess.tmp, ignore_errors=True) if sess.tmp else None
            if mine:
                self.emit("done" if finished else "state")


__all__ = ["Chunk", "ENGINES", "ENGINE_CHOICES", "Engine", "NO_ENGINE", "PLAYER_INSTALL", "Playback", "Reader",
           "RATES", "SAMPLE", "TTSError", "Voice", "chunks_of", "delete_piper_voice", "download_piper_voice", "engine",
           "forget_voices", "piper_catalog", "player", "players", "resolve", "speakable", "usable", "voices_dir"]
