"""Telegram triage bot — factory wiring the FastmailAdapter behind handlers."""

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler


def build_application(adapter, bot_token, allowed_user_id, nudge_schedule=None):
    allowed_user_id = int(allowed_user_id)
    application = Application.builder().token(bot_token).build()
    application.bot_data["adapter"] = adapter
    application.bot_data["allowed_user_id"] = allowed_user_id
    application.bot_data["nudge_schedule"] = nudge_schedule or None
    application.add_handler(CommandHandler("mail", handle_mail))
    application.add_handler(CallbackQueryHandler(handle_callback))

    nudge_time = _parse_schedule(nudge_schedule)
    if nudge_time is not None:
        application.job_queue.run_daily(
            nudge_job,
            time=nudge_time,
            data={"adapter": adapter, "allowed_user_id": allowed_user_id},
        )

    return application


def _parse_schedule(schedule):
    if not schedule:
        return None
    for fmt in ("%H:%M", "%H%M"):
        try:
            return datetime.strptime(schedule, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"NUDGE_SCHEDULE unrecognized: {schedule!r}")


async def nudge_job(context):
    adapter = context.job.data["adapter"]
    allowed_user_id = context.job.data["allowed_user_id"]
    try:
        unread = adapter.list_unread()
    except Exception as exc:
        await context.bot.send_message(
            chat_id=allowed_user_id,
            text=_safe_error_text(exc, adapter),
        )
        return
    if not unread:
        return
    await context.bot.send_message(
        chat_id=allowed_user_id,
        text=f"{len(unread)} unread. Triage now? /mail",
    )


def _safe_error_text(exc, adapter):
    msg = str(exc)
    token = getattr(adapter, "_token", None)
    if token and token in msg:
        msg = msg.replace(token, "[REDACTED]")
    return f"⚠️ Error: {exc.__class__.__name__}: {msg}\n\nSend /mail to restart triage."


async def handle_mail(update, context):
    if update.effective_user.id != context.bot_data["allowed_user_id"]:
        return

    adapter = context.bot_data["adapter"]
    try:
        unread = adapter.list_unread()
    except Exception as exc:
        await update.message.reply_text(_safe_error_text(exc, adapter))
        return

    if not unread:
        await update.message.reply_text("Inbox zero. ✓")
        return

    try:
        mailboxes = adapter.list_mailboxes()
    except Exception as exc:
        await update.message.reply_text(_safe_error_text(exc, adapter))
        return

    context.user_data["triage_queue"] = [m["id"] for m in unread]
    context.user_data["triage_messages"] = {m["id"]: m for m in unread}
    context.user_data["triage_index"] = 0
    # Resolve mailbox ids -> names once per session; the render path reads
    # this cache so it never re-fetches the folder list per item.
    context.user_data["mailbox_names"] = {m["id"]: m["name"] for m in mailboxes}

    first = unread[0]
    await update.message.reply_text(
        _format_message(
            first,
            position=1,
            total=len(unread),
            mailbox_names=context.user_data["mailbox_names"],
        ),
        reply_markup=_build_keyboard(first["id"]),
    )


async def handle_callback(update, context):
    if update.effective_user.id != context.bot_data["allowed_user_id"]:
        return

    query = update.callback_query
    await query.answer()

    adapter = context.bot_data["adapter"]
    parts = query.data.split(":")
    action = parts[0]
    email_id = parts[1] if len(parts) > 1 else None

    if action == "mark_read":
        if not await _run_safely(query, adapter, lambda: adapter.mark_read(email_id)):
            return
        await _advance(query, context)
    elif action == "mark_unread":
        if not await _run_safely(query, adapter, lambda: adapter.mark_unread(email_id)):
            return
        await _advance(query, context)
    elif action == "archive":
        if not await _run_safely(query, adapter, lambda: adapter.archive(email_id)):
            return
        await _advance(query, context)
    elif action == "pin":
        if not await _run_safely(query, adapter, lambda: adapter.flag(email_id)):
            return
        await _advance(query, context)
    elif action == "skip":
        await _advance(query, context)
    elif action == "trash_confirm":
        await query.edit_message_text(
            "Trash this email?",
            reply_markup=_build_trash_confirm_keyboard(email_id),
        )
    elif action == "trash_yes":
        if not await _run_safely(query, adapter, lambda: adapter.trash(email_id)):
            return
        await _advance(query, context)
    elif action == "trash_cancel":
        await _redraw_current(query, context, email_id)
    elif action == "move":
        try:
            mailboxes = adapter.list_mailboxes()
        except Exception as exc:
            await query.edit_message_text(_safe_error_text(exc, adapter))
            return
        await query.edit_message_text(
            "Move to which folder?",
            reply_markup=_build_folder_picker_keyboard(email_id, mailboxes),
        )
    elif action == "move_to":
        mailbox_id = parts[2]
        if not await _run_safely(query, adapter, lambda: adapter.move(email_id, mailbox_id)):
            return
        await _advance(query, context)
    elif action == "move_cancel":
        await _redraw_current(query, context, email_id)


async def _run_safely(query, adapter, call):
    try:
        call()
        return True
    except Exception as exc:
        await query.edit_message_text(_safe_error_text(exc, adapter))
        return False


async def _advance(query, context):
    """Move to the next item, silently skipping any that are no longer unread.

    The mailbox's $seen flag is the single source of truth. Re-fetch
    list_unread on each advance and drop items not in the current unread set
    — so anything the user cleared in another client, read earlier in this
    flow, or otherwise marked seen falls out automatically rather than being
    served from the original /mail snapshot.
    """
    context.user_data["triage_index"] += 1
    queue = context.user_data["triage_queue"]

    if context.user_data["triage_index"] < len(queue):
        adapter = context.bot_data["adapter"]
        try:
            fresh_unread_ids = {m["id"] for m in adapter.list_unread()}
        except Exception as exc:
            await query.edit_message_text(_safe_error_text(exc, adapter))
            return

        while context.user_data["triage_index"] < len(queue):
            next_id = queue[context.user_data["triage_index"]]
            if next_id in fresh_unread_ids:
                next_msg = context.user_data["triage_messages"][next_id]
                await query.edit_message_text(
                    _format_message(
                        next_msg,
                        position=context.user_data["triage_index"] + 1,
                        total=len(queue),
                        mailbox_names=context.user_data.get("mailbox_names", {}),
                    ),
                    reply_markup=_build_keyboard(next_id),
                )
                return
            context.user_data["triage_index"] += 1

    await query.edit_message_text("Triage complete. ✓")
    context.user_data.pop("triage_queue", None)
    context.user_data.pop("triage_messages", None)
    context.user_data.pop("triage_index", None)


async def _redraw_current(query, context, email_id):
    queue = context.user_data["triage_queue"]
    index = context.user_data["triage_index"]
    msg = context.user_data["triage_messages"][email_id]
    await query.edit_message_text(
        _format_message(
            msg,
            position=index + 1,
            total=len(queue),
            mailbox_names=context.user_data.get("mailbox_names", {}),
        ),
        reply_markup=_build_keyboard(email_id),
    )


def _format_message(msg, position, total, mailbox_names):
    from_list = msg.get("from") or []
    sender = from_list[0] if from_list else None
    if sender:
        name = sender.get("name") or ""
        email = sender.get("email") or ""
        sender_str = f"{name} <{email}>".strip()
    else:
        sender_str = "(unknown)"
    folders = [mailbox_names.get(mid) for mid in (msg.get("mailbox_ids") or [])]
    folders = [f for f in folders if f]
    folder_str = ", ".join(folders) if folders else "(unknown folder)"
    return (
        f"[{position}/{total}]\n"
        f"From: {sender_str}\n"
        f"Subject: {msg.get('subject') or '(no subject)'}\n"
        f"Folder: {folder_str}\n"
        f"Date: {msg.get('received_at') or '(unknown)'}\n"
        f"\n"
        f"{msg.get('preview') or ''}"
    )


def _build_keyboard(email_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Mark read", callback_data=f"mark_read:{email_id}"),
                InlineKeyboardButton("Mark unread", callback_data=f"mark_unread:{email_id}"),
            ],
            [
                InlineKeyboardButton("Archive", callback_data=f"archive:{email_id}"),
                InlineKeyboardButton("📌 Pin", callback_data=f"pin:{email_id}"),
            ],
            [
                InlineKeyboardButton("Move ▸", callback_data=f"move:{email_id}"),
                InlineKeyboardButton("Skip", callback_data=f"skip:{email_id}"),
            ],
            [
                InlineKeyboardButton("🗑 Trash", callback_data=f"trash_confirm:{email_id}"),
            ],
        ]
    )


def _build_trash_confirm_keyboard(email_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes, trash", callback_data=f"trash_yes:{email_id}"),
                InlineKeyboardButton("Cancel", callback_data=f"trash_cancel:{email_id}"),
            ],
        ]
    )


def _build_folder_picker_keyboard(email_id, mailboxes):
    rows = [
        [InlineKeyboardButton(m["name"], callback_data=f"move_to:{email_id}:{m['id']}")]
        for m in mailboxes
    ]
    rows.append([InlineKeyboardButton("Cancel", callback_data=f"move_cancel:{email_id}")])
    return InlineKeyboardMarkup(rows)
