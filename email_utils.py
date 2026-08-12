import smtplib
from email.message import EmailMessage

import streamlit as st

from config import (
    OWNER_EMAILS,
    EMAIL_NOTIFICATIONS_ENABLED,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_TLS,
)


FRIENDLY_STATUS_LABELS = {
    'submitted': 'submitted',
    'approved': 'approved',
    'ordered': 'ordered',
    'fulfilled': 'fulfilled',
    'cancelled': 'cancelled',
}


def send_email(subject: str, body: str, to_email: str) -> None:
    if not to_email:
        return

    if not EMAIL_NOTIFICATIONS_ENABLED:
        print(f'[EMAIL DISABLED] To: {to_email} | Subject: {subject}\n{body}')
        return

    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print('[EMAIL ERROR] SMTP credentials missing.')
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SMTP_USERNAME
    msg['To'] = to_email
    msg.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)



def maybe_send_ball_batch_email(current_count: int) -> None:
    subject = 'Bowling ball order batch ready'
    body = (
        f'The owner dashboard now has {current_count} bowling balls waiting '
        f'in submitted/approved status. The next order batch is ready to place.'
    )
    owner_emails = [str(email).strip() for email in OWNER_EMAILS if str(email).strip()]
    for owner_email in owner_emails:
        send_email(subject, body, owner_email)
    try:
        st.toast('Owner notification sent for bowling ball batch.')
    except Exception:
        pass



def _format_item_line(item: dict) -> str:
    quantity = int(item.get('quantity', 1) or 1)
    name = str(item.get('product_name', '') or '').strip() or 'Item'
    sku = str(item.get('sku', '') or '').strip()
    option_type = str(item.get('option_type', '') or '').strip()
    option_value = str(item.get('option_value', '') or '').strip()
    line_total = float(item.get('total_price', 0) or 0)

    detail = []
    if option_type and option_value:
        detail.append(f'{option_type}: {option_value}')
    if sku:
        detail.append(f'SKU {sku}')
    suffix = f"  ({', '.join(detail)})" if detail else ''

    line = f'  {quantity} x {name}{suffix}  -  ${line_total:,.2f}'

    note = str(item.get('note', '') or '').strip()
    if note:
        line += f'\n      Note: {note}'
    return line


def send_order_status_email(order: dict, new_status: str) -> None:
    """
    One email for the whole order.

    Orders used to be one row per item, so a five-item order sent five separate
    emails on every status change. An order now owns its items and this sends a
    single message listing all of them.
    """
    if new_status not in {'approved', 'ordered', 'fulfilled'}:
        return

    to_email = str(order.get('customer_email', '') or '').strip()
    if not to_email:
        return

    label = FRIENDLY_STATUS_LABELS.get(new_status, new_status)
    customer_name = (
        f"{str(order.get('customer_first_name', '')).strip()} "
        f"{str(order.get('customer_last_name', '')).strip()}"
    ).strip()

    items = order.get('items') or []
    unit_count = sum(int(i.get('quantity', 1) or 1) for i in items)
    order_id = order.get('id')

    if items:
        item_block = '\n'.join(_format_item_line(item) for item in items)
        heading = f"{unit_count} item{'s' if unit_count != 1 else ''} in this order:"
    else:
        item_block = '  (no items recorded)'
        heading = 'Items:'

    order_note = str(order.get('note', '') or '').strip()
    note_block = f"\nYour note: {order_note}\n" if order_note else ''

    subject = f"Your bowling order is now {label}"
    if order_id:
        subject += f" (order #{order_id})"

    body = (
        f"Hi {customer_name or 'there'},\n\n"
        f"Your order has been updated to {label}.\n\n"
        f"{heading}\n"
        f"{item_block}\n"
        f"{note_block}"
        f"\nOrder total: ${float(order.get('total_price', 0) or 0):,.2f}\n"
        f"Status: {label}\n\n"
        f"This is an automatic update from the team bowling order dashboard."
    )
    send_email(subject, body, to_email)
    try:
        st.toast(f"Status email sent to {to_email}.")
    except Exception:
        pass
