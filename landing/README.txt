TREDIS landing (RU + EN) — what to replace before publishing
=============================================================
Search these tokens in ru/*.html and en/*.html and replace them:

1. https://tredis.kbtu.us         -> your real domain or subdomain (canonical, og:url, share links, hreflang)
2. https://t.me/YOUR_BOT_USERNAME -> your Telegram bot link (main button)
3. https://forms.gle/YOUR_CUSTDEV_FORM -> your Google Forms CustDev link
4. var YM_ID = 0;                 -> your Yandex Metrika counter number (metrika.yandex.ru)
5. team@tredis.kbtu.us and +7 000 000 00 00 and tel:+77000000000 -> real email and phone
6. SlideShare iframe (comment in the team section) and YouTube iframe (YOUTUBE_ID) -> uncomment/replace the grey blocks

Hosting: drag this whole folder into Netlify (the signup form uses Netlify Forms), or upload to your kbtu.us subdomain.
Open index.html: it sends visitors to RU or EN by browser language.
