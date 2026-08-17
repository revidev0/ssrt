# Termux Screen Reader (SSR)

Skrip Python untuk membuat emulator terminal pembaca layar lisan di Termux. Skrip ini berbasis PTY dan pyte[cite: 1]. Proyek ini dirancang dan dioptimalkan untuk aksesibilitas mandiri, navigasi tingkat lanjut, serta interaksi TUI[cite: 1].

## Fitur
* Menangkap baris yang bergeser keluar layar[cite: 1].
* Mendeteksi dan menyesuaikan ukuran resolusi terminal[cite: 1].
* Menggunakan eSpeak atau espeak-ng untuk sintesis suara[cite: 1].

## Status Pengembangan dan Bug
Secara konsep dasar, program ini sudah dapat berjalan. Namun, karena keterbatasan kemampuan pemrograman saya saat ini, masih terdapat beberapa masalah yang membutuhkan perbaikan:
* Interaksi dengan antarmuka pengguna (UI) dialog TUI seperti `termux-change-repo` masih memiliki kendala dan belum berfungsi dengan sempurna[cite: 1].
* Dukungan pengetikan dan pembacaan pada editor teks seperti `nano` sudah mengalami peningkatan dari versi sebelumnya dan berjalan lebih baik[cite: 1].

## Berkontribusi
Proyek ini sangat terbuka untuk modifikasi dan perbaikan. Jika Anda memiliki kemampuan pemrograman yang lebih baik dan tertarik dengan konsep ini, silakan lakukan modifikasi (fork) pada repositori ini dan kirimkan pembaruan.
