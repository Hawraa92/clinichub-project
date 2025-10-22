// static/js/prescription_voice.js

document.addEventListener('DOMContentLoaded', () => {
    const startBtn     = document.getElementById('startRecordBtn');
    const stopBtn      = document.getElementById('stopRecordBtn');
    const resetBtn     = document.getElementById('resetRecordBtn');
    const recordStatus = document.getElementById('recordStatus');
    const audioPlayer  = document.getElementById('audioPlayer');
    const voiceInput   = document.getElementById('voiceNoteInput');
    let mediaRecorder, audioChunks = [];
  
    // تأكد من دعم MediaRecorder
    if (!navigator.mediaDevices || typeof MediaRecorder === 'undefined') {
      startBtn.disabled = true;
      recordStatus.textContent = '⚠️ التسجيل غير مدعوم في هذا المتصفح.';
      return;
    }
  
    // ابدأ التسجيل
    startBtn.addEventListener('click', async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
  
        mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
        mediaRecorder.onstop = () => {
          const blob = new Blob(audioChunks, { type: 'audio/webm' });
          const url  = URL.createObjectURL(blob);
          audioPlayer.src = url;
          audioPlayer.classList.remove('d-none');
  
          const file = new File([blob], 'voice_note.webm', { type: 'audio/webm' });
          const dt   = new DataTransfer();
          dt.items.add(file);
          voiceInput.files = dt.files;
  
          resetBtn.disabled = false;
          recordStatus.textContent = '✅ جاهز للإرسال.';
        };
  
        mediaRecorder.start();
        recordStatus.textContent = '🎙️ جاري التسجيل…';
        startBtn.disabled = true;
        stopBtn.disabled  = false;
      } catch (err) {
        alert('عنصر الميكروفون غير متاح أو تم رفض الإذن.');
        console.error(err);
      }
    });
  
    // إيقاف التسجيل
    stopBtn.addEventListener('click', () => {
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        recordStatus.textContent = '⏹️ توقف التسجيل.';
        startBtn.disabled = false;
        stopBtn.disabled  = true;
      }
    });
  
    // إعادة التعيين
    resetBtn.addEventListener('click', () => {
      audioChunks = [];
      audioPlayer.pause();
      audioPlayer.src = '';
      audioPlayer.classList.add('d-none');
      voiceInput.value = '';
      recordStatus.textContent = '🔄 تم إعادة التعيين.';
      resetBtn.disabled = true;
    });
  });
  