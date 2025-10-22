// static/js/home.js
(function () {
  'use strict';

  const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $  = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const cssVar = (name, fallback = '') => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

  document.addEventListener('DOMContentLoaded', () => {
    initAnimatedCounters();
    initOrganPreview();
    initTypingEffect();
    initHealthCharts();
    initAIDemo();
  });

  /* -------------------- 1) Animated Counters -------------------- */
  function initAnimatedCounters() {
    const nodes = document.querySelectorAll('.stat-number[data-count], .num[data-target]');
    if (!nodes.length) return;

    const easeOutQuad = (t) => t * (2 - t);
    const DURATION = 2000;

    const animate = (el) => {
      const target = parseInt(el.getAttribute('data-count') || el.getAttribute('data-target') || '0', 10);
      if (!Number.isFinite(target)) return;
      if (prefersReduced) { el.textContent = target.toLocaleString(); return; }

      let start;
      const tick = (ts) => {
        if (!start) start = ts;
        const p = Math.min(1, (ts - start) / DURATION);
        const eased = easeOutQuad(p);
        el.textContent = Math.round(target * eased).toLocaleString();
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };

    if ('IntersectionObserver' in window && !prefersReduced) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          animate(e.target);
          io.unobserve(e.target);
        });
      }, { threshold: 0.2 });
      nodes.forEach((n) => { n.textContent = '0'; io.observe(n); });
    } else {
      nodes.forEach(animate);
    }
  }

  /* -------------------- 2) Organ Preview -------------------- */
  function initOrganPreview() {
    const organs = $$('.organ');
    if (!organs.length) return;

    const setActive = (i) => {
      organs.forEach((o) => o.classList.remove('active'));
      if (organs[i]) organs[i].classList.add('active');
    };

    setActive(0);
    if (prefersReduced) return;

    let idx = 0;
    setInterval(() => {
      idx = (idx + 1) % organs.length;
      setActive(idx);
    }, 3000);
  }

  /* -------------------- 3) Typing Effect -------------------- */
  function initTypingEffect() {
    const el = $('.typing-text');
    if (!el) return;

    const words =
      (el.getAttribute('data-words') || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean) ||
      ['Management Platform', 'Diagnostic System', 'Patient Hub', 'AI Assistant'];

    if (prefersReduced) { el.textContent = words[0]; return; }

    let wi = 0, ci = 0, del = false;
    const tick = () => {
      const w = words[wi];
      el.textContent = del ? w.slice(0, ci--) : w.slice(0, ci++);
      let delay = del ? 60 : 90;

      if (!del && ci === w.length + 2) { del = true; delay = 800; }
      else if (del && ci < 0) { del = false; wi = (wi + 1) % words.length; delay = 350; }

      setTimeout(tick, delay);
    };
    setTimeout(tick, 500);
  }

  /* -------------------- 4) Health Charts -------------------- */
  function initHealthCharts() {
    const heartEl = $('#heartRateChart');
    const respEl  = $('#respiratoryChart');
    const neuroEl = $('#neuroChart');
    if (!heartEl && !respEl && !neuroEl) return;

    const palette = {
      primary:   cssVar('--medical-primary', cssVar('--primary', '#2563eb')),
      secondary: cssVar('--medical-secondary', cssVar('--accent', '#0ea5e9')),
      accent:    cssVar('--medical-accent', '#10b981'),
      ink:       cssVar('--ink', '#0f172a'),
      grid:      'rgba(100,116,139,.20)'
    };

    const hexToRgba = (hex, a = 0.15) => {
      const m = hex.replace('#', '');
      const full = m.length === 3 ? m.split('').map((x) => x + x).join('') : m;
      const n = parseInt(full, 16);
      const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
      return `rgba(${r},${g},${b},${a})`;
    };

    const demo = {
      heart: [68, 70, 72, 71, 73, 76, 72, 71, 72, 73, 72, 72],
      o2:    [97, 98, 96, 99, 97, 98, 97],
      brain: [65, 59, 80, 70, 75]
    };

    const drawFallbackLine = (canvas, data, color) => {
      if (!canvas || !canvas.getContext) return;
      const W = canvas.clientWidth || 320;
      const H = canvas.clientHeight || 180;
      canvas.width = W; canvas.height = H;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, W, H);
      ctx.strokeStyle = palette.grid; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, H - 0.5); ctx.lineTo(W, H - 0.5); ctx.stroke();
      const min = Math.min(...data), max = Math.max(...data), span = (max - min) || 1;
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
      data.forEach((v, i) => {
        const x = (i / (data.length - 1)) * (W - 10) + 5;
        const y = H - ((v - min) / span) * (H - 10) - 5;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.stroke();
    };

    if (window.Chart) {
      // Heart (line)
      if (heartEl) {
        const ctx = heartEl.getContext('2d');
        const grad = ctx.createLinearGradient(0, 0, 0, heartEl.height || 180);
        grad.addColorStop(0, hexToRgba(palette.primary, .25));
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        new Chart(heartEl, {
          type: 'line',
          data: {
            labels: demo.heart.map((_, i) => i + 1),
            datasets: [{
              data: demo.heart, borderColor: palette.primary, backgroundColor: grad,
              tension: .35, pointRadius: 0, borderWidth: 2, fill: true
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false } }
          }
        });
      }

      // Respiratory (bar)
      if (respEl) {
        new Chart(respEl, {
          type: 'bar',
          data: {
            labels: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],
            datasets: [{
              data: demo.o2,
              backgroundColor: hexToRgba(palette.secondary, .7),
              borderColor: palette.secondary, borderWidth: 1, borderRadius: 6
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
              y: { beginAtZero: false, min: 95, max: 100, grid: { color: palette.grid } },
              x: { grid: { display: false } }
            }
          }
        });
      }

      // Neuro (radar)
      if (neuroEl) {
        new Chart(neuroEl, {
          type: 'radar',
          data: {
            labels: ['Alpha','Beta','Theta','Delta','Gamma'],
            datasets: [{
              data: demo.brain,
              backgroundColor: hexToRgba(palette.accent, .2),
              borderColor: palette.accent,
              pointBackgroundColor: palette.accent,
              pointBorderColor: '#fff'
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { r: {
              min: 0, max: 100,
              angleLines: { color: palette.grid },
              grid: { color: palette.grid },
              pointLabels: { color: palette.ink }
            } }
          }
        });
      }
    } else {
      // Fallback بسيط لو Chart.js غير متوفر
      if (heartEl) drawFallbackLine(heartEl, demo.heart, palette.primary);
      if (respEl)  drawFallbackLine(respEl,  demo.o2,    palette.secondary);
      if (neuroEl) drawFallbackLine(neuroEl, demo.brain, palette.accent);
    }
  }

  /* -------------------- 5) AI Demo Steps -------------------- */
  function initAIDemo() {
    const steps = $$('.process-step');
    if (!steps.length) return;

    const setActive = (i) => {
      steps.forEach((s) => s.classList.remove('active'));
      steps[i].classList.add('active');
    };

    setActive(0);
    if (prefersReduced) return;

    let i = 0;
    setInterval(() => {
      i = (i + 1) % steps.length;
      setActive(i);
    }, 1500);
  }
})();
