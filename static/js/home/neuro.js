// neuro.js - Medical Background Animation
function initNeuroBackground() {
    const canvas = document.getElementById('neuroCanvas');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    
    // Set canvas dimensions
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    
    // Neuron class
    class Neuron {
      constructor() {
        this.x = Math.random() * canvas.width;
        this.y = Math.random() * canvas.height;
        this.size = Math.random() * 3 + 1;
        this.speedX = Math.random() * 2 - 1;
        this.speedY = Math.random() * 2 - 1;
        this.color = `rgba(26, 158, 143, ${Math.random() * 0.5 + 0.3})`;
      }
      
      update() {
        this.x += this.speedX;
        this.y += this.speedY;
        
        if (this.x > canvas.width || this.x < 0) this.speedX *= -1;
        if (this.y > canvas.height || this.y < 0) this.speedY *= -1;
      }
      
      draw() {
        ctx.fillStyle = this.color;
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    
    // Synapse class
    class Synapse {
      constructor(neuron1, neuron2) {
        this.neuron1 = neuron1;
        this.neuron2 = neuron2;
        this.life = 100;
        this.active = false;
        this.color = `rgba(26, 158, 143, ${Math.random() * 0.2})`;
      }
      
      update() {
        const dx = this.neuron1.x - this.neuron2.x;
        const dy = this.neuron1.y - this.neuron2.y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        
        if (distance < 150 && Math.random() > 0.95) {
          this.active = true;
          this.life = 100;
        }
        
        if (this.active) {
          this.life--;
          if (this.life <= 0) this.active = false;
        }
      }
      
      draw() {
        if (!this.active) return;
        
        const alpha = this.life / 100;
        ctx.strokeStyle = `rgba(26, 158, 143, ${alpha * 0.3})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(this.neuron1.x, this.neuron1.y);
        ctx.lineTo(this.neuron2.x, this.neuron2.y);
        ctx.stroke();
      }
    }
    
    // Create neurons and synapses
    const neurons = [];
    const synapses = [];
    const neuronCount = 80;
    
    for (let i = 0; i < neuronCount; i++) {
      neurons.push(new Neuron());
    }
    
    for (let i = 0; i < neurons.length; i++) {
      for (let j = i + 1; j < neurons.length; j++) {
        if (Math.random() > 0.97) {
          synapses.push(new Synapse(neurons[i], neurons[j]));
        }
      }
    }
    
    // Animation loop
    function animate() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      // Draw neurons
      neurons.forEach(neuron => {
        neuron.update();
        neuron.draw();
      });
      
      // Draw synapses
      synapses.forEach(synapse => {
        synapse.update();
        synapse.draw();
      });
      
      // Draw floating particles
      ctx.fillStyle = 'rgba(79, 195, 247, 0.05)';
      for (let i = 0; i < 5; i++) {
        const x = Math.random() * canvas.width;
        const y = Math.random() * canvas.height;
        const size = Math.random() * 5 + 1;
        ctx.beginPath();
        ctx.arc(x, y, size, 0, Math.PI * 2);
        ctx.fill();
      }
      
      requestAnimationFrame(animate);
    }
    
    animate();
    
    // Handle window resize
    window.addEventListener('resize', () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    });
  }
  
  // Initialize when DOM is loaded
  document.addEventListener('DOMContentLoaded', initNeuroBackground);