❯ 026-07-20 21:17:10,338 [INFO] [rss:mk-stock] 다이제스트 전송 완료: 금리 호재로 은행주 반등          2026-07-20 21:17:10,341 [INFO] Job "fetch_all (trigger: interval[0:05:00], next run at:             2026-07-20 21:20:33 KST)" executed successfully                                                     2026-07-20 21:18:24,715 [INFO] [BRIEFING] 마감 브리핑 전송 완료
  2026-07-20 21:18:36,268 [INFO] [SCORE] 시세 조회: 14종목 (2026-07-20 ~ 2026-07-20)
  2026-07-20 21:18:40,842 [WARNING] [PRICE] AkShare retry exhausted for 03589 (CN): ('Connection    
  aborted.', RemoteDisconnected('Remote end closed connection without response'))
  2026-07-20 21:18:43,007 [ERROR] HTTP Error 404:
  {"quoteSummary":{"result":null,"error":{"code":"Not Found","description":"Quote not found for     
  symbol: 03589"}}}
  2026-07-20 21:18:43,356 [ERROR] $03589: possibly delisted; no timezone found
  2026-07-20 21:18:43,357 [ERROR]
  1 Failed download:
  2026-07-20 21:18:43,357 [ERROR] ['03589']: possibly delisted; no timezone found
  2026-07-20 21:18:48,068 [WARNING] [PRICE] AkShare retry exhausted for 054980 (CN): ('Connection   
  aborted.', RemoteDisconnected('Remote end closed connection without response'))
  2026-07-20 21:18:49,725 [ERROR] HTTP Error 404:
  {"quoteSummary":{"result":null,"error":{"code":"Not Found","description":"Quote not found for     
  symbol: 054980.SZ"}}}
  2026-07-20 21:18:49,951 [ERROR] $054980.SZ: possibly delisted; no timezone found
  2026-07-20 21:18:49,952 [ERROR]
  1 Failed download:
  2026-07-20 21:18:49,952 [ERROR] ['054980.SZ']: possibly delisted; no timezone found
  2026-07-20 21:18:54,096 [WARNING] [PRICE] AkShare retry exhausted for 09567 (CN): ('Connection    
  aborted.', RemoteDisconnected('Remote end closed connection without response'))
  2026-07-20 21:18:54,781 [ERROR] $09567: possibly delisted; no timezone found
  2026-07-20 21:18:54,782 [ERROR]
  1 Failed download:
  2026-07-20 21:18:54,782 [ERROR] ['09567']: possibly delisted; no timezone found
                                                                                                    

● Searching for 2 patterns, reading 1 file… (ctrl+o to expand)
  Searched for 3 patterns, read 2 files (ctrl+o to expand)

● 로그의l3건i실패는1전부↓같은 뿌리입니다h—nmarket 태그가 코드 형식과 어긋나는데 태그가 무조건 
  이깁니다.

  app/stocks/market_data.py:19-33, normalize_market()는 명시된 market이 화이트리스트에 있으면 즉시
  반환합니다. 그래서 리서치 로그가 market: "CN"으로 태깅한 종목은 코드 모양이 아무리 홍콩/한국이어도
  CN으로 굳습니다:

  ┌────────┬─────────────┬──────┬─────────────────────────────────────────────────────┐
  │  코드  │  실제 시장  │ 태그 │                        결과                         │  ├────────┼─────────────┼──────┼─────────────────────────────────────────────────────┤             
  │ 03589  │ HK (5자리)  │ CN   │ stock_zh_a_hist("003589") → 실패, Yahoo 03589 → 404 │
  ├────────┼─────────────┼──────┼─────────────────────────────────────────────────────┤
  │ 09567  │ HK (5자리)  │ CN   │ 동일                                                │
  ├────────┼─────────────┼──────┼─────────────────────────────────────────────────────┤
  │ 054980 │ KR (코스닥) │ CN   │ Yahoo 054980.SZ → 404 (SZ는 000/002/300대)          │
  └────────┴─────────────┴──────┴─────────────────────────────────────────────────────┘

  normalize_market이 line 31의 \d{5} → HK 규칙을 갖고 있는데도 line 21에서 먼저 빠져나가 도달하지   
  못합니다.

  부수적으로 yahoo_ticker() (market_data.py:54)의 폴스루도 문제입니다. market=CN이면서 6자리가 아닌 
  코드는 접미사 없이 03589 그대로 반환돼 Yahoo에서 무조건 404입니다. 조용히 None을 주는 게 아니라   
  매번 3회 재시도 + 404 로그를 태우고 있습니다.

  AkShare retry exhausted의 RemoteDisconnected는 별개로 보이지만 — 잘못된 심볼로 조회할 때
  동방재부가 연결을 끊는 것이라 같은 원인일 가능성이 높습니다 (기억해둔 overseas-IP 스로틀링과는    
  다른 양상).

  고칠 방향 두 가지:

  1. 코드 형식이 태그와 충돌하면 형식을 신뢰 — normalize_market에서 CN 계열 태그 + 5자리 코드는     
  HK로, 6자리인데 0/6/3으로 시작하지 않으면 태그를 버리고 재추론.
  2. yahoo_ticker 폴스루를 실패로 처리 — 접미사를 못 붙이는 조합은 None을 반환해 네트워크 호출      
  자체를 건너뛰기.

  어느 쪽으로 갈지, 아니면 둘 다 적용할지 말씀해주시면 수정하겠습니다. 다만 근본은 리서치 로그의    
  market 태깅 품질이라 거기도 손볼 여지가 있어 보입니다.

❯ /model                                                                                            

❯ /model                                                                                              1. 코드 형식이 태그와 충돌하면 형식을 신뢰 — normalize_market에서 CN 계열 태그 + 5자리 코드는     
  HK로, 6자리인데 0/6/3으로 시작하지 않으면 태그를 버리고 재추론.
  2. yahoo_ticker 폴스루를 실패로 처리 — 접미사를 못 붙이는 조합은 None을 반환해 네트워크 호출      
  자체를 건너뛰기.

  어느 쪽으로 갈지, 아니면 둘 다 적용할지 말씀해주시면 수정하겠습니다. 다만 근본은 리서치 로그의    
  market 태깅 품질이라 거기도 손볼 여지가 있어 보입니다.
