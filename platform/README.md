# Learning platform (tradeacademy.world)

**The code of the platform is not in this repository yet.** It was deployed to Railway straight from a local folder, and that folder still has to be found and added here.

What is known:

- Railway: project `trading-academy`, service `web`, domains `tradeacademy.world` and `www.tradeacademy.world`.
- Data: SQLite and lesson videos on the Railway volume `web-data` (`/data`). This is students' data and must never be committed.
- Variables: `DATA_DIR`, `DELETE_CODE`, `MAX_UPLOAD_MB`, `OWNER_LOGIN`, `OWNER_PASSWORD`, `SITE_NAME`.
- Features: roles, streams, video lessons and articles, comments, analytics, device and region log, watermark over the video, landing page at `/tredis`.

To add it: copy the site folder here without the database, uploads and virtual environment, and keep secrets out of the code.
