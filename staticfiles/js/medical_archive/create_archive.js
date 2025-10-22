// Initialize Select2
$(document).ready(function() {
    $('select').select2({
        theme: 'bootstrap4',
        width: '100%',
        placeholder: 'Select an option',
        allowClear: true,
        dropdownParent: $('.archive-card')
    });
});

// Rich text editor functionality
document.querySelectorAll('.format-btn').forEach(button => {
    button.addEventListener('click', function() {
        const command = this.dataset.command;
        const notesField = document.getElementById('id_notes');
        
        if (command === 'createLink') {
            const url = prompt('Enter the URL:');
            if (url) {
                document.execCommand('createLink', false, url);
            }
        } else {
            document.execCommand(command, false, null);
        }
        
        notesField.focus();
        
        // Dispatch input event for form validation
        const event = new Event('input', { bubbles: true });
        notesField.dispatchEvent(event);
    });
});

// File upload and preview
const fileInput = document.getElementById('id_files');
const filePreview = document.getElementById('filePreview');
const uploadContainer = document.getElementById('uploadContainer');
const uploadLoading = document.getElementById('uploadLoading');

// Handle drag and drop
['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    uploadContainer.addEventListener(eventName, preventDefaults, false);
    document.body.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    uploadContainer.addEventListener(eventName, highlight, false);
});

['dragleave', 'drop'].forEach(eventName => {
    uploadContainer.addEventListener(eventName, unhighlight, false);
});

function highlight() {
    uploadContainer.classList.add('highlight');
}

function unhighlight() {
    uploadContainer.classList.remove('highlight');
}

// Handle file drop
uploadContainer.addEventListener('drop', handleDrop, false);

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    handleFiles(files);
    fileInput.files = files; // Update the file input
}

// Handle file input change
fileInput.addEventListener('change', function() {
    handleFiles(this.files);
});

// File type to icon mapping
const fileIcons = {
    'image': 'file-image',
    'application/pdf': 'file-pdf',
    'application/msword': 'file-word',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'file-word',
    'application/vnd.ms-excel': 'file-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'file-excel',
    'application/vnd.ms-powerpoint': 'file-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'file-powerpoint',
    'text/plain': 'file-alt',
    'text/csv': 'file-csv',
    'application/zip': 'file-archive'
};

// Show loading spinner
function showLoading() {
    uploadLoading.classList.add('active');
}

// Hide loading spinner
function hideLoading() {
    uploadLoading.classList.remove('active');
}

// Process and preview files
function handleFiles(files) {
    filePreview.innerHTML = '';
    
    if (!files || files.length === 0) return;
    
    // Show loading spinner
    showLoading();
    
    // Simulate processing delay
    setTimeout(() => {
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const fileType = file.type;
            let iconClass = 'file';
            
            // Check for specific file types
            if (fileIcons[fileType]) {
                iconClass = fileIcons[fileType];
            } 
            // Check for general categories
            else if (fileType.startsWith('image/')) {
                iconClass = 'file-image';
            } else if (fileType.startsWith('audio/')) {
                iconClass = 'file-audio';
            } else if (fileType.startsWith('video/')) {
                iconClass = 'file-video';
            } else if (fileType.startsWith('text/')) {
                iconClass = 'file-alt';
            }
            
            const fileSize = (file.size / 1024 / 1024).toFixed(2);
            
            const previewItem = document.createElement('div');
            previewItem.className = 'file-preview-item';
            previewItem.innerHTML = `
                <div class="file-preview-icon">
                    <i class="fas fa-${iconClass}"></i>
                </div>
                <div class="file-preview-content">
                    <div class="file-preview-name">${file.name}</div>
                    <div class="file-preview-size">${fileSize} MB</div>
                </div>
                <div class="file-preview-remove" data-index="${i}">
                    <i class="fas fa-times"></i>
                </div>
            `;
            
            filePreview.appendChild(previewItem);
        }
        
        // Hide loading spinner
        hideLoading();
        
        // Show toast if files are uploaded
        if (files.length > 0) {
            showToast(`${files.length} file${files.length > 1 ? 's' : ''} added`, 'success');
        }
    }, 1500); // Simulate processing time
}

// Remove file from preview and input
filePreview.addEventListener('click', function(e) {
    if (e.target.closest('.file-preview-remove')) {
        const removeBtn = e.target.closest('.file-preview-remove');
        const index = parseInt(removeBtn.dataset.index);
        const files = Array.from(fileInput.files);
        
        // Get filename for toast message
        const fileName = files[index].name;
        
        files.splice(index, 1);
        
        // Create new FileList
        const dataTransfer = new DataTransfer();
        files.forEach(file => dataTransfer.items.add(file));
        fileInput.files = dataTransfer.files;
        
        // Re-render preview
        handleFiles(fileInput.files);
        
        // Show toast
        showToast(`Removed: ${fileName}`, 'success');
    }
});

// Clear form button
document.getElementById('clearForm').addEventListener('click', function() {
    // Reset form
    document.getElementById('medicalRecordForm').reset();
    
    // Clear file preview
    filePreview.innerHTML = '';
    
    // Reset select2 fields
    $('select').val(null).trigger('change');
    
    // Clear rich text editor
    document.getElementById('id_notes').innerHTML = '';
    
    // Show toast notification
    showToast('Form has been cleared', 'success');
});

// Show toast notification
function showToast(message, type) {
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'success' ? '' : 'toast-error'}`;
    toast.innerHTML = `
        <div class="toast-content">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
            <span>${message}</span>
        </div>
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('show');
    }, 100);
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300);
    }, 3000);
}

// Close alert buttons
document.querySelectorAll('.close-btn').forEach(button => {
    button.addEventListener('click', function() {
        const alert = this.closest('.alert');
        alert.style.transform = 'translateX(100%)';
        alert.style.opacity = '0';
        
        setTimeout(() => {
            alert.remove();
        }, 300);
    });
});

// Form submission loading indicator
document.getElementById('medicalRecordForm').addEventListener('submit', function() {
    const submitBtn = document.getElementById('submitBtn');
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    submitBtn.disabled = true;
    
    // Add a small delay to allow the button state to update
    setTimeout(() => {
        this.submit();
    }, 100);
});

// Auto-resize textarea
function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = (textarea.scrollHeight) + 'px';
}

// Apply to all textareas
document.querySelectorAll('textarea').forEach(textarea => {
    textarea.addEventListener('input', function() {
        autoResize(this);
    });
    
    // Initialize on load
    autoResize(textarea);
});

// Tooltip hover functionality
document.querySelectorAll('.section-tooltip').forEach(tooltip => {
    tooltip.addEventListener('mouseenter', function() {
        const tooltipText = this.querySelector('.tooltip-text');
        tooltipText.style.visibility = 'visible';
        tooltipText.style.opacity = '1';
        tooltipText.style.transform = 'translateX(-50%) translateY(-5px)';
    });
    
    tooltip.addEventListener('mouseleave', function() {
        const tooltipText = this.querySelector('.tooltip-text');
        tooltipText.style.visibility = 'hidden';
        tooltipText.style.opacity = '0';
        tooltipText.style.transform = 'translateX(-50%)';
    });
});