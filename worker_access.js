const TELEGRAM_API = (token, method) =>
  `https://api.telegram.org/bot${token}/${method}`;

async function telegram(env, method, data) {
  const response = await fetch(TELEGRAM_API(env.TELEGRAM_BOT_TOKEN, method), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  return await response.json();
}

async function sendMessage(env, chatId, text, extra = {}) {
  return telegram(env, "sendMessage", {
    chat_id: chatId,
    text,
    parse_mode: "HTML",
    ...extra,
  });
}

async function answerCallback(env, callbackId) {
  return telegram(env, "answerCallbackQuery", {
    callback_query_id: callbackId,
  });
}

async function saveUser(env, user, status = "pending") {
  await env.DB.prepare(`
    INSERT INTO users (id, first_name, last_name, username, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      first_name = excluded.first_name,
      last_name = excluded.last_name,
      username = excluded.username
  `).bind(
    String(user.id),
    user.first_name || "",
    user.last_name || "",
    user.username || "",
    status,
    new Date().toISOString()
  ).run();
}

async function getUser(env, id) {
  return await env.DB.prepare(
    "SELECT * FROM users WHERE id = ?"
  ).bind(String(id)).first();
}

async function requestAccess(env, user) {
  const existing = await getUser(env, user.id);

  if (existing?.status === "approved") {
    await sendMessage(
      env,
      user.id,
      "✅ <b>Έχεις ήδη πρόσβαση.</b>\n\nΕίσαι εγκεκριμένος χρήστης."
    );
    return;
  }

  await saveUser(env, user, "pending");

  const name = [user.first_name, user.last_name]
    .filter(Boolean)
    .join(" ") || "—";

  const username = user.username ? `@${user.username}` : "—";

  await sendMessage(
    env,
    env.ADMIN_CHAT_ID,
    `📩 <b>ΝΕΟ ACCESS REQUEST</b>\n\n` +
    `👤 Όνομα: ${escapeHtml(name)}\n` +
    `🔗 Username: ${escapeHtml(username)}\n` +
    `🆔 ID: <code>${user.id}</code>`,
    {
      reply_markup: {
        inline_keyboard: [
          [
            { text: "✅ ACCEPT", callback_data: `accept:${user.id}` },
            { text: "❌ REJECT", callback_data: `reject:${user.id}` }
          ]
        ]
      }
    }
  );

  await sendMessage(
    env,
    user.id,
    "📩 <b>Το αίτημά σου στάλθηκε.</b>\n\n" +
    "Περίμενε την έγκριση του διαχειριστή."
  );
}

async function handleCallback(env, callback) {
  const fromId = String(callback.from?.id || "");

  if (fromId !== String(env.ADMIN_CHAT_ID)) {
    await answerCallback(env, callback.id);
    return;
  }

  const data = callback.data || "";
  const [action, userId] = data.split(":");

  if (!userId || !["accept", "reject"].includes(action)) {
    await answerCallback(env, callback.id);
    return;
  }

  const user = await getUser(env, userId);

  if (!user) {
    await answerCallback(env, callback.id);
    return;
  }

  if (action === "accept") {
    await env.DB.prepare(
      "UPDATE users SET status = 'approved' WHERE id = ?"
    ).bind(userId).run();

    await sendMessage(
      env,
      userId,
      "✅ <b>ACCESS APPROVED</b>\n\n" +
      "Καλώς ήρθες! Έχεις πλέον πρόσβαση στα Football Tips."
    );

    await telegram(env, "editMessageText", {
      chat_id: env.ADMIN_CHAT_ID,
      message_id: callback.message.message_id,
      text:
        `✅ <b>USER ACCEPTED</b>\n\n` +
        `👤 ${escapeHtml([user.first_name, user.last_name].filter(Boolean).join(" ") || "—")}\n` +
        `🔗 ${escapeHtml(user.username ? "@" + user.username : "—")}\n` +
        `🆔 <code>${userId}</code>`,
      parse_mode: "HTML",
    });
  }

  if (action === "reject") {
    await env.DB.prepare(
      "UPDATE users SET status = 'rejected' WHERE id = ?"
    ).bind(userId).run();

    await sendMessage(
      env,
      userId,
      "❌ <b>Το αίτημά σου απορρίφθηκε.</b>"
    );

    await telegram(env, "editMessageText", {
      chat_id: env.ADMIN_CHAT_ID,
      message_id: callback.message.message_id,
      text:
        `❌ <b>USER REJECTED</b>\n\n` +
        `👤 ${escapeHtml([user.first_name, user.last_name].filter(Boolean).join(" ") || "—")}\n` +
        `🔗 ${escapeHtml(user.username ? "@" + user.username : "—")}\n` +
        `🆔 <code>${userId}</code>`,
      parse_mode: "HTML",
    });
  }

  await answerCallback(env, callback.id);
}

async function broadcast(env, message) {
  const result = await env.DB.prepare(
    "SELECT id FROM users WHERE status = 'approved'"
  ).all();

  let sent = 0;

  for (const user of result.results || []) {
    try {
      const response = await sendMessage(env, user.id, message);

      if (response.ok) {
        sent++;
      }
    } catch (_) {}
  }

  return sent;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function handleTelegramUpdate(env, update) {
  if (update.callback_query) {
    await handleCallback(env, update.callback_query);
    return;
  }

  const message = update.message;
  if (!message) return;

  const user = message.from;
  const text = message.text || "";

  if (text === "/start") {
    await sendMessage(
      env,
      message.chat.id,
      "🔥 <b>FOOTBALL TIPS</b>\n\n" +
      "Καλώς ήρθες!\n\n" +
      "Πάτησε το κουμπί παρακάτω για να ζητήσεις πρόσβαση.",
      {
        reply_markup: {
          inline_keyboard: [
            [{ text: "📩 REQUEST ACCESS", callback_data: "request_access" }]
          ]
        }
      }
    );
    return;
  }

  if (text === "/status") {
    const existing = await getUser(env, user.id);

    const status = existing?.status || "pending";

    await sendMessage(
      env,
      message.chat.id,
      `📊 <b>Access status:</b> ${status}`
    );
  }
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);

      if (request.method === "GET") {
        return new Response("FootballTips Access Worker OK");
      }

      if (url.pathname === "/broadcast" && request.method === "POST") {
        const secret = request.headers.get("X-Broadcast-Secret");

        if (!secret || secret !== env.BROADCAST_SECRET) {
          return new Response("Unauthorized", { status: 401 });
        }

        const body = await request.json();
        const message = body.message;

        if (!message) {
          return new Response("Missing message", { status: 400 });
        }

        const sent = await broadcast(env, message);

        return Response.json({
          ok: true,
          sent,
        });
      }

      if (url.pathname === "/" && request.method === "POST") {
        const update = await request.json();

        if (update.callback_query?.data === "request_access") {
          await requestAccess(env, update.callback_query.from);
          await answerCallback(env, update.callback_query.id);
          return Response.json({ ok: true });
        }

        await handleTelegramUpdate(env, update);

        return Response.json({ ok: true });
      }

      return new Response("Not Found", { status: 404 });

    } catch (error) {
      return new Response(
        JSON.stringify({ ok: false, error: String(error) }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" }
        }
      );
    }
  }
};
