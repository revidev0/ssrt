#!/usr/bin/env python3
"""
speech.py -- Modul suara (Text-To-Speech) untuk ssr.

Modul ini menampung SEMUA hal yang berkaitan dengan pengucapan teks. Berbeda
dari versi sebelumnya yang memanggil binari `espeak`/`espeak-ng` lewat
subprocess untuk setiap ucapan, modul ini mengikat (bind) LANGSUNG ke shared
library `libespeak-ng.so` memakai ctypes -- mesin TTS dimuat SEKALI ke dalam
memori proses Python saat modul diimpor/kelas diinisialisasi, lalu setiap
ucapan cukup memanggil fungsi C `espeak_Synth()` secara langsung. Ini
menghilangkan overhead spawn proses baru (fork+exec) untuk setiap potong
teks yang dibacakan -- penting untuk umpan balik ketikan huruf-demi-huruf
yang butuh latensi serendah mungkin.

Modul ini SENGAJA dipisahkan dari logika utama pembaca layar (pembuatan
PTY, parsing buffer terminal via pyte, navigasi, dsb -- lihat ssr.py)
supaya:
  - bagian suara bisa diuji, diganti, atau dikembangkan (mis. mengganti
    backend TTS) tanpa menyentuh logika terminal sama sekali, dan
    sebaliknya;
  - ssr.py tidak perlu tahu detail eSpeak NG (binding ctypes, signature
    fungsi C, dst) -- ia cukup memanggil SpeechEngine.speak()/
    stop_speaking(), PERSIS seperti sebelumnya. Seluruh perubahan pada
    berkas ini backward-compatible terhadap ssr.py; tidak ada perubahan
    API publik (speak/stop_speaking/shutdown/available/voice/rate).

Konfigurasi (opsional, lewat environment variable):
    SSR_VOICE   suara eSpeak, default "id" (Indonesia)
    SSR_RATE    kecepatan bicara (kata/menit), default "175"
"""

import ctypes
import ctypes.util
import os
import re
import sys
from typing import Optional

# ----------------------------------------------------------------------
# Escape sequence terminal (CSI dan OSC) yang perlu dibuang sebelum teks
# dibacakan atau dicocokkan sebagai prompt. OSC (mis. penentu judul jendela
# "\x1b]0;...\x07") sangat umum muncul di dalam PS1 bash. Bagian ini TIDAK
# berubah oleh migrasi ke ctypes -- murni utilitas teks, tidak menyentuh
# mesin TTS sama sekali.
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# Binding ctypes ke libespeak-ng.so
# ----------------------------------------------------------------------
# Konstanta enum dari <espeak-ng/speak_lib.h> yang benar-benar kita pakai.
# Tidak memakai seluruh enum eSpeak NG -- hanya yang relevan bagi modul ini,
# supaya berkas ini tetap ringkas dan mudah diverifikasi terhadap header
# aslinya bila suatu saat perlu diperbarui.
_AUDIO_OUTPUT_PLAYBACK = 0    # espeak_AUDIO_OUTPUT: keluarkan suara langsung
                              # lewat backend audio internal library (PulseAudio/
                              # ALSA/OpenSL-ES/dst) -- sama seperti yang dipakai
                              # binari `espeak-ng` baris perintah, tanpa kita
                              # perlu menangani sampel PCM mentah sendiri.
_ESPEAKCHARS_UTF8 = 1         # espeak_CHARACTERS: teks yang dikirim berenkode UTF-8.
_POS_CHARACTER = 1            # espeak_POSITION_TYPE untuk argumen `position`.
_ESPEAK_RATE = 1              # espeak_PARAMETER: kecepatan bicara (kata/menit).
_ESPEAK_PITCH = 3             # espeak_PARAMETER: nada suara.

# Nama/lokasi shared library yang dicoba, dari yang paling umum. Termux
# menaruh library di bawah $PREFIX/lib (bukan /usr/lib standar seperti
# kebanyakan distro Linux), dan nama file .so yang persis (dengan/tanpa
# suffix versi ".1") juga bisa berbeda antar rilis paket -- karena itu
# beberapa kandidat dicoba berurutan alih-alih menembak satu nama saja.
_LIB_NAME_CANDIDATES = ('libespeak-ng.so.1', 'libespeak-ng.so')


def _find_and_load_library() -> Optional[ctypes.CDLL]:
    """Mencari & memuat shared library libespeak-ng.so.

    Dipanggil sekali saat modul ini diimpor (lihat _espeak_lib di bawah).
    Mengembalikan None (bukan melempar exception) bila tidak ditemukan --
    supaya seluruh program tetap bisa berjalan tanpa suara alih-alih crash
    total, konsisten dengan perilaku versi berbasis subprocess sebelumnya
    yang juga hanya memberi peringatan saat binari eSpeak tidak ditemukan.
    """
    candidates = list(_LIB_NAME_CANDIDATES)

    found = ctypes.util.find_library('espeak-ng')
    if found:
        candidates.insert(0, found)

    # Fallback path absolut khas instalasi Termux, untuk berjaga-jaga bila
    # resolver linker dinamis standar (dipakai ctypes.util.find_library)
    # tidak berhasil menemukannya di lingkungan Android/Termux.
    termux_prefix = os.environ.get('PREFIX', '/data/data/com.termux/files/usr')
    candidates.append(os.path.join(termux_prefix, 'lib', 'libespeak-ng.so'))
    candidates.append(os.path.join(termux_prefix, 'lib', 'libespeak-ng.so.1'))

    for name in candidates:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    return None


def _configure_prototypes(lib: ctypes.CDLL) -> None:
    """Mendeklarasikan argtypes & restype fungsi API C eSpeak NG yang dipakai.

    Ini WAJIB dilakukan secara eksplisit -- tanpa argtypes/restype yang
    benar, ctypes menebak semua argumen sebagai `int` C standar, yang salah
    pada arsitektur 64-bit (mis. pointer/size_t butuh 8 byte, bukan 4) dan
    bisa membuat proses Python crash (segfault) alih-alih sekadar salah
    bicara.
    """
    # int espeak_Initialize(espeak_AUDIO_OUTPUT output, int buflength,
    #                        const char *path, int options);
    lib.espeak_Initialize.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
    ]
    lib.espeak_Initialize.restype = ctypes.c_int

    # espeak_ERROR espeak_SetVoiceByName(const char *name);
    lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    lib.espeak_SetVoiceByName.restype = ctypes.c_int

    # espeak_ERROR espeak_SetParameter(espeak_PARAMETER parameter,
    #                                   int value, int relative);
    # CATATAN: fungsi ini tidak eksplisit diminta, tetapi WAJIB ditambahkan
    # supaya parameter `pitch` per-ucapan dan kecepatan (SSR_RATE) yang
    # sebelumnya dikirim lewat argumen `-p`/`-s` pada CLI eSpeak tetap bisa
    # diatur -- espeak_SetVoiceByName() HANYA mengatur suara, bukan
    # kecepatan/nada. Tanpa ini, fitur pitch yang sudah dipakai luas di
    # ssr.py (mis. pitch berbeda untuk backspace vs navigasi) akan diam-diam
    # berhenti berfungsi. Lihat catatan kompatibilitas di speak().
    lib.espeak_SetParameter.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]
    lib.espeak_SetParameter.restype = ctypes.c_int

    # espeak_ERROR espeak_Synth(const void *text, size_t size,
    #                           unsigned int position,
    #                           espeak_POSITION_TYPE position_type,
    #                           unsigned int end_position,
    #                           unsigned int flags,
    #                           unsigned int *unique_identifier,
    #                           void *user_data);
    lib.espeak_Synth.argtypes = [
        ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint),
        ctypes.c_void_p,
    ]
    lib.espeak_Synth.restype = ctypes.c_int

    # void espeak_Cancel(void);
    lib.espeak_Cancel.argtypes = []
    lib.espeak_Cancel.restype = None

    # espeak_ERROR espeak_Terminate(void);
    lib.espeak_Terminate.argtypes = []
    lib.espeak_Terminate.restype = ctypes.c_int


# Dimuat SEKALI pada level modul (bukan per-instance SpeechEngine) --
# library C dan thread audio internalnya bersifat proses-global, jadi tidak
# ada gunanya (dan berisiko) memuatnya berulang kali.
_espeak_lib: Optional[ctypes.CDLL] = _find_and_load_library()
if _espeak_lib is not None:
    try:
        _configure_prototypes(_espeak_lib)
    except AttributeError:
        # Salah satu fungsi yang diharapkan tidak ada pada library ini
        # (mis. versi yang jauh berbeda) -- anggap tidak tersedia daripada
        # crash saat runtime dengan pesan yang sulit dipahami pengguna.
        _espeak_lib = None


class SpeechEngine:
    """Mengelola siklus hidup mesin TTS eSpeak NG lewat binding ctypes
    langsung ke libespeak-ng.so (bukan lagi subprocess ke binari CLI)."""

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

        self._lib = _espeak_lib
        self._ready = False

        if self._lib is None:
            sys.stderr.write(
                "[ssr] Peringatan: tidak dapat memuat libespeak-ng.so. "
                "Umpan balik suara TIDAK AKTIF. Pasang eSpeak NG, misal:\n"
                "  pkg install espeak-ng\n"
            )
            return

        try:
            # buflength=500 (mS) adalah nilai umum yang dipakai eSpeak NG
            # sendiri untuk ukuran potongan sintesis internal; path=None
            # supaya library memakai lokasi data bawaannya sendiri (persis
            # seperti binari `espeak-ng` tanpa opsi --path).
            sample_rate = self._lib.espeak_Initialize(
                _AUDIO_OUTPUT_PLAYBACK, 500, None, 0
            )
            if sample_rate <= 0:
                raise OSError(f"espeak_Initialize gagal (kode {sample_rate})")

            self._lib.espeak_SetVoiceByName(self.voice.encode('utf-8'))

            try:
                rate_value = int(self.rate)
            except (TypeError, ValueError):
                rate_value = 175
            self._lib.espeak_SetParameter(_ESPEAK_RATE, rate_value, 0)

            self._ready = True
        except OSError as exc:
            sys.stderr.write(
                f"[ssr] Peringatan: gagal menginisialisasi eSpeak NG ({exc}). "
                "Umpan balik suara TIDAK AKTIF.\n"
            )
            self._lib = None

    # ----------------------------------------------------------------------
    # Status Mesin TTS
    # ----------------------------------------------------------------------
    @property
    def available(self) -> bool:
        """True jika libespeak-ng.so berhasil dimuat & diinisialisasi."""
        return self._lib is not None and self._ready

    # ----------------------------------------------------------------------
    # Kontrol Ucapan
    # ----------------------------------------------------------------------
    def stop_speaking(self) -> None:
        """Menghentikan ucapan yang sedang berjalan maupun yang masih antre.

        Dengan binding ctypes langsung, ini hanyalah SATU panggilan fungsi C
        (espeak_Cancel()) -- seluruh manajemen proses OS (poll/terminate/
        kill/wait/timeout) yang sebelumnya diperlukan saat memakai
        subprocess untuk binari eSpeak CLI tidak relevan lagi di sini,
        karena tidak ada proses terpisah yang dibuat sama sekali; mesin TTS
        berjalan di dalam proses Python ini sendiri.
        """
        if not self.available:
            return
        try:
            self._lib.espeak_Cancel()
        except Exception:
            pass

    def speak(self, text: str, interrupt: bool = True, pitch: int = 50, is_character: bool = False) -> None:
        """Mengucapkan teks lewat espeak_Synth()."""
        if not text or not self.available:
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
        # Saat interrupt=False (mis. umpan balik kata sebelumnya ketika
        # menekan Spasi), kita CUKUP memanggil espeak_Synth() tanpa
        # espeak_Cancel() -- eSpeak NG sendiri yang mengantrekan ucapan baru
        # setelah ucapan yang sedang berjalan selesai. Ini menggantikan
        # daftar proses latar belakang (_tts_bg_procs) yang dulu perlu kita
        # kelola manual saat memakai subprocess.

        try:
            self._lib.espeak_SetParameter(_ESPEAK_PITCH, int(pitch), 0)
        except Exception:
            pass

        text_bytes = text.encode('utf-8', errors='replace')
        size = len(text_bytes) + 1  # +1 mengikutkan byte NUL terminator

        try:
            self._lib.espeak_Synth(
                text_bytes, size, 0, _POS_CHARACTER, 0, _ESPEAKCHARS_UTF8,
                None, None,
            )
        except Exception:
            pass

    def shutdown(self) -> None:
        """Dipanggil sekali saat sesi berakhir untuk melepaskan alokasi
        memori & thread audio internal milik libespeak-ng secara bersih,
        menggantikan perulangan mematikan proses latar belakang yang dulu
        dipakai versi subprocess."""
        if not self.available:
            return
        try:
            self._lib.espeak_Cancel()
        except Exception:
            pass
        try:
            self._lib.espeak_Terminate()
        except Exception:
            pass
        self._ready = False
