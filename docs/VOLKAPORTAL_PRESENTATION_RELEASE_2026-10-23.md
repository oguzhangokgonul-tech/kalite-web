# VolkaPortal tanitim sunumu

- URL: `/static/presentations/vp-tanitim-a91f4c72/index.html`
- 16 bolumlu, koyu marka temali HTML sunumu; once platform kabiliyetlerini, sonra modulleri anlatir. Masaustu, tablet ve mobil duzenleri, bolum listesi, klavye gezinmesi, tam ekran ve gorsel buyutme icerir.
- Urun ekranlari daha genis alanda, kaynak en-boy orani korunarak ve kirpilma olmadan gosterilir. Modul ekranlari icin daha tam demo yakalamalari kullanilir.
- Uygulama ekranlari, onceki sunum icin `presentations/volkaportal-customer-2026-10-23/.build/demo_server.py` tarafindan uretilen `Demo Uretim A.S.` verilerinden alinmistir. Fotografik uretim/saha gorselleri bu sunum icin AI ile uretilmistir; gercek tesis veya personel fotografi olarak sunulmamalidir.
- Sayfa menude listelenmez ve `noindex` ister. Buna ragmen `/static/` herkese aciktir; baglantiyi bilen herkes sayfayi ve gorselleri gorebilir. Gizli musteri verisi eklenmemelidir.
- Yalnizca statik dosyalar ve UI testi eklenir. Veritabani migration, Flask servis yeniden baslatma ve yeni subdomain/SSL degisikligi gerekmez.

## Kontroller

1. `node --check app/static/presentations/vp-tanitim-a91f4c72/deck.js`
2. `PLAYWRIGHT_MODULE_PATH=<playwright-yolu> node tests/ui/volkaportal_presentation.mjs`
3. Canlida `PRESENTATION_URL=https://volkaportal.com/static/presentations/vp-tanitim-a91f4c72/index.html` ile ayni UI testini tekrar calistir.
4. HTTPS 200, medya/CSS/JS 200, Turkce metin, masaustu/mobil gezinme ve konsol hatalarini kontrol et.

## Geri donus

Yalnizca bu sunumun statik klasorunu yayin dizininden cikar veya onceki commit'e donuk yeni bir geri alma commit'i yayinla. Uygulama verileri ve diger moduller etkilenmez.
