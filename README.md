# Termux Screen Reader (SSR)

Emulator terminal pembaca layar lisan untuk **Termux** (Android), berbasis **PTY** (pseudo-terminal) dan [**pyte**](https://pyte.readthedocs.io/) (emulator layar terminal murni-Python). SSR membungkus shell interaktif Anda (bash, zsh, sh, dst) di dalam sebuah "terminal virtual", membaca setiap perubahan pada layar, dan membacakannya lewat suara (Text-To-Speech) memakai **eSpeak NG**.

Proyek ini dirancang untuk aksesibilitas mandiri di Termux: penggunaan shell sehari-hari, navigasi keluaran perintah, serta interaksi dengan aplikasi berbasis TUI (Text User Interface) seperti `nano`, `less`, `htop`, atau dialog `whiptail`/`dialog` (mis. `termux-change-repo`).

---

## Daftar Isi

1. [Struktur Proyek](#struktur-proyek)
2. [Fitur](#fitur)
3. [Persyaratan](#persyaratan)
4. [Instalasi](#instalasi)
5. [Menjalankan](#menjalankan)
6. [Konfigurasi](#konfigurasi)
7. [Kontrol Dasar](#kontrol-dasar)
8. [Cara Kerja (Ringkas)](#cara-kerja-ringkas)
9. [Status Pengembangan & Keterbatasan yang Diketahui](#status-pengembangan--keterbatasan-yang-diketahui)
10. [Pemecahan Masalah](#pemecahan-masalah)
11. [Berkontribusi](#berkontribusi)

---

## Struktur Proyek

Proyek ini terdiri dari **dua berkas Python** yang harus selalu berada **berdampingan di folder yang sama** (disebut "root proyek" di seluruh dokumen ini):

| Berkas | Tanggung Jawab |
|---|---|
| **`ssr`** (skrip utama) | Seluruh logika terminal: pembuatan PTY, menjalankan shell anak, parsing buffer layar lewat `pyte`, deteksi mode editor/TUI, mode penjelajahan (review mode), dan umpan balik ketikan. **Tidak tahu apa pun soal detail eSpeak** — ia hanya memanggil `SpeechEngine.speak()`/`stop_speaking()`. |
| **`speech.py`** | Seluruh logika suara (Text-To-Speech): inisialisasi mesin eSpeak NG lewat *binding* `ctypes` langsung ke `libespeak-ng.so`, pemetaan simbol ke pengucapan Bahasa Indonesia, serta pembersihan escape sequence terminal dari teks. |

Kedua berkas ini sengaja dipisah supaya bagian suara bisa diuji/diganti (mis. mengganti mesin TTS lain) tanpa menyentuh logika terminal, dan sebaliknya.

`ssr` mengimpor `speech.py` berdasarkan **lokasi skrip itu sendiri** (`os.path.dirname(os.path.abspath(__file__))`), bukan berdasarkan direktori kerja (CWD) saat dijalankan. Artinya `ssr` tetap bisa menemukan `speech.py` meski dijalankan dari direktori mana pun — misalnya lewat symlink di `$PATH`, atau `python3 /path/lengkap/ke/ssr` — **selama kedua berkas tetap berada di folder yang sama**.

---

## Fitur

- **Pembacaan output shell otomatis** — hasil perintah (`ls`, `cat`, `pip list`, dst) dibacakan begitu selesai dicetak, termasuk baris yang sudah **tergeser keluar layar (scroll)** karena outputnya lebih panjang dari tinggi terminal — baris-baris ini ditangkap sebelum hilang dari buffer lewat `_CapturingScreen`, bukan hanya baris terakhir yang terlihat.
- **Deteksi prompt shell** — baris prompt (mis. `user@host:~$`) tidak ikut dibacakan berulang-ulang sebagai "output", memakai heuristik akhiran karakter (`$`, `#`, `%`, `]`, `)`, `>`, `>>>`, `...`) yang hanya diterapkan pada baris tempat kursor benar-benar berada, untuk meminimalkan salah tangkap terhadap output biasa yang kebetulan berakhir dengan karakter serupa (mis. keluaran `df -h` yang diakhiri angka persentase).
- **Umpan balik ketikan huruf-demi-huruf** — setiap karakter yang diketik langsung dibacakan saat tombol ditekan, konsisten baik di shell biasa maupun di editor teks/TUI. Huruf **kapital diumumkan secara eksplisit** ("kapital A", dst) khusus saat mengeja karakter satu per satu — saat membaca kata penuh atau satu baris penuh, huruf besar tetap dibacakan apa adanya tanpa pengumuman tambahan.
- **Umpan balik Backspace/Delete** — karakter yang dihapus dibacakan dengan nada (pitch) berbeda dari ketikan biasa.
- **Umpan balik Spasi cerdas** — menekan Spasi membacakan **kata yang baru saja selesai diketik**, tanpa memotong ucapan yang sedang berjalan (diucapkan di latar belakang).
- **Deteksi otomatis mode Editor/TUI** — memakai deteksi *Alternate Screen Buffer* (`\x1b[?1049h`/`\x1b[?47h`), sehingga SSR tahu kapan sebuah aplikasi layar-penuh seperti `nano`, `vim`, `htop`, atau `less` aktif, dan mengumumkan "mode interaktif aktif"/"keluar dari mode interaktif".
- **Pembacaan navigasi di dalam editor/TUI** — perpindahan baris/kolom kursor (panah, lompat kata, dst) dibacakan sesuai konteks (karakter tunggal vs. kata penuh saat lompatan lebih dari satu kolom).
- **Deteksi item menu ter-highlight pada dialog `whiptail`/`dialog`** — banyak dialog TUI (mis. `termux-change-repo`) menandai pilihan lewat **reverse-video** (warna terbalik), bukan dengan memindahkan kursor asli. SSR memindai layar untuk sel ber-atribut reverse-video dan membacakan baris yang sedang disorot, sehingga navigasi Atas/Bawah pada daftar pilihan tetap terdengar.
- **Mode Penjelajahan (Review Mode)** — jelajahi baris/kata/karakter pada layar yang sedang "dibekukan" secara bebas, independen dari posisi kursor asli aplikasi.
- **Penyesuaian ukuran terminal otomatis** — saat jendela/aplikasi Termux di-resize, ukuran baru dipropagasikan ke buffer `pyte` **dan** ke PTY milik shell anak (`TIOCSWINSZ` + `SIGWINCH`), persis seperti perilaku terminal emulator sungguhan, supaya aplikasi seperti `vim`/`htop`/`less` tidak salah gambar setelah resize.
- **TTS bermesin langsung (bukan subprocess)** — memakai *binding* `ctypes` langsung ke `libespeak-ng.so`, bukan memanggil binari `espeak`/`espeak-ng` lewat `subprocess` untuk tiap ucapan. Ini menghilangkan overhead *fork+exec* per potongan teks, penting untuk latensi umpan balik ketikan yang serendah mungkin.
- **Suara & kecepatan bicara dapat dikonfigurasi** lewat *environment variable* (`SSR_VOICE`, `SSR_RATE`).

---

## Persyaratan

- **Termux** (Android) — skrip ini bergantung pada API POSIX (`pty`, `fcntl`, `termios`, `os.fork`) dan **tidak berjalan di Windows**.
- **Python 3.8+**
- Paket Python **`pyte`**
- Paket Termux **`espeak-ng`** (menyediakan `libespeak-ng.so`, dipakai langsung lewat `ctypes` — binari command-line `espeak-ng` sendiri **tidak** dipanggil oleh skrip ini, tetapi memasang paketnya adalah cara termudah untuk mendapatkan shared library-nya beserta data suaranya)

---

## Instalasi

```bash
# 1. Perbarui paket & pasang dependensi sistem
pkg update
pkg install python espeak-ng

# 2. Pasang dependensi Python
pip install pyte

# 3. Letakkan ssr dan speech.py di folder yang SAMA
mkdir -p ~/ssr-project
cd ~/ssr-project
# (salin berkas `ssr` dan `speech.py` ke folder ini)

# 4. (Opsional) Jadikan skrip utama dapat dieksekusi langsung
chmod +x ssr
```

> **Penting:** `ssr` dan `speech.py` **harus** berada di folder yang sama. Lihat [Struktur Proyek](#struktur-proyek).

---

## Menjalankan

```bash
python3 ssr
```

Atau, jika sudah dijadikan executable (`chmod +x ssr`):

```bash
./ssr
```

Untuk bisa dipanggil dari mana saja seperti perintah biasa, buat symlink ke `$PREFIX/bin` (tetap merujuk ke lokasi asli, sehingga `speech.py` tetap ditemukan):

```bash
ln -s ~/ssr-project/ssr $PREFIX/bin/ssr
ssr
```

Saat dijalankan, SSR akan menampilkan ringkasan kontrol dasar, lalu membuka shell interaktif (`$SHELL`, atau `/system/bin/sh` bila tidak diset) di dalamnya. Ketik `exit` pada shell tersebut (atau tekan `Ctrl+D`) untuk mengakhiri sesi SSR.

---

## Konfigurasi

Seluruh konfigurasi suara diatur lewat *environment variable*, dibaca oleh `speech.py`:

| Variabel | Default | Keterangan |
|---|---|---|
| `SSR_VOICE` | `id` | Kode suara eSpeak NG yang dipakai (mis. `id` untuk Indonesia, `en` untuk Inggris). Lihat daftar suara yang tersedia dengan `espeak-ng --voices`. |
| `SSR_RATE` | `175` | Kecepatan bicara dalam kata per menit. |

Contoh menjalankan dengan suara/kecepatan berbeda untuk satu sesi:

```bash
SSR_VOICE=en SSR_RATE=200 python3 ssr
```

Atau tambahkan ke `~/.bashrc` agar permanen:

```bash
export SSR_VOICE=id
export SSR_RATE=175
```

---

## Kontrol Dasar

### Kontrol Global (berlaku kapan saja)

| Tombol | Aksi |
|---|---|
| `Ctrl+I` / `Tab` | Memaksa **masuk/keluar Mode Interaktif** secara manual |
| `Ctrl+T` | Masuk/keluar **Mode Penjelajahan** (Review Mode) |
| `Ctrl+C` | Hentikan ucapan yang sedang berjalan (tetap diteruskan ke aplikasi seperti biasa, mis. untuk membatalkan proses di shell) |
| `Ctrl+S` | Masuk/keluar **Mode Pengaturan** (fitur diagnosis manual — lihat di bawah) |

> **Catatan teknis:** `Ctrl+I` dan tombol `Tab` menghasilkan byte yang **benar-benar identik** (0x09) di hampir semua terminal termasuk Termux — keduanya tidak bisa dibedakan sama sekali di level ini, sehingga selalu berfungsi sebagai satu kontrol yang sama, bukan dua kontrol terpisah.

### Mode Pengaturan (Ctrl+S) — Diagnosis/Override Manual

Fitur ini dibuat untuk mendiagnosis dan mengakali kasus ketika **deteksi otomatis mode interaktif gagal** (mis. saat berpindah antar-tahap dialog `whiptail` terlalu cepat sehingga status lama "bocor" ke dialog baru — lihat [Status Pengembangan](#status-pengembangan--keterbatasan-yang-diketahui)). Ctrl+S **tidak langsung mengeksekusi apa pun** — ia hanya "mempersenjatai" (arm) mode ini dan menunggu perintah berikutnya. Selama Mode Pengaturan aktif, **seluruh input TIDAK diteruskan** ke shell/aplikasi anak (persis seperti Mode Penjelajahan), sehingga tombol perintah tidak bocor menjadi ketikan biasa.

Sejak `Ctrl+I`/`Tab` kini menjadi jalan pintas langsung untuk toggle manual yang sama, Mode Pengaturan berperan sebagai **cara alternatif** untuk hal yang sama (berguna bila `Ctrl+I`/`Tab` tidak nyaman diakses di tata letak keyboard/extra-keys tertentu).

| Tombol | Aksi |
|---|---|
| `Ctrl+S` | Masuk ke Mode Pengaturan (mengumumkan "Mode pengaturan aktif") |
| `E` (di dalam Mode Pengaturan) | Memaksa **masuk/keluar mode interaktif secara manual**, mengabaikan hasil deteksi otomatis. Mode Pengaturan **tidak otomatis keluar** setelah ini — bisa ditekan berkali-kali bila perlu. |
| Tombol lain (di dalam Mode Pengaturan) | Diabaikan (belum ada perintah lain yang didefinisikan), tetap tidak diteruskan ke shell |
| `Ctrl+S` (ditekan lagi) | Keluar dari Mode Pengaturan, mengembalikan input seperti semula |

Contoh alur: `Ctrl+S` → `E` (memaksa masuk mode interaktif) → `Ctrl+S` (keluar dari Mode Pengaturan, kembali mengetik normal — status mode interaktif yang baru saja dipaksa tetap berlaku).

### Saat Mengetik (Shell biasa & Editor/TUI)

Berlaku di luar Mode Penjelajahan — baik langsung di shell (bash, dsb.) maupun di dalam aplikasi layar-penuh seperti `nano`/`vim`.

| Tombol | Aksi |
|---|---|
| Huruf/angka/simbol biasa | Dibacakan langsung sebagai karakter saat ditekan |
| `Spasi` | Membacakan **kata yang baru selesai diketik** (tidak memotong ucapan lain yang sedang berjalan) |
| `Backspace` | Membacakan karakter yang **dihapus** (nada lebih tinggi dari ketikan biasa) |
| `Delete` | Sama seperti Backspace, untuk karakter tepat di posisi kursor |
| `Enter` | Diam di shell biasa (agar tidak berisik); mengumumkan "enter" di dalam mode editor/TUI |
| `Escape` | Mengumumkan "escape" di dalam mode editor/TUI; menghentikan ucapan di shell biasa |
| Tombol panah, `Home`, `End`, `PageUp/Down`, dsb. | Diteruskan apa adanya ke aplikasi/shell (tidak dibacakan sebagai "karakter ketikan") — lihat perilaku spesifik di bawah untuk masing-masing mode |

### Di Dalam Mode Editor/TUI (nano, vim, htop, dialog whiptail, dst.)

SSR mendeteksi otomatis saat sebuah aplikasi layar-penuh aktif (dan mengumumkan **"mode interaktif aktif"** / **"keluar dari mode interaktif"**). Selama mode ini aktif:

| Kejadian | Aksi Suara |
|---|---|
| Kursor berpindah ke baris lain (panah Atas/Bawah, Enter membuat baris baru, dst.) | Membacakan **seluruh isi baris baru** (atau "kosong" bila baris kosong) |
| Kursor berpindah kolom lebih dari satu karakter (lompat kata, mis. `Ctrl+Panah`) | Membacakan **kata** di posisi tujuan |
| Kursor berpindah satu kolom (panah Kiri/Kanan) tanpa berasal dari ketikan sendiri | Membacakan **karakter tunggal** di posisi tujuan |
| Item pada daftar dialog (`whiptail`/`dialog`, mis. `termux-change-repo`) berpindah sorotan (reverse-video) walau kursor asli diam | Membacakan **baris yang sedang disorot** |

> Catatan: Ketikan huruf/angka/simbol biasa di dalam mode ini dibacakan **langsung saat tombol ditekan** (lihat tabel "Saat Mengetik" di atas) — bukan dibaca ulang dari posisi kursor, untuk menghindari duplikasi maupun salah baca.

### Mode Penjelajahan (Review Mode)

Aktifkan/nonaktifkan dengan `Ctrl+T`. Dalam mode ini, **input Anda TIDAK diteruskan ke shell/aplikasi** — Anda menjelajahi isi layar secara bebas ("dibekukan") tanpa mengganggu proses yang sedang berjalan. Posisi jelajah dimulai dari lokasi kursor saat mode ini diaktifkan.

| Tombol | Aksi |
|---|---|
| `↑` (Atas) | Pindah & bacakan baris di atasnya (atau ucapkan "atas" bila sudah di baris paling atas) |
| `↓` (Bawah) | Pindah & bacakan baris di bawahnya (atau ucapkan "bawah" bila sudah di baris paling bawah) |
| `←` (Kiri) | Pindah & bacakan karakter di kirinya (atau ucapkan "awal baris") |
| `→` (Kanan) | Pindah & bacakan karakter di kanannya (atau ucapkan "akhir baris"/"baris kosong") |
| `Ctrl+←` | Lompat & bacakan **kata sebelumnya** |
| `Ctrl+→` | Lompat & bacakan **kata berikutnya** |
| `Home` | Lompat ke **awal baris** & bacakan karakter pertamanya |
| `End` | Lompat ke **akhir baris** & bacakan karakter terakhirnya (atau "baris kosong") |
| `Enter` | Baca ulang **seluruh baris** saat ini |
| `Ctrl+C` / `Escape` | Hentikan ucapan yang sedang berjalan |
| `Ctrl+T` | Keluar dari Mode Penjelajahan (kembali mengetik normal) |

---

## Cara Kerja (Ringkas)

1. **PTY & shell anak** — `ssr` membuat pseudo-terminal (`pty.openpty()`) lalu menjalankan shell (`$SHELL`) sebagai proses anak (`os.fork()` + `os.execvp()`) yang terhubung ke ujung *slave* PTY tersebut sebagai terminal kontrolnya.
2. **Loop I/O non-blocking** — proses utama memakai `select()` untuk memantau dua sumber data sekaligus: input keyboard Anda (`stdin`) dan output dari shell anak (lewat ujung *master* PTY).
3. **Emulasi layar via `pyte`** — setiap byte output dari shell diumpankan ke `pyte.Stream`, yang mem-parsing seluruh escape sequence ANSI/VT100 dan mempertahankan representasi "layar virtual" (posisi kursor, isi setiap sel, atribut warna/reverse-video, dst) — sama seperti yang dilakukan terminal emulator sungguhan, hanya saja di sini dipakai untuk menentukan **apa yang perlu dibacakan**, bukan digambar ke layar.
4. **Heuristik pembacaan** — berdasarkan perubahan pada layar virtual tersebut (baris baru, kursor berpindah, sel ber-atribut reverse-video berubah, baris tergeser keluar layar), `ssr` memutuskan teks apa yang perlu dikirim ke `SpeechEngine.speak()`.
5. **Sintesis suara** — `speech.py` mengikat langsung ke `libespeak-ng.so` lewat `ctypes` (fungsi `espeak_Initialize`, `espeak_SetVoiceByName`, `espeak_SetParameter`, `espeak_Synth`, `espeak_Cancel`, `espeak_Terminate`), sehingga mesin TTS berjalan di dalam proses Python yang sama, tanpa perlu men-spawn proses eksternal untuk tiap ucapan.

---

## Status Pengembangan & Keterbatasan yang Diketahui

Program ini sudah dapat dipakai untuk pekerjaan sehari-hari di shell maupun editor teks, dan sejumlah bug signifikan pada versi-versi sebelumnya (pembacaan berulang "spasi" saat mengetik di `nano`, output panjang yang tidak terbaca karena scroll, dialog TUI yang bisu terhadap navigasi Atas/Bawah, mode interaktif yang gagal setelah berpindah tampilan, crash akibat bug internal `pyte` saat menjalankan `tmux`) sudah diperbaiki. Meski begitu, masih ada beberapa keterbatasan yang perlu diketahui:

- **Heuristik deteksi prompt shell** tetap berbasis tebakan pola akhiran karakter, bukan sinyal pasti dari shell itu sendiri — pada kasus yang jarang, baris output biasa yang persis meniru pola prompt bisa saja terlewat terbaca.
- **Penangkapan baris yang ter-scroll** dibatasi pada satu potongan data yang diterima dari PTY sekaligus; output yang jauh lebih panjang dari tinggi layar dalam SATU semburan data besar tetap bisa kehilangan sebagian baris paling awal.
- **Deteksi item ter-highlight** pada dialog TUI kini memeriksa DUA konvensi: atribut reverse-video klasik, DAN perubahan warna latar eksplisit (untuk tema dialog seperti skema biru khas Debian/Termux yang tidak memakai reverse-video sama sekali). Baris yang dibacakan juga sudah dibersihkan dari karakter bingkai (box-drawing) dan spasi berlebihan supaya fokus pembacaan lebih jelas saat memilih menu. Dialog dengan skema warna yang sangat tidak lazim (mis. banyak warna latar berbeda sekaligus tanpa satu warna "dominan" yang jelas) berpotensi belum terbaca sempurna.
- **Deteksi mode interaktif otomatis** kini tahan terhadap dua sumber kegagalan yang pernah ditemukan: (1) sekuens keluar+masuk alternate-screen yang tiba bersamaan dalam satu potongan data (mis. saat `termux-change-repo` berpindah tahap dan menjalankan proses `whiptail` baru), dan (2) sekuens escape yang **terpotong tepat di batas antar-`read()`** (kernel tidak menjamin satu semburan data PTY selalu utuh dalam satu panggilan) — penyebab utama laporan "mode interaktif gagal setelah konfirmasi". Sebagai jalan pintas tambahan bila deteksi otomatis masih meleset di skenario lain yang belum teridentifikasi, tersedia toggle manual lewat `Ctrl+I`/`Tab` atau Mode Pengaturan (`Ctrl+S` lalu `E`) — lihat [Kontrol Dasar](#kontrol-dasar).
- **Suara "melompat"/pembacaan "spasi" berlebihan saat redraw** — perpindahan kolom kursor di dalam mode interaktif kini hanya dibacakan bila didahului ketikan atau tombol navigasi (panah/Home/End/lompat-kata) yang benar-benar dari pengguna; perpindahan yang murni efek samping redraw internal aplikasi (mis. saat dialog baru sedang digambar ulang) diam-diam diabaikan. Baris/highlight yang benar-benar berubah tetap terbaca melalui jalur pembacaan baris seperti biasa.
- **Pertahanan terhadap bug internal `pyte`** — kesalahan library pihak ketiga (mis. ketidakcocokan versi yang membuat `Screen.report_device_status()` gagal dipanggil, seperti yang pernah terjadi saat menjalankan `tmux`) kini ditangkap dan tidak lagi menjatuhkan seluruh sesi; parser dibuat ulang secara otomatis dan sesi tetap berjalan. Ini bersifat pertahanan umum (menangkap `Exception` secara luas di titik-titik kritis) sehingga bug internal library LAIN yang belum teridentifikasi pun seharusnya tidak lagi menjatuhkan sesi — namun tetap laporkan bila menemukan pesan peringatan di layar agar bisa ditelusuri lebih lanjut.
- **`tmux` kadang memicu mode interaktif secara otomatis saat sesi dimulai** — efek samping ringan dari perbaikan deteksi mode interaktif di atas; tidak mengganggu penggunaan (tidak fatal, tidak berulang), dan untuk saat ini sengaja belum diusut lebih lanjut (diagendakan untuk perbaikan berikutnya).
- **Peringatan `DeprecationWarning: ... multi-threaded, use of fork() may lead to deadlocks`** yang sebelumnya kadang muncul saat memulai sesi sudah diperbaiki pada akarnya: `SpeechEngine` (yang membuat thread audio internal eSpeak NG lewat `espeak_Initialize`) kini baru diinisialisasi **setelah** `os.fork()` di `run()`, bukan lagi di konstruktor -- pada saat fork terjadi, proses Python kembali benar-benar single-threaded sehingga peringatan tersebut tidak lagi muncul.
- **Backend TTS berbasis `ctypes`** (binding langsung ke `libespeak-ng.so`) adalah perubahan yang relatif baru dan bergantung pada lokasi serta kapabilitas *build* `libespeak-ng.so` di perangkat Anda (lihat [Pemecahan Masalah](#pemecahan-masalah)) — sejauh ini sudah diuji secara fungsional, namun perilaku detail pada berbagai perangkat/versi Termux bisa sedikit berbeda.

Secara umum, kendala-kendala di atas bersifat kecil dan tidak menghalangi penggunaan normal sehari-hari.

---

## Pemecahan Masalah

**Tidak ada suara sama sekali, dan muncul pesan `Peringatan: tidak dapat memuat libespeak-ng.so`:**
1. Pastikan paket terpasang: `pkg install espeak-ng`.
2. Cari lokasi pasti library di perangkat Anda:
   ```bash
   find $PREFIX -iname 'libespeak-ng*'
   ```
3. Jika lokasinya tidak umum/tidak ditemukan otomatis, beri tahu path lengkapnya agar daftar kandidat pencarian pada `speech.py` (fungsi `_find_and_load_library`) dapat disesuaikan.

**Suara terputus-putus atau salah bahasa:**
- Cek suara yang tersedia dengan `espeak-ng --voices`, lalu atur `SSR_VOICE` sesuai kode suara yang valid.

**Tampilan aplikasi (`vim`/`htop`/dst.) berantakan setelah mengubah ukuran jendela Termux:**
- Pastikan Anda menjalankan versi `ssr` terbaru — versi lama tidak mempropagasikan ukuran baru ke shell anak.

**`speech.py` tidak ditemukan / `ModuleNotFoundError: No module named 'speech'`:**
- Pastikan `ssr` dan `speech.py` berada di folder yang **sama persis**. Jangan memindahkan salah satunya saja.

**Ingin melaporkan bug:** sertakan langkah reproduksi, aplikasi/perintah yang dijalankan, serta (bila memungkinkan) versi Termux dan versi paket `espeak-ng`.

---

## Berkontribusi

Proyek ini sangat terbuka untuk modifikasi dan perbaikan. Jika Anda memiliki kemampuan pemrograman yang lebih baik dan tertarik dengan konsep ini, silakan lakukan modifikasi (fork) pada repositori ini dan kirimkan pembaruan.
