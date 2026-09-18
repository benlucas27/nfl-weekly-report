// Shared subscribe form. Mounts into every element matching
// [data-subscribe-widget] (any number per page, e.g. one near the top and one
// at the bottom). Usage: <div data-subscribe-widget></div>
// plus once per page: <script src="/subscribe-widget.js"></script>
(function () {
  const mounts = document.querySelectorAll('[data-subscribe-widget]');
  if (!mounts.length) return;

  mounts.forEach((mount, i) => {
    const emailId = `widget-email-${i}`;
    const msgId = `widget-msg-${i}`;
    const btnId = `widget-btn-${i}`;

    mount.innerHTML = `
      <div class="subscribe-cta">
        <div class="subscribe-cta-text">Get this in your inbox before kickoff, every week.</div>
        <form class="signup">
          <input type="email" id="${emailId}" placeholder="you@email.com" required />
          <button type="submit" id="${btnId}">Subscribe</button>
        </form>
        <div class="msg" id="${msgId}"></div>
      </div>
    `;

    const form = mount.querySelector('form');
    const msg = document.getElementById(msgId);
    const btn = document.getElementById(btnId);
    const emailInput = document.getElementById(emailId);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = emailInput.value.trim();
      btn.disabled = true;
      msg.textContent = '';
      msg.className = 'msg';

      try {
        const res = await fetch('/api/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        });
        const data = await res.json();

        if (res.ok) {
          msg.textContent = data.message || 'Subscribed.';
          msg.classList.add('ok');
          form.reset();
        } else {
          msg.textContent = data.error || 'Something went wrong.';
          msg.classList.add('err');
        }
      } catch (err) {
        msg.textContent = 'Network error — try again.';
        msg.classList.add('err');
      } finally {
        btn.disabled = false;
      }
    });
  });
})();
