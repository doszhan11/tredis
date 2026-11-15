TREDIS NLP prototype
====================
python tredis_nlp.py     # runs the demo and the evaluation (no dependencies, Python 3.9+)

Files
- tredis_nlp.py     text -> alert settings (baseline and improved parser), alert JSON -> text (Kazakh, Russian, English)
- nlp_data.py       18 dev sentences (used to tune the parser) and 50 test sentences (held out)
- glossary.json     Sweep, Raid, MSS, ... in 3 languages (the "meaning" layer)
- alert_schema.json JSON Schema of the GENESIS alert (the "metadata" layer)

Notes
- The test sentences were written for this evaluation; they are not real user messages.
- First run on the 50 held-out sentences: improved parser 48/50 exact (96%), baseline 8/50 (16%).
  The 2 errors exposed stemming bugs in the direction words; they were fixed afterwards.
  The fixed parser scores 50/50, but that number is no longer a held-out result.
