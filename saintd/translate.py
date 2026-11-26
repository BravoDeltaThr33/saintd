"""Machine translation into English through free services (or a local
Ollama model). Every result is cached, so each text is translated once."""

from __future__ import annotations

import re
from typing import Callable
from urllib.parse import quote

from .net import Cancelled, Http, NetError

BACKEND_INFO = {
    "mymemory": ("MyMemory", "https://api.mymemory.translated.net/get",
                 "Free public API, no key. ~5,000 characters/day anonymously, ~50,000/day if you add an e-mail."),
    "lingva": ("Lingva Translate", "<instance>/api/v1/{src}/{tgt}/{text}",
               "Free open-source front-end; public instances come and go, so set one that works for you."),
    "libretranslate": ("LibreTranslate", "<url>/translate",
                       "Open-source; free when self-hosted (docker run libretranslate/libretranslate)."),
    "ollama": ("Ollama (local)", "<url>/api/generate",
               "Runs a model on your own machine: unlimited, offline, slower on CPU."),
    "off": ("Off", "-", "No machine translation. Russian names use the built-in glossary."),
}


class TranslationError(Exception):
    pass


class Translator:
    def __init__(self, cfg, db, http: Http) -> None:
        self.cfg = cfg
        self.db = db
        self.http = http
        self.quota_hit = False

    @property
    def backend(self) -> str:
        return self.cfg["translator"]

    def available(self) -> bool:
        b = self.backend
        if b == "off":
            return False
        if b == "ollama" and not self.cfg["ollama_model"].strip():
            return False
        return not self.quota_hit

    # -------------------------------------------------------------- api
    def translate(self, text: str, src: str = "ru", tgt: str = "en", *, cached_only: bool = False) -> str | None:
        text = (text or "").strip()
        if not text:
            return ""
        hit = self.db.tr_get(src, tgt, text)
        if hit is not None:
            return hit
        if cached_only or not self.available():
            return None
        out = self._call(text, src, tgt)
        if out:
            self.db.tr_put(src, tgt, text, out, self.backend)
        return out

    def translate_long(self, text: str, src: str, tgt: str = "en",
                       progress: Callable[[int, int], None] | None = None) -> str | None:
        """Translate a long text paragraph by paragraph (long paragraphs in
        sentence-sized pieces that are joined back together). Returns None if
        any piece fails (no half-translated output is ever shown)."""
        limit = self._limit(src)
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        plan = [self._chunks(p, limit) for p in paras]
        total = sum(len(c) for c in plan)
        done = 0
        out = []
        for pieces in plan:
            parts = []
            for ch in pieces:
                if progress:
                    progress(done, total)
                done += 1
                if not re.search(r"\w", ch):
                    parts.append(ch)
                    continue
                heading = re.match(r"^(#+\s*)(.*)$", ch)
                t = self.translate(heading.group(2) if heading else ch, src, tgt)
                if t is None:
                    return None
                parts.append(heading.group(1) + t if heading else t)
            out.append(" ".join(x.strip() for x in parts))
        if progress:
            progress(total, total)
        return "\n\n".join(out)

    def test(self) -> str:
        """Translate a short sample; returns the result or raises."""
        out = self._call("Преподобный Сергий Радонежский, игумен, чудотворец", "ru", "en")
        if not out:
            raise TranslationError("empty response")
        return out

    def ollama_models(self) -> list[str]:
        url = self.cfg["ollama_url"].rstrip("/") + "/api/tags"
        data = self.http.get_json(url, timeout=8, retries=0)
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    # -------------------------------------------------------------- internals
    def _limit(self, src: str) -> int:
        b = self.backend
        if b == "mymemory":
            return 230 if src in ("ru", "el", "sr", "bg", "uk", "ka") else 450
        if b == "lingva":
            return 900
        if b == "ollama":
            return 1800
        return 2500

    @staticmethod
    def _chunks(text: str, limit: int) -> list[str]:
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        out: list[str] = []
        for p in paras:
            if len(p) <= limit:
                out.append(p)
                continue
            sents = re.split(r"(?<=[.!?;])\s+", p)
            cur = ""
            for s in sents:
                while len(s) > limit:          # pathological sentence
                    out.append(s[:limit])
                    s = s[limit:]
                if len(cur) + len(s) + 1 > limit and cur:
                    out.append(cur)
                    cur = s
                else:
                    cur = (cur + " " + s).strip()
            if cur:
                out.append(cur)
        return out

    def _call(self, text: str, src: str, tgt: str) -> str | None:
        b = self.backend
        try:
            if b == "mymemory":
                return self._mymemory(text, src, tgt)
            if b == "lingva":
                return self._lingva(text, src, tgt)
            if b == "libretranslate":
                return self._libre(text, src, tgt)
            if b == "ollama":
                return self._ollama(text, src, tgt)
        except Cancelled:
            raise
        except (NetError, TranslationError, KeyError, TypeError, ValueError) as e:
            raise TranslationError(str(e) or e.__class__.__name__) from e
        return None

    def _mymemory(self, text, src, tgt):
        params = {"q": text, "langpair": f"{src}|{tgt}"}
        if self.cfg["mymemory_email"].strip():
            params["de"] = self.cfg["mymemory_email"].strip()
        data = self.http.get_json("https://api.mymemory.translated.net/get", params, retries=1)
        out = (data.get("responseData") or {}).get("translatedText") or ""
        status = data.get("responseStatus")
        if "MYMEMORY WARNING" in out or str(status) == "429":
            self.quota_hit = True
            raise TranslationError("MyMemory daily free quota used up")
        if str(status) not in ("200", "None") and status is not None:
            raise TranslationError(data.get("responseDetails") or f"MyMemory status {status}")
        return self._clean(out, text)

    def _lingva(self, text, src, tgt):
        base = self.cfg["lingva_url"].rstrip("/")
        data = self.http.get_json(f"{base}/api/v1/{src}/{tgt}/{quote(text, safe='')}", retries=1)
        if data.get("error"):
            raise TranslationError(str(data["error"]))
        return self._clean(data.get("translation", ""), text)

    def _libre(self, text, src, tgt):
        base = self.cfg["libre_url"].rstrip("/")
        body = {"q": text, "source": src, "target": tgt, "format": "text"}
        if self.cfg["libre_key"].strip():
            body["api_key"] = self.cfg["libre_key"].strip()
        data = self.http.post_json(f"{base}/translate", body)
        if isinstance(data, dict) and data.get("error"):
            raise TranslationError(str(data["error"]))
        return self._clean(data.get("translatedText", ""), text)

    def _ollama(self, text, src, tgt):
        lang = {"ru": "Russian", "el": "Greek", "sr": "Serbian", "bg": "Bulgarian", "uk": "Ukrainian",
                "ro": "Romanian", "ka": "Georgian"}.get(src, src)
        prompt = (f"Translate the following {lang} text about Orthodox Christian saints into natural English. "
                  f"Use the customary English forms of saints' names and church titles. "
                  f"Output only the translation, with no notes.\n\n{text}")
        base = self.cfg["ollama_url"].rstrip("/")
        data = self.http.post_json(f"{base}/api/generate",
                                   {"model": self.cfg["ollama_model"].strip(), "prompt": prompt, "stream": False,
                                    "options": {"temperature": 0.1}}, timeout=600, retries=0)
        out = data.get("response", "")
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
        return self._clean(out, text)

    @staticmethod
    def _clean(out: str, original: str) -> str:
        out = (out or "").strip()
        if not out:
            raise TranslationError("empty translation")
        if out == original.strip() and re.search(r"[Ѐ-ӿͰ-Ͽ]", original):
            raise TranslationError("text came back untranslated")
        return out
