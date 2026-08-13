# VolkaPortal Web Brand Assets

Tüm görseller gerçek alfa şeffaflığına sahiptir. PNG dosyaları RGBA, WebP
dosyaları kayıpsız ve şeffaf, favicon ise çoklu boyutlu ICO biçimindedir.

## Önerilen kullanım

- Giriş ekranı: `logo/volkaportal-logo-stacked-768.png`
- Masaüstü header: `logo/volkaportal-logo-horizontal-640.png`
- Açık sidebar: `logo/volkaportal-logo-horizontal-400.png`
- Lacivert/koyu sidebar: `logo/volkaportal-logo-horizontal-on-dark-400.png`
- Kapalı sidebar: `icon/volkaportal-stag-128.png`
- Büyük dekoratif geyik: `icon/volkaportal-stag-512.png`
- Tarayıcı ikonu: `favicon/favicon.ico`
- Apple Touch Icon: `favicon/favicon-180x180.png`
- PWA ikonu: `favicon/favicon-512x512.png`

## HTML örneği

```html
<link rel="icon" href="/static/brand/favicon/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/static/brand/favicon/favicon-180x180.png">

<picture>
  <source srcset="/static/brand/webp/volkaportal-logo-horizontal.webp" type="image/webp">
  <img src="/static/brand/logo/volkaportal-logo-horizontal-640.png"
       alt="VolkaPortal — Kurumsal Süreç Yönetim Platformu">
</picture>
```

Görselleri CSS ile büyütmek yerine ihtiyaca en yakın veya daha büyük dosyayı
seçin; `width: auto; height: auto; object-fit: contain;` kullanın.
