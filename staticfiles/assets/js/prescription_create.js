// prescription_create.js
// Handles audio recording and front-end form validation

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('prescriptionForm');
    const startBtn = document.getElementById('startRecordBtn');
    const stopBtn = document.getElementById('stopRecordBtn');
    const resetBtn = document.getElementById('resetRecordBtn');
    const recordStatus = document.getElementById('recordStatus');
    const audioPlayer = document.getElementById('audioPlayer');
    const voiceInput = document.getElementById('voiceNoteInput');
    let mediaRecorder;
    let audioChunks = [];
  
    // Front-end validation on submit
    form.addEventListener('submit', (e) => {
      if (!form.checkValidity()) {
        e.preventDefault();
        e.stopPropagation();
        form.classList.add('was-validated');
        return false;
      }
    });
  
    // Start recording
    startBtn.onclick = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
  
        mediaRecorder.ondataavailable = (event) => {
          audioChunks.push(event.data);
        };
  
        mediaRecorder.onstop = () => {
          // Create blob and play
          const audioBlob = new Blob(audioChunks, { type: 'audio/webm; codecs=opus' });
          const audioUrl = URL.createObjectURL(audioBlob);
          audioPlayer.src = audioUrl;
          audioPlayer.classList.remove('d-none');
  
          // Create File object to attach to form
          const file = new File([audioBlob], 'voice_note.webm', { type: 'audio/webm' });
          const dataTransfer = new DataTransfer();
          dataTransfer.items.add(file);
          voiceInput.files = dataTransfer.files;
  
          // Enable reset button
          resetBtn.disabled = false;
        };
  
        mediaRecorder.start();
        recordStatus.textContent = 'Recording…';
        startBtn.disabled = true;
        stopBtn.disabled = false;
      } catch (err) {
        alert('Microphone access denied or unavailable.');
        console.error(err);
      }
    };
  
    // Stop recording
    stopBtn.onclick = () => {
      mediaRecorder.stop();
      recordStatus.textContent = 'Recording stopped.';
      startBtn.disabled = false;
      stopBtn.disabled = true;
    };
  
    // Reset recording
    resetBtn.onclick = () => {
      audioChunks = [];
      audioPlayer.pause();
      audioPlayer.src = '';
      audioPlayer.classList.add('d-none');
      voiceInput.value = '';
      recordStatus.textContent = '';
      resetBtn.disabled = true;
    };
  });
  