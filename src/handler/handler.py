def handle_zalo_incoming(body: dict):
    # print(body)
    body = {'event_name': 'message.image.received', 'message': {'date': 1776450581626, 'chat': {'chat_type': 'PRIVATE', 'id': '833a6db79ee377bd2ef2'}, 'caption': '', 'message_id': '635fdf5d2c79cc20956f', 'message_type': 'CHAT_PHOTO', 'from': {'id': '833a6db79ee377bd2ef2', 'is_bot': False, 'display_name': 'Hoang Hoan'}, 'photo_url': 'https://photo-stal-11.zdn.vn/no/jpg/f14423af321efc40a50f/278739967834305344.jpg'}}
    if body['message']['message_type'] == 'CHAT_PHOTO':
        photo_url = body['message']['photo_url']
        caption = body['message']['caption']
        if caption:
            print(f"{caption} - {photo_url}")
        else:
            handle_zalo_ask_for_caption(photo_url)
            print(f"{photo_url}")

def handle_zalo_ask_for_caption(photo_url: str):
    pass