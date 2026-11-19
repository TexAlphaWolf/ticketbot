"""Translations (English, Italian, German) for bot messages and slash commands."""

from discord import app_commands

LANGUAGES = {"en": "English", "it": "Italiano", "de": "Deutsch"}

# key, label, emoji, description
DEFAULT_TYPES = {
    "en": [
        ("support", "Support", "🛠️", "General help or questions"),
        ("bug", "Bug report", "🐞", "Something is broken or not working"),
        ("report", "User report", "🚨", "Report a member or a rule violation"),
        ("other", "Other", "💬", "Anything else"),
    ],
    "it": [
        ("support", "Supporto", "🛠️", "Aiuto generale o domande"),
        ("bug", "Segnalazione bug", "🐞", "Qualcosa non funziona"),
        ("report", "Segnalazione utente", "🚨", "Segnala un membro o una violazione delle regole"),
        ("other", "Altro", "💬", "Qualsiasi altra cosa"),
    ],
    "de": [
        ("support", "Support", "🛠️", "Allgemeine Hilfe oder Fragen"),
        ("bug", "Fehlermeldung", "🐞", "Etwas ist kaputt oder funktioniert nicht"),
        ("report", "Nutzer melden", "🚨", "Ein Mitglied oder einen Regelverstoß melden"),
        ("other", "Sonstiges", "💬", "Alles andere"),
    ],
}

STRINGS: dict[str, dict[str, str]] = {}

STRINGS["en"] = {
    # buttons
    "btn.open": "Open ticket",
    "btn.claim": "Claim",
    "btn.claimed_by": "Claimed by {name}",
    "btn.close": "Close",
    "btn.reopen": "Reopen",
    "btn.delete": "Delete now",
    # panel and opening
    "panel.title": "🎫 Support",
    "panel.description": "Having an issue, found a bug or need to report something?\n"
                         "Click the button below, choose the ticket type and a private "
                         "channel with the staff team will be opened.",
    "panel.choose_prompt": "What do you need help with?",
    "panel.choose_type": "Choose the ticket type...",
    "modal.title": "{type} ticket",
    "modal.subject": "Subject",
    "modal.description": "Describe your issue",
    "open.already": "You already have an open ticket: {channel}",
    "open.created": "Ticket created: {channel}",
    "open.footer": "The staff team will reply here as soon as possible. If the staff asks you "
                   "something, please reply within {hours} hours or the ticket will be "
                   "closed automatically.",
    "queue.line": "**{waiting}** waiting · **{in_progress}** in progress",
    "queue.first": "none, you're first in line!",
    # fields
    "field.type": "Type",
    "field.queue": "Other open tickets",
    "field.priority": "Priority",
    "field.subject": "Subject",
    "field.opened_by": "Opened by",
    "field.opened_at": "Opened at",
    "field.claimed_by": "Claimed by",
    "field.closed_by": "Closed by",
    "field.closed_at": "Closed at",
    "field.reason": "Reason",
    "field.duration": "Duration",
    "field.notes": "Staff notes",
    # errors
    "error.not_setup": "The ticket system has not been set up yet. An admin can use /setup.",
    "error.bad_setup": "The ticket system is not configured correctly. Please contact an admin.",
    "error.no_types": "There are no ticket types. An admin can add them with /types add.",
    "error.type_gone": "This ticket type no longer exists.",
    "error.not_ticket": "This only works inside a ticket.",
    "error.ticket_closed": "This ticket is closed.",
    "error.staff_only": "Only staff members can do this.",
    "error.no_log_channel": "The log channel no longer exists: run /setup again.",
    # claim and priority
    "claim.already": "This ticket has already been claimed by {user}.",
    "claim.choose_priority": "Choose the priority of this ticket "
                             "(see the guidelines pinned in the log channel):",
    "claim.placeholder": "Choose the priority...",
    "claim.option": "First reply {target}",
    "claim.done": "You claimed this ticket with priority **{priority}**.",
    "claim.public": "✋ {user} has claimed this ticket · Priority: **{priority}**",
    "priority.low": "Low",
    "priority.medium": "Medium",
    "priority.high": "High",
    "priority.none": "Not set",
    "priority.target.low": "within 48 hours",
    "priority.target.medium": "within 24 hours",
    "priority.target.high": "as soon as possible",
    "priority.changed": "📌 Priority changed from **{old}** to **{new}** by {user}.",
    "transfer.not_staff": "{user} is not a staff member.",
    "transfer.same": "This ticket is already assigned to {user}.",
    "transfer.done": "🔁 This ticket is now handled by {user} (assigned by {by}).",
    # closing
    "close.not_allowed": "You can't close this ticket.",
    "close.reason_user": "Closed by the user",
    "close.reason_staff": "Closed by the staff",
    "close.closing": "🔒 Closing the ticket...",
    "close.log_title": "Ticket closed: #{channel}",
    "close.channel_message": "🔒 Ticket closed by {user}.\n**Reason:** {reason}\n\n"
                             "The staff can reopen it within {hours} hours, "
                             "then this channel will be deleted.",
    "close.dm": "Your ticket **#{channel}** on **{guild}** has been closed.\n**Reason:** {reason}",
    "footer.auto_delete": "🗑️ Deleted automatically after {days} days",
    "footer.archived": "🗂️ Archived",
    "footer.kept": "🔒 Kept until an admin deletes it",
    "reopen.not_closed": "This ticket is not closed.",
    "reopen.done": "🔓 Ticket reopened by {user}.",
    "delete.not_closed": "Close the ticket before deleting it.",
    "delete.deleting": "🗑️ Deleting the ticket...",
    "auto.warning": "⏰ {user} the staff is waiting for your reply. This ticket will be closed "
                    "automatically in {hours} hours if there is no response.",
    "auto.reason": "No response from the user within {hours} hours",
    # ratings
    "rating.ask": "⭐ How was the support? Rate it from 1 to 5:",
    "rating.modal_title": "Your rating: {stars}",
    "rating.comment": "Any comment? (optional)",
    "rating.thanks": "Thanks for your feedback! {stars}",
    "rating.already": "You have already rated this ticket.",
    "rating.not_owner": "Only the user who opened the ticket can rate it.",
    "rating.unavailable": "This ticket no longer exists.",
    "rating.log_title": "⭐ New rating for ticket {ticket}",
    # members and notes
    "member.added": "➕ {user} has been added to the ticket.",
    "member.removed": "➖ {user} has been removed from the ticket.",
    "member.cant_remove_owner": "You can't remove the user who opened the ticket.",
    "note.added": "📝 Note saved. Only the staff can see it, and it's included in the "
                  "staff transcript.",
    "note.none": "This ticket has no notes.",
    "note.title": "📝 Staff notes",
    # setup and guidelines
    "setup.done": "✅ Ticket system configured (language: {language}). Panel posted in "
                  "{channel}.\nNext steps: `/guidelines`, `/types list`, `/settings show`.",
    "setup.panel_failed": "I can't send messages in {channel}. Check my permissions there.",
    "guidelines.title": "📋 Ticket priority guidelines",
    "guidelines.intro": "When you **claim** a ticket, choose its priority using these rules. "
                        "It can be changed later with `/priority`.",
    "guidelines.priority.low": "General questions, suggestions or cosmetic issues. "
                               "Nothing is broken and nobody is affected.",
    "guidelines.priority.medium": "A bug or problem affecting a user or a feature, account "
                                  "or role issues, minor rule violations.",
    "guidelines.priority.high": "Harassment, threats, scams or serious rule violations, "
                                "security issues, problems affecting the whole server, or "
                                "anything that may need to be kept as evidence.",
    "guidelines.first_reply": "**First reply:** {target}",
    "guidelines.transcripts_title": "🗂️ Transcripts",
    "guidelines.transcripts": "• In the log channel, {kept} transcripts are **kept** until an "
                              "admin deletes them.\n• All other transcripts are **deleted "
                              "automatically** from the log channel after **{days} days**.\n"
                              "• The archive channel always keeps every transcript.\n"
                              "• Tickets closed without a priority are treated as Low.",
    "guidelines.posted": "📋 Guidelines posted in {channel} and pinned.",
    "guidelines.posted_not_pinned": "📋 Guidelines posted in {channel}, but I couldn't pin "
                                    "them: give me the **Pin Messages** permission there, "
                                    "or pin them manually.",
    # stats
    "stats.title": "📊 Ticket statistics · {period}",
    "stats.title_member": "📊 {member} · {period}",
    "stats.period.7": "last 7 days",
    "stats.period.30": "last 30 days",
    "stats.period.90": "last 90 days",
    "stats.period.all": "all time",
    "stats.tickets": "Tickets",
    "stats.tickets_value": "Opened: **{opened}** · Closed: **{closed}** · "
                           "Still open: **{open}**",
    "stats.first_response": "⏱️ Avg. first response",
    "stats.resolution": "✅ Avg. resolution time",
    "stats.rating": "⭐ Avg. rating",
    "stats.by_type": "By type",
    "stats.by_priority": "By priority",
    "stats.staff": "👥 Staff",
    "stats.staff_line": "{rank}. {user} · {handled} tickets · {rating} · {response}",
    "stats.empty": "No tickets in this period.",
    # settings
    "settings.title": "⚙️ Ticket settings",
    "settings.language": "Language",
    "settings.staff_role": "Staff role",
    "settings.category": "Ticket category",
    "settings.log": "Log channel",
    "settings.archive": "Archive channel",
    "settings.panel": "Panel channel",
    "settings.retention": "Log retention",
    "settings.days": "{days} days",
    "settings.telegram": "Telegram chat",
    "settings.types": "Ticket types",
    "settings.language_set": "🌍 Language set to **{language}**. The panel and the guidelines "
                             "have been updated.",
    "settings.retention_set": "🗑️ Low and Medium transcripts will be deleted from the log "
                              "channel after **{days} days**.",
    "settings.archive_set": "🗂️ Every transcript will also be saved in {channel}.",
    "settings.archive_off": "🗂️ Archive channel disabled.",
    # ticket types
    "types.title": "🏷️ Ticket types ({count}/{max})",
    "types.too_many": "You can have at most {max} ticket types.",
    "types.bad_emoji": "That's not a valid emoji. Use a single emoji like 🐞 or a custom "
                       "server emoji.",
    "types.added": "✅ Type {type} added (channel prefix: `{key}`).",
    "types.edited": "✅ Type updated: {type}.",
    "types.nothing": "Nothing to change.",
    "types.last": "You can't remove the last ticket type.",
    "types.removed": "🗑️ Type {type} removed. Open tickets of this type are not affected.",
    # transcripts
    "transcript.title": "Transcript of #{channel}",
    "transcript.notes": "Staff notes",
    "transcript.footer": "{count} messages · Generated by TicketBot",
    # telegram (HTML)
    "tg.new": "🎫 <b>New ticket</b> on <b>{guild}</b>\n\n<b>Type:</b> {type}\n"
              "<b>From:</b> {user}\n<b>Subject:</b> {subject}\n\n{description}\n\n"
              "📊 Other open tickets: {waiting} waiting · {in_progress} in progress\n"
              "<a href=\"{url}\">Open in Discord</a>",
    "tg.high": "🔴 <b>High priority ticket</b> on <b>{guild}</b>\n#{channel} · {type}\n"
               "<b>Subject:</b> {subject}\n<b>Set by:</b> {user}\n"
               "<a href=\"{url}\">Open in Discord</a>",
    "tg.closed": "🔒 <b>Ticket closed</b> on <b>{guild}</b>\n#{channel} · {type} · {priority}\n"
                 "<b>Closed by:</b> {user}\n<b>Reason:</b> {reason}",
    "tg.rating": "⭐ <b>New rating</b> on <b>{guild}</b>\nTicket {ticket} · {stars}\n"
                 "<b>Handled by:</b> {staff}\n<b>Comment:</b> {comment}",
    "tg.disabled": "Telegram notifications are not enabled on this bot "
                   "(TELEGRAM_BOT_TOKEN is missing).",
    "tg.bad_id": "That doesn't look like a valid chat ID (it should be a number).",
    "tg.code": "🔐 Verification code for <b>{guild}</b>: <code>{code}</code>\n\n"
               "Run <code>/telegram verify</code> in Discord with this code. It expires in "
               "{minutes} minutes.\nIf you didn't request this, just ignore this message.",
    "tg.unreachable": "I couldn't send a message to that chat. Open **@{bot}** on Telegram and "
                      "press **Start** (for a group, add the bot to the group first), "
                      "then try again.",
    "tg.code_sent": "📨 I sent a verification code to that Telegram chat. "
                    "Run `/telegram verify` to complete the link.",
    "tg.no_code": "No valid code to verify. Run `/telegram link` again.",
    "tg.too_many": "Wrong code. Too many attempts: run `/telegram link` again.",
    "tg.wrong_code": "Wrong code. {left} attempts left.",
    "tg.linked": "✅ Telegram linked! Tickets of this server will be notified to that chat.",
    "tg.linked_chat": "✅ This chat is now linked to <b>{guild}</b>.",
    "tg.status_linked": "✅ Linked to Telegram chat `{chat}`.",
    "tg.status_none": "❌ No Telegram chat linked. Send /start to **@{bot}** on Telegram, "
                      "then use `/telegram link`.",
    "tg.not_linked": "No Telegram chat linked yet. Use `/telegram link` first.",
    "tg.test": "🔔 Test notification from <b>{guild}</b>.",
    "tg.test_sent": "🔔 Test notification sent.",
    "tg.unlinked": "🔕 Telegram notifications disabled.",
    "profile.name_set": "✅ In this server I'm now called **{name}**.",
    "profile.avatar_set": "✅ Avatar updated for this server.",
    "profile.banner_set": "✅ Banner updated for this server.",
    "profile.bio_set": "✅ Bio updated for this server.",
    "profile.reset":
        "↩️ Name, avatar, banner and bio restored to the original ones in this server.",
    "profile.bad_image": "Use a PNG, JPG, GIF or WEBP image of at most {mb} MB.",
    "profile.forbidden": "I can't change my profile here. Give my role the "
                         "**Change Nickname** permission.",
    "profile.failed": "Discord refused the change: {error}\nIf you changed the avatar or "
                      "banner many times in a row, wait a few minutes and try again.",
    "transcript.reactions": "Reactions",
    "transcript.sticker": "Sticker",
    "replies.signature": "— {staff}",
    "replies.unknown": "There's no quick reply called `{name}`. Use `/replies list` to see them.",
    "replies.none": "There are no quick replies yet. An admin can add them with `/replies add`.",
    "replies.title": "💬 Quick replies ({count}/{max})",
    "replies.exists":
        "A quick reply called `{name}` already exists: use `/replies edit` to change it.",
    "replies.too_many": "You can have at most {max} quick replies.",
    "replies.bad_name": "Use a name with letters or numbers, e.g. `logs` or `solved`.",
    "replies.modal_title": "Quick reply: {name}",
    "replies.modal_label": "Text of the reply",
    "replies.modal_hint": "You can use {{user}}, {{staff}} and {{server}}",
    "replies.saved": "✅ Quick reply `{name}` saved. Preview:\n\n{preview}",
    "replies.removed": "🗑️ Quick reply `{name}` removed.",
    "reminder.channel":
        "⏰ {target} this ticket has been waiting for a staff reply for **{waited}** (priority "
        "{priority}: first reply within {hours}h).",
    "tg.reminder":
        "⏰ <b>Ticket waiting for the staff</b> on <b>{guild}</b>\n#{channel} · "
        "{priority}\nWaiting for {waited}\n<a href=\"{url}\">Open in Discord</a>",
    "guidelines.reminders_title": "⏰ Staff reminders",
    "guidelines.reminders":
        "If a ticket waits too long for a staff reply, the bot reminds the staff: 🔴 after "
        "{high}h, 🟡 after {medium}h, 🟢 after {low}h, ⚪ without a priority after {none}h.",
    "settings.reminders": "Staff reminders",
    "settings.on": "On",
    "settings.off": "Off",
    "settings.reminders_on": "⏰ Staff reminders enabled.",
    "settings.reminders_off": "⏰ Staff reminders disabled.",
}

STRINGS["it"] = {
    "btn.open": "Apri ticket",
    "btn.claim": "Prendi in carico",
    "btn.claimed_by": "Preso da {name}",
    "btn.close": "Chiudi",
    "btn.reopen": "Riapri",
    "btn.delete": "Elimina ora",
    "panel.title": "🎫 Supporto",
    "panel.description": "Hai un problema, hai trovato un bug o devi segnalare qualcosa?\n"
                         "Clicca il pulsante qui sotto, scegli il tipo di ticket e si aprirà "
                         "un canale privato con lo staff.",
    "panel.choose_prompt": "Di cosa hai bisogno?",
    "panel.choose_type": "Scegli il tipo di ticket...",
    "modal.title": "Ticket: {type}",
    "modal.subject": "Oggetto",
    "modal.description": "Descrivi il problema",
    "open.already": "Hai già un ticket aperto: {channel}",
    "open.created": "Ticket creato: {channel}",
    "open.footer": "Lo staff ti risponderà qui il prima possibile. Se lo staff ti chiede "
                   "qualcosa, rispondi entro {hours} ore, altrimenti il ticket verrà "
                   "chiuso automaticamente.",
    "queue.line": "**{waiting}** in attesa · **{in_progress}** in lavorazione",
    "queue.first": "nessuno, sei il primo della fila!",
    "field.type": "Tipo",
    "field.queue": "Altri ticket aperti",
    "field.priority": "Priorità",
    "field.subject": "Oggetto",
    "field.opened_by": "Aperto da",
    "field.opened_at": "Aperto il",
    "field.claimed_by": "Preso in carico da",
    "field.closed_by": "Chiuso da",
    "field.closed_at": "Chiuso il",
    "field.reason": "Motivo",
    "field.duration": "Durata",
    "field.notes": "Note dello staff",
    "error.not_setup": "Il sistema ticket non è ancora configurato. Un admin può usare /setup.",
    "error.bad_setup": "Il sistema ticket non è configurato correttamente. Contatta un admin.",
    "error.no_types": "Non ci sono tipi di ticket. Un admin può aggiungerli con /types add.",
    "error.type_gone": "Questo tipo di ticket non esiste più.",
    "error.not_ticket": "Funziona solo dentro un ticket.",
    "error.ticket_closed": "Questo ticket è chiuso.",
    "error.staff_only": "Solo lo staff può farlo.",
    "error.no_log_channel": "Il canale log non esiste più: rilancia /setup.",
    "claim.already": "Questo ticket è già stato preso in carico da {user}.",
    "claim.choose_priority": "Scegli la priorità del ticket "
                             "(vedi le linee guida fissate nel canale log):",
    "claim.placeholder": "Scegli la priorità...",
    "claim.option": "Prima risposta {target}",
    "claim.done": "Hai preso in carico il ticket con priorità **{priority}**.",
    "claim.public": "✋ {user} ha preso in carico questo ticket · Priorità: **{priority}**",
    "priority.low": "Bassa",
    "priority.medium": "Media",
    "priority.high": "Alta",
    "priority.none": "Non impostata",
    "priority.target.low": "entro 48 ore",
    "priority.target.medium": "entro 24 ore",
    "priority.target.high": "il prima possibile",
    "priority.changed": "📌 Priorità cambiata da **{old}** a **{new}** da {user}.",
    "transfer.not_staff": "{user} non fa parte dello staff.",
    "transfer.same": "Questo ticket è già assegnato a {user}.",
    "transfer.done": "🔁 Ora questo ticket è gestito da {user} (assegnato da {by}).",
    "close.not_allowed": "Non puoi chiudere questo ticket.",
    "close.reason_user": "Chiuso dall'utente",
    "close.reason_staff": "Chiuso dallo staff",
    "close.closing": "🔒 Chiusura del ticket in corso...",
    "close.log_title": "Ticket chiuso: #{channel}",
    "close.channel_message": "🔒 Ticket chiuso da {user}.\n**Motivo:** {reason}\n\n"
                             "Lo staff può riaprirlo entro {hours} ore, poi questo canale "
                             "verrà eliminato.",
    "close.dm": "Il tuo ticket **#{channel}** su **{guild}** è stato chiuso.\n"
                "**Motivo:** {reason}",
    "footer.auto_delete": "🗑️ Eliminato automaticamente dopo {days} giorni",
    "footer.archived": "🗂️ Archiviato",
    "footer.kept": "🔒 Conservato finché un admin non lo elimina",
    "reopen.not_closed": "Questo ticket non è chiuso.",
    "reopen.done": "🔓 Ticket riaperto da {user}.",
    "delete.not_closed": "Chiudi il ticket prima di eliminarlo.",
    "delete.deleting": "🗑️ Eliminazione del ticket in corso...",
    "auto.warning": "⏰ {user} lo staff sta aspettando una tua risposta. Questo ticket verrà "
                    "chiuso automaticamente tra {hours} ore se non rispondi.",
    "auto.reason": "Nessuna risposta dall'utente entro {hours} ore",
    "rating.ask": "⭐ Com'è stata l'assistenza? Dai un voto da 1 a 5:",
    "rating.modal_title": "Il tuo voto: {stars}",
    "rating.comment": "Vuoi lasciare un commento? (facoltativo)",
    "rating.thanks": "Grazie per il tuo feedback! {stars}",
    "rating.already": "Hai già valutato questo ticket.",
    "rating.not_owner": "Solo chi ha aperto il ticket può valutarlo.",
    "rating.unavailable": "Questo ticket non esiste più.",
    "rating.log_title": "⭐ Nuova valutazione per il ticket {ticket}",
    "member.added": "➕ {user} è stato aggiunto al ticket.",
    "member.removed": "➖ {user} è stato rimosso dal ticket.",
    "member.cant_remove_owner": "Non puoi rimuovere chi ha aperto il ticket.",
    "note.added": "📝 Nota salvata. È visibile solo allo staff ed è inclusa nella "
                  "trascrizione per lo staff.",
    "note.none": "Questo ticket non ha note.",
    "note.title": "📝 Note dello staff",
    "setup.done": "✅ Sistema ticket configurato (lingua: {language}). Pannello pubblicato in "
                  "{channel}.\nPassi successivi: `/guidelines`, `/types list`, `/settings show`.",
    "setup.panel_failed": "Non riesco a scrivere in {channel}. Controlla i miei permessi.",
    "guidelines.title": "📋 Linee guida sulla priorità dei ticket",
    "guidelines.intro": "Quando **prendi in carico** un ticket, scegli la priorità seguendo "
                        "queste regole. Puoi cambiarla in seguito con `/priority`.",
    "guidelines.priority.low": "Domande generali, suggerimenti o problemi estetici. "
                               "Non c'è niente di rotto e nessuno è coinvolto.",
    "guidelines.priority.medium": "Un bug o un problema che riguarda un utente o una "
                                  "funzione, problemi di account o ruoli, violazioni lievi "
                                  "delle regole.",
    "guidelines.priority.high": "Molestie, minacce, truffe o violazioni gravi delle regole, "
                                "problemi di sicurezza, problemi che riguardano tutto il "
                                "server o qualsiasi cosa da conservare come prova.",
    "guidelines.first_reply": "**Prima risposta:** {target}",
    "guidelines.transcripts_title": "🗂️ Trascrizioni",
    "guidelines.transcripts": "• Nel canale log, le trascrizioni {kept} vengono **conservate** "
                              "finché un admin non le elimina.\n• Tutte le altre vengono "
                              "**eliminate automaticamente** dal canale log dopo "
                              "**{days} giorni**.\n• Il canale archivio conserva sempre "
                              "tutte le trascrizioni.\n• I ticket chiusi senza priorità "
                              "contano come Bassa.",
    "guidelines.posted": "📋 Linee guida pubblicate in {channel} e fissate.",
    "guidelines.posted_not_pinned": "📋 Linee guida pubblicate in {channel}, ma non sono "
                                    "riuscito a fissarle: dammi il permesso **Fissare i "
                                    "messaggi** in quel canale, oppure fissale a mano.",
    "stats.title": "📊 Statistiche ticket · {period}",
    "stats.title_member": "📊 {member} · {period}",
    "stats.period.7": "ultimi 7 giorni",
    "stats.period.30": "ultimi 30 giorni",
    "stats.period.90": "ultimi 90 giorni",
    "stats.period.all": "da sempre",
    "stats.tickets": "Ticket",
    "stats.tickets_value": "Aperti: **{opened}** · Chiusi: **{closed}** · "
                           "Ancora aperti: **{open}**",
    "stats.first_response": "⏱️ Prima risposta media",
    "stats.resolution": "✅ Tempo medio di risoluzione",
    "stats.rating": "⭐ Voto medio",
    "stats.by_type": "Per tipo",
    "stats.by_priority": "Per priorità",
    "stats.staff": "👥 Staff",
    "stats.staff_line": "{rank}. {user} · {handled} ticket · {rating} · {response}",
    "stats.empty": "Nessun ticket in questo periodo.",
    "settings.title": "⚙️ Impostazioni ticket",
    "settings.language": "Lingua",
    "settings.staff_role": "Ruolo staff",
    "settings.category": "Categoria ticket",
    "settings.log": "Canale log",
    "settings.archive": "Canale archivio",
    "settings.panel": "Canale pannello",
    "settings.retention": "Conservazione log",
    "settings.days": "{days} giorni",
    "settings.telegram": "Chat Telegram",
    "settings.types": "Tipi di ticket",
    "settings.language_set": "🌍 Lingua impostata su **{language}**. Pannello e linee guida "
                             "sono stati aggiornati.",
    "settings.retention_set": "🗑️ Le trascrizioni Bassa e Media verranno eliminate dal "
                              "canale log dopo **{days} giorni**.",
    "settings.archive_set": "🗂️ Tutte le trascrizioni verranno salvate anche in {channel}.",
    "settings.archive_off": "🗂️ Canale archivio disattivato.",
    "types.title": "🏷️ Tipi di ticket ({count}/{max})",
    "types.too_many": "Puoi avere al massimo {max} tipi di ticket.",
    "types.bad_emoji": "Non è un'emoji valida. Usa una sola emoji come 🐞 o un'emoji "
                       "personalizzata del server.",
    "types.added": "✅ Tipo {type} aggiunto (prefisso canale: `{key}`).",
    "types.edited": "✅ Tipo aggiornato: {type}.",
    "types.nothing": "Niente da cambiare.",
    "types.last": "Non puoi rimuovere l'ultimo tipo di ticket.",
    "types.removed": "🗑️ Tipo {type} rimosso. I ticket aperti di questo tipo non cambiano.",
    "transcript.title": "Trascrizione di #{channel}",
    "transcript.notes": "Note dello staff",
    "transcript.footer": "{count} messaggi · Generato da TicketBot",
    "tg.new": "🎫 <b>Nuovo ticket</b> su <b>{guild}</b>\n\n<b>Tipo:</b> {type}\n"
              "<b>Da:</b> {user}\n<b>Oggetto:</b> {subject}\n\n{description}\n\n"
              "📊 Altri ticket aperti: {waiting} in attesa · {in_progress} in lavorazione\n"
              "<a href=\"{url}\">Apri su Discord</a>",
    "tg.high": "🔴 <b>Ticket ad alta priorità</b> su <b>{guild}</b>\n#{channel} · {type}\n"
               "<b>Oggetto:</b> {subject}\n<b>Impostata da:</b> {user}\n"
               "<a href=\"{url}\">Apri su Discord</a>",
    "tg.closed": "🔒 <b>Ticket chiuso</b> su <b>{guild}</b>\n#{channel} · {type} · {priority}\n"
                 "<b>Chiuso da:</b> {user}\n<b>Motivo:</b> {reason}",
    "tg.rating": "⭐ <b>Nuova valutazione</b> su <b>{guild}</b>\nTicket {ticket} · {stars}\n"
                 "<b>Gestito da:</b> {staff}\n<b>Commento:</b> {comment}",
    "tg.disabled": "Le notifiche Telegram non sono attive su questo bot "
                   "(manca TELEGRAM_BOT_TOKEN).",
    "tg.bad_id": "Non sembra un chat ID valido (deve essere un numero).",
    "tg.code": "🔐 Codice di verifica per <b>{guild}</b>: <code>{code}</code>\n\n"
               "Usa <code>/telegram verify</code> su Discord con questo codice. Scade tra "
               "{minutes} minuti.\nSe non l'hai richiesto tu, ignora questo messaggio.",
    "tg.unreachable": "Non riesco a scrivere in quella chat. Apri **@{bot}** su Telegram e "
                      "premi **Avvia** (per un gruppo, aggiungi prima il bot al gruppo), "
                      "poi riprova.",
    "tg.code_sent": "📨 Ho inviato un codice di verifica a quella chat Telegram. "
                    "Usa `/telegram verify` per completare il collegamento.",
    "tg.no_code": "Nessun codice valido da verificare. Rilancia `/telegram link`.",
    "tg.too_many": "Codice errato. Troppi tentativi: rilancia `/telegram link`.",
    "tg.wrong_code": "Codice errato. Tentativi rimasti: {left}.",
    "tg.linked": "✅ Telegram collegato! I ticket di questo server verranno notificati in "
                 "quella chat.",
    "tg.linked_chat": "✅ Questa chat ora è collegata a <b>{guild}</b>.",
    "tg.status_linked": "✅ Collegato alla chat Telegram `{chat}`.",
    "tg.status_none": "❌ Nessuna chat Telegram collegata. Invia /start a **@{bot}** su "
                      "Telegram, poi usa `/telegram link`.",
    "tg.not_linked": "Nessuna chat Telegram collegata. Usa prima `/telegram link`.",
    "tg.test": "🔔 Notifica di prova da <b>{guild}</b>.",
    "tg.test_sent": "🔔 Notifica di prova inviata.",
    "tg.unlinked": "🔕 Notifiche Telegram disattivate.",
    "profile.name_set": "✅ In questo server ora mi chiamo **{name}**.",
    "profile.avatar_set": "✅ Avatar aggiornato per questo server.",
    "profile.banner_set": "✅ Banner aggiornato per questo server.",
    "profile.bio_set": "✅ Bio aggiornata per questo server.",
    "profile.reset": "↩️ Nome, avatar, banner e bio ripristinati a quelli originali in questo "
                     "server.",
    "profile.bad_image": "Usa un'immagine PNG, JPG, GIF o WEBP di massimo {mb} MB.",
    "profile.forbidden": "Non posso cambiare il mio profilo qui. Dai al mio ruolo il permesso "
                         "**Cambiare il nickname**.",
    "profile.failed": "Discord ha rifiutato la modifica: {error}\nSe hai cambiato avatar o "
                      "banner tante volte di fila, aspetta qualche minuto e riprova.",
    "transcript.reactions": "Reazioni",
    "transcript.sticker": "Sticker",
    "replies.signature": "— {staff}",
    "replies.unknown":
        "Non esiste una risposta rapida chiamata `{name}`. Usa `/replies list` per vederle.",
    "replies.none":
        "Non ci sono ancora risposte rapide. Un admin può aggiungerle con `/replies add`.",
    "replies.title": "💬 Risposte rapide ({count}/{max})",
    "replies.exists":
        "Esiste già una risposta rapida chiamata `{name}`: usa `/replies edit` per modificarla.",
    "replies.too_many": "Puoi avere al massimo {max} risposte rapide.",
    "replies.bad_name": "Usa un nome con lettere o numeri, per esempio `log` o `risolto`.",
    "replies.modal_title": "Risposta rapida: {name}",
    "replies.modal_label": "Testo della risposta",
    "replies.modal_hint": "Puoi usare {{user}}, {{staff}} e {{server}}",
    "replies.saved": "✅ Risposta rapida `{name}` salvata. Anteprima:\n\n{preview}",
    "replies.removed": "🗑️ Risposta rapida `{name}` rimossa.",
    "reminder.channel":
        "⏰ {target} questo ticket aspetta una risposta dello staff da **{waited}** (priorità "
        "{priority}: prima risposta entro {hours}h).",
    "tg.reminder":
        "⏰ <b>Ticket in attesa dello staff</b> su <b>{guild}</b>\n#{channel} · {priority}\nIn "
        "attesa da {waited}\n<a href=\"{url}\">Apri su Discord</a>",
    "guidelines.reminders_title": "⏰ Promemoria per lo staff",
    "guidelines.reminders":
        "Se un ticket aspetta troppo una risposta dello staff, il bot avvisa lo staff: 🔴 dopo "
        "{high}h, 🟡 dopo {medium}h, 🟢 dopo {low}h, ⚪ senza priorità dopo {none}h.",
    "settings.reminders": "Promemoria staff",
    "settings.on": "Attivi",
    "settings.off": "Disattivati",
    "settings.reminders_on": "⏰ Promemoria per lo staff attivati.",
    "settings.reminders_off": "⏰ Promemoria per lo staff disattivati.",
}

STRINGS["de"] = {
    "btn.open": "Ticket öffnen",
    "btn.claim": "Übernehmen",
    "btn.claimed_by": "Übernommen von {name}",
    "btn.close": "Schließen",
    "btn.reopen": "Wieder öffnen",
    "btn.delete": "Jetzt löschen",
    "panel.title": "🎫 Support",
    "panel.description": "Du hast ein Problem, einen Fehler gefunden oder möchtest etwas "
                         "melden?\nKlicke auf den Button unten, wähle die Ticket-Art und es "
                         "wird ein privater Kanal mit dem Team geöffnet.",
    "panel.choose_prompt": "Wobei brauchst du Hilfe?",
    "panel.choose_type": "Ticket-Art auswählen...",
    "modal.title": "Ticket: {type}",
    "modal.subject": "Betreff",
    "modal.description": "Beschreibe dein Problem",
    "open.already": "Du hast bereits ein offenes Ticket: {channel}",
    "open.created": "Ticket erstellt: {channel}",
    "open.footer": "Das Team antwortet dir hier so schnell wie möglich. Wenn das Team dir eine "
                   "Frage stellt, antworte bitte innerhalb von {hours} Stunden, sonst wird "
                   "das Ticket automatisch geschlossen.",
    "queue.line": "**{waiting}** wartend · **{in_progress}** in Bearbeitung",
    "queue.first": "keine, du bist als Erster dran!",
    "field.type": "Art",
    "field.queue": "Andere offene Tickets",
    "field.priority": "Priorität",
    "field.subject": "Betreff",
    "field.opened_by": "Geöffnet von",
    "field.opened_at": "Geöffnet am",
    "field.claimed_by": "Übernommen von",
    "field.closed_by": "Geschlossen von",
    "field.closed_at": "Geschlossen am",
    "field.reason": "Grund",
    "field.duration": "Dauer",
    "field.notes": "Team-Notizen",
    "error.not_setup": "Das Ticket-System ist noch nicht eingerichtet. Ein Admin kann "
                       "/setup verwenden.",
    "error.bad_setup": "Das Ticket-System ist nicht richtig eingerichtet. Bitte kontaktiere "
                       "einen Admin.",
    "error.no_types": "Es gibt keine Ticket-Arten. Ein Admin kann sie mit /types add "
                      "hinzufügen.",
    "error.type_gone": "Diese Ticket-Art existiert nicht mehr.",
    "error.not_ticket": "Das funktioniert nur in einem Ticket.",
    "error.ticket_closed": "Dieses Ticket ist geschlossen.",
    "error.staff_only": "Das kann nur das Team.",
    "error.no_log_channel": "Der Log-Kanal existiert nicht mehr: führe /setup erneut aus.",
    "claim.already": "Dieses Ticket wurde bereits von {user} übernommen.",
    "claim.choose_priority": "Wähle die Priorität dieses Tickets "
                             "(siehe die angepinnten Richtlinien im Log-Kanal):",
    "claim.placeholder": "Priorität auswählen...",
    "claim.option": "Erste Antwort {target}",
    "claim.done": "Du hast dieses Ticket mit Priorität **{priority}** übernommen.",
    "claim.public": "✋ {user} hat dieses Ticket übernommen · Priorität: **{priority}**",
    "priority.low": "Niedrig",
    "priority.medium": "Mittel",
    "priority.high": "Hoch",
    "priority.none": "Nicht gesetzt",
    "priority.target.low": "innerhalb von 48 Stunden",
    "priority.target.medium": "innerhalb von 24 Stunden",
    "priority.target.high": "so schnell wie möglich",
    "priority.changed": "📌 Priorität von **{old}** auf **{new}** geändert durch {user}.",
    "transfer.not_staff": "{user} gehört nicht zum Team.",
    "transfer.same": "Dieses Ticket ist bereits {user} zugewiesen.",
    "transfer.done": "🔁 Dieses Ticket wird jetzt von {user} bearbeitet (zugewiesen von {by}).",
    "close.not_allowed": "Du kannst dieses Ticket nicht schließen.",
    "close.reason_user": "Vom Nutzer geschlossen",
    "close.reason_staff": "Vom Team geschlossen",
    "close.closing": "🔒 Ticket wird geschlossen...",
    "close.log_title": "Ticket geschlossen: #{channel}",
    "close.channel_message": "🔒 Ticket geschlossen von {user}.\n**Grund:** {reason}\n\n"
                             "Das Team kann es innerhalb von {hours} Stunden wieder öffnen, "
                             "danach wird dieser Kanal gelöscht.",
    "close.dm": "Dein Ticket **#{channel}** auf **{guild}** wurde geschlossen.\n"
                "**Grund:** {reason}",
    "footer.auto_delete": "🗑️ Wird nach {days} Tagen automatisch gelöscht",
    "footer.archived": "🗂️ Archiviert",
    "footer.kept": "🔒 Bleibt erhalten, bis ein Admin es löscht",
    "reopen.not_closed": "Dieses Ticket ist nicht geschlossen.",
    "reopen.done": "🔓 Ticket wieder geöffnet von {user}.",
    "delete.not_closed": "Schließe das Ticket, bevor du es löschst.",
    "delete.deleting": "🗑️ Ticket wird gelöscht...",
    "auto.warning": "⏰ {user} das Team wartet auf deine Antwort. Dieses Ticket wird in "
                    "{hours} Stunden automatisch geschlossen, wenn keine Antwort kommt.",
    "auto.reason": "Keine Antwort vom Nutzer innerhalb von {hours} Stunden",
    "rating.ask": "⭐ Wie war der Support? Bewerte ihn von 1 bis 5:",
    "rating.modal_title": "Deine Bewertung: {stars}",
    "rating.comment": "Möchtest du etwas anmerken? (optional)",
    "rating.thanks": "Danke für dein Feedback! {stars}",
    "rating.already": "Du hast dieses Ticket bereits bewertet.",
    "rating.not_owner": "Nur wer das Ticket geöffnet hat, kann es bewerten.",
    "rating.unavailable": "Dieses Ticket existiert nicht mehr.",
    "rating.log_title": "⭐ Neue Bewertung für Ticket {ticket}",
    "member.added": "➕ {user} wurde zum Ticket hinzugefügt.",
    "member.removed": "➖ {user} wurde aus dem Ticket entfernt.",
    "member.cant_remove_owner": "Du kannst die Person, die das Ticket geöffnet hat, "
                                "nicht entfernen.",
    "note.added": "📝 Notiz gespeichert. Nur das Team kann sie sehen, und sie ist im "
                  "Team-Transkript enthalten.",
    "note.none": "Dieses Ticket hat keine Notizen.",
    "note.title": "📝 Team-Notizen",
    "setup.done": "✅ Ticket-System eingerichtet (Sprache: {language}). Panel in {channel} "
                  "gepostet.\nNächste Schritte: `/guidelines`, `/types list`, `/settings show`.",
    "setup.panel_failed": "Ich kann in {channel} keine Nachrichten senden. Prüfe dort meine "
                          "Berechtigungen.",
    "guidelines.title": "📋 Richtlinien für Ticket-Prioritäten",
    "guidelines.intro": "Wenn du ein Ticket **übernimmst**, wähle die Priorität nach diesen "
                        "Regeln. Sie kann später mit `/priority` geändert werden.",
    "guidelines.priority.low": "Allgemeine Fragen, Vorschläge oder optische Probleme. "
                               "Nichts ist kaputt und niemand ist betroffen.",
    "guidelines.priority.medium": "Ein Fehler oder Problem, das einen Nutzer oder eine "
                                  "Funktion betrifft, Konto- oder Rollenprobleme, leichte "
                                  "Regelverstöße.",
    "guidelines.priority.high": "Belästigung, Drohungen, Betrug oder schwere Regelverstöße, "
                                "Sicherheitsprobleme, Probleme, die den ganzen Server "
                                "betreffen, oder alles, was als Beweis aufbewahrt werden muss.",
    "guidelines.first_reply": "**Erste Antwort:** {target}",
    "guidelines.transcripts_title": "🗂️ Transkripte",
    "guidelines.transcripts": "• Im Log-Kanal bleiben {kept}-Transkripte **erhalten**, bis "
                              "ein Admin sie löscht.\n• Alle anderen werden nach **{days} "
                              "Tagen** **automatisch** aus dem Log-Kanal **gelöscht**.\n"
                              "• Der Archiv-Kanal behält immer alle Transkripte.\n"
                              "• Tickets, die ohne Priorität geschlossen werden, zählen "
                              "als Niedrig.",
    "guidelines.posted": "📋 Richtlinien in {channel} gepostet und angepinnt.",
    "guidelines.posted_not_pinned": "📋 Richtlinien in {channel} gepostet, aber ich konnte "
                                    "sie nicht anpinnen: gib mir dort die Berechtigung "
                                    "**Nachrichten anpinnen** oder pinne sie manuell an.",
    "stats.title": "📊 Ticket-Statistiken · {period}",
    "stats.title_member": "📊 {member} · {period}",
    "stats.period.7": "letzte 7 Tage",
    "stats.period.30": "letzte 30 Tage",
    "stats.period.90": "letzte 90 Tage",
    "stats.period.all": "gesamter Zeitraum",
    "stats.tickets": "Tickets",
    "stats.tickets_value": "Geöffnet: **{opened}** · Geschlossen: **{closed}** · "
                           "Noch offen: **{open}**",
    "stats.first_response": "⏱️ Ø erste Antwort",
    "stats.resolution": "✅ Ø Bearbeitungszeit",
    "stats.rating": "⭐ Ø Bewertung",
    "stats.by_type": "Nach Art",
    "stats.by_priority": "Nach Priorität",
    "stats.staff": "👥 Team",
    "stats.staff_line": "{rank}. {user} · {handled} Tickets · {rating} · {response}",
    "stats.empty": "Keine Tickets in diesem Zeitraum.",
    "settings.title": "⚙️ Ticket-Einstellungen",
    "settings.language": "Sprache",
    "settings.staff_role": "Team-Rolle",
    "settings.category": "Ticket-Kategorie",
    "settings.log": "Log-Kanal",
    "settings.archive": "Archiv-Kanal",
    "settings.panel": "Panel-Kanal",
    "settings.retention": "Log-Aufbewahrung",
    "settings.days": "{days} Tage",
    "settings.telegram": "Telegram-Chat",
    "settings.types": "Ticket-Arten",
    "settings.language_set": "🌍 Sprache auf **{language}** gesetzt. Panel und Richtlinien "
                             "wurden aktualisiert.",
    "settings.retention_set": "🗑️ Niedrig- und Mittel-Transkripte werden nach **{days} "
                              "Tagen** aus dem Log-Kanal gelöscht.",
    "settings.archive_set": "🗂️ Alle Transkripte werden zusätzlich in {channel} gespeichert.",
    "settings.archive_off": "🗂️ Archiv-Kanal deaktiviert.",
    "types.title": "🏷️ Ticket-Arten ({count}/{max})",
    "types.too_many": "Du kannst höchstens {max} Ticket-Arten haben.",
    "types.bad_emoji": "Das ist kein gültiges Emoji. Verwende ein einzelnes Emoji wie 🐞 "
                       "oder ein Server-Emoji.",
    "types.added": "✅ Art {type} hinzugefügt (Kanal-Präfix: `{key}`).",
    "types.edited": "✅ Art aktualisiert: {type}.",
    "types.nothing": "Nichts zu ändern.",
    "types.last": "Du kannst die letzte Ticket-Art nicht entfernen.",
    "types.removed": "🗑️ Art {type} entfernt. Offene Tickets dieser Art sind nicht betroffen.",
    "transcript.title": "Transkript von #{channel}",
    "transcript.notes": "Team-Notizen",
    "transcript.footer": "{count} Nachrichten · Erstellt von TicketBot",
    "tg.new": "🎫 <b>Neues Ticket</b> auf <b>{guild}</b>\n\n<b>Art:</b> {type}\n"
              "<b>Von:</b> {user}\n<b>Betreff:</b> {subject}\n\n{description}\n\n"
              "📊 Andere offene Tickets: {waiting} wartend · {in_progress} in Bearbeitung\n"
              "<a href=\"{url}\">In Discord öffnen</a>",
    "tg.high": "🔴 <b>Ticket mit hoher Priorität</b> auf <b>{guild}</b>\n#{channel} · {type}\n"
               "<b>Betreff:</b> {subject}\n<b>Gesetzt von:</b> {user}\n"
               "<a href=\"{url}\">In Discord öffnen</a>",
    "tg.closed": "🔒 <b>Ticket geschlossen</b> auf <b>{guild}</b>\n"
                 "#{channel} · {type} · {priority}\n"
                 "<b>Geschlossen von:</b> {user}\n<b>Grund:</b> {reason}",
    "tg.rating": "⭐ <b>Neue Bewertung</b> auf <b>{guild}</b>\nTicket {ticket} · {stars}\n"
                 "<b>Bearbeitet von:</b> {staff}\n<b>Kommentar:</b> {comment}",
    "tg.disabled": "Telegram-Benachrichtigungen sind bei diesem Bot nicht aktiviert "
                   "(TELEGRAM_BOT_TOKEN fehlt).",
    "tg.bad_id": "Das sieht nicht nach einer gültigen Chat-ID aus (es muss eine Zahl sein).",
    "tg.code": "🔐 Bestätigungscode für <b>{guild}</b>: <code>{code}</code>\n\n"
               "Verwende <code>/telegram verify</code> in Discord mit diesem Code. Er läuft "
               "in {minutes} Minuten ab.\nWenn du das nicht angefordert hast, ignoriere "
               "diese Nachricht.",
    "tg.unreachable": "Ich kann diesem Chat nicht schreiben. Öffne **@{bot}** in Telegram und "
                      "tippe auf **Start** (bei einer Gruppe füge den Bot zuerst der Gruppe "
                      "hinzu), dann versuche es erneut.",
    "tg.code_sent": "📨 Ich habe einen Bestätigungscode an diesen Telegram-Chat gesendet. "
                    "Verwende `/telegram verify`, um die Verknüpfung abzuschließen.",
    "tg.no_code": "Kein gültiger Code zum Bestätigen. Führe `/telegram link` erneut aus.",
    "tg.too_many": "Falscher Code. Zu viele Versuche: führe `/telegram link` erneut aus.",
    "tg.wrong_code": "Falscher Code. Verbleibende Versuche: {left}.",
    "tg.linked": "✅ Telegram verknüpft! Tickets dieses Servers werden in diesen Chat "
                 "gemeldet.",
    "tg.linked_chat": "✅ Dieser Chat ist jetzt mit <b>{guild}</b> verknüpft.",
    "tg.status_linked": "✅ Mit dem Telegram-Chat `{chat}` verknüpft.",
    "tg.status_none": "❌ Kein Telegram-Chat verknüpft. Sende /start an **@{bot}** in "
                      "Telegram und verwende dann `/telegram link`.",
    "tg.not_linked": "Noch kein Telegram-Chat verknüpft. Verwende zuerst `/telegram link`.",
    "tg.test": "🔔 Test-Benachrichtigung von <b>{guild}</b>.",
    "tg.test_sent": "🔔 Test-Benachrichtigung gesendet.",
    "tg.unlinked": "🔕 Telegram-Benachrichtigungen deaktiviert.",
    "profile.name_set": "✅ Auf diesem Server heiße ich jetzt **{name}**.",
    "profile.avatar_set": "✅ Avatar für diesen Server aktualisiert.",
    "profile.banner_set": "✅ Banner für diesen Server aktualisiert.",
    "profile.bio_set": "✅ Bio für diesen Server aktualisiert.",
    "profile.reset": "↩️ Name, Avatar, Banner und Bio auf diesem Server auf das Original "
                     "zurückgesetzt.",
    "profile.bad_image": "Verwende ein PNG-, JPG-, GIF- oder WEBP-Bild mit höchstens {mb} MB.",
    "profile.forbidden": "Ich kann mein Profil hier nicht ändern. Gib meiner Rolle die "
                         "Berechtigung **Nickname ändern**.",
    "profile.failed": "Discord hat die Änderung abgelehnt: {error}\nWenn du Avatar oder "
                      "Banner oft hintereinander geändert hast, warte ein paar Minuten und "
                      "versuche es erneut.",
    "transcript.reactions": "Reaktionen",
    "transcript.sticker": "Sticker",
    "replies.signature": "— {staff}",
    "replies.unknown":
        "Es gibt keine Schnellantwort namens `{name}`. Verwende `/replies list`, um sie zu sehen.",
    "replies.none":
        "Es gibt noch keine Schnellantworten. Ein Admin kann sie mit `/replies add` hinzufügen.",
    "replies.title": "💬 Schnellantworten ({count}/{max})",
    "replies.exists":
        "Eine Schnellantwort namens `{name}` gibt es bereits: "
        "verwende `/replies edit`, um sie zu ändern.",
    "replies.too_many": "Du kannst höchstens {max} Schnellantworten haben.",
    "replies.bad_name":
        "Verwende einen Namen mit Buchstaben oder Zahlen, z. B. `logs` oder `erledigt`.",
    "replies.modal_title": "Schnellantwort: {name}",
    "replies.modal_label": "Text der Antwort",
    "replies.modal_hint": "Du kannst {{user}}, {{staff}} und {{server}} verwenden",
    "replies.saved": "✅ Schnellantwort `{name}` gespeichert. Vorschau:\n\n{preview}",
    "replies.removed": "🗑️ Schnellantwort `{name}` entfernt.",
    "reminder.channel":
        "⏰ {target} dieses Ticket wartet seit **{waited}** auf eine Antwort des Teams (Priorität "
        "{priority}: erste Antwort innerhalb von {hours} Std.).",
    "tg.reminder":
        "⏰ <b>Ticket wartet auf das Team</b> auf <b>{guild}</b>\n#{channel} · {priority}\nWartet "
        "seit {waited}\n<a href=\"{url}\">In Discord öffnen</a>",
    "guidelines.reminders_title": "⏰ Erinnerungen für das Team",
    "guidelines.reminders":
        "Wenn ein Ticket zu lange auf eine Antwort des Teams wartet, erinnert der Bot das Team: "
        "🔴 nach {high} Std., 🟡 nach {medium} Std., 🟢 nach {low} Std., ⚪ ohne Priorität nach "
        "{none} Std.",
    "settings.reminders": "Team-Erinnerungen",
    "settings.on": "An",
    "settings.off": "Aus",
    "settings.reminders_on": "⏰ Team-Erinnerungen aktiviert.",
    "settings.reminders_off": "⏰ Team-Erinnerungen deaktiviert.",
}


def t(lang: str, key: str, /, **kwargs) -> str:
    text = STRINGS.get(lang, {}).get(key) or STRINGS["en"].get(key) or key
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text


# ------------------------------------------------- slash command texts ---

# English text -> translation, used for command, option and choice descriptions.
COMMAND_TEXT: dict[str, dict[str, str]] = {
    "it": {
        "Turn the staff reminders on or off": "Attiva o disattiva i promemoria per lo staff",
        "Remind the staff when a ticket waits too long for a reply":
            "Avvisa lo staff quando un ticket aspetta troppo una risposta",
        "Send a quick reply in this ticket": "Invia una risposta rapida in questo ticket",
        "Quick reply to send": "Risposta rapida da inviare",
        "Manage the quick replies of this server": "Gestisci le risposte rapide di questo server",
        "Show the quick replies": "Mostra le risposte rapide",
        "Add a quick reply": "Aggiungi una risposta rapida",
        "Name of the quick reply (e.g. logs)": "Nome della risposta rapida (es. log)",
        "Edit a quick reply": "Modifica una risposta rapida",
        "Quick reply to edit": "Risposta rapida da modificare",
        "Remove a quick reply": "Rimuovi una risposta rapida",
        "Quick reply to remove": "Risposta rapida da rimuovere",
        "Customize the bot's profile in this server":
            "Personalizza il profilo del bot in questo server",
        "Change the bot's name in this server": "Cambia il nome del bot in questo server",
        "New name (up to 32 characters)": "Nuovo nome (massimo 32 caratteri)",
        "Change the bot's avatar in this server": "Cambia l'avatar del bot in questo server",
        "Image (PNG, JPG, GIF or WEBP, max 8 MB)": "Immagine (PNG, JPG, GIF o WEBP, max 8 MB)",
        "Change the bot's banner in this server": "Cambia il banner del bot in questo server",
        "Change the bot's bio in this server": "Cambia la bio del bot in questo server",
        "New bio (up to 190 characters)": "Nuova bio (massimo 190 caratteri)",
        "Restore the bot's original profile in this server":
            "Ripristina il profilo originale del bot in questo server",
        "Set up the ticket system and post the panel":
            "Configura il sistema ticket e pubblica il pannello",
        "Role of the moderators who handle tickets": "Ruolo dei moderatori che gestiscono i ticket",
        "Category where ticket channels are created": "Categoria in cui creare i canali ticket",
        "Channel where transcripts are logged": "Canale in cui salvare le trascrizioni",
        "Channel where the 'Open ticket' button is posted":
            "Canale in cui pubblicare il pulsante 'Apri ticket'",
        "(Optional) Archive channel that keeps every transcript":
            "(Facoltativo) Canale archivio che conserva tutte le trascrizioni",
        "Post and pin the priority guidelines in the log channel":
            "Pubblica e fissa le linee guida sulle priorità nel canale log",
        "Show how many tickets are open right now": "Mostra quanti ticket sono aperti ora",
        "Add a member to this ticket": "Aggiungi un membro a questo ticket",
        "Member to add": "Membro da aggiungere",
        "Remove a member from this ticket": "Rimuovi un membro da questo ticket",
        "Member to remove": "Membro da rimuovere",
        "Close this ticket": "Chiudi questo ticket",
        "(Optional) Reason for closing the ticket": "(Facoltativo) Motivo della chiusura",
        "Reopen this closed ticket": "Riapri questo ticket chiuso",
        "Change the priority of this ticket": "Cambia la priorità di questo ticket",
        "New priority": "Nuova priorità",
        "Low": "Bassa",
        "Medium": "Media",
        "High": "Alta",
        "Assign this ticket to another staff member":
            "Assegna questo ticket a un altro membro dello staff",
        "Staff member who will handle the ticket": "Membro dello staff che gestirà il ticket",
        "Private staff notes on this ticket": "Note private dello staff su questo ticket",
        "Add a private note visible only to the staff":
            "Aggiungi una nota privata visibile solo allo staff",
        "Text of the note": "Testo della nota",
        "Show the private notes of this ticket": "Mostra le note private di questo ticket",
        "Show ticket statistics": "Mostra le statistiche dei ticket",
        "Time period": "Periodo",
        "Show the statistics of one staff member": "Mostra le statistiche di un membro dello staff",
        "Last 7 days": "Ultimi 7 giorni",
        "Last 30 days": "Ultimi 30 giorni",
        "Last 90 days": "Ultimi 90 giorni",
        "All time": "Da sempre",
        "Ticket system settings": "Impostazioni del sistema ticket",
        "Show the current settings": "Mostra le impostazioni attuali",
        "Change the language of the bot": "Cambia la lingua del bot",
        "Language used by the bot in this server": "Lingua usata dal bot in questo server",
        "Days after which Low/Medium transcripts are deleted from the log":
            "Giorni dopo cui le trascrizioni Bassa/Media vengono eliminate dal log",
        "Number of days (1-365)": "Numero di giorni (1-365)",
        "Set or remove the archive channel": "Imposta o rimuovi il canale archivio",
        "Archive channel (leave empty to disable it)":
            "Canale archivio (lascia vuoto per disattivarlo)",
        "Manage the ticket types of this server": "Gestisci i tipi di ticket di questo server",
        "Show the ticket types": "Mostra i tipi di ticket",
        "Add a ticket type": "Aggiungi un tipo di ticket",
        "Name of the type": "Nome del tipo",
        "Emoji shown next to the name": "Emoji mostrata accanto al nome",
        "(Optional) Short description shown in the menu":
            "(Facoltativo) Breve descrizione mostrata nel menu",
        "Edit a ticket type": "Modifica un tipo di ticket",
        "Type to edit": "Tipo da modificare",
        "New name": "Nuovo nome",
        "New emoji": "Nuova emoji",
        "New description": "Nuova descrizione",
        "Remove a ticket type": "Rimuovi un tipo di ticket",
        "Type to remove": "Tipo da rimuovere",
        "Ticket notifications on Telegram": "Notifiche dei ticket su Telegram",
        "Link a Telegram chat to this server": "Collega una chat Telegram a questo server",
        "Telegram chat ID (send /start to the Telegram bot to get it)":
            "Chat ID di Telegram (invia /start al bot Telegram per ottenerlo)",
        "Confirm the Telegram link with the code":
            "Conferma il collegamento Telegram con il codice",
        "The 6-digit code you received on Telegram": "Il codice di 6 cifre ricevuto su Telegram",
        "Show the Telegram link of this server": "Mostra il collegamento Telegram di questo server",
        "Send a test notification to Telegram": "Invia una notifica di prova su Telegram",
        "Stop sending notifications to Telegram": "Smetti di inviare notifiche su Telegram",
    },
    "de": {
        "Turn the staff reminders on or off": "Team-Erinnerungen ein- oder ausschalten",
        "Remind the staff when a ticket waits too long for a reply":
            "Das Team erinnern, wenn ein Ticket zu lange auf eine Antwort wartet",
        "Send a quick reply in this ticket": "Eine Schnellantwort in diesem Ticket senden",
        "Quick reply to send": "Zu sendende Schnellantwort",
        "Manage the quick replies of this server": "Schnellantworten dieses Servers verwalten",
        "Show the quick replies": "Schnellantworten anzeigen",
        "Add a quick reply": "Schnellantwort hinzufügen",
        "Name of the quick reply (e.g. logs)": "Name der Schnellantwort (z. B. logs)",
        "Edit a quick reply": "Schnellantwort bearbeiten",
        "Quick reply to edit": "Zu bearbeitende Schnellantwort",
        "Remove a quick reply": "Schnellantwort entfernen",
        "Quick reply to remove": "Zu entfernende Schnellantwort",
        "Customize the bot's profile in this server": "Profil des Bots auf diesem Server anpassen",
        "Change the bot's name in this server": "Namen des Bots auf diesem Server ändern",
        "New name (up to 32 characters)": "Neuer Name (bis zu 32 Zeichen)",
        "Change the bot's avatar in this server": "Avatar des Bots auf diesem Server ändern",
        "Image (PNG, JPG, GIF or WEBP, max 8 MB)": "Bild (PNG, JPG, GIF oder WEBP, max. 8 MB)",
        "Change the bot's banner in this server": "Banner des Bots auf diesem Server ändern",
        "Change the bot's bio in this server": "Bio des Bots auf diesem Server ändern",
        "New bio (up to 190 characters)": "Neue Bio (bis zu 190 Zeichen)",
        "Restore the bot's original profile in this server":
            "Ursprüngliches Profil des Bots auf diesem Server wiederherstellen",
        "Set up the ticket system and post the panel":
            "Ticket-System einrichten und das Panel posten",
        "Role of the moderators who handle tickets":
            "Rolle der Moderatoren, die Tickets bearbeiten",
        "Category where ticket channels are created":
            "Kategorie, in der Ticket-Kanäle erstellt werden",
        "Channel where transcripts are logged": "Kanal, in dem Transkripte protokolliert werden",
        "Channel where the 'Open ticket' button is posted":
            "Kanal, in dem der Button 'Ticket öffnen' gepostet wird",
        "(Optional) Archive channel that keeps every transcript":
            "(Optional) Archiv-Kanal, der alle Transkripte behält",
        "Post and pin the priority guidelines in the log channel":
            "Prioritäts-Richtlinien im Log-Kanal posten und anpinnen",
        "Show how many tickets are open right now": "Zeigen, wie viele Tickets gerade offen sind",
        "Add a member to this ticket": "Ein Mitglied zu diesem Ticket hinzufügen",
        "Member to add": "Hinzuzufügendes Mitglied",
        "Remove a member from this ticket": "Ein Mitglied aus diesem Ticket entfernen",
        "Member to remove": "Zu entfernendes Mitglied",
        "Close this ticket": "Dieses Ticket schließen",
        "(Optional) Reason for closing the ticket": "(Optional) Grund für das Schließen",
        "Reopen this closed ticket": "Dieses geschlossene Ticket wieder öffnen",
        "Change the priority of this ticket": "Priorität dieses Tickets ändern",
        "New priority": "Neue Priorität",
        "Low": "Niedrig",
        "Medium": "Mittel",
        "High": "Hoch",
        "Assign this ticket to another staff member":
            "Dieses Ticket einem anderen Teammitglied zuweisen",
        "Staff member who will handle the ticket": "Teammitglied, das das Ticket bearbeitet",
        "Private staff notes on this ticket": "Private Team-Notizen zu diesem Ticket",
        "Add a private note visible only to the staff":
            "Private Notiz hinzufügen, nur für das Team sichtbar",
        "Text of the note": "Text der Notiz",
        "Show the private notes of this ticket": "Private Notizen dieses Tickets anzeigen",
        "Show ticket statistics": "Ticket-Statistiken anzeigen",
        "Time period": "Zeitraum",
        "Show the statistics of one staff member": "Statistiken eines Teammitglieds anzeigen",
        "Last 7 days": "Letzte 7 Tage",
        "Last 30 days": "Letzte 30 Tage",
        "Last 90 days": "Letzte 90 Tage",
        "All time": "Gesamter Zeitraum",
        "Ticket system settings": "Einstellungen des Ticket-Systems",
        "Show the current settings": "Aktuelle Einstellungen anzeigen",
        "Change the language of the bot": "Sprache des Bots ändern",
        "Language used by the bot in this server": "Sprache des Bots auf diesem Server",
        "Days after which Low/Medium transcripts are deleted from the log":
            "Tage, nach denen Niedrig-/Mittel-Transkripte aus dem Log gelöscht werden",
        "Number of days (1-365)": "Anzahl der Tage (1-365)",
        "Set or remove the archive channel": "Archiv-Kanal festlegen oder entfernen",
        "Archive channel (leave empty to disable it)":
            "Archiv-Kanal (leer lassen zum Deaktivieren)",
        "Manage the ticket types of this server": "Ticket-Arten dieses Servers verwalten",
        "Show the ticket types": "Ticket-Arten anzeigen",
        "Add a ticket type": "Ticket-Art hinzufügen",
        "Name of the type": "Name der Art",
        "Emoji shown next to the name": "Emoji neben dem Namen",
        "(Optional) Short description shown in the menu":
            "(Optional) Kurze Beschreibung im Menü",
        "Edit a ticket type": "Ticket-Art bearbeiten",
        "Type to edit": "Zu bearbeitende Art",
        "New name": "Neuer Name",
        "New emoji": "Neues Emoji",
        "New description": "Neue Beschreibung",
        "Remove a ticket type": "Ticket-Art entfernen",
        "Type to remove": "Zu entfernende Art",
        "Ticket notifications on Telegram": "Ticket-Benachrichtigungen auf Telegram",
        "Link a Telegram chat to this server": "Einen Telegram-Chat mit diesem Server verknüpfen",
        "Telegram chat ID (send /start to the Telegram bot to get it)":
            "Telegram-Chat-ID (sende /start an den Telegram-Bot, um sie zu erhalten)",
        "Confirm the Telegram link with the code": "Telegram-Verknüpfung mit dem Code bestätigen",
        "The 6-digit code you received on Telegram": "Der 6-stellige Code aus Telegram",
        "Show the Telegram link of this server": "Telegram-Verknüpfung dieses Servers anzeigen",
        "Send a test notification to Telegram": "Test-Benachrichtigung an Telegram senden",
        "Stop sending notifications to Telegram":
            "Keine Benachrichtigungen mehr an Telegram senden",
    },
}

_NOT_TRANSLATED = (
    app_commands.TranslationContextLocation.command_name,
    app_commands.TranslationContextLocation.group_name,
    app_commands.TranslationContextLocation.parameter_name,
)


class CommandTranslator(app_commands.Translator):
    """Translates descriptions and choice names; command names stay in English."""

    async def translate(self, string: app_commands.locale_str, locale, context):
        if context.location in _NOT_TRANSLATED:
            return None
        lang = str(locale.value if hasattr(locale, "value") else locale).split("-")[0]
        return COMMAND_TEXT.get(lang, {}).get(string.message)
