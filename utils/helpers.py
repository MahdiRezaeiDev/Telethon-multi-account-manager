import re
from config.database import get_connection  # import the connection
from datetime import datetime


def save_account(user_id, phone, api_id, api_hash, session_path, photo_path=None):
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        INSERT INTO telegram_accounts (user_id, phone, api_id, api_hash, session_path, profile_photo, is_logged_in, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, 0, CURRENT_TIMESTAMP)
        ON DUPLICATE KEY UPDATE api_id=%s, api_hash=%s, session_path=%s, profile_photo=%s
    """
    cursor.execute(query, (user_id, phone, api_id, api_hash, session_path, photo_path,
                           api_id, api_hash, session_path, photo_path))
    conn.commit()
    cursor.close()
    conn.close()


def mark_logged_in(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE telegram_accounts SET is_logged_in=1 WHERE phone=%s", (phone,))
    conn.commit()
    cursor.close()
    conn.close()


def update_account(phone, **kwargs):
    if not kwargs:
        return

    conn = get_connection()
    cursor = conn.cursor()
    set_clause = ', '.join(f"{key}=%s" for key in kwargs.keys())
    values = list(kwargs.values())
    values.append(phone)

    query = f"UPDATE telegram_accounts SET {set_clause} WHERE phone=%s"
    cursor.execute(query, values)
    conn.commit()
    cursor.close()
    conn.close()

# --- Get account by phone ---


def get_account(id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM telegram_accounts WHERE user_id=%s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

# --- Mark account as logged in ---


def mark_logged_in(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE telegram_accounts SET is_logged_in=1 WHERE phone=%s", (phone,))
    conn.commit()
    cursor.close()
    conn.close()

# ✅ Save the incoming codes message in to the database


def save_incoming_message(sender_id, text):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
                    INSERT INTO incoming_messages (sender, message, is_resolved, created_at, updated_at)
                    VALUES (%s, %s, 0, %s, %s)
                """, (sender_id, text, datetime.now(), datetime.now()))
    conn.commit()
    cursor.close()
    conn.close()


# ✅ Get all logged-in accounts
def get_telegram_accounts():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM telegram_accounts WHERE is_logged_in = 1")
    accounts = cursor.fetchall()
    cursor.close()
    conn.close()
    return accounts

# ✅ Fetch all unprocessed messages


def get_unprocessed_messages():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM incoming_messages WHERE is_resolved = 0")
    messages = cursor.fetchall()
    cursor.close()
    conn.close()
    return messages

# ✅ Get price for a given code


def get_price_by_code(code, user_id):
    """
    Fetch price for a given code, considering similar_products,
    and only for products belonging to the specified user_id.
    """

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Step 1: Find product(s) matching the code or similar_products
    query = """
        SELECT p.id AS product_id
        FROM products p
        LEFT JOIN similar_products sp ON sp.product_id = p.id
        WHERE p.user_id = %s AND (p.code = %s OR sp.similar_code = %s)
        LIMIT 1
    """
    cursor.execute(query, (user_id, code, code))
    product = cursor.fetchone()

    if not product:
        cursor.close()
        conn.close()
        return None

    product_id = product['product_id']

    # Step 2: Get price from prices table using the product_id
    cursor.execute(
        "SELECT * FROM products WHERE id = %s LIMIT 1", (product_id,))
    price_data = cursor.fetchone()

    cursor.close()
    conn.close()

    return price_data


# ✅ Mark a message as processed


def mark_message_processed(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE incoming_messages SET is_resolved = 1 WHERE id = %s", (message_id,))
    conn.commit()
    cursor.close()
    conn.close()

# ✅ Filter the message to extract codes


def filter_code(message: str):
    if not message or not message.strip():
        return ""

    lines = message.split("\n")
    filtered_codes = []

    for code in lines:
        # Remove things inside [brackets]
        code = re.sub(r'\[[^\]]*\]', '', code)

        # Split by colon or comma
        parts = re.split(r'[:,]', code, maxsplit=1)

        right_side = ""
        if len(parts) > 1 and "/" in parts[1]:
            right_side = parts[1].split("/")[0]
        elif len(parts) > 1:
            right_side = parts[1]

        right_side = re.sub(r'[^a-zA-Z0-9 ]', '', right_side.strip())
        candidate = right_side if right_side else re.sub(
            r'[^a-zA-Z0-9 ]', '', code).strip()

        filtered_codes.append(candidate)

    # Filter codes with first word length > 6
    final_codes = []
    for item in filtered_codes:
        data = item.split()
        if len(data) > 0 and len(data[0]) > 6:
            final_codes.append(item)

    # Merge parts if needed
    mapped_final = []
    for item in final_codes:
        parts = item.split()
        if len(parts) >= 2:
            part_one, part_two = parts[0], parts[1]
            if not re.search(r'[a-zA-Z]{4,}', part_one) and not re.search(r'[a-zA-Z]{4,}', part_two):
                mapped_final.append(part_one + part_two)
                continue
        mapped_final.append(parts[0])

    # Remove items with long consecutive letters
    non_consecutive = [
        item for item in mapped_final if not re.search(r'[a-zA-Z]{4,}', item)]

    # Uppercase + unique
    non_consecutive = list(set([item.upper() for item in non_consecutive]))

    # Return joined string with newline
    return "\n".join([item.split(" ")[0] for item in non_consecutive]) + "\n"


async def notify_owner(client, account, code, price_data, msg, reason):
    owner_id = account['owner_id'] if 'owner_id' in account else None
    if not owner_id:
        return

    code_text = code if code else "کد نامشخص"
    price_text = price_data['price'] if price_data else "—"
    user_text = msg.get('username', msg.get('sender'))

    message = (
        f"❗ پیغام شما برای کاربر {user_text} ارسال نشد.\n\n"
        f"🔹 کد: {code_text}\n"
        f"💰 قیمت: {price_text}\n"
        f"🚫 دلیل: {reason}"
    )

    try:
        await client.send_message(owner_id, message)
    except Exception as e:
        print(f"⚠️ Failed to notify owner: {e}")


def get_default_message(user_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT message
        FROM default_messages
        WHERE user_id = %s
        LIMIT 1
    """

    cursor.execute(query, (user_id,))
    message = cursor.fetchone()

    cursor.close()
    conn.close()

    # Return just the message string, or None if not found
    return message['message'] if message else None
