#!/usr/bin/env python3
"""
speech.py -- Modul suara (Text-To-Speech) untuk ssr.

Modul ini menampung SEMUA hal yang berkaitan dengan pengucapan teks:
deteksi mesin eSpeak yang tersedia di sistem, manajemen siklus hidup
proses TTS (menghentikan/menimpa ucapan yang sedang berjalan tanpa
meninggalkan proses zombie), pemetaan simbol ke pengucapan dalam Bahasa
Indonesia, serta pembersihan escape sequence terminal dari teks.

Modul ini SENGAJA dipisahkan dari logika utama pembaca layar (pembuatan
PTY, parsing buffer terminal via pyte, navigasi, dsb -- lihat ssr.py)
supaya:
  - bagian suara bisa diuji, diganti, atau dikembangkan (mis. menambah
    backend TTS lain selain eSpeak) tanpa menyentuh logika terminal sama
    sekali, dan sebaliknya;
  - ssr.py tidak perlu tahu detail proses eSpeak (nama binari, argumen
    command line, penanganan proses latar belakang, dst) -- ia cukup
    memanggil SpeechEngine.speak()/stop_speaking().

Konfigurasi (opsional, lewat environment variable):
    SSR_VOICE   suara eSpeak, default "id" (Indonesia)
    SSR_RATE    kecepatan bicara (kata/menit), default "175"
"""

import os
import re
import shutil
import subprocess
import sys
from typing import List, Optional

# Escape sequence terminal (CSI dan OSC) yang perlu dibuang sebelum teks
# dibacakan atau dicocokkan sebagai prompt. OSC (mis. penentu judul jendela
# "\x1b]0;...\x07") sangat umum muncul di dalam PS1 bash.
_CSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
_OSC_RE = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')


def strip_escapes(text: str) -> str:
    """Membuang escape sequence CSI dan OSC dari sebuah string.

    Fungsi level-modul (bukan method) supaya bisa dipakai baik oleh
    SpeechEngine sendiri (membersihkan teks sebelum dibacakan) maupun oleh
    ssr.py (mis. untuk heuristik deteksi prompt shell) tanpa perlu membuat
    instance SpeechEngine terlebih dahulu.
    """
    text = _OSC_RE.sub('', text)
    text = _CSI_RE.sub('', text)
    return text


class SpeechEngine:
    """Mengelola seluruh siklus hidup proses TTS (eSpeak / eSpeak-ng)."""

    # Pemetaan simbol untuk pembacaan karakter demi karakter.
    SYMBOL_MAP = {
        '~': 'tilde', '`': 'aksen grave', '!': 'tanda seru', '@': 'keong',
        '#': 'tagar', '$': 'dolar', '%': 'persen', '^': 'sisipan',
        '&': 'dan', '*': 'bintang', '(': 'kurung buka', ')': 'kurung tutup',
        '-': 'strip', '_': 'garis bawah', '+': 'tambah', '=': 'sama dengan',
        '{': 'kurung kurawal buka', '}': 'kurung kurawal tutup', '[': 'kurung siku buka',
        ']': 'kurung siku tutup', '|': 'garis vertikal', '\\': 'garis miring terbalik',
        ':': 'titik dua', ';': 'titik koma', '"': 'kutip dua', "'": 'kutip satu',
        '<': 'lebih kecil', '>': 'lebih besar', ',': 'koma', '.': 'titik',
        '?': 'tanda tanya', '/': 'garis miring', ' ': 'spasi'
    }

    def __init__(self, voice: Optional[str] = None, rate: Optional[str] = None) -> None:
        self.voice = voice if voice is not None else os.environ.get('SSR_VOICE', 'id')
        self.rate = rate if rate is not None else os.environ.get('SSR_RATE', '175')

        self.tts_process: Optional[subprocess.Popen] = None
        self._tts_bg_procs: List[subprocess.Popen] = []

        self.tts_bin = self._detect_tts_binary()
        if self.tts_bin is None:
            sys.stderr.write(
                "[ssr] Peringatan: tidak menemukan 'espeak' maupun 'espeak-ng'. "
                "Umpan balik suara TIDAK AKTIF. Pasang salah satunya, misal:\n"
                "  pkg install espeak-ng\n"
            )

    # ----------------------------------------------------------------------
    # Deteksi Mesin TTS
    # ----------------------------------------------------------------------
    @staticmethod
    def _detect_tts_binary() -> Optional[str]:
        """Mencari mesin eSpeak yang tersedia. Termux umumnya menyediakan
        paket 'espeak-ng' (binari 'espeak-ng'), sedangkan beberapa sistem lain
        memakai nama 'espeak'. Menembak keras nama 'espeak' saja akan gagal
        total dan diam-diam di banyak instalasi Termux."""
        for candidate in ('espeak-ng', 'espeak'):
            if shutil.which(candidate):
                return candidate
        return None

    @property
    def available(self) -> bool:
        """True jika ada mesin TTS yang bisa dipakai untuk berbicara."""
        return self.tts_bin is not None

    # ----------------------------------------------------------------------
    # Kontrol Proses TTS
    # ----------------------------------------------------------------------
    def stop_speaking(self) -> None:
        """Menghentikan proses eSpeak yang sedang berjalan secara aman.

        Selalu menunggu (wait) proses yang dihentikan agar tidak menyisakan
        proses zombie/defunct -- proses yang di-kill() tapi tidak pernah
        di-wait() bisa menumpuk sebagai proses zombie pada sesi yang panjang
        dengan banyak ketikan.
        """
        proc, self.tts_process = self.tts_process, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=0.2)
                except Exception:
                    pass
            except Exception:
                pass

        # Proses latar belakang (dipicu dengan interrupt=False) yang sudah
        # selesai juga dibersihkan di sini supaya tidak menumpuk.
        self._tts_bg_procs = [p for p in self._tts_bg_procs if p.poll() is None]

    def speak(self, text: str, interrupt: bool = True, pitch: int = 50, is_character: bool = False) -> None:
        """Mengeksekusi eSpeak untuk membaca teks."""
        if not text or not self.tts_bin:
            return

        if is_character and text in self.SYMBOL_MAP:
            text = self.SYMBOL_MAP[text]
        elif not is_character:
            # Membersihkan escape sequence ANSI/OSC jika membaca baris/kata,
            # tetapi biarkan simbol standar.
            text = strip_escapes(text).strip()

        if not text:
            return

        if interrupt:
            self.stop_speaking()
        else:
            self._tts_bg_procs = [p for p in self._tts_bg_procs if p.poll() is None]

        try:
            proc = subprocess.Popen(
                [self.tts_bin, '-v', self.voice, '-s', str(self.rate), '-p', str(pitch), '--', text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except OSError:
            return

        self.tts_process = proc
        if not interrupt:
            self._tts_bg_procs.append(proc)

    def shutdown(self) -> None:
        """Dipanggil sekali saat sesi berakhir untuk memastikan seluruh
        proses TTS (baik yang aktif maupun yang berjalan di latar belakang)
        benar-benar dihentikan dan di-reap, supaya tidak ada proses eSpeak
        yang tertinggal setelah ssr keluar."""
        self.stop_speaking()
        for proc in self._tts_bg_procs:
            if proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=0.2)
                except Exception:
                    pass
        self._tts_bg_procs = []
