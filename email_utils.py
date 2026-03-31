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



def send_order_status_email(order: dict, new_status: str) -> None:
    if new_status not in {'approved', 'ordered', 'fulfilled'}:
        return

    to_email = str(order.get('customer_email', '') or '').strip()
    if not to_email:
        return

    customer_name = f"{str(order.get('customer_first_name', '')).strip()} {str(order.get('customer_last_name', '')).strip()}".strip()
    product_name = str(order.get('product_name', 'your order')).strip() or 'your order'
    quantity = int(order.get('quantity', 1) or 1)
    option_type = str(order.get('option_type', '') or '').strip()
    option_value = str(order.get('option_value', '') or '').strip()

    option_line = ''
    if option_type and option_value:
        option_line = f"\n{option_type}: {option_value}"

    subject = f"Your bowling order is now {FRIENDLY_STATUS_LABELS.get(new_status, new_status)}"
    body = (
        f"Hi {customer_name or 'there'},\n\n"
        f"Your order status has been updated to {FRIENDLY_STATUS_LABELS.get(new_status, new_status)}.\n\n"
        f"Product: {product_name}\n"
        f"SKU: {str(order.get('sku', '') or '').strip()}\n"
        f"Quantity: {quantity}"
        f"{option_line}\n"
        f"Status: {FRIENDLY_STATUS_LABELS.get(new_status, new_status)}\n"
        f"Total: ${float(order.get('total_price', 0) or 0):,.2f}\n\n"
        f"This is an automatic update from the team bowling order dashboard."
    )
    send_email(subject, body, to_email)
    try:
        st.toast(f"Status email sent to {to_email}.")
    except Exception:
        pass
