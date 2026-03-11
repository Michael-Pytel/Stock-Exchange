/* ─── HEADER: context-aware dark/light pill mode ─────────── */
const header = document.getElementById('main-header');

function updateHeader() {
  if (window.scrollY < 60) {
    header.classList.remove('scrolled-dark', 'scrolled-light');
    return;
  }

  const featuresEl = document.getElementById('features');
  if (!featuresEl) {
    // No features section on this page — always use dark mode
    header.classList.add('scrolled-dark');
    header.classList.remove('scrolled-light');
    return;
  }

  const rect = featuresEl.getBoundingClientRect();
  const overLight = rect.top <= 72 && rect.bottom > 72;

  header.classList.toggle('scrolled-light', overLight);
  header.classList.toggle('scrolled-dark', !overLight);
}

window.addEventListener('scroll', updateHeader, { passive: true });
updateHeader();