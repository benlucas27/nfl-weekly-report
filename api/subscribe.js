// POST { email } -> adds the address to the Resend audience used for the weekly send.
// Requires RESEND_API_KEY and RESEND_AUDIENCE_ID set as Vercel env vars.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "Method not allowed" });
  }

  const { email } = req.body || {};

  if (typeof email !== "string" || !EMAIL_RE.test(email)) {
    return res.status(400).json({ error: "Enter a valid email address." });
  }

  const apiKey = process.env.RESEND_API_KEY;
  const audienceId = process.env.RESEND_AUDIENCE_ID;

  if (!apiKey || !audienceId) {
    return res.status(500).json({ error: "Server is not configured yet." });
  }

  try {
    const resendRes = await fetch(
      `https://api.resend.com/audiences/${audienceId}/contacts`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, unsubscribed: false }),
      }
    );

    if (!resendRes.ok) {
      const detail = await resendRes.text();
      // Resend returns 409-ish errors for duplicates depending on version; treat as success either way.
      if (resendRes.status === 400 && /already exists|duplicate/i.test(detail)) {
        return res.status(200).json({ ok: true, message: "You're already subscribed." });
      }
      console.error("Resend error:", resendRes.status, detail);
      return res.status(502).json({ error: "Could not subscribe right now. Try again shortly." });
    }

    return res.status(200).json({ ok: true, message: "Subscribed — first report lands Thursday." });
  } catch (err) {
    console.error("Subscribe handler failed:", err);
    return res.status(500).json({ error: "Unexpected error. Try again shortly." });
  }
}
