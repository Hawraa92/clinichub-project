const canvas = document.getElementById('innerverse-canvas');
const ctx = canvas.getContext('2d');

let width, height;
function resizeCanvas() {
  width = canvas.width = window.innerWidth;
  height = canvas.height = canvas.parentElement.offsetHeight;
}
window.addEventListener('resize', resizeCanvas);
resizeCanvas();

const syringeImg = new Image();
syringeImg.src = '/static/assets/icons/syringe.jpg';

syringeImg.onload = () => {
  const particles = [];

  for (let i = 0; i < 40; i++) {
    particles.push({
      x: Math.random() * width,
      y: Math.random() * height,
      dx: 0.2 - Math.random() * 0.4,
      dy: 0.2 - Math.random() * 0.4,
      size: Math.random() * 24 + 20,
      opacity: Math.random() * 0.3 + 0.2,
      angle: Math.random() * Math.PI * 2
    });
  }

  function animate() {
    ctx.clearRect(0, 0, width, height);

    particles.forEach(p => {
      p.x += p.dx;
      p.y += p.dy;
      p.angle += 0.003;

      if (p.x < -50 || p.x > width + 50) p.dx *= -1;
      if (p.y < -50 || p.y > height + 50) p.dy *= -1;

      ctx.save();
      ctx.globalAlpha = p.opacity;
      ctx.translate(p.x, p.y);
      ctx.rotate(p.angle);
      ctx.drawImage(syringeImg, -p.size / 2, -p.size / 2, p.size, p.size);
      ctx.restore();
    });

    requestAnimationFrame(animate);
  }

  animate();
};
