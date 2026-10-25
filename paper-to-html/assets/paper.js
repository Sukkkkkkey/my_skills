(() => {
  'use strict';
  const dialog = document.querySelector('#image-dialog');
  let previousFocus;
  document.querySelectorAll('a.zoom').forEach(link => link.addEventListener('click', event => {
    if (!dialog || typeof dialog.showModal !== 'function') return;
    event.preventDefault();
    previousFocus = link;
    const original = link.querySelector('img');
    const large = dialog.querySelector('img');
    large.src = link.href;
    large.alt = original.alt;
    large.style.width = '100%';
    const sizeButton = document.querySelector('#image-size');
    sizeButton.setAttribute('aria-pressed', 'false');
    sizeButton.textContent = '原尺寸';
    document.querySelector('#image-title').textContent = link.closest('figure').querySelector('figcaption > strong').textContent;
    dialog.showModal();
    document.querySelector('#image-close').focus();
  }));
  document.querySelector('#image-close')?.addEventListener('click', () => dialog.close());
  document.querySelector('#image-size')?.addEventListener('click', event => {
    const button = event.currentTarget;
    const originalSize = button.getAttribute('aria-pressed') !== 'true';
    const large = document.querySelector('#image-large');
    large.style.width = originalSize ? large.naturalWidth + 'px' : '100%';
    button.setAttribute('aria-pressed', String(originalSize));
    button.textContent = originalSize ? '适应窗口' : '原尺寸';
  });
  dialog?.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog?.addEventListener('close', () => previousFocus?.focus());
  const fontButton = document.querySelector('#font-toggle');
  if (fontButton) {
    fontButton.hidden = false;
    fontButton.addEventListener('click', () => {
      const enlarged = document.body.classList.toggle('large');
      fontButton.setAttribute('aria-pressed', String(enlarged));
      fontButton.textContent = enlarged ? '标准字号' : '大字阅读';
    });
  }
  const sections = [...document.querySelectorAll('main section[id]')];
  const links = [...document.querySelectorAll('.toc a')];
  let queued = false;
  const updateCurrent = () => {
    queued = false;
    const current = sections.filter(s => s.getBoundingClientRect().top <= 160).at(-1);
    links.forEach(a => {
      const active = !!current && a.hash === '#' + current.id;
      a.classList.toggle('active', active);
      if (active) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
    });
  };
  window.addEventListener('scroll', () => {if (!queued) {queued = true; requestAnimationFrame(updateCurrent);}}, {passive:true});
  window.addEventListener('resize', updateCurrent);
  updateCurrent();
  window.addEventListener('beforeprint', () => {
    document.querySelectorAll('details:not(.toc)').forEach(d => { d.dataset.printOpen = String(d.open); d.open = true; });
  });
  window.addEventListener('afterprint', () => {
    document.querySelectorAll('details[data-print-open]').forEach(d => { d.open = d.dataset.printOpen === 'true'; delete d.dataset.printOpen; });
  });
})();
