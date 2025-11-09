import os
import asyncio
import threading
import asyncio
from flask import Blueprint, jsonify, request
from telethon import TelegramClient, events
from telethon.errors import PeerIdInvalidError
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch

from telethon.errors import SessionPasswordNeededError
from utils.helpers import *


BOT_TOKEN = "1419296006:AAHZ6FWdGAX2dWB7ALuPQR7Td9TqTjVExPE"
API_ID = 2350050
API_HASH = "57ce60256d4679ce04c883dbeeb8cf37"

telegram_bp = Blueprint('telegram', __name__)
SESSIONS_DIR = 'sessions'
PROFILE_DIR = 'static/profiles'
os.makedirs(PROFILE_DIR, exist_ok=True)
pending_logins = {}

# مرحله اول: ارسال کد تأیید


@telegram_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    user_id = data.get('user_id')
    phone = data.get('phone')
    api_id = data.get('apiId')
    api_hash = data.get('apiHash')

    if not all([phone, api_id, api_hash]):
        return jsonify({'error': 'phone, apiId و apiHash الزامی هستند'}), 400

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    session_path = os.path.join(SESSIONS_DIR, f"{phone}.session")

    async def send_code():
        client = TelegramClient(session_path, api_id, api_hash)
        await client.connect()
        sent = await client.send_code_request(phone)
        await client.disconnect()
        return sent.phone_code_hash

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    phone_code_hash = loop.run_until_complete(send_code())

    pending_logins[phone] = {
        'api_id': api_id,
        'api_hash': api_hash,
        'phone_code_hash': phone_code_hash
    }
    save_account(user_id, phone, api_id, api_hash, session_path)

    return jsonify({'status': 'code_sent', 'message': 'کد تأیید ارسال شد'})


# مرحله دوم: تأیید کد ارسال‌شده
@telegram_bp.route('/verify', methods=['POST'])
def verify():
    data = request.get_json()
    phone = data.get('phone')
    code = data.get('code')

    if not all([phone, code]):
        return jsonify({'error': 'phone و code الزامی هستند'}), 400

    login_data = pending_logins.get(phone)
    if not login_data:
        return jsonify({'error': 'هیچ لاگین در حال انتظاری برای این شماره یافت نشد'}), 400

    session_path = os.path.join(SESSIONS_DIR, f"{phone}.session")

    async def complete_login():
        client = TelegramClient(
            session_path, login_data['api_id'], login_data['api_hash'])
        await client.connect()
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=login_data['phone_code_hash'])

            me = await client.get_me()

            # download profile photo
            photo_path = None
            if me.photo:
                filename = f"{phone.replace('+', '')}.jpg"
                photo_path = os.path.join(PROFILE_DIR, filename)
                await client.download_profile_photo(me, file=photo_path)

            await client.disconnect()
            pending_logins.pop(phone, None)

            # mark logged in
            mark_logged_in(phone)

            # update profile photo in DB
            if photo_path:
                update_account(phone=phone,
                               telegram_id=me.id,
                               profile_photo=photo_path)

            return {
                'status': 'logged_in',
                'message': f"ورود با موفقیت انجام شد: {me.first_name}",
                'profile_photo': photo_path
            }

        except SessionPasswordNeededError:
            await client.disconnect()
            return {'two_factor_required': True}
        except Exception as e:
            await client.disconnect()
            return {'error': str(e)}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(complete_login())
    return jsonify(result), (200 if 'status' in result or 'two_factor_required' in result else 400)

# مرحله سوم: ارسال رمز دومرحله‌ای


@telegram_bp.route('/verify-password', methods=['POST'])
def verify_password():
    data = request.get_json()
    phone = data.get('phone')
    password = data.get('password')

    if not all([phone, password]):
        return jsonify({'error': 'phone و password الزامی هستند'}), 400

    login_data = pending_logins.get(phone)
    if not login_data:
        return jsonify({'error': 'هیچ لاگین در حال انتظاری برای این شماره یافت نشد'}), 400

    session_path = os.path.join(SESSIONS_DIR, f"{phone}.session")

    async def complete_password_login():
        client = TelegramClient(
            session_path, login_data['api_id'], login_data['api_hash'])
        await client.connect()
        try:
            await client.sign_in(password=password)
            me = await client.get_me()

            # Download profile photo
            photo_path = None
            if me.photo:
                filename = f"{phone.replace('+', '')}.jpg"
                photo_path = os.path.join('static/profiles', filename)
                os.makedirs(os.path.dirname(photo_path), exist_ok=True)
                await client.download_profile_photo(me, file=photo_path)

            await client.disconnect()
            pending_logins.pop(phone, None)

            # Mark as logged in in DB
            mark_logged_in(phone)

            # Update profile photo in DB
            if photo_path:
                update_account(phone=phone,
                               telegram_id=me.id,
                               profile_photo=photo_path)

            return {
                'status': 'logged_in',
                'message': f"ورود با موفقیت انجام شد: {me.first_name}",
                'profile_photo': photo_path
            }

        except Exception as e:
            await client.disconnect()
            return {'error': str(e)}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(complete_password_login())

    return jsonify(result), (200 if 'status' in result else 400)


# ---------- Get account info ----------
@telegram_bp.route('/me', methods=['POST'])
def get_me():
    data = request.get_json()
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id الزامی است'}), 400

    account = get_account(user_id)
    if not account:
        return jsonify({'error': 'حساب یافت نشد. ابتدا وارد شوید'}), 400

    session_path = account['session_path']

    async def fetch_me():
        client = TelegramClient(
            session_path, account['api_id'], account['api_hash'])
        await client.connect()
        me = await client.get_me()
        await client.disconnect()
        return me

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    me = loop.run_until_complete(fetch_me())

    return jsonify({
        'id': me.id,
        'first_name': me.first_name,
        'last_name': me.last_name,
        'username': me.username,
        'phone': me.phone
    })

# ---------- Get participated Groups list ---------


@telegram_bp.route('/my-groups', methods=['POST'])
def my_groups():
    data = request.get_json()
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id الزامی است'}), 400

    account = get_account(user_id)
    if not account:
        return jsonify({'error': 'حساب یافت نشد'}), 404

    session_path = account['session_path']
    api_id = account['api_id']
    api_hash = account['api_hash']

    async def fetch_my_groups():
        groups = []
        client = TelegramClient(session_path, api_id, api_hash)
        await client.connect()
        try:
            async for dialog in client.iter_dialogs():
                if dialog.is_group or dialog.is_channel:
                    groups.append({
                        'id': dialog.id,
                        'title': dialog.title,
                        'username': getattr(dialog.entity, 'username', None)
                    })
        finally:
            await client.disconnect()
        return groups

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        groups = loop.run_until_complete(fetch_my_groups())
        return jsonify({'groups': groups})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@telegram_bp.route('/group-members', methods=['POST'])
def group_members():
    data = request.get_json()
    user_id = data.get('user_id')
    group_link = 'https://t.me/+ztzMYQ09O_42OWQ1'

    if not user_id:
        return jsonify({'error': 'user_id الزامی است'}), 400

    account = get_account(user_id)
    if not account:
        return jsonify({'error': 'حساب یافت نشد'}), 404

    session_path = account['session_path']
    api_id = account['api_id']
    api_hash = account['api_hash']

    async def fetch_members():
        client = TelegramClient(session_path, api_id, api_hash)
        await client.connect()

        try:
            # ✅ Get the logged-in account info
            me = await client.get_me()
            account_info = {
                'id': me.id,
                'full_name': f"{me.first_name or ''} {me.last_name or ''}".strip() or '(بدون نام)',
                'username': me.username,
                'phone': me.phone
            }

            # ✅ Resolve group entity
            entity = await client.get_entity(group_link)

            members_list = []
            offset = 0
            limit = 100

            while True:
                participants = await client(GetParticipantsRequest(
                    channel=entity,
                    filter=ChannelParticipantsSearch(''),
                    offset=offset,
                    limit=limit,
                    hash=0
                ))

                users = participants.users
                if not users:
                    break

                for user in users:
                    first_name = getattr(user, 'first_name', '') or ''
                    last_name = getattr(user, 'last_name', '') or ''
                    full_name = f"{first_name} {last_name}".strip()

                    profile_photo_url = None
                    if user.photo:
                        filename = f"{user.id}.jpg"
                        path = os.path.join(PROFILE_DIR, filename)
                        await client.download_profile_photo(user, file=path)
                        profile_photo_url = f"/{path.replace(os.sep, '/')}"

                    members_list.append({
                        'id': user.id,
                        'full_name': full_name or '(بدون نام)',
                        'username': getattr(user, 'username', None),
                        'phone': getattr(user, 'phone', None),
                        'profile_photo': profile_photo_url
                    })

                offset += len(users)

            return {
                'account': account_info,
                'members': members_list
            }

        finally:
            await client.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(fetch_members())
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@telegram_bp.route('/listen-bot', methods=['GET'])
def listen_bot():
    group_id = -1002696248330  # must be int, not string

    async def run_bot():
        session_path = os.path.join(SESSIONS_DIR, f"bot.session")

        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.start(bot_token=BOT_TOKEN)

        entity = await client.get_entity(group_id)
        print(f"🤖 Bot is now listening to: {entity.title}")

        @client.on(events.NewMessage(chats=entity))
        async def handler(event):
            sender = await event.get_sender()
            sender_id = sender.id
            text = event.raw_text.strip()

            filtered = filter_code(text)
            if filtered.strip():
                print(f"✅ Filtered code(s) from {sender_id}:\n{filtered}")
                save_incoming_message(sender_id, filtered)
            else:
                print(f"⚠️ Message ignored (no valid code): {text}")

        await client.run_until_disconnected()

    thread = threading.Thread(target=lambda: asyncio.run(run_bot()))
    thread.daemon = True
    thread.start()

    return jsonify({'status': 'listening', 'message': '🤖 Bot در حال گوش دادن به گروه است'}), 200


@telegram_bp.route('/process-messages', methods=['GET'])
def process_messages():
    try:
        accounts = get_telegram_accounts()
        if not accounts:
            return jsonify({'message': 'هیچ حساب فعالی یافت نشد.'}), 400

        messages = get_unprocessed_messages()
        if not messages:
            return jsonify({'message': 'هیچ پیام جدیدی وجود ندارد.'}), 200

        # ------------------------------------------------------------
        async def process_account(account):
            """Process messages for one Telegram account."""
            session_path = account['session_path']
            api_id = account['api_id']
            api_hash = account['api_hash']

            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()

            for msg in messages:
                sender_id = msg['sender']
                message = (msg.get('message') or "").strip()

                # Split by new lines and clean
                codes = [line.strip()
                         for line in message.splitlines() if line.strip()]
                if not codes:
                    continue

                if account['telegram_id'] == msg['sender']:
                    continue

                responses = []
                for code in codes:
                    price_data = get_price_by_code(code, account['user_id'])

                    if not price_data['is_bot_allowed']:
                        continue

                    if price_data:
                        if price_data['without_price']:
                            message = get_default_message(account['user_id'])
                            responses.append(
                                f"{code}: {message}")
                        else:
                            responses.append(
                                f"{code}: {price_data['price']} {price_data['brand']}")

                # Skip if no matching codes found
                if not responses:
                    continue

                final_response = "\n".join(responses)

                try:
                    # Try to resolve by sender ID
                    entity = await client.get_input_entity(sender_id)
                except Exception:
                    # Try fallback: username
                    if msg.get('username'):
                        try:
                            entity = await client.get_input_entity(msg['username'])
                        except Exception as e:
                            reason = "کاربر یافت نشد یا شناسه نامعتبر است."
                            print(f"⚠️ {reason}: {e}")
                            await notify_owner(client, account, msg, ', '.join(codes), None, reason)
                            continue
                    else:
                        reason = "کاربر نامشخص است (شناسه یا نام کاربری موجود نیست)."
                        await notify_owner(client, account, msg, ', '.join(codes), None, reason)
                        continue

                # Send message and mark as processed
                try:
                    await client.send_message(entity, final_response)
                    await asyncio.sleep(2)
                    mark_message_processed(msg['id'])
                except PeerIdInvalidError:
                    reason = "پیام قابل ارسال نیست (کاربر در لیست تماس‌ها نیست یا محدودیت حریم خصوصی دارد)."
                    print(f"🚫 {reason}")
                    await notify_owner(client, account, msg, ', '.join(codes), None, reason)
                except Exception as e:
                    reason = f"خطا هنگام ارسال پیام: {e}"
                    print(f"⚠️ {reason}")
                    await notify_owner(client, account, msg, ', '.join(codes), None, reason)

            await client.disconnect()

        # ------------------------------------------------------------
        async def main():
            for acc in accounts:
                await process_account(acc)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())

        return jsonify({'status': 'success', 'message': 'تمام پیام‌ها پردازش شدند.'}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
