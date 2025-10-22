// prescription-tilt.js
// Vanilla JS tilt effect
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-tilt]').forEach(card => {
      const inner = card.querySelector('.card-inner');
      card.addEventListener('mousemove', e => {
        const rect = card.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width)  * 2 - 1;
        const y = ((e.clientY - rect.top)  / rect.height) * 2 - 1;
        inner.style.transform = `rotateY(${x * 15}deg) rotateX(${ -y * 15 }deg)`;
      });
      card.addEventListener('mouseleave', () => {
        inner.style.transform = 'rotateY(0) rotateX(0)';
      });
    });
  });
  