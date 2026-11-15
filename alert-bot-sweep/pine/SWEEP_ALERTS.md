# Genesis Sweep: ботқа alert қою

Скрипт TradingView аккаунтта **Genesis Sweep BOT** деген атпен сақталған (бастапқы коды: `pine/genesis_sweep.pine`).
Бір alert бір нарықтың барлық Sweep таймфреймін (M12, M15, M20, M30, M45, H1, H4, D1) қамтиды.
Сондықтан әр нарыққа **бір ғана** alert керек, барлығы 12.

## Webhook URL

```
https://sweep-bot-production.up.railway.app/webhook/sweep
```

Бот тек TradingView-дің ресми IP адрестерінен келген хабарды қабылдайды, сондықтан URL ішінде құпия кілт жоқ.

## Әр нарық үшін

FOREXCOM: XAUUSD, XAUEUR, BTCUSD, XAGUSD, GBPUSD, EURUSD, GER40, AUDUSD, USDJPY, CADJPY.
OANDA: XAUUSD, EURUSD (ботта «XAUUSD (OANDA)», «EURUSD (OANDA)» деген бөлек нарық).

1. Символды ашыңыз, таймфреймді **M1** қойыңыз. M12, M20, M45 свечаларының басы дәл ұсталуы үшін график M1 болуы керек.
2. Индикаторлар → Мои скрипты → **Genesis Sweep BOT** қосыңыз. Баптауларды өзгертпеңіз.
3. Alert жасаңыз (Alt + A):
   - Условие: **Genesis Sweep** → **при любом вызове функции alert()** (Any alert() function call).
   - Срок действия: шексіз (Open-ended).
   - Уведомления → **Webhook URL**: жоғарыдағы адрес.
   - Атауы: `SWEEP XAUUSD` сияқты.
4. Alert жасалғаннан кейін индикаторды графиктен алып тастауға болады.

## Ескерту

- Индикатор баптауы alert жасалған сәтте alert ішіне «қатып» қалады. Баптауды өзгертсеңіз, alert-ты қайта жасау керек.
- Тексеру: ботта /start → «🧪 Тест хабар».
