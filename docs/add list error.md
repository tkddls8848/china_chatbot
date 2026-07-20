2026-07-20 21:31:29,836 [INFO] [sina] 다이제스트 전송 완료: 杰创智能 1500~3000 만 원 분할 매수
2026-07-20 21:31:29,839 [INFO] [sina] 다이제스트 전송 완료: 九州일궤의 이사회원이자 핵심 기술자 샤오빈이 개인 자금
2026-07-20 21:31:29,841 [INFO] [sina] 다이제스트 전송 완료: 캐나다 6 월 CPI, 인플레이션 둔화
2026-07-20 21:31:29,841 [INFO] Job "fetch_all (trigger: interval[0:05:00], next run at: 2026-07-20 21:35:33 KST)" executed successfully
2026-07-20 21:35:33,812 [INFO] Running job "fetch_all (trigger: interval[0:05:00], next run at: 2026-07-20 21:40:33 KST)" (scheduled at 2026-07-20 21:35:33.798827+09:00)
2026-07-20 21:35:33,812 [INFO] [GLOBAL] 이번 주기 처리 소스 5/5 (커서 0->0): futu, sina, gnews, gnews_us, rss:mk-stock
2026-07-20 21:35:34,368 [INFO] [rss:mk-stock] 기사 준비: 수집 10 / 확인 10 / 중복 10 / 번역 준비 0 / 번역 실패 0
2026-07-20 21:35:34,959 [INFO] [gnews_us] 기사 준비: 수집 10 / 확인 10 / 중복 10 / 번역 준비 0 / 번역 실패 0
2026-07-20 21:35:35,339 [INFO] [gnews] 발행시각 필터 후 기사 0건 (수집 10건, 최근 48시간)
2026-07-20 21:35:55,776 [WARNING] [TRANSLATE] global title remains Chinese; requesting Korean rewrite: 普惠加拿大公司获10亿美元JPATS发动机大修合同
2026-07-20 21:36:03,452 [WARNING] [TRANSLATE] global title remains Chinese after rewrite; using the Korean brief as title: RTX 산하 P&G Canada 가 미국 JPATS T-6 조종사 훈련기 엔진 대수리 사업에 9 년간, 총 10 억 달러 규모의 유지보수 계약을        
2026-07-20 21:36:17,962 [INFO] [sina] 기사 준비: 수집 10 / 확인 3 / 중복 0 / 번역 준비 3 / 번역 실패 0
2026-07-20 21:36:25,239 [INFO] [futu] 기사 준비: 수집 10 / 확인 3 / 중복 0 / 번역 준비 3 / 번역 실패 0
2026-07-20 21:36:26,265 [INFO] [futu] 다이제스트 전송 완료: 캐나다 6 월 CPI 연율 2.8%
2026-07-20 21:36:26,267 [INFO] [futu] 다이제스트 전송 완료: 캐나다 6 월 핵심 CPI 연율 2.1%
2026-07-20 21:36:26,268 [INFO] [futu] 다이제스트 전송 완료: 캐나다 6 월 CPI 감소
2026-07-20 21:36:26,270 [INFO] [sina] 다이제스트 전송 완료: 국여행합 주주변동, 실권자 변경
2026-07-20 21:36:26,273 [INFO] [sina] 다이제스트 전송 완료: RTX 산하 P&G Canada 가 미국 JPATS T
2026-07-20 21:36:26,275 [INFO] [sina] 다이제스트 전송 완료: 온다스, 호주 국방부 690만 달러 주문
2026-07-20 21:36:26,276 [INFO] Job "fetch_all (trigger: interval[0:05:00], next run at: 2026-07-20 21:40:33 KST)" executed successfully
2026-07-20 21:38:13,269 [ERROR] [TELEGRAM] update processing failed: Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message
Traceback (most recent call last):
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\ext\_application.py", line 1315, in process_update 
    await coroutine
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\ext\_handlers\basehandler.py", line 159, in handle_update
    return await self.callback(update, context)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\china_chat_bot\china_chatbot\app\core\access.py", line 98, in wrapper
    await handler(update, context)
  File "C:\china_chat_bot\china_chatbot\app\handlers\commands.py", line 35, in callback_handler
    if await handle_menu_callback(update, context, data):
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\china_chat_bot\china_chatbot\app\handlers\navigation.py", line 208, in handle_menu_callback
    await cmd_menu(update, _context(context, []))
  File "C:\china_chat_bot\china_chatbot\app\watchlist\handlers.py", line 64, in cmd_menu
    await send(
    ...<3 lines>...
    )
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\_message.py", line 4243, in edit_text
    return await self.get_bot().edit_message_text(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<15 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\ext\_extbot.py", line 1733, in edit_message_text   
    return await super().edit_message_text(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<15 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\_bot.py", line 4548, in edit_message_text
    return await self._send_message(
           ^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<11 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\ext\_extbot.py", line 630, in _send_message        
    result = await super()._send_message(
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<23 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\_bot.py", line 820, in _send_message
    result = await self._post(
             ^^^^^^^^^^^^^^^^^
    ...<7 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\_bot.py", line 704, in _post
    return await self._do_post(
           ^^^^^^^^^^^^^^^^^^^^
    ...<6 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\ext\_extbot.py", line 370, in _do_post
    return await super()._do_post(
           ^^^^^^^^^^^^^^^^^^^^^^^
    ...<6 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\_bot.py", line 733, in _do_post
    result = await request.post(
             ^^^^^^^^^^^^^^^^^^^
    ...<6 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\request\_baserequest.py", line 198, in post        
    result = await self._request_wrapper(
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<7 lines>...
    )
    ^
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\request\_baserequest.py", line 375, in _request_wrapper
    raise exception
telegram.error.BadRequest: Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message
2026-07-20 21:39:10,749 [ERROR] [TELEGRAM] update processing failed: 'types.SimpleNamespace' object has no attribute 'user_data'
Traceback (most recent call last):
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\ext\_application.py", line 1315, in process_update 
    await coroutine
  File "C:\china_chat_bot\china_chatbot\venv\Lib\site-packages\telegram\ext\_handlers\basehandler.py", line 159, in handle_update
    return await self.callback(update, context)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\china_chat_bot\china_chatbot\app\core\access.py", line 98, in wrapper
    await handler(update, context)
  File "C:\china_chat_bot\china_chatbot\app\handlers\navigation.py", line 330, in handle_menu_text
    await cmd_add(update, _context(context, [text.strip()]))
  File "C:\china_chat_bot\china_chatbot\app\watchlist\handlers.py", line 78, in cmd_add
    selection = context.user_data.pop("add_market", "")
                ^^^^^^^^^^^^^^^^^
AttributeError: 'types.SimpleNamespace' object has no attribute 'user_data'

관심종목 열기 및 메뉴버튼을 이용한 관심종목 추가 실패 (홍콩, 09988)