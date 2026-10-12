# Mobil Merkez - Musteri Sikayeti

Lider istegi ve canliya alma onayiyla 12 Ekim 2026 tarihinde yayinlandi.
Ozellik commit'i: `6084af77c37ae14591f7dd696e12d28ee71664a8`.

## Degisiklik

- Mobil Merkez hizli islemlerine `Müşteri Şikayeti` karti eklendi.
- Hedef: `/musteri-geri-bildirimleri/yeni`; musteri/proje bilgisi ve once/sonra gorselleri olan mevcut form.
- Kart firma baglami, etkin `customer_feedback_portal`, `customer_portal.view` ve `customer_portal.create` gerektirir.
- Eski `Yeni Şikayet` akisina dokunulmadi; veri, rol veya sema degisikligi yapilmadi.

## Dogrulama

- Ana ajan: PWA ve ic geri bildirim kapsaminda 67 test basarili.
- Bagimsiz QA ajani: PWA, mobil performans ve ic geri bildirim kapsaminda 71 test basarili; yayin engeli bildirilmedi.
- Tarayici: 390/768/1440 pikselde kart gorunumu ve form yonlendirmesi basarili; sayfa tasmasi yok, kart yuksekligi 78/88/88 piksel.
- Graphify yalniz yerel AST analizi ile guncellendi; commit/deploy kapsaminda degil.
- Canli: uygulama, nginx, hatirlatma ve webhook zamanlayicilari aktif; servis hata logunda yeni kayit yok.
- Iki sirket giris adresi HTTPS 200. Canli verinin gecici kopyasinda iki sirketin kimlikli Mobil Merkez karti ve yeni formu dogrulandi; canli is verisine test kaydi yazilmadi.

## Yedek ve Geri Donus

- Taze yedek: `volkaportal-backup-20261012-180725.zip`, 59.402.594 bayt, 204 ek dosya.
- Sunucu: `/var/data/aksiyon-takip/backups/mobile-feedback-release.TjpxunSz/archive/`.
- Sunucu disi: `C:\Users\Asus\VolkaPortalBackups\20261012-mobile-feedback\`.
- SHA256: `491a000b5341b3531c8e083273f428287e63bae05e67dfe8319b3aea0b0c8de8`.
- Checksum, SQLite integrity ve geri yukleme dry-run basarili; sunucu disi kopya ayni SHA256 ile dogrulandi.
- Sema `202610120001` olarak kaldi; eski is kayitlarinin ozetleri degismedi.
- Geri donus gerekirse yalniz kart commit'ini geri alan yeni commit yayinlanabilir; bu UI degisikligi icin veritabani geri yuklemesi gerekmez.
